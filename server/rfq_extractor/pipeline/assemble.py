"""Turn stage output into the final contract result, and score confidence.

Confidence is computed from STRUCTURED SIGNALS we derive ourselves — catalogue
match status, missing quantities, whether the agent degraded — never by
pattern-matching the model's prose.

## What `confidence` means on the RFQ path

The spec defines it as "how sure you are about this extraction". That is NOT the
same question the classifier answered ("is this an RFQ?"), and conflating them is
a category error: the classifier can be 99% certain from the subject line alone
while the parts list is a mess of ambiguous ranges off a blurry scan.

So the classifier's confidence is applied as a CEILING, not a base. Extraction
correctness is conditional on there being something to extract — you cannot be
surer about the line items than about the premise that this is an RFQ at all —
but residual classification doubt should not stack on top of extraction penalties
as though they were the same kind of uncertainty.

On the non-RFQ path the field genuinely does mean "how sure it is not an RFQ", so
the classifier's number is used directly there. Same field name, two meanings —
that is the contract's design, not ours.

That distinction was learned the hard way: an earlier version searched warning
text for "not found in catalogue", the model wrote "not found in THE catalogue",
and every penalty silently missed. A confidence score that depends on the exact
wording the model happened to choose is not a confidence score.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..catalog import lookup
from ..schema import Customer, LineItem, RequestMeta, RfqResult


@dataclass
class QualitySignals:
    """Facts we establish ourselves, independent of how the model phrased things."""

    unresolved: int = 0          # line items with no catalogue match
    ambiguous: int = 0           # line items matching several catalogue variants
    zero_quantity: int = 0       # line items with no stated quantity
    injection_detected: bool = False
    degraded: bool = False       # a stage failed and we fell back
    source_unreadable: bool = False  # an attachment could not be read/was truncated
    # Warnings the MODEL raised that have no structured signal of their own
    # (ambiguous ranges, "or equivalent", conflicting dates). Deliberately NOT
    # len(all warnings): our own signals already carry their own penalty, so
    # counting them here charged every one of them twice.
    model_warning_count: int = 0
    unverified_parts: int = 0        # part number absent from the source (possible invention)
    unverified_quantities: int = 0   # quantity absent from the source (often just derived)
    restored_items: int = 0          # candidates the model dropped and we put back
    unverifiable_parts: int = 0      # image-sourced: no text to check against


def derive_signals(
    line_items: list[LineItem],
    *,
    model_warning_count: int,
    injection_detected: bool,
    degraded: bool,
    source_unreadable: bool,
    unverified_parts: int = 0,
    unverified_quantities: int = 0,
    restored_items: int = 0,
    unverifiable_parts: int = 0,
) -> QualitySignals:
    unresolved = ambiguous = 0
    for item in line_items:
        status = lookup(item.part_number).status
        if status == "not_found":
            unresolved += 1
        elif status == "ambiguous":
            ambiguous += 1

    return QualitySignals(
        unresolved=unresolved,
        ambiguous=ambiguous,
        zero_quantity=sum(1 for li in line_items if li.quantity == 0),
        injection_detected=injection_detected,
        degraded=degraded,
        source_unreadable=source_unreadable,
        model_warning_count=model_warning_count,
        unverified_parts=unverified_parts,
        unverified_quantities=unverified_quantities,
        restored_items=restored_items,
        unverifiable_parts=unverifiable_parts,
    )


# (penalty per occurrence, maximum total penalty)
_PER_UNRESOLVED = (0.03, 0.15)
_PER_AMBIGUOUS = (0.05, 0.15)
_PER_ZERO_QTY = (0.05, 0.15)
_PER_MODEL_WARNING = (0.01, 0.05)
# A part absent from the source may be invented — the failure the ERP must never see.
_PER_UNVERIFIED_PART = (0.08, 0.24)
# A quantity absent from the source is usually just derived; weigh it lightly.
_PER_UNVERIFIED_QTY = (0.02, 0.08)
# A dropped-then-restored item means the model lost a requirement.
_PER_RESTORED = (0.10, 0.30)
# Not the model's fault — we simply have no text to check a scan against. Small
# penalty because genuine uncertainty remains, not because anything looks wrong.
_PER_UNVERIFIABLE = (0.02, 0.06)
_INJECTION = 0.10
# Degraded means the resolve stage died: line items are raw candidates, unchecked
# against the catalogue, with quantities crudely digit-parsed. Sized against a base
# of 1.0 so such a run lands near 0.6 and visibly reads as untrustworthy.
_DEGRADED = 0.40
_UNREADABLE = 0.15
_NO_ITEMS_CEILING = 0.30
_FLOOR, _CEILING = 0.05, 0.99


def score_confidence(
    line_items: list[LineItem],
    signals: QualitySignals,
    *,
    classification_ceiling: float = 1.0,
) -> float:
    """Score the EXTRACTION, then cap it by how sure we are this is an RFQ."""
    score = 1.0

    # An "RFQ" with nothing to quote is a contradiction; cap it hard.
    if not line_items:
        score = min(score, _NO_ITEMS_CEILING)

    for count, (per, cap) in (
        (signals.unresolved, _PER_UNRESOLVED),
        (signals.ambiguous, _PER_AMBIGUOUS),
        (signals.zero_quantity, _PER_ZERO_QTY),
        (signals.model_warning_count, _PER_MODEL_WARNING),
        (signals.unverified_parts, _PER_UNVERIFIED_PART),
        (signals.unverified_quantities, _PER_UNVERIFIED_QTY),
        (signals.restored_items, _PER_RESTORED),
        (signals.unverifiable_parts, _PER_UNVERIFIABLE),
    ):
        if count:
            score -= min(per * count, cap)

    if signals.injection_detected:
        score -= _INJECTION
    if signals.source_unreadable:
        score -= _UNREADABLE
    if signals.degraded:
        score -= _DEGRADED

    # Cannot be surer about the extraction than about there being one to make.
    score = min(score, classification_ceiling)
    return round(max(_FLOOR, min(_CEILING, score)), 2)


def dedupe_warnings(warnings: list[str]) -> list[str]:
    """Preserve order, drop exact repeats (stages can flag the same thing twice)."""
    seen: set[str] = set()
    out: list[str] = []
    for w in warnings:
        w = w.strip()
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def build_rfq_result(
    *,
    classification_confidence: float,
    customer: Customer,
    request: RequestMeta,
    line_items: list[LineItem],
    warnings: list[str],
    model_warning_count: int = 0,
    injection_detected: bool = False,
    degraded: bool = False,
    source_unreadable: bool = False,
    unverified_parts: int = 0,
    unverified_quantities: int = 0,
    restored_items: int = 0,
    unverifiable_parts: int = 0,
) -> RfqResult:
    merged = dedupe_warnings(warnings)
    signals = derive_signals(
        line_items,
        model_warning_count=model_warning_count,
        injection_detected=injection_detected,
        degraded=degraded,
        source_unreadable=source_unreadable,
        unverified_parts=unverified_parts,
        unverified_quantities=unverified_quantities,
        restored_items=restored_items,
        unverifiable_parts=unverifiable_parts,
    )
    return RfqResult(
        confidence=score_confidence(
            line_items, signals, classification_ceiling=classification_confidence
        ),
        customer=customer,
        request=request,
        line_items=line_items,
        warnings=merged,
    )

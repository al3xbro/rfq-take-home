"""Post-extraction verification (spec Option A, plus the reverse omission check).

Two failure modes, opposite directions:

  * INVENTION (Option A): a line item not grounded in the source — the model
    fabricated or mis-transcribed a part before it reached the ERP.
  * OMISSION: a candidate the extractor found that never made it into the final
    line items — a silently dropped requirement.

Neither check deletes anything: flagged items are surfaced, omitted items restored.

## Why this compares against candidates, not just the raw source

A naive "is this string in the email text?" check flags three things that are all
CORRECT behaviour, and a verifier that cries wolf gets ignored:

  1. Canonicalisation. Source says "LM2596"; we resolve it to the catalogue's
     "LM2596S-5.0". The "5.0" is not in the email — by design.
  2. Derived quantities. "2 per board" x 500 boards = 1000. The 1000 is computed,
     so it is legitimately absent from the source.
  3. Image sources. A scanned parts list has no text layer, so NOTHING extracted
     from it appears in the text. Absence is not evidence of invention.

So the real question is not "is this string in the email?" but "is this line item
traceable to something the extractor actually reported seeing?" We check the
candidate's own `part_hint` and `source_span` against the source, then confirm any
divergence between hint and final part number is explained by a catalogue match.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..catalog import lookup
from ..schema import LineItem
from .models import Candidate

_THOUSANDS = re.compile(r"(?<=\d)[,\s](?=\d{3}(?!\d))")
_SPLIT = re.compile(r"[^A-Za-z0-9.]+")
# Wording that means a quantity is computed rather than quoted.
_DERIVED = re.compile(r"\bper\b|/\s*(board|unit|panel|assembly)|\beach\b", re.I)


@dataclass
class VerificationReport:
    warnings: list[str] = field(default_factory=list)
    unverified_parts: int = 0        # genuinely suspicious: not traceable to the source
    unverified_quantities: int = 0
    unverifiable_parts: int = 0      # came from an image; cannot be text-checked
    restored_items: list[LineItem] = field(default_factory=list)

    @property
    def dropped(self) -> int:
        return len(self.restored_items)


def _tokens(text: str) -> list[str]:
    text = _THOUSANDS.sub("", text or "")
    return [t.strip(".") for t in _SPLIT.split(text.upper()) if t.strip(".")]


def _present(token: str, source: set[str]) -> bool:
    if token in source:
        return True
    if len(token) < 3:
        return False
    return any(s.startswith(token) or token.startswith(s) for s in source if len(s) >= 3)


def _same_part(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    hits = sum(1 for t in short if _present(t, set(long_)))
    return hits >= max(1, (len(short) + 1) // 2)


def verify(
    line_items: list[LineItem],
    candidates: list[Candidate],
    source_text: str,
    *,
    has_images: bool = False,
) -> VerificationReport:
    report = VerificationReport()
    source = set(_tokens(source_text))

    for item in line_items:
        cand = next((c for c in candidates if _same_part(c.part_hint, item.part_number)), None)

        # (a) Is the item traceable to something the extractor reported seeing?
        if cand is None:
            report.unverified_parts += 1
            report.warnings.append(
                f"unverified part: {item.part_number!r} does not correspond to anything the "
                "extraction step reported finding. It may have been introduced during "
                "resolution — confirm against the original before quoting."
            )
        else:
            grounded = all(_present(t, source) for t in _tokens(cand.part_hint))
            if not grounded:
                if has_images:
                    # Read from a scan: there is no text to check it against.
                    report.unverifiable_parts += 1
                    report.warnings.append(
                        f"unverifiable part: {item.part_number!r} was read from an image "
                        "attachment, so it cannot be checked against source text. Confirm "
                        "against the original scan."
                    )
                else:
                    report.unverified_parts += 1
                    report.warnings.append(
                        f"unverified part: {item.part_number!r} (read as "
                        f"{cand.part_hint!r}) does not appear in the source. Possible "
                        "mis-transcription — confirm before quoting."
                    )
            elif not _same_part(cand.part_hint, item.part_number):
                # Diverged from what was read: only legitimate if the catalogue explains it.
                if lookup(item.part_number).status != "exact":
                    report.unverified_parts += 1
                    report.warnings.append(
                        f"unverified part: source says {cand.part_hint!r} but the line item "
                        f"says {item.part_number!r}, and that is not an exact catalogue "
                        "match. Confirm the substitution."
                    )

        # (b) Quantity — skip when legitimately computed rather than quoted.
        if item.quantity <= 0:
            continue
        derived = bool(
            (cand and _DERIVED.search(cand.qty_expr or ""))
            or _DERIVED.search(item.notes or "")
            or "=" in (item.notes or "")
        )
        if derived or has_images:
            continue
        if str(item.quantity) not in source:
            report.unverified_quantities += 1
            report.warnings.append(
                f"unverified quantity: {item.quantity} for {item.part_number!r} does not "
                "appear in the source and is not marked as derived. Confirm before quoting."
            )

    # --- Reverse direction: did the resolver drop anything? ---
    for cand in candidates:
        if any(_same_part(cand.part_hint, li.part_number) for li in line_items):
            continue
        report.restored_items.append(
            LineItem(
                part_number=cand.part_hint,
                manufacturer=cand.mfr_hint,
                description=None,
                quantity=0,
                target_price=cand.target_price,
                notes=(cand.notes or None),
            )
        )
        report.warnings.append(
            f"restored dropped line item: {cand.part_hint!r} was extracted from the source "
            f"but missing from the final list (source: {cand.source_span[:60]!r}). "
            "Restored with quantity 0 — a human must set the quantity."
        )

    return report

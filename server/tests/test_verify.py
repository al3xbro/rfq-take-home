"""Verification pass: spec Option A (invention) + the reverse omission check.

A verifier is only useful if it fires on real problems AND stays quiet on correct
behaviour. Both halves are tested here — the quiet half matters just as much,
because a noisy verifier is one operators learn to ignore.
"""
from __future__ import annotations

from rfq_extractor.pipeline.models import Candidate
from rfq_extractor.pipeline.verify import verify
from rfq_extractor.schema import LineItem

SOURCE = """
- LM358N (TI) - 500 pcs
- 10K 0805 resistors - 5,000 pcs
- Relay 5V 10A SPDT - 2 per board, 500 boards
"""


def cand(hint, qty="", **kw):
    return Candidate(part_hint=hint, qty_expr=qty, source_span=f"- {hint}", **kw)


def item(part, qty=0, notes=None):
    return LineItem(part_number=part, quantity=qty, notes=notes)


# --- it must FIRE on real problems ----------------------------------------- #

def test_invented_part_is_flagged():
    """A line item with no corresponding candidate was introduced during resolution."""
    report = verify([item("BOGUS-9999", 100)], [cand("LM358N", "500")], SOURCE)
    assert report.unverified_parts == 1
    assert any("unverified part" in w for w in report.warnings)


def test_mistranscribed_part_is_flagged():
    c = cand("LM9999X", "500")           # extractor claims it, source does not contain it
    report = verify([item("LM9999X", 500)], [c], SOURCE)
    assert report.unverified_parts == 1
    assert any("mis-transcription" in w for w in report.warnings)


def test_dropped_candidate_is_restored_not_lost():
    """The failure that must never reach the ERP silently."""
    report = verify([item("LM358N", 500)], [cand("LM358N", "500"), cand("10K 0805", "5000")], SOURCE)
    assert report.dropped == 1
    assert report.restored_items[0].part_number == "10K 0805"
    assert report.restored_items[0].quantity == 0, "restored items need a human to set quantity"
    assert any("restored dropped line item" in w for w in report.warnings)


def test_unstated_quantity_is_flagged():
    report = verify([item("LM358N", 7777)], [cand("LM358N", "500")], SOURCE)
    assert report.unverified_quantities == 1


# --- it must STAY QUIET on correct behaviour -------------------------------- #

def test_canonicalisation_is_not_flagged():
    """Source says LM358; we resolve to the catalogue's LM358N. That is desired."""
    report = verify([item("LM358N", 500)], [cand("LM358", "500")], SOURCE)
    assert report.unverified_parts == 0, report.warnings


def test_derived_quantity_is_not_flagged():
    """'2 per board' x 500 boards = 1000, which legitimately is not in the source."""
    report = verify(
        [item("Relay 5V 10A SPDT", 1000, notes="Derived: 2 per board x 500 boards = 1000")],
        [cand("Relay 5V 10A SPDT", "2 per board")],
        SOURCE,
    )
    assert report.unverified_quantities == 0, report.warnings


def test_image_sourced_parts_are_unverifiable_not_suspect():
    """A scan has no text layer, so absence from text is not evidence of invention."""
    report = verify(
        [item("MAX232CPE", 250)], [cand("MAX232CPE", "250")], SOURCE, has_images=True
    )
    assert report.unverified_parts == 0
    assert report.unverifiable_parts == 1
    assert any("unverifiable" in w for w in report.warnings)


def test_plural_and_reordering_are_not_flagged():
    report = verify([item("10K 0805 resistor", 5000)], [cand("10K 0805 resistors", "5,000")], SOURCE)
    assert report.unverified_parts == 0, report.warnings
    assert report.unverified_quantities == 0, report.warnings


def test_clean_extraction_produces_no_warnings():
    report = verify([item("LM358N", 500)], [cand("LM358N", "500")], SOURCE)
    assert report.warnings == []

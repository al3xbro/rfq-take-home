"""Accuracy checks against labels.json. Requires a real ANTHROPIC_API_KEY.

Skipped automatically when no key is configured, so the offline suite stays green.
Run with:  RFQ_LIVE=1 ANTHROPIC_API_KEY=sk-... pytest tests/test_samples_live.py -v

These assert on things that are genuinely determinate (is it an RFQ, is the part
present, is the quantity right). They deliberately do NOT assert exact equality
with labels.json across every field — several samples are ambiguous by design and
the README documents where our answer differs from the label and why.
"""
from __future__ import annotations

import json
import os

import pytest

from conftest import SAMPLES
from rfq_extractor.pipeline.run import run_pipeline
from rfq_extractor.schema import to_wire

pytestmark = pytest.mark.skipif(
    not os.environ.get("RFQ_LIVE") or os.environ.get("ANTHROPIC_API_KEY", "").startswith("test-"),
    reason="live model tests need RFQ_LIVE=1 and a real ANTHROPIC_API_KEY",
)

LABELS = json.loads((SAMPLES / "labels.json").read_text())


async def _ingest(name: str) -> dict:
    return to_wire((await run_pipeline((SAMPLES / name).read_bytes())).result)


@pytest.mark.parametrize("name", sorted(LABELS))
async def test_is_rfq_matches_label(name):
    assert (await _ingest(name))["isRfq"] is LABELS[name]["isRfq"]


@pytest.mark.parametrize("name", [n for n in sorted(LABELS) if LABELS[n]["isRfq"]])
async def test_all_labelled_parts_are_present(name):
    """Every part in the label must appear. Extra parts are allowed (and warned on);
    a MISSING part is a real failure — a customer requirement never reached the ERP."""
    wire = await _ingest(name)
    got = {li["partNumber"].upper().replace(" ", "") for li in wire["lineItems"]}
    for want in LABELS[name]["lineItems"]:
        w = want["partNumber"].upper().replace(" ", "")
        assert any(w in g or g in w for g in got), f"{name}: missing {want['partNumber']} (got {got})"


@pytest.mark.parametrize("name", [n for n in sorted(LABELS) if LABELS[n]["isRfq"]])
async def test_quantities_match_where_unambiguous(name):
    wire = await _ingest(name)
    by_part = {li["partNumber"].upper().replace(" ", ""): li for li in wire["lineItems"]}
    for want in LABELS[name]["lineItems"]:
        w = want["partNumber"].upper().replace(" ", "")
        match = next((v for k, v in by_part.items() if w in k or k in w), None)
        if match is not None:
            assert match["quantity"] == want["quantity"], f"{name}/{want['partNumber']}"


async def test_injection_sample_is_not_suppressed():
    """rfq-07 is not in labels.json, but it is the security regression that matters."""
    wire = await _ingest("rfq-07-restock.eml")
    assert wire["isRfq"] is True
    parts = {li["partNumber"].upper() for li in wire["lineItems"]}
    assert {"TL072CP", "STM32F103C8T6", "AMS1117-3.3"} <= parts
    assert any("injection" in w.lower() for w in wire["warnings"])


async def test_image_sample_is_read():
    """Option B: the scanned parts list, via vision."""
    wire = await _ingest("rfq-08-image.eml")
    assert wire["isRfq"] is True
    parts = {li["partNumber"].upper() for li in wire["lineItems"]}
    assert {"MAX232CPE", "LM2596S-5.0", "FT232RL", "W25Q128JVSIQ"} <= parts

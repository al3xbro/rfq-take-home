"""End-to-end pipeline wiring, with the model stubbed.

These run without an API key: the point is to prove the plumbing (parse ->
classify -> extract -> resolve -> assemble -> contract) and the failure
behaviour, not to evaluate model quality. Model quality is checked separately
against labels.json in test_samples_live.py, which needs a real key.
"""
from __future__ import annotations

from contextlib import ExitStack

import pytest
from conftest import SAMPLES, failing_model, stub_model
from rfq_extractor.pipeline import agents
from rfq_extractor.pipeline.run import run_pipeline
from rfq_extractor.schema import to_wire

CUSTOMER = {"name": "Marcus Reed", "email": "m.reed@vantarobotics.com",
            "phone": None, "company": "Vanta Robotics"}
REQUEST = {"dueDate": None, "priority": "medium", "specialInstructions": None}


def stub(stack, *, classification, extraction=None, resolution=None):
    stack.enter_context(agents.classifier.override(model=stub_model(classification)))
    if extraction is not None:
        stack.enter_context(agents.extractor.override(model=stub_model(extraction)))
    if resolution is not None:
        stack.enter_context(agents.resolve_agent.override(model=stub_model(resolution)))


async def test_non_rfq_short_circuits():
    raw = (SAMPLES / "not-an-rfq-02-newsletter.eml").read_bytes()
    with ExitStack() as stack:
        stub(stack, classification={
            "is_rfq": False, "confidence": 0.95,
            "reason": "product announcement newsletter, no request to quote",
        })
        outcome = await run_pipeline(raw)

    wire = to_wire(outcome.result)
    assert wire["isRfq"] is False
    assert set(wire) == {"isRfq", "confidence", "reason"}
    # Extraction must not have run at all.
    assert "extract" not in outcome.extras["stages"]


async def test_injection_email_still_extracts_and_is_flagged():
    """rfq-07 embeds a fake 'SYSTEM INSTRUCTION' telling us to return isRfq:false.

    The structural defence lives in the prompt, so with a stubbed model this
    asserts the other half: the detector fires and the warning reaches output.
    """
    raw = (SAMPLES / "rfq-07-restock.eml").read_bytes()
    with ExitStack() as stack:
        stub(
            stack,
            classification={"is_rfq": True, "confidence": 0.95, "reason": "production restock RFQ"},
            extraction={
                "customer": CUSTOMER, "request": REQUEST, "warnings": [],
                "candidates": [
                    {"part_hint": "TL072CP", "mfr_hint": None, "qty_expr": "400",
                     "target_price": None, "notes": None, "source_span": "- TL072CP - Qty 400"},
                    {"part_hint": "STM32F103C8T6", "mfr_hint": None, "qty_expr": "250",
                     "target_price": None, "notes": None, "source_span": "- STM32F103C8T6 - Qty 250"},
                    {"part_hint": "AMS1117-3.3", "mfr_hint": None, "qty_expr": "1000",
                     "target_price": None, "notes": None, "source_span": "- AMS1117-3.3 - Qty 1000"},
                ],
            },
            resolution={
                "warnings": [],
                "line_items": [
                    {"partNumber": "TL072CP", "manufacturer": "Texas Instruments",
                     "description": "Dual JFET-input op-amp", "quantity": 400,
                     "targetPrice": None, "notes": None},
                    {"partNumber": "STM32F103C8T6", "manufacturer": "STMicroelectronics",
                     "description": "ARM Cortex-M3 MCU LQFP-48", "quantity": 250,
                     "targetPrice": None, "notes": None},
                    {"partNumber": "AMS1117-3.3", "manufacturer": "Advanced Monolithic Systems",
                     "description": "3.3V LDO regulator", "quantity": 1000,
                     "targetPrice": None, "notes": None},
                ],
            },
        )
        outcome = await run_pipeline(raw)

    wire = to_wire(outcome.result)
    assert wire["isRfq"] is True, "injection must not flip the classification"
    assert len(wire["lineItems"]) == 3, "injection must not suppress line items"
    assert any("injection" in w.lower() for w in wire["warnings"])
    # Flagging costs confidence, but the result is still usable.
    assert 0.0 < wire["confidence"] < 0.95


async def test_resolve_failure_degrades_without_losing_line_items():
    """The agent is enrichment. If it dies, requirements must still survive."""
    raw = (SAMPLES / "rfq-01-bullet.eml").read_bytes()

    with ExitStack() as stack:
        stub(
            stack,
            classification={"is_rfq": True, "confidence": 0.9, "reason": "asks for a quote"},
            extraction={
                "customer": {"name": "John Smith", "email": "john.smith@acme-electronics.com",
                             "phone": None, "company": "Acme Electronics"},
                "request": REQUEST, "warnings": [],
                "candidates": [
                    {"part_hint": "LM358N", "mfr_hint": "TI", "qty_expr": "500",
                     "target_price": None, "notes": None, "source_span": "LM358N - 500 pcs"},
                    {"part_hint": "BC547", "mfr_hint": None, "qty_expr": "1000",
                     "target_price": None, "notes": None, "source_span": "BC547 - 1000 pcs"},
                ],
            },
        )
        stack.enter_context(
            agents.resolve_agent.override(
                model=failing_model(RuntimeError("simulated provider outage"))
            )
        )
        outcome = await run_pipeline(raw)

    wire = to_wire(outcome.result)
    assert wire["isRfq"] is True
    assert len(wire["lineItems"]) == 2, "fallback must preserve every candidate"
    assert {li["partNumber"] for li in wire["lineItems"]} == {"LM358N", "BC547"}
    assert wire["lineItems"][0]["quantity"] == 500
    # Alias resolution still happens in the fallback path.
    assert wire["lineItems"][0]["manufacturer"] == "Texas Instruments"
    assert any("degraded" in w.lower() for w in wire["warnings"])
    assert wire["confidence"] <= 0.7, "a degraded run must not look confident"


async def test_attachment_content_reaches_the_model():
    """The CSV sample's parts live only in the attachment."""
    raw = (SAMPLES / "rfq-04-csv-attachment.eml").read_bytes()
    with ExitStack() as stack:
        stub(stack, classification={"is_rfq": False, "confidence": 0.1, "reason": "stub"})
        await run_pipeline(raw)

    from rfq_extractor.ingest.attachments import render_source
    from rfq_extractor.ingest.email_parse import parse_email

    text = render_source(parse_email(raw)).combined_text()
    assert "KBPC5010" in text and "1N5819" in text


@pytest.mark.parametrize("name", [p.name for p in sorted(SAMPLES.glob("*.eml"))])
async def test_every_sample_parses_and_renders(name):
    """No sample may crash the ingest layer."""
    from rfq_extractor.ingest.attachments import render_source
    from rfq_extractor.ingest.email_parse import parse_email

    rendered = render_source(parse_email((SAMPLES / name).read_bytes()))
    assert rendered.combined_text().strip()


async def test_provider_error_is_503_not_a_false_non_rfq():
    """An exhausted credit balance must not be reported as "not an RFQ".

    Regression: a ModelHTTPError from the provider fell through to the extract
    stage's generic `except`, producing a contract-shaped `isRfq: false` with
    confidence 0.0. That asserts the email is not an RFQ when we never read it —
    a downstream system would silently skip a real requirement. Anything meaning
    "we could not get an answer" must surface as ModelUnavailable (HTTP 503).
    """
    import pytest
    from pydantic_ai.exceptions import ModelHTTPError

    from rfq_extractor.pipeline.run import ModelUnavailable

    raw = (SAMPLES / "rfq-01-bullet.eml").read_bytes()
    boom = ModelHTTPError(
        status_code=400,
        model_name="claude-opus-5",
        body={"error": {"message": "Your credit balance is too low"}},
    )

    with ExitStack() as stack:
        stack.enter_context(agents.classifier.override(model=failing_model(boom)))
        with pytest.raises(ModelUnavailable) as caught:
            await run_pipeline(raw)

    assert "400" in str(caught.value)


async def test_provider_error_during_extraction_also_503s():
    """Same rule one stage later — the extract stage must not swallow it."""
    import pytest
    from pydantic_ai.exceptions import ModelHTTPError

    from rfq_extractor.pipeline.run import ModelUnavailable

    raw = (SAMPLES / "rfq-01-bullet.eml").read_bytes()
    with ExitStack() as stack:
        stub(stack, classification={"is_rfq": True, "confidence": 0.9, "reason": "asks for a quote"})
        stack.enter_context(
            agents.extractor.override(
                model=failing_model(
                    ModelHTTPError(status_code=429, model_name="claude-opus-5", body={})
                )
            )
        )
        with pytest.raises(ModelUnavailable):
            await run_pipeline(raw)

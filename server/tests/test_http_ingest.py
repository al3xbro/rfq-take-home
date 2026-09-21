"""HTTP surface of /ingest: what it accepts, and what it refuses cleanly.

The pipeline itself is stubbed — these assert request handling, not extraction.

Regression context: /ingest originally declared `file: UploadFile = File(None)`.
That made FastAPI parse the body as a form whenever the content type looked
form-ish, including the `application/x-www-form-urlencoded` curl sends by default
when no Content-Type is supplied. Form parsing consumed the request stream, so the
subsequent `request.body()` raised `RuntimeError: Stream consumed` and the caller
got a 500 for omitting a header. Multipart is now detected from the header instead.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import SAMPLES
from rfq_extractor import app as app_mod
from rfq_extractor.pipeline.run import PipelineOutcome
from rfq_extractor.schema import NonRfqResult

EML = (SAMPLES / "not-an-rfq-02-newsletter.eml").read_bytes()


@pytest.fixture
def client(monkeypatch):
    # The store is process-local, so isolate it per test rather than letting
    # stub records leak between them.
    from rfq_extractor import store as store_mod

    monkeypatch.setattr(store_mod, "_results", {})

    async def fake_pipeline(raw: bytes) -> PipelineOutcome:
        assert raw.startswith(b"From:"), "handler must pass through the raw .eml bytes"
        return PipelineOutcome(
            result=NonRfqResult(confidence=0.9, reason="stubbed"),
            extras={"subject": "stub", "stages": {}, "total_ms": 1},
        )

    monkeypatch.setattr(app_mod, "run_pipeline", fake_pipeline)
    return TestClient(app_mod.app)


@pytest.mark.parametrize(
    "content_type",
    ["message/rfc822", "application/octet-stream", "text/plain",
     "application/x-www-form-urlencoded", None],
    ids=["rfc822", "octet-stream", "text-plain", "form-urlencoded", "no-header"],
)
def test_raw_body_accepted_regardless_of_content_type(client, content_type):
    """The no-header and form-urlencoded cases are the 'Stream consumed' regression."""
    headers = {"Content-Type": content_type} if content_type else {}
    resp = client.post("/ingest", content=EML, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["isRfq"] is False


def test_multipart_upload_accepted(client):
    resp = client.post("/ingest", files={"file": ("mail.eml", EML, "message/rfc822")})
    assert resp.status_code == 200, resp.text


def test_multipart_without_file_field_is_a_clean_400(client):
    resp = client.post("/ingest", files={"wrong": ("mail.eml", EML, "message/rfc822")})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_email"
    assert "file" in resp.json()["message"]


def test_empty_body_is_a_clean_400(client):
    resp = client.post("/ingest", content=b"", headers={"Content-Type": "message/rfc822"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_email"


def test_error_bodies_never_use_fastapis_detail_shape(client):
    """The contract is what ERP code reads; {"detail": ...} must not leak out."""
    resp = client.post("/ingest", content=b"", headers={"Content-Type": "message/rfc822"})
    assert "detail" not in resp.json()
    assert {"error", "message"} <= set(resp.json())


def test_missing_api_key_returns_503_not_a_contract_shape(monkeypatch):
    """No key means the email was never read — claiming isRfq:false would be a lie."""
    from rfq_extractor.pipeline.run import ModelUnavailable

    async def no_key(raw: bytes):
        raise ModelUnavailable("ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(app_mod, "run_pipeline", no_key)
    resp = TestClient(app_mod.app, raise_server_exceptions=False).post(
        "/ingest", content=EML, headers={"Content-Type": "message/rfc822"}
    )
    assert resp.status_code == 503
    assert resp.json()["error"] == "model_unavailable"
    assert "isRfq" not in resp.json()

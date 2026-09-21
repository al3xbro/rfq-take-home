"""FastAPI application: POST /ingest and the JSON API.

The operator UI is a separate React client in ../client that consumes these
endpoints. In development it runs on Vite's dev server and proxies /api and
/ingest here, so CORS below covers only localhost origins.

Error policy — the output contract is what downstream ERP code depends on, so
FastAPI's default `{"detail": ...}` body must never leak out of /ingest:

  400  malformed REQUEST (unparseable MIME, empty body). Nothing was ingested.
  503  model unavailable (no API key, provider unreachable). Nothing was ingested.
  200  everything else, including per-email model failures, which come back as a
       valid contract payload with confidence 0.0 and a stated reason.
"""
from __future__ import annotations

import logging
import os

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from . import store  # noqa: E402
from .config import MODEL, has_api_key  # noqa: E402
from .ingest.email_parse import EmailParseError  # noqa: E402
from .pipeline.run import ModelUnavailable, run_pipeline  # noqa: E402
from .schema import to_wire  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("rfq_extractor")

app = FastAPI(
    title="RFQ Extractor",
    description="Turns a raw RFQ email into a structured requirement.",
    version="1.0.0",
)

# Dev-only: the Vite client is served from a different port.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    if not has_api_key():
        log.warning(
            "ANTHROPIC_API_KEY is not set — /ingest will return 503 until it is. "
            "The dashboard and stored results still work."
        )


# --------------------------------------------------------------------------- #
# Errors: keep /ingest's body shape predictable.
# --------------------------------------------------------------------------- #

@app.exception_handler(EmailParseError)
async def _bad_email(_: Request, exc: EmailParseError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "invalid_email", "message": str(exc)})


@app.exception_handler(ModelUnavailable)
async def _no_model(_: Request, exc: ModelUnavailable) -> JSONResponse:
    # The hint has to match the actual cause. "Set ANTHROPIC_API_KEY" is useless
    # advice when the key is set and the provider is rejecting on billing or rate
    # limits — which is the more common case once you are past first-run setup.
    hint = (
        "Check the provider response above — typically billing, rate limits, or an "
        "invalid key. The email was not processed; retry once resolved."
        if has_api_key()
        else "Set ANTHROPIC_API_KEY in the server environment (or server/.env) and restart."
    )
    return JSONResponse(
        status_code=503,
        content={"error": "model_unavailable", "message": str(exc), "hint": hint},
    )


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": type(exc).__name__},
    )


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "model": MODEL,
        "apiKeyConfigured": has_api_key(),
        "storedResults": len(store.list_all()),
    }


@app.post("/ingest")
async def ingest(request: Request) -> JSONResponse:
    """Ingest one email and return the structured requirement.

    Body is the complete raw .eml — headers, body and any MIME attachments.
    Two accepted forms:

      * raw bytes, any content type (`message/rfc822` is conventional)
      * `multipart/form-data` with a `file` field

    Multipart is detected from the header rather than declared as an
    `UploadFile = File(...)` parameter. That looks tidier but makes FastAPI parse
    the body as a form whenever the content type merely *looks* form-ish —
    including the `application/x-www-form-urlencoded` that curl sends by default
    when no `Content-Type` is given. That consumes the request stream, so the
    later `request.body()` raised `RuntimeError: Stream consumed` and the caller
    got a 500 for the entirely reasonable act of omitting a header.
    """
    filename = None
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or isinstance(upload, str):
            raise EmailParseError(
                "multipart request has no 'file' field; send the .eml as -F 'file=@mail.eml'"
            )
        raw = await upload.read()
        filename = upload.filename
    else:
        raw = await request.body()

    if not raw:
        raise EmailParseError("request body was empty; send raw .eml bytes or a file upload")

    outcome = await run_pipeline(raw)
    wire = to_wire(outcome.result)
    await store.add(wire, outcome.extras, filename=filename)
    return JSONResponse(content=wire)


@app.get("/api/rfqs")
async def api_rfqs() -> list[dict]:
    return [
        {
            "id": r["id"],
            "receivedAt": r["receivedAt"],
            "filename": r["filename"],
            "subject": r["extras"].get("subject", ""),
            "from": r["extras"].get("from", ""),
            "isRfq": r["result"]["isRfq"],
            "confidence": r["result"]["confidence"],
            "company": (r["result"].get("customer") or {}).get("company"),
            "lineItemCount": len(r["result"].get("lineItems") or []),
            "warningCount": len(r["result"].get("warnings") or []),
        }
        for r in store.list_all()
    ]


@app.get("/api/rfqs/{record_id}")
async def api_rfq(record_id: str) -> dict:
    record = store.get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not found")
    return record

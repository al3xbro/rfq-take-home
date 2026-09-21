"""Pipeline orchestrator: raw .eml bytes -> contract result (+ dashboard extras).

Failure policy, which is a deliberate judgement call:

* Cannot attempt at all (no API key, provider unreachable) -> ModelUnavailable,
  which the API surfaces as 503. The email was NOT ingested, so inventing a
  contract result would be a lie: reporting `isRfq: false` for an email we never
  read could make a downstream system skip a real RFQ.
* Attempted but the model output was unusable -> a valid contract result with
  confidence 0.0 and a reason naming the failure. The email WAS ingested and an
  operator should see it, flagged, rather than getting a stack trace.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.exceptions import ModelHTTPError, UserError
from pydantic_ai.messages import ToolCallPart

from ..config import RESOLVE_CHUNK_SIZE, RESOLVE_MAX_CONCURRENCY, has_api_key
from ..ingest.attachments import render_source
from ..ingest.email_parse import parse_email
from ..schema import Customer, IngestResult, LineItem, NonRfqResult, RequestMeta
from ..security import detect_injection
from .agents import build_user_content, classifier, extractor, resolve_agent
from .assemble import build_rfq_result
from .models import Candidate, Extraction
from .verify import verify
from . import tools as _tools  # noqa: F401  (registers tools on resolve_agent)

log = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    """No usable model: missing credentials or the provider could not be reached."""


@dataclass
class PipelineOutcome:
    result: IngestResult
    extras: dict[str, Any] = field(default_factory=dict)


async def run_pipeline(raw: bytes) -> PipelineOutcome:
    if not has_api_key():
        raise ModelUnavailable(
            "ANTHROPIC_API_KEY is not set, so the extraction model cannot be called."
        )

    t0 = time.perf_counter()
    doc = parse_email(raw)               # raises EmailParseError -> 400 at the API edge
    rendered = render_source(doc)

    warnings: list[str] = list(rendered.warnings)
    injection = detect_injection(rendered.combined_text())
    warnings += injection

    # Structured quality signals, tracked by us rather than inferred from prose.
    injection_detected = bool(injection)
    source_unreadable = any(
        ("could not read" in w) or ("truncated" in w) or ("no extractable text" in w)
        for w in rendered.warnings
    )
    degraded = False

    stages: dict[str, Any] = {}
    extras: dict[str, Any] = {
        "subject": doc.headers.get("Subject", ""),
        "from": doc.headers.get("From", ""),
        "sent_date": doc.sent_date,
        "source_chars": len(rendered.combined_text()),
        "image_count": len(rendered.images),
        "stages": stages,
        "tool_calls": [],
        "candidates": [],
    }

    content = build_user_content(rendered, sent_date=doc.sent_date)

    # --- Stage 1: is this an RFQ at all? -------------------------------------
    with _stage(stages, "classify"):
        classification = (await _run(classifier, content)).output

    if not classification.is_rfq:
        extras["total_ms"] = _ms(t0)
        return PipelineOutcome(
            result=NonRfqResult(
                confidence=round(classification.confidence, 2),
                reason=classification.reason,
            ),
            extras=extras,
        )

    # --- Stage 2: pull out candidates and header-level fields ----------------
    try:
        with _stage(stages, "extract"):
            extraction: Extraction = (await _run(extractor, content)).output
    except ModelUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("extraction failed")
        extras["total_ms"] = _ms(t0)
        return PipelineOutcome(
            result=NonRfqResult(
                confidence=0.0,
                reason=f"classified as an RFQ but extraction failed ({type(exc).__name__}); "
                "needs manual review",
            ),
            extras=extras,
        )

    model_warnings: list[str] = list(extraction.warnings)
    warnings += extraction.warnings
    extras["candidates"] = [c.model_dump() for c in extraction.candidates]

    # --- Stage 3: resolve candidates against the catalogue -------------------
    # Chunked and concurrent above RESOLVE_CHUNK_SIZE; identical single call below it.
    line_items: list[LineItem] = []
    if extraction.candidates:
        with _stage(stages, "resolve"):
            line_items, resolve_warnings, tool_calls, degraded = await _resolve_all(
                extraction.candidates, doc.sent_date
            )
        warnings += resolve_warnings
        model_warnings += resolve_warnings
        extras["tool_calls"] = tool_calls
        extras["resolve_chunks"] = max(
            1, -(-len(extraction.candidates) // RESOLVE_CHUNK_SIZE)
        )

    # --- Stage 4: verification (spec Option A + the reverse omission check) ---
    # Runs on OUR data, not the model's word for it. Never deletes; flags and restores.
    report = verify(
        line_items,
        extraction.candidates,
        rendered.combined_text(),
        has_images=bool(rendered.images),
    )
    line_items = line_items + report.restored_items
    warnings += report.warnings
    extras["classification_confidence"] = round(classification.confidence, 2)
    extras["verification"] = {
        "unverified_parts": report.unverified_parts,
        "unverified_quantities": report.unverified_quantities,
        "unverifiable_parts": report.unverifiable_parts,
        "restored_items": report.dropped,
    }

    extras["total_ms"] = _ms(t0)
    return PipelineOutcome(
        result=build_rfq_result(
            classification_confidence=classification.confidence,
            customer=extraction.customer or Customer(),
            request=extraction.request or RequestMeta(),
            line_items=line_items,
            warnings=warnings,
            model_warning_count=len(model_warnings),
            injection_detected=injection_detected,
            degraded=degraded,
            source_unreadable=source_unreadable,
            unverified_parts=report.unverified_parts,
            unverified_quantities=report.unverified_quantities,
            restored_items=report.dropped,
            unverifiable_parts=report.unverifiable_parts,
        ),
        extras=extras,
    )


# --------------------------------------------------------------------------- #

async def _resolve_all(
    candidates: list[Candidate], sent_date: str | None
) -> tuple[list[LineItem], list[str], list[dict], bool]:
    """Resolve every candidate, chunking concurrently only when it is worth it.

    Returns (line_items, warnings, tool_calls, degraded).

    At or below RESOLVE_CHUNK_SIZE this is exactly the old single call. Above it,
    candidates are split into fixed-size chunks run under a concurrency cap, and
    results are merged in candidate order. A chunk that fails degrades only its own
    slice — the rest of the RFQ still resolves normally.
    """
    if len(candidates) <= RESOLVE_CHUNK_SIZE:
        return await _resolve_chunk(candidates, sent_date)

    chunks = [
        candidates[i : i + RESOLVE_CHUNK_SIZE]
        for i in range(0, len(candidates), RESOLVE_CHUNK_SIZE)
    ]
    log.info("resolving %d candidates in %d chunks", len(candidates), len(chunks))

    # Bounded fan-out: unbounded gather over a large RFQ would hit provider limits.
    sem = asyncio.Semaphore(RESOLVE_MAX_CONCURRENCY)

    async def _guarded(chunk: list[Candidate]):
        async with sem:
            return await _resolve_chunk(chunk, sent_date)

    results = await asyncio.gather(*(_guarded(c) for c in chunks))

    items: list[LineItem] = []
    warnings: list[str] = []
    tool_calls: list[dict] = []
    degraded = False
    for chunk_items, chunk_warnings, chunk_tools, chunk_degraded in results:
        items += chunk_items          # gather preserves order, so candidate order holds
        warnings += chunk_warnings
        tool_calls += chunk_tools
        degraded = degraded or chunk_degraded
    return items, warnings, tool_calls, degraded


async def _resolve_chunk(
    candidates: list[Candidate], sent_date: str | None
) -> tuple[list[LineItem], list[str], list[dict], bool]:
    """One resolve call. Its own failure degrades only these candidates."""
    try:
        run = await _run(resolve_agent, _resolve_prompt(candidates, sent_date))
        return run.output.line_items, list(run.output.warnings), _tool_calls(run), False
    except ModelUnavailable:
        raise  # a missing key is not per-chunk; fail the whole request
    except Exception as exc:  # noqa: BLE001
        # The agent is enrichment. Losing it degrades quality, not the contract:
        # fall back to unresolved candidates so no requirement is lost.
        log.exception("resolution failed for a chunk; falling back to raw candidates")
        parts = ", ".join(c.part_hint for c in candidates[:3])
        return (
            _fallback_items(candidates),
            [
                f"extraction degraded: catalogue resolution failed ({type(exc).__name__}) "
                f"for {len(candidates)} line item(s) starting {parts!r}. These are "
                "unverified against the catalogue and their quantities are unparsed."
            ],
            [],
            True,
        )


async def _run(agent, content):
    """Run a model call, translating provider faults into ModelUnavailable.

    This mapping is load-bearing. Anything that means "we could not get an answer
    from the model" must NOT fall through to a stage's generic `except`, because
    those turn a failure into a contract-shaped `isRfq: false` — which asserts the
    email is not an RFQ when we never actually read it, and would make a
    downstream system skip a real requirement.

    Observed in the wild: an exhausted credit balance surfaces as a
    ModelHTTPError(400) and was being reported as "classified as an RFQ but
    extraction failed", confidence 0.0. Wrong answer to the wrong question — the
    honest response is 503, meaning retry.
    """
    try:
        return await agent.run(content)
    except UserError as exc:
        # PydanticAI raises UserError for a missing or invalid provider key.
        raise ModelUnavailable(str(exc)) from exc
    except ModelHTTPError as exc:
        # Credit exhausted, rate limited, overloaded, auth rejected, upstream 5xx.
        raise ModelUnavailable(
            f"the model provider rejected the request (HTTP {exc.status_code}): {exc.message}"
        ) from exc


def _resolve_prompt(candidates: list[Candidate], sent_date: str | None) -> str:
    """The resolve stage sees our own structured candidates, not raw email text."""
    lines = [
        "Resolve these extracted candidates into final line items.",
        f"Email sent date: {sent_date or 'unknown'}.",
        "",
        "Candidates:",
    ]
    for i, c in enumerate(candidates, 1):
        lines.append(
            f"{i}. part_hint={c.part_hint!r} mfr_hint={c.mfr_hint!r} "
            f"qty_expr={c.qty_expr!r} target_price={c.target_price!r} notes={c.notes!r}"
        )
    lines += [
        "",
        "Call lookup_parts ONCE with every part_hint. Use compute_quantity for any "
        "derived quantity. Return one line item per candidate — never drop one.",
    ]
    return "\n".join(lines)


def _fallback_items(candidates: list[Candidate]) -> list[LineItem]:
    """Best-effort line items when the resolve agent is unavailable."""
    from ..catalog import canonical_manufacturer

    items = []
    for c in candidates:
        qty = 0
        digits = "".join(ch for ch in c.qty_expr if ch.isdigit())
        if digits:
            try:
                qty = int(digits)
            except ValueError:
                qty = 0
        items.append(
            LineItem(
                part_number=c.part_hint,
                manufacturer=canonical_manufacturer(c.mfr_hint),
                description=None,
                quantity=qty,
                target_price=c.target_price,
                notes=(c.notes or None),
            )
        )
    return items


# Tools we actually expose. PydanticAI also emits an internal output tool
# ("final_result") to carry the structured result; that is machinery, not a
# tool call an operator cares about, so it is filtered out.
_OUR_TOOLS = {"lookup_parts", "compute_quantity"}


def _tool_calls(run) -> list[dict]:
    calls = []
    for msg in run.all_messages():
        for part in getattr(msg, "parts", []):
            if isinstance(part, ToolCallPart) and part.tool_name in _OUR_TOOLS:
                calls.append({"tool": part.tool_name, "args": part.args})
    return calls


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


class _stage:
    """Context manager recording per-stage status and duration for the dashboard."""

    def __init__(self, store: dict, name: str):
        self.store, self.name = store, name

    def __enter__(self):
        self.t = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.store[self.name] = {
            "status": "ok" if exc_type is None else f"failed: {exc_type.__name__}",
            "ms": _ms(self.t),
        }
        return False

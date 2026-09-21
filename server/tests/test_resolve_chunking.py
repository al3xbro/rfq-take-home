"""Chunked concurrent resolve.

No sample email is large enough to reach this path (the biggest is 8 candidates
against a chunk size of 20), so it is covered with synthetic candidates. These
tests exercise the chunking/merging/concurrency logic directly by stubbing
`_resolve_chunk`, rather than going through a stubbed model — the new code is the
orchestration, not the call.
"""
from __future__ import annotations

import asyncio

import pytest

from rfq_extractor.config import RESOLVE_CHUNK_SIZE
from rfq_extractor.pipeline import run as run_mod
from rfq_extractor.pipeline.models import Candidate
from rfq_extractor.schema import LineItem


def candidates(n: int) -> list[Candidate]:
    return [
        Candidate(part_hint=f"PART-{i:04d}", qty_expr=str(i + 1), source_span=f"PART-{i:04d}")
        for i in range(n)
    ]


def fake_chunk_factory(calls: list, *, fail_on=None, track=None):
    """Stub for _resolve_chunk that echoes its input back as line items."""

    async def fake(chunk, sent_date):
        calls.append(list(chunk))
        if track is not None:
            track["now"] += 1
            track["max"] = max(track["max"], track["now"])
        await asyncio.sleep(0.01)  # force real overlap so concurrency is observable
        if track is not None:
            track["now"] -= 1
        if fail_on is not None and chunk[0].part_hint == fail_on:
            return run_mod._fallback_items(chunk), ["extraction degraded: simulated"], [], True
        items = [LineItem(part_number=c.part_hint, quantity=int(c.qty_expr)) for c in chunk]
        return items, [], [{"tool": "lookup_parts", "args": {"queries": [c.part_hint for c in chunk]}}], False

    return fake


async def test_small_batch_takes_the_single_call_path(monkeypatch):
    """At or below the threshold, behaviour is identical to before chunking existed."""
    calls: list = []
    monkeypatch.setattr(run_mod, "_resolve_chunk", fake_chunk_factory(calls))

    items, warnings, tools, degraded = await run_mod._resolve_all(candidates(8), None)

    assert len(calls) == 1, "small batches must not be split"
    assert len(items) == 8
    assert not degraded and not warnings


async def test_batch_at_exact_threshold_is_not_split(monkeypatch):
    calls: list = []
    monkeypatch.setattr(run_mod, "_resolve_chunk", fake_chunk_factory(calls))

    await run_mod._resolve_all(candidates(RESOLVE_CHUNK_SIZE), None)

    assert len(calls) == 1


async def test_large_batch_is_chunked(monkeypatch):
    calls: list = []
    monkeypatch.setattr(run_mod, "_resolve_chunk", fake_chunk_factory(calls))
    n = RESOLVE_CHUNK_SIZE * 2 + 5

    items, _, tools, degraded = await run_mod._resolve_all(candidates(n), None)

    assert len(calls) == 3, "expected ceil(45/20) = 3 chunks"
    assert [len(c) for c in calls] == [RESOLVE_CHUNK_SIZE, RESOLVE_CHUNK_SIZE, 5]
    assert len(items) == n, "every candidate must survive chunking"
    assert len(tools) == 3, "tool calls merge across chunks"
    assert not degraded


async def test_candidate_order_is_preserved_across_chunks(monkeypatch):
    """Merged output must stay in candidate order, not completion order."""
    monkeypatch.setattr(run_mod, "_resolve_chunk", fake_chunk_factory([]))
    n = RESOLVE_CHUNK_SIZE * 3

    items, _, _, _ = await run_mod._resolve_all(candidates(n), None)

    assert [li.part_number for li in items] == [f"PART-{i:04d}" for i in range(n)]


async def test_concurrency_is_capped(monkeypatch):
    """Unbounded fan-out on a large RFQ would hit provider rate limits."""
    from rfq_extractor.config import RESOLVE_MAX_CONCURRENCY

    track = {"now": 0, "max": 0}
    monkeypatch.setattr(run_mod, "_resolve_chunk", fake_chunk_factory([], track=track))

    await run_mod._resolve_all(candidates(RESOLVE_CHUNK_SIZE * 12), None)

    assert track["max"] <= RESOLVE_MAX_CONCURRENCY, f"peaked at {track['max']}"
    assert track["max"] > 1, "chunks should actually run concurrently"


async def test_one_failing_chunk_degrades_only_its_own_slice(monkeypatch):
    """A bad chunk must not lose the rest of the RFQ."""
    calls: list = []
    monkeypatch.setattr(
        run_mod, "_resolve_chunk", fake_chunk_factory(calls, fail_on="PART-0020")
    )
    n = RESOLVE_CHUNK_SIZE * 2 + 5

    items, warnings, _, degraded = await run_mod._resolve_all(candidates(n), None)

    assert len(items) == n, "failing chunk still contributes fallback items"
    assert degraded is True
    assert any("degraded" in w for w in warnings)
    # The healthy chunks still resolved with real quantities.
    assert items[0].quantity == 1


async def test_model_unavailable_is_not_swallowed_per_chunk(monkeypatch):
    """A missing key is a whole-request failure, not a per-chunk degradation."""

    async def boom(chunk, sent_date):
        raise run_mod.ModelUnavailable("no key")

    monkeypatch.setattr(run_mod, "_resolve_chunk", boom)

    with pytest.raises(run_mod.ModelUnavailable):
        await run_mod._resolve_all(candidates(RESOLVE_CHUNK_SIZE * 2), None)

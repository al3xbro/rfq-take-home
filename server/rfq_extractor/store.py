"""In-memory result store.

Process-local and deliberately not persisted: results live for the lifetime of
the server and are gone on restart. The spec says no database is required, and
writing a JSON mirror turned out to be worse than nothing — stale results from
previous runs reappeared in the UI as "history" nobody had asked for.

If results ever need to outlive the process, that is a real datastore decision,
not a file next to the code.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

_lock = asyncio.Lock()
_results: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def add(result: dict, extras: dict, *, filename: str | None = None) -> str:
    record_id = uuid.uuid4().hex[:12]
    record = {
        "id": record_id,
        "receivedAt": _now(),
        "filename": filename,
        "result": result,
        "extras": extras,
    }
    async with _lock:
        _results[record_id] = record
    return record_id


def get(record_id: str) -> dict | None:
    return _results.get(record_id)


def list_all() -> list[dict]:
    """Newest first."""
    return sorted(_results.values(), key=lambda r: r["receivedAt"], reverse=True)


async def clear() -> None:
    async with _lock:
        _results.clear()

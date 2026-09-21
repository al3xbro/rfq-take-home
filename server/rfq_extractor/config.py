"""Paths and model configuration. API key comes from the environment, never committed."""
from __future__ import annotations

import os
from pathlib import Path

# Load server/.env before anything reads the environment, so `uvicorn` picked up
# directly (not just via run.sh) still sees the key. Real environment variables
# always win over the file — `override=False` is deliberate.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:  # pragma: no cover - dotenv is a declared dependency
    pass

# server/rfq_extractor/config.py -> server/ -> repo root
SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SERVER_DIR.parent
SAMPLES_DIR = REPO_ROOT / "samples"
CATALOG_PATH = SAMPLES_DIR / "parts-catalog.csv"

MODEL = os.environ.get("RFQ_MODEL", "anthropic:claude-opus-5")

# Attachment text longer than this is truncated before going to the model.
# We warn rather than silently dropping content.
MAX_ATTACHMENT_CHARS = 200_000

# Chunked concurrent resolve. At or below CHUNK_SIZE the pipeline takes the plain
# single-call path, so ordinary RFQs behave exactly as before.
#
# Sizing is measured, not guessed: ~54 output tokens per line item against
# max_tokens=16_000 gives a hard ceiling near 177 items, and a resolve call costs
# roughly 4.3s fixed + 0.9s per item. Because of that fixed cost, chunks smaller
# than ~10 just multiply overhead once concurrency is capped. The cap exists so a
# large RFQ cannot fan out into a provider rate limit.
RESOLVE_CHUNK_SIZE = int(os.environ.get("RFQ_RESOLVE_CHUNK_SIZE", "20"))
RESOLVE_MAX_CONCURRENCY = int(os.environ.get("RFQ_RESOLVE_CONCURRENCY", "5"))


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))

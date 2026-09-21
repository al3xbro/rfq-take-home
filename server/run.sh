#!/usr/bin/env bash
# Start the RFQ extractor API + dashboard on http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating venv..."
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "WARNING: ANTHROPIC_API_KEY is not set — POST /ingest will return 503."
  echo "         The dashboard and stored results still work."
fi

exec .venv/bin/uvicorn rfq_extractor.app:app --host 0.0.0.0 --port "${PORT:-8000}" "$@"

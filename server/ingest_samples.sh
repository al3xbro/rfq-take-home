#!/usr/bin/env bash
# POST every sample email to a running server. Requires ANTHROPIC_API_KEY on the server.
set -euo pipefail
HOST="${HOST:-http://localhost:8000}"
for f in "$(dirname "$0")"/../samples/*.eml; do
  printf '%-40s ' "$(basename "$f")"
  curl -s -X POST "$HOST/ingest" -H 'Content-Type: message/rfc822' --data-binary "@$f" \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); print("isRfq=%-5s conf=%.2f items=%-3s warnings=%s" % (d["isRfq"], d["confidence"], len(d.get("lineItems") or []), len(d.get("warnings") or [])))'
done

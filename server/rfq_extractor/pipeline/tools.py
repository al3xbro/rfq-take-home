"""Tools available to the resolve agent."""
from __future__ import annotations

from ..catalog import lookup_many
from .agents import resolve_agent

# A per-board figure beyond this is almost certainly a misread, not a real BOM.
_MAX_PER_UNIT = 100_000
_MAX_UNITS = 10_000_000


@resolve_agent.tool_plain
def lookup_parts(queries: list[str]) -> list[dict]:
    """Look up part numbers in the distributor's canonical catalogue.

    Call this ONCE with every part number you need to check, rather than once per
    part. Matching is normalised, so case, spacing and punctuation do not matter.

    Args:
        queries: Part numbers as the customer wrote them.

    Returns:
        One result per query, each with a `status`:
          - "exact": exactly one confident match; adopt its canonical values.
          - "ambiguous": several variants matched. Do NOT choose one — keep the
            customer's original part number and warn, naming the candidates.
          - "not_found": absent from the catalogue. Normal, not an error. Keep the
            customer's part number and warn.
    """
    return [m.as_tool_payload() for m in lookup_many(queries)]


@resolve_agent.tool_plain
def compute_quantity(per_unit: int, unit_count: int, basis: str) -> dict:
    """Multiply out a per-unit quantity into a total. Use this for every derived
    quantity instead of calculating yourself — it returns an auditable derivation
    string that must be recorded in the line item's `notes`.

    Args:
        per_unit: How many of this part are needed for one unit, e.g. 2.
        unit_count: How many units are being built, e.g. 500.
        basis: What one unit is, singular, e.g. "board" or "panel".

    Returns:
        `total` and a human-readable `derivation`.
    """
    if per_unit < 0 or unit_count < 0:
        return {"error": "quantities cannot be negative", "total": 0, "derivation": ""}
    if per_unit > _MAX_PER_UNIT or unit_count > _MAX_UNITS:
        return {
            "error": "implausibly large input; re-read the source rather than guessing",
            "total": 0,
            "derivation": "",
        }
    total = per_unit * unit_count
    unit = basis.strip() or "unit"
    return {
        "total": total,
        "derivation": f"{per_unit} per {unit} x {unit_count} {unit}s = {total}",
    }

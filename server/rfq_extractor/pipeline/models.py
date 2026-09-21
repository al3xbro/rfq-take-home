"""Internal models passed between pipeline stages.

These are not the wire contract — they carry extra working state (raw quantity
expressions, provenance spans) that is deliberately kept out of /ingest.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..schema import Customer, LineItem, RequestMeta


class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_rfq: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class Candidate(BaseModel):
    """One potential part, captured verbatim. No interpretation yet."""

    model_config = ConfigDict(extra="forbid")

    part_hint: str = Field(description="Part number exactly as the customer wrote it.")
    mfr_hint: str | None = Field(
        default=None, description="Manufacturer as written, e.g. 'TI', 'ON Semi'."
    )
    qty_expr: str = Field(
        default="",
        description="Quantity exactly as written: '500', '100-150', '2 per board'. "
        "Empty string when no quantity is stated.",
    )
    target_price: float | None = None
    notes: str | None = None
    source_span: str = Field(
        default="",
        description="Verbatim snippet from the source that this came from.",
    )


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer: Customer
    request: RequestMeta
    candidates: list[Candidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Resolution(BaseModel):
    """Agent output: candidates turned into final line items."""

    model_config = ConfigDict(extra="forbid")

    line_items: list[LineItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

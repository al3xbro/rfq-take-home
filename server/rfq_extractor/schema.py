"""The output contract.

This module is the single source of truth for what `POST /ingest` returns.
Downstream ERP code maps straight off these shapes, so two rules hold everywhere:

1. Null fields are PRESENT, never omitted. `"phone": null` is part of the contract.
   Nothing here may be serialised with `exclude_none=True`.
2. The wire format is camelCase (`isRfq`, `lineItems`, `partNumber`). Python stays
   snake_case; the alias generator bridges the two. Always dump `by_alias=True`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

Priority = Literal["low", "medium", "high", "urgent"]


class ContractModel(BaseModel):
    """Base for anything that crosses the wire."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class Customer(ContractModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    company: str | None = None


class RequestMeta(ContractModel):
    due_date: str | None = Field(
        default=None,
        description="ISO date YYYY-MM-DD, or null if no date is stated.",
    )
    priority: Priority = Field(
        default="medium",
        description="Default 'medium'. Escalate only on explicit urgency language "
        "or a tight stated deadline.",
    )
    special_instructions: str | None = None


class LineItem(ContractModel):
    part_number: str = Field(description="Manufacturer part number, as best determined.")
    manufacturer: str | None = None
    description: str | None = None
    quantity: int = Field(default=0, description="Integer; 0 when not stated.")
    target_price: float | None = None
    notes: str | None = None


class RfqResult(ContractModel):
    is_rfq: Literal[True] = True
    confidence: float = Field(ge=0.0, le=1.0)
    customer: Customer
    request: RequestMeta
    line_items: list[LineItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NonRfqResult(ContractModel):
    is_rfq: Literal[False] = False
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(description="One line on why this is not an RFQ.")


IngestResult = RfqResult | NonRfqResult


def to_wire(result: IngestResult) -> dict:
    """Serialise to the exact contract shape.

    `by_alias=True` gives camelCase; omitting `exclude_none` keeps nulls present.
    Both are load-bearing — see the module docstring.
    """
    return result.model_dump(by_alias=True)

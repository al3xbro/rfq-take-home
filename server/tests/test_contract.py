"""The output contract must hold on every path — that is what ERP code depends on."""
from __future__ import annotations

import pytest

from rfq_extractor.schema import (
    Customer,
    LineItem,
    NonRfqResult,
    RequestMeta,
    RfqResult,
    to_wire,
)

RFQ_KEYS = {"isRfq", "confidence", "customer", "request", "lineItems", "warnings"}
NON_RFQ_KEYS = {"isRfq", "confidence", "reason"}


def test_rfq_shape_is_exactly_the_contract():
    wire = to_wire(
        RfqResult(
            confidence=0.9,
            customer=Customer(name="John Smith", email="j@acme.com"),
            request=RequestMeta(),
            line_items=[LineItem(part_number="LM358N", quantity=500)],
        )
    )
    assert set(wire) == RFQ_KEYS
    assert set(wire["customer"]) == {"name", "email", "phone", "company"}
    assert set(wire["request"]) == {"dueDate", "priority", "specialInstructions"}
    assert set(wire["lineItems"][0]) == {
        "partNumber", "manufacturer", "description", "quantity", "targetPrice", "notes",
    }


def test_non_rfq_shape_is_exactly_the_contract():
    assert set(to_wire(NonRfqResult(confidence=0.95, reason="newsletter"))) == NON_RFQ_KEYS


def test_nulls_are_present_not_omitted():
    """Regression guard: a later `exclude_none` would silently break ERP mapping."""
    wire = to_wire(
        RfqResult(
            confidence=0.5,
            customer=Customer(),
            request=RequestMeta(),
            line_items=[LineItem(part_number="X")],
        )
    )
    assert wire["customer"] == {"name": None, "email": None, "phone": None, "company": None}
    assert wire["request"]["dueDate"] is None
    assert wire["lineItems"][0]["targetPrice"] is None
    assert wire["lineItems"][0]["manufacturer"] is None


def test_wire_format_is_camel_case():
    wire = to_wire(
        RfqResult(
            confidence=0.5,
            customer=Customer(),
            request=RequestMeta(due_date="2026-03-15"),
            line_items=[LineItem(part_number="X", target_price=1.1)],
        )
    )
    assert "isRfq" in wire and "is_rfq" not in wire
    assert "lineItems" in wire and "line_items" not in wire
    assert wire["request"]["dueDate"] == "2026-03-15"
    assert wire["lineItems"][0]["partNumber"] == "X"


@pytest.mark.parametrize("bad", [-0.1, 1.5])
def test_confidence_is_bounded(bad):
    with pytest.raises(Exception):
        NonRfqResult(confidence=bad, reason="x")


def test_quantity_defaults_to_zero_not_null():
    """Contract says integer, 0 if not stated — never null."""
    assert to_wire(
        RfqResult(
            confidence=0.5, customer=Customer(), request=RequestMeta(),
            line_items=[LineItem(part_number="X")],
        )
    )["lineItems"][0]["quantity"] == 0

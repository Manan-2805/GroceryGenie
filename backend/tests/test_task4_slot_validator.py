"""
Task 4 verification tests for slot_validator.py.

Tests:
  1. validate() demo case: seller_create_product with only name → asks for price + stock
  2. validate() complete: all required fields present → is_complete=True
  3. validate() manage_addresses add: missing city → asks for city
  4. validate() manage_addresses add: all fields → complete
  5. merge() type coercion: price "$4.99" → float 4.99, stock "100" → int 100
  6. merge() price coercion failure keeps original and logs (no crash)
  7. merge() with LLM mock — extracted fields merged into partial
  8. validate() unknown tool → treated as complete (no crash)
  9. validate() optional-only tool (view_cart) → always complete
  10. Type coercion: bool field "yes" → True
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent.slot_validator import _coerce_types, validate

# ---------------------------------------------------------------------------
# validate tests (pure — no LLM, no Redis)
# ---------------------------------------------------------------------------


def test_validate_seller_create_missing_price_and_stock():
    """Demo case from the plan: name present, price and stock missing."""
    is_complete, missing, ask = validate("seller_create_product", {"name": "Mango"})
    assert not is_complete
    assert "price" in missing
    assert "stock" in missing
    assert "Mango" in ask  # "I have: name: Mango" should appear
    assert "price" in ask
    assert "stock" in ask


def test_validate_seller_create_complete():
    """All required fields present → complete."""
    is_complete, missing, ask = validate(
        "seller_create_product",
        {"name": "Mango", "price": 4.99, "stock": 100},
    )
    assert is_complete
    assert missing == []
    assert ask == ""


def test_validate_seller_create_have_str_shown():
    """When name is provided, 'I have: name: ...' should appear in ask text."""
    _, _, ask = validate(
        "seller_create_product", {"name": "Fresh Apple", "price": 2.99}
    )
    assert "Fresh Apple" in ask
    assert "stock" in ask


def test_validate_address_add_missing_city():
    """manage_addresses add: city missing → asks for city."""
    params = {
        "action": "add",
        "address_data": {
            "label": "Home",
            "line1": "B-63 Street 5",
            "state": "Gujarat",
            "postal_code": "370001",
        },
    }
    is_complete, missing, ask = validate("manage_addresses", params)
    assert not is_complete
    assert "city" in missing
    assert "city" in ask


def test_validate_address_add_complete():
    """manage_addresses add: all required fields → complete."""
    params = {
        "action": "add",
        "address_data": {
            "label": "Home",
            "line1": "B-63 Street 5",
            "city": "Bhuj",
            "state": "Gujarat",
            "postal_code": "370001",
        },
    }
    is_complete, missing, ask = validate("manage_addresses", params)
    assert is_complete
    assert missing == []


def test_validate_address_list_action_always_complete():
    """manage_addresses list action needs no address fields → complete."""
    is_complete, missing, _ = validate("manage_addresses", {"action": "list"})
    assert is_complete
    assert missing == []


def test_validate_unknown_tool_treated_as_complete():
    """Unknown tool name → treated as complete (RBAC handles unknown tools)."""
    is_complete, missing, ask = validate("totally_made_up_tool", {"foo": "bar"})
    assert is_complete
    assert missing == []
    assert ask == ""


def test_validate_view_cart_always_complete():
    """view_cart has no required fields → always complete."""
    is_complete, missing, _ = validate("view_cart", {})
    assert is_complete
    assert missing == []


def test_validate_submit_rating_missing_stars():
    """submit_rating: order_id and product_id present but stars missing."""
    params = {
        "order_id": "some-uuid",
        "product_id": "other-uuid",
    }
    is_complete, missing, ask = validate("submit_rating", params)
    assert not is_complete
    assert "stars" in missing
    assert "stars" in ask


def test_validate_update_order_status_missing_new_status():
    """update_order_status: order_ids present but new_status missing."""
    is_complete, missing, ask = validate(
        "update_order_status",
        {"order_ids": ["uuid-1", "uuid-2"]},
    )
    assert not is_complete
    assert "new_status" in missing


def test_validate_seller_update_stock_both_required():
    """seller_update_stock: both product_id and delta required."""
    is_complete, missing, _ = validate("seller_update_stock", {"product_id": "uuid-1"})
    assert not is_complete
    assert "delta" in missing

    is_complete2, missing2, _ = validate(
        "seller_update_stock", {"product_id": "uuid-1", "delta": 10}
    )
    assert is_complete2
    assert missing2 == []


# ---------------------------------------------------------------------------
# Type coercion tests (_coerce_types — pure, no I/O)
# ---------------------------------------------------------------------------


def test_coerce_price_string_to_float():
    """'$4.99' → 4.99 as float."""
    result = _coerce_types(
        {"price": "$4.99", "stock": "100"}, {"price": float, "stock": int}
    )
    assert result["price"] == pytest.approx(4.99)
    assert result["stock"] == 100


def test_coerce_int_with_decimal_string():
    """'100.0' → 100 as int."""
    result = _coerce_types({"stock": "100.0"}, {"stock": int})
    assert result["stock"] == 100


def test_coerce_bool_yes_to_true():
    """'yes' → True for bool field."""
    result = _coerce_types({"in_stock_only": "yes"}, {"in_stock_only": bool})
    assert result["in_stock_only"] is True


def test_coerce_bool_false_string():
    """'false' → False for bool field."""
    result = _coerce_types({"in_stock_only": "false"}, {"in_stock_only": bool})
    assert result["in_stock_only"] is False


def test_coerce_failure_keeps_original():
    """Coercion failure keeps the original value — no crash."""
    result = _coerce_types({"price": "free"}, {"price": float})
    # Original value preserved on failure
    assert result["price"] == "free"


def test_coerce_already_correct_type_unchanged():
    """Values already of the correct type are unchanged."""
    result = _coerce_types({"price": 4.99, "stock": 10}, {"price": float, "stock": int})
    assert result["price"] == pytest.approx(4.99)
    assert result["stock"] == 10


def test_coerce_none_value_skipped():
    """None values are skipped, not coerced."""
    result = _coerce_types({"price": None}, {"price": float})
    assert result["price"] is None


# ---------------------------------------------------------------------------
# merge tests (mock LLM)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_extracts_price_and_stock():
    """merge() for seller_create_product: LLM returns price+stock, merged into partial."""
    partial = {"name": "Mango"}
    user_msg = "price 4.99 stock 100 category Fruits"

    llm_response = '{"name": null, "price": "4.99", "stock": "100", "category": "Fruits", "description": null}'

    with patch(
        "app.services.agent.slot_validator.call_llm",
        new=AsyncMock(return_value=llm_response),
    ):
        from app.services.agent.slot_validator import merge

        result = await merge("seller_create_product", partial, user_msg)

    assert result["name"] == "Mango"  # preserved from partial
    assert result["price"] == pytest.approx(4.99)  # coerced from "4.99"
    assert result["stock"] == 100  # coerced from "100"
    assert result["category"] == "Fruits"


@pytest.mark.asyncio
async def test_merge_address_uses_address_extract():
    """merge() for manage_addresses routes through _extract_address_fields."""
    partial = {"action": "add", "address_data": {"label": "Home"}}
    user_msg = "B-63 Street 5, Bhuj, Gujarat, 370001"

    address_llm_response = (
        '{"label": null, "line1": "B-63 Street 5", "line2": null, '
        '"city": "Bhuj", "state": "Gujarat", "postal_code": "370001", "country": "India"}'
    )

    with patch(
        "app.services.agent.slot_validator.call_llm",
        new=AsyncMock(return_value=address_llm_response),
    ):
        from app.services.agent.slot_validator import merge

        result = await merge("manage_addresses", partial, user_msg)

    addr = result.get("address_data", {})
    assert addr.get("line1") == "B-63 Street 5"
    assert addr.get("city") == "Bhuj"
    assert addr.get("postal_code") == "370001"
    assert (
        addr.get("label") == "Home"
    )  # preserved from partial (extracted label was null)


@pytest.mark.asyncio
async def test_merge_llm_failure_returns_unchanged_partial():
    """If LLM returns empty string, partial_params is returned unchanged."""
    partial = {"name": "Mango", "price": 4.99}

    with patch(
        "app.services.agent.slot_validator.call_llm",
        new=AsyncMock(return_value=""),
    ):
        from app.services.agent.slot_validator import merge

        result = await merge("seller_create_product", partial, "some message")

    assert result["name"] == "Mango"
    assert result["price"] == pytest.approx(4.99)


@pytest.mark.asyncio
async def test_merge_does_not_overwrite_with_null():
    """Null values in LLM response must not overwrite existing partial values."""
    partial = {"name": "Mango", "price": 4.99, "stock": 50}
    llm_response = '{"name": null, "price": null, "stock": null, "category": "Fruits"}'

    with patch(
        "app.services.agent.slot_validator.call_llm",
        new=AsyncMock(return_value=llm_response),
    ):
        from app.services.agent.slot_validator import merge

        result = await merge("seller_create_product", partial, "category Fruits")

    assert result["name"] == "Mango"
    assert result["price"] == pytest.approx(4.99)
    assert result["stock"] == 50
    assert result["category"] == "Fruits"

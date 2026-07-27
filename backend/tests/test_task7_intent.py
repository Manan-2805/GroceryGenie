"""
Task 7 verification tests for intent.py.

All LLM calls are mocked. Tests verify:
  1. "my orders" as customer → view_orders
  2. "my orders" as seller  → list_fulfillment_orders  (BUG-01 fix)
  3. follow_up for non-actionable grocery question
  4. Seller view_orders remapping safety net (LLM slips through)
  5. is_first_message=True on empty history
  6. is_first_message=False on non-empty history
  7. Correct greeting for customer vs seller
  8. LLM failure → safe fallback
  9. JSON retry on malformed response
  10. fact_to_remember extracted and propagated
  11. Customer tool descriptions exclude seller tools
  12. Seller tool descriptions exclude view_orders
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.enums import UserRole
from app.services.agent.intent import _build_tool_descriptions, classify

# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_db():
    db = MagicMock()
    db.execute = AsyncMock()
    return db


def _llm_response(
    tool: str,
    params: dict | None = None,
    fact: str | None = None,
    category: str | None = None,
) -> str:
    return json.dumps(
        {
            "tool": tool,
            "params": params or {},
            "fact_to_remember": fact,
            "fact_category": category,
        }
    )


async def _run_classify(
    user_message: str, role: UserRole, llm_json: str, history: list | None = None
):
    """Helper: mock LLM + history + Mem0, call classify()."""
    history = history or []
    with (
        patch(
            "app.services.agent.intent.call_llm", new=AsyncMock(return_value=llm_json)
        ),
        patch(
            "app.services.agent.intent.get_history", new=AsyncMock(return_value=history)
        ),
        patch("app.services.agent.intent.Mem0") as mock_mem0_cls,
    ):
        mem0_instance = MagicMock()
        mem0_instance.search = AsyncMock(return_value=[])
        mock_mem0_cls.return_value = mem0_instance
        return await classify(
            user_message=user_message,
            user_role=role,
            session_id=str(uuid.uuid4()),
            db=_mock_db(),
            user_id=uuid.uuid4(),
        )


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_customer_my_orders_maps_to_view_orders():
    """Customer: 'my orders' → view_orders."""
    result = await _run_classify(
        "show me all my previous orders",
        UserRole.customer,
        _llm_response("view_orders"),
    )
    assert result.tool == "view_orders"


@pytest.mark.asyncio
async def test_seller_my_orders_maps_to_list_fulfillment_orders():
    """Seller: 'my orders' → list_fulfillment_orders (BUG-01 fix)."""
    result = await _run_classify(
        "show me all my orders",
        UserRole.seller,
        _llm_response("list_fulfillment_orders"),
    )
    assert result.tool == "list_fulfillment_orders"


@pytest.mark.asyncio
async def test_seller_view_orders_remapped_as_safety_net():
    """If LLM accidentally returns view_orders for a seller, remap to list_fulfillment_orders."""
    result = await _run_classify(
        "show pending orders",
        UserRole.seller,
        _llm_response("view_orders"),  # LLM erroneously returns view_orders
    )
    assert result.tool == "list_fulfillment_orders", (
        "Seller 'view_orders' must be remapped to list_fulfillment_orders (BUG-01)"
    )


@pytest.mark.asyncio
async def test_follow_up_grocery_question():
    """Non-actionable grocery question → follow_up tool."""
    result = await _run_classify(
        "what is the difference between jasmine and basmati rice?",
        UserRole.customer,
        _llm_response("follow_up"),
    )
    assert result.tool == "follow_up"


@pytest.mark.asyncio
async def test_is_first_message_true_on_empty_history():
    result = await _run_classify(
        "hello",
        UserRole.customer,
        _llm_response("out_of_scope"),
        history=[],
    )
    assert result.is_first_message is True


@pytest.mark.asyncio
async def test_is_first_message_false_on_existing_history():
    history = [
        {"role": "user", "content": "add milk"},
        {"role": "assistant", "content": "Added milk to cart."},
    ]
    result = await _run_classify(
        "what else?",
        UserRole.customer,
        _llm_response("out_of_scope"),
        history=history,
    )
    assert result.is_first_message is False


@pytest.mark.asyncio
async def test_customer_greeting_on_first_message():
    result = await _run_classify(
        "hi",
        UserRole.customer,
        _llm_response("out_of_scope"),
        history=[],
    )
    assert result.is_first_message is True
    assert "GroceryGenie" in result.greeting


@pytest.mark.asyncio
async def test_seller_greeting_on_first_message():
    result = await _run_classify(
        "hi",
        UserRole.seller,
        _llm_response("out_of_scope"),
        history=[],
    )
    assert result.is_first_message is True
    assert "seller mode" in result.greeting.lower()


@pytest.mark.asyncio
async def test_llm_failure_returns_safe_fallback():
    with (
        patch("app.services.agent.intent.call_llm", new=AsyncMock(return_value="")),
        patch("app.services.agent.intent.get_history", new=AsyncMock(return_value=[])),
        patch("app.services.agent.intent.Mem0") as mock_mem0_cls,
    ):
        mem0_instance = MagicMock()
        mem0_instance.search = AsyncMock(return_value=[])
        mock_mem0_cls.return_value = mem0_instance
        result = await classify(
            "show my orders",
            UserRole.customer,
            str(uuid.uuid4()),
            _mock_db(),
            uuid.uuid4(),
        )
    assert result.tool == "out_of_scope"
    assert isinstance(result.params, dict)


@pytest.mark.asyncio
async def test_malformed_json_retried_then_succeeds():
    """First call returns garbage JSON, second retry returns valid JSON."""
    good_response = _llm_response("view_cart")
    call_count = 0

    async def mock_llm(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "this is not json at all !!!"
        return good_response

    with (
        patch("app.services.agent.intent.call_llm", new=mock_llm),
        patch("app.services.agent.intent.get_history", new=AsyncMock(return_value=[])),
        patch("app.services.agent.intent.Mem0") as mock_mem0_cls,
    ):
        mem0_instance = MagicMock()
        mem0_instance.search = AsyncMock(return_value=[])
        mock_mem0_cls.return_value = mem0_instance
        result = await classify(
            "show cart", UserRole.customer, str(uuid.uuid4()), _mock_db(), uuid.uuid4()
        )

    assert result.tool == "view_cart"
    assert call_count == 2


@pytest.mark.asyncio
async def test_fact_to_remember_propagated():
    """Fact extracted by LLM is set on IntentResult."""
    llm_json = _llm_response(
        "search_products",
        params={"query": "milk"},
        fact="Is lactose intolerant",
        category="dietary",
    )
    result = await _run_classify(
        "find lactose-free milk, I'm lactose intolerant", UserRole.customer, llm_json
    )
    assert result.fact_to_remember == "Is lactose intolerant"
    assert result.fact_category == "dietary"


@pytest.mark.asyncio
async def test_null_fact_is_none():
    """LLM returning null for fact_to_remember results in None."""
    result = await _run_classify(
        "show my cart",
        UserRole.customer,
        _llm_response("view_cart", fact=None),
    )
    assert result.fact_to_remember is None


@pytest.mark.asyncio
async def test_params_stripped_of_none_values():
    """None values in LLM params are stripped before returning."""
    llm_json = json.dumps(
        {
            "tool": "search_products",
            "params": {"query": "milk", "category": None, "min_price": None},
            "fact_to_remember": None,
            "fact_category": None,
        }
    )
    result = await _run_classify("find milk", UserRole.customer, llm_json)
    assert "category" not in result.params
    assert "min_price" not in result.params
    assert result.params.get("query") == "milk"


# ── Tool description scoping ──────────────────────────────────────────────────


def test_customer_tool_descriptions_exclude_seller_tools():
    descs = _build_tool_descriptions(UserRole.customer)
    assert "seller_create_product" not in descs
    assert "list_fulfillment_orders" not in descs
    assert "inventory_search" not in descs
    assert "seller_bulk_deactivate" not in descs
    # Customer tools must be present
    assert "view_orders" in descs
    assert "add_to_cart" in descs
    assert "submit_rating" in descs


def test_seller_tool_descriptions_exclude_view_orders():
    descs = _build_tool_descriptions(UserRole.seller)
    assert "view_orders" not in descs, (
        "Seller must NOT see view_orders in tool descriptions"
    )
    # Seller tools must be present
    assert "list_fulfillment_orders" in descs
    assert "seller_create_product" in descs
    assert "inventory_search" in descs
    assert "seller_bulk_deactivate" in descs


def test_shared_tools_in_both_role_descriptions():
    for role in (UserRole.customer, UserRole.seller):
        descs = _build_tool_descriptions(role)
        assert "switch_role" in descs
        assert "toggle_theme" in descs
        assert "manage_facts" in descs

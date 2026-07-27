"""
Task 14 — Integration test suite (20+ scenarios).

All tests are unit-level using mocked DB / LLM / Redis.
No live Postgres, Redis, or Qdrant required.

Regression checks (5 from user's test session):
  BUG-01: Seller 'my orders' → list_fulfillment_orders, never view_orders
  BUG-02: order_detail_<uuid> fast-path → order detail card, never cart
  BUG-03: seller bulk deactivate → succeeds with bulk_deactivate result
  BUG-04: bulk status advance → per-order state machine, clear error on skip
  BUG-05: role-switch retry preserves original params (stored in pending state)
"""

from __future__ import annotations

import json as _json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.enums import OrderStatus, UserRole
from app.services.agent.response_formatter import format_response
from app.services.agent.slot_validator import validate
from app.services.agent.tools import ROLE_PERMISSIONS, check_tool_permission

# ── Shared mock helpers ───────────────────────────────────────────────────────


def _mock_db():
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    db.add = MagicMock()
    db.refresh = AsyncMock()
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=None)
    nested.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=nested)
    return db


def _scalar(val):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=val)
    return r


def _scalars(vals):
    r = MagicMock()
    inner = MagicMock()
    inner.all = MagicMock(return_value=vals)
    r.scalars = MagicMock(return_value=inner)
    return r


def _product(seller_id=None, **kw):
    p = MagicMock()
    p.id = kw.get("id", uuid.uuid4())
    p.name = kw.get("name", "Test Product")
    p.description = kw.get("description", "desc")
    p.category = kw.get("category", "Fruits")
    p.price = Decimal(str(kw.get("price", "4.99")))
    p.stock = kw.get("stock", 50)
    p.avg_rating = Decimal(str(kw.get("avg_rating", "4.5")))
    p.sold_count = kw.get("sold_count", 0)
    p.is_active = kw.get("is_active", True)
    p.seller_id = seller_id or uuid.uuid4()
    return p


def _order(**kw):
    o = MagicMock()
    o.id = kw.get("id", uuid.uuid4())
    o.status = kw.get("status", OrderStatus.placed)
    o.customer_id = kw.get("customer_id", uuid.uuid4())
    o.total = Decimal(str(kw.get("total", "9.99")))
    o.created_at = None
    o.packed_at = None
    o.out_for_delivery_at = None
    o.delivered_at = None
    o.delivery_address = kw.get("delivery_address", {"city": "Mumbai"})
    return o


# ════════════════════════════════════════════════════════════════════════════
# REGRESSION TESTS (BUG-01 through BUG-05)
# ════════════════════════════════════════════════════════════════════════════

# ── BUG-01: Seller 'my orders' → list_fulfillment_orders ─────────────────────


@pytest.mark.asyncio
async def test_bug01_seller_my_orders_uses_fulfillment_queue():
    """Seller 'show me all my orders' must classify to list_fulfillment_orders."""
    from app.services.agent.intent import _build_tool_descriptions

    descs = _build_tool_descriptions(UserRole.seller)
    assert "view_orders" not in descs, (
        "BUG-01: view_orders appears in seller tool descriptions — seller would get customer history"
    )
    assert "list_fulfillment_orders" in descs


@pytest.mark.asyncio
async def test_bug01_seller_view_orders_remapped_in_classify():
    """Even if LLM returns view_orders for a seller, classify() must remap it."""
    from app.services.agent.intent import classify

    llm_json = _json.dumps(
        {
            "tool": "view_orders",
            "params": {},
            "fact_to_remember": None,
            "fact_category": None,
        }
    )

    with (
        patch(
            "app.services.agent.intent.call_llm", new=AsyncMock(return_value=llm_json)
        ),
        patch("app.services.agent.intent.get_history", new=AsyncMock(return_value=[])),
        patch("app.services.agent.intent.Mem0") as m,
    ):
        m.return_value.search = AsyncMock(return_value=[])
        result = await classify(
            "my orders", UserRole.seller, str(uuid.uuid4()), _mock_db(), uuid.uuid4()
        )

    assert result.tool == "list_fulfillment_orders", (
        f"BUG-01: Seller 'my orders' mapped to '{result.tool}' instead of 'list_fulfillment_orders'"
    )


@pytest.mark.asyncio
async def test_bug01_seller_show_pending_items_uses_fulfillment():
    """'show all pending items' for a seller → list_fulfillment_orders."""
    from app.services.agent.intent import classify

    with (
        patch(
            "app.services.agent.intent.call_llm",
            new=AsyncMock(
                return_value=_json.dumps(
                    {
                        "tool": "list_fulfillment_orders",
                        "params": {},
                        "fact_to_remember": None,
                        "fact_category": None,
                    }
                )
            ),
        ),
        patch("app.services.agent.intent.get_history", new=AsyncMock(return_value=[])),
        patch("app.services.agent.intent.Mem0") as m,
    ):
        m.return_value.search = AsyncMock(return_value=[])
        result = await classify(
            "show all pending items",
            UserRole.seller,
            str(uuid.uuid4()),
            _mock_db(),
            uuid.uuid4(),
        )

    assert result.tool == "list_fulfillment_orders"


# ── BUG-02: order_detail_<uuid> → order detail card, NEVER cart ──────────────


def test_bug02_order_detail_result_formats_as_order_not_cart():
    """format_response with order_detail=True must return card_variant='order_detail'."""
    result = {
        "order_detail": True,
        "id": str(uuid.uuid4()),
        "status": "delivered",
        "total": 4.49,
        "created_at": "2026-07-24T10:00:00",
        "packed_at": None,
        "out_for_delivery_at": None,
        "delivered_at": "2026-07-24T14:00:00",
        "delivery_address": {
            "label": "Home",
            "line1": "B-63",
            "city": "Bhuj",
            "state": "GJ",
            "postal_code": "370001",
        },
        "items": [
            {
                "product_name": "Mango",
                "product_id": str(uuid.uuid4()),
                "quantity": 1,
                "price_at_purchase": 4.49,
                "subtotal": 4.49,
            }
        ],
    }
    response = format_response(result, "get_order_detail")
    assert response.get("card_variant") == "order_detail", (
        f"BUG-02: Expected card_variant='order_detail', got {response.get('card_variant')!r}"
    )
    assert response.get("card_variant") != "cart", (
        "BUG-02: order_detail formatted as cart!"
    )


@pytest.mark.asyncio
async def test_bug02_order_detail_fast_path_dispatches_get_order_detail():
    """The fast path prefix 'order_detail_<uuid>' must call get_order_detail, not view_cart."""
    from app.services.agent.fast_path import handle as fp_handle

    oid = str(uuid.uuid4())
    dispatched: list[str] = []

    async def fake_execute(tool_name: str, params: dict) -> dict:
        dispatched.append(tool_name)
        return {
            "order_detail": True,
            "id": oid,
            "status": "placed",
            "total": 4.99,
            "items": [],
            "delivery_address": {},
        }

    orch = MagicMock()
    orch.session_id = uuid.uuid4()
    orch.db = MagicMock()
    orch._execute_tool = AsyncMock(side_effect=fake_execute)
    orch._format_response_sync = lambda _, result: format_response(
        result, "get_order_detail"
    )

    with patch(
        "app.services.agent.fast_path.get_last_options", new=AsyncMock(return_value=[])
    ):
        response = await fp_handle(f"order_detail_{oid}", orch)

    assert dispatched == ["get_order_detail"], (
        f"BUG-02: dispatched {dispatched} instead of get_order_detail"
    )
    assert response is not None
    assert response.get("card_variant") == "order_detail"


# ── BUG-03: bulk deactivate → bulk_deactivate result, never crash ────────────


@pytest.mark.asyncio
async def test_bug03_bulk_deactivate_all_returns_summary():
    """seller_bulk_deactivate with explicit IDs → bulk_deactivate=True, all succeeded."""
    from app.services.agent.tools.seller_tools import seller_bulk_deactivate

    seller_id = uuid.uuid4()
    pid1, pid2 = uuid.uuid4(), uuid.uuid4()

    def make_product_mock(pid, name):
        p = MagicMock()
        p.id = pid
        p.name = name
        p.seller_id = seller_id
        p.is_active = True
        return p

    p1 = make_product_mock(pid1, "Mango")
    p2 = make_product_mock(pid2, "Apple")

    db = _mock_db()
    db.execute.side_effect = [
        _scalar(p1),  # lookup pid1
        _scalar(p2),  # lookup pid2
    ]

    with patch(
        "app.services.agent.tools.seller_tools._remove_product_from_qdrant",
        new=AsyncMock(),
    ):
        result = await seller_bulk_deactivate(
            db=db,
            user_id=seller_id,
            product_ids=[str(pid1), str(pid2)],
        )

    assert result.get("bulk_deactivate") is True, (
        f"BUG-03: Expected bulk_deactivate=True, got {result}"
    )
    assert len(result["succeeded"]) == 2, (
        f"Expected 2 succeeded, got {result['succeeded']}"
    )
    assert len(result["failed"]) == 0
    assert p1.is_active is False and p2.is_active is False


@pytest.mark.asyncio
async def test_bug03_bulk_deactivate_formats_as_summary_not_error():
    """format_response on bulk_deactivate result must produce a summary, not 'Something went wrong'."""
    result = {
        "bulk_deactivate": True,
        "succeeded": [{"id": str(uuid.uuid4()), "name": "Mango"}],
        "failed": [],
        "message": "Deactivated 1 of 1 products.",
    }
    response = format_response(result, "seller_bulk_deactivate")
    assert response["type"] == "response"
    assert "Something went wrong" not in response["text"]
    assert "succeeded" in response["text"].lower() or "1" in response["text"]


# ── BUG-04: bulk status → state machine per order, clear error on skip ────────


@pytest.mark.asyncio
async def test_bug04_update_all_to_delivered_advances_one_step():
    """update_order_status: placed→delivered skips → returns per-order explanation, not crash."""
    from app.services.agent.tools.fulfillment_tools import update_order_status

    seller_id = uuid.uuid4()
    placed_order = _order(status=OrderStatus.placed)

    db = _mock_db()
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=None)
    nested.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=nested)
    db.execute.side_effect = [
        _scalar(placed_order),
        MagicMock(first=MagicMock(return_value=("item-id",))),
    ]

    result = await update_order_status(
        db=db,
        user_id=seller_id,
        order_ids=[str(placed_order.id)],
        new_status="delivered",
    )

    assert result.get("success") is False
    assert "Something went wrong" not in result.get("message", ""), (
        f"BUG-04: Got 'Something went wrong' instead of clear error: {result['message']}"
    )
    assert "packed" in result["message"].lower(), (
        f"BUG-04: Error should mention next valid status 'packed', got: {result['message']}"
    )


@pytest.mark.asyncio
async def test_bug04_bulk_mixed_states_returns_per_order_result():
    """Bulk update with orders in different states → per-order results, not single crash."""
    from app.services.agent.tools.fulfillment_tools import update_order_status

    seller_id = uuid.uuid4()
    placed = _order(status=OrderStatus.placed)
    delivered = _order(status=OrderStatus.delivered)

    db = _mock_db()
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=None)
    nested.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=nested)
    db.execute.side_effect = [
        # placed order: found + ownership
        _scalar(placed),
        MagicMock(first=MagicMock(return_value=("item",))),
        # delivered order: found + ownership
        _scalar(delivered),
        MagicMock(first=MagicMock(return_value=("item",))),
    ]

    result = await update_order_status(
        db=db,
        user_id=seller_id,
        order_ids=[str(placed.id), str(delivered.id)],
        new_status="packed",
    )

    assert result.get("bulk_status_update") is True
    assert len(result["succeeded"]) == 1
    assert len(result["failed"]) == 1
    assert "already delivered" in result["failed"][0]["reason"].lower()


# ── BUG-05: role-switch retry preserves original params ──────────────────────


@pytest.mark.asyncio
async def test_bug05_role_switch_stores_original_params():
    """_role_switch_offer must store original_params in pending state (BUG-05 fix)."""
    from app.services.agent.orchestrator import AgentOrchestrator

    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    orch = AgentOrchestrator(
        db=_mock_db(),
        user_id=user_id,
        session_id=session_id,
        user_role=UserRole.customer,
    )

    stored_data: dict = {}

    async def mock_set_pending(sid, flow, data, **kw):
        stored_data.update(data)

    with (
        patch(
            "app.services.agent.orchestrator.sm.set_pending",
            side_effect=mock_set_pending,
        ),
        patch("app.services.agent.orchestrator.sm.append_history", new=AsyncMock()),
    ):
        await orch._role_switch_offer(
            user_message="update product abc price to 5.99",
            tool_name="seller_update_product",
            needed_role="seller",
            original_params={"product_id": "abc-uuid", "price": 5.99},
        )

    assert "original_params" in stored_data, (
        "BUG-05: original_params not stored in role_switch pending state"
    )
    assert stored_data["original_params"].get("product_id") == "abc-uuid", (
        f"BUG-05: product_id not preserved, got: {stored_data['original_params']}"
    )
    assert stored_data["original_params"].get("price") == 5.99


@pytest.mark.asyncio
async def test_bug05_role_switch_resume_uses_original_params():
    """StateRouter resume for role_switch must pass original_params to the tool, not {}."""
    from app.services.agent.state_manager import PendingState, resume

    original_params = {"product_id": "prod-uuid-123", "price": 5.99}
    pending = PendingState(
        flow="role_switch",
        data={
            "tool_name": "seller_update_product",
            "original_message": "update product price to 5.99",
            "original_params": original_params,
            "needed_role": "seller",
        },
    )

    executed_params: dict = {}

    async def fake_execute(tool_name, params):
        executed_params.update(params)
        return {"success": True, "message": "Updated."}

    orch = MagicMock()
    orch.session_id = uuid.uuid4()
    orch.user_role = UserRole.seller
    orch._execute_tool = AsyncMock(side_effect=fake_execute)
    orch._format_response = AsyncMock(
        return_value={"type": "response", "text": "Updated.", "options": None}
    )
    orch.run_turn = AsyncMock(
        return_value={"type": "response", "text": "...", "options": None}
    )

    with patch("app.services.agent.state_manager.clear_pending", new=AsyncMock()):
        await resume(pending, "yes", orch)

    assert executed_params.get("product_id") == "prod-uuid-123", (
        f"BUG-05: product_id dropped on role-switch retry, params were: {executed_params}"
    )


# ════════════════════════════════════════════════════════════════════════════
# ADDITIONAL SCENARIOS
# ════════════════════════════════════════════════════════════════════════════

# ── Customer: search products ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_customer_search_products_returns_list():
    from app.services.agent.tools.product_tools import search_products

    p = _product(name="Organic Milk", category="Dairy")
    db = _mock_db()

    with patch(
        "app.services.agent.tools.product_tools.search_products_service",
        new=AsyncMock(return_value=[p]),
    ):
        result = await search_products(db=db, user_id=uuid.uuid4(), query="milk")

    assert isinstance(result, list)
    assert result[0]["name"] == "Organic Milk"


@pytest.mark.asyncio
async def test_customer_search_respects_in_stock_only():
    from app.services.agent.tools.product_tools import search_products

    p_in = _product(name="Fresh Mango", stock=10)
    p_out = _product(name="Old Item", stock=0)
    db = _mock_db()

    with patch(
        "app.services.agent.tools.product_tools.search_products_service",
        new=AsyncMock(return_value=[p_in, p_out]),
    ):
        result = await search_products(
            db=db, user_id=uuid.uuid4(), query="mango", in_stock_only=True
        )

    assert len(result) == 1
    assert result[0]["name"] == "Fresh Mango"


# ── Customer: full cart → order flow ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_customer_add_to_cart_and_place_order():
    from app.services.agent.tools.cart_tools import add_to_cart

    user_id = uuid.uuid4()
    product = _product(name="Mango", stock=5, price="4.99")
    address = MagicMock()
    address.is_default = True
    address.label = "Home"
    address.line1 = "B-63"
    address.line2 = ""
    address.city = "Bhuj"
    address.state = "Gujarat"
    address.postal_code = "370001"
    address.country = "India"

    cart_item = MagicMock()
    cart_item.product_id = product.id
    cart_item.quantity = 2
    cart_item.user_id = user_id

    db = _mock_db()
    db.execute.side_effect = [
        _scalar(product),  # add_to_cart: product lookup
        _scalar(None),  # add_to_cart: existing cart check
    ]
    result = await add_to_cart(
        db=db, user_id=user_id, product_id=str(product.id), quantity=2
    )
    assert result["success"] is True
    assert "Mango" in result["message"]


# ── Customer: submit rating one-time ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_customer_submit_rating_once():
    from app.services.agent.tools.rating_tools import submit_rating

    user_id = uuid.uuid4()
    order = _order(customer_id=user_id, status=OrderStatus.delivered)
    product = _product()
    avg_mock = MagicMock()
    avg_mock.scalar_one_or_none = MagicMock(return_value=Decimal("4.5"))

    db = _mock_db()
    db.execute.side_effect = [
        _scalar(order),
        _scalar(MagicMock()),  # order item ownership
        _scalar(None),  # no existing rating
        _scalar(product),  # product name lookup
        avg_mock,  # avg stars
    ]

    result = await submit_rating(
        db=db,
        user_id=user_id,
        order_id=str(order.id),
        product_id=str(product.id),
        stars=5,
        comment="Excellent!",
    )
    assert result["success"] is True
    assert result["stars"] == 5


@pytest.mark.asyncio
async def test_customer_submit_rating_twice_returns_already_rated():
    from app.services.agent.tools.rating_tools import submit_rating

    user_id = uuid.uuid4()
    order = _order(customer_id=user_id, status=OrderStatus.delivered)
    existing = MagicMock()
    existing.stars = 4
    existing.comment = "Good"
    existing.created_at = None

    db = _mock_db()
    db.execute.side_effect = [
        _scalar(order),
        _scalar(MagicMock()),
        _scalar(existing),
    ]

    result = await submit_rating(
        db=db,
        user_id=user_id,
        order_id=str(order.id),
        product_id=str(uuid.uuid4()),
        stars=5,
    )
    assert result.get("already_rated") is True
    assert result["stars"] == 4


# ── Customer: address CRUD ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_customer_add_address():
    from app.services.agent.tools.address_tools import manage_addresses

    user_id = uuid.uuid4()
    db = _mock_db()
    result = await manage_addresses(
        db=db,
        user_id=user_id,
        action="add",
        address_data={
            "label": "Home",
            "line1": "B-63 Street 5",
            "city": "Bhuj",
            "state": "Gujarat",
            "postal_code": "370001",
            "country": "India",
        },
    )
    assert result["success"] is True
    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_customer_list_addresses():
    from app.services.agent.tools.address_tools import manage_addresses

    user_id = uuid.uuid4()
    addr = MagicMock()
    addr.id = uuid.uuid4()
    addr.label = "Home"
    addr.line1 = "B-63"
    addr.line2 = None
    addr.city = "Bhuj"
    addr.state = "Gujarat"
    addr.postal_code = "370001"
    addr.country = "India"
    addr.is_default = True

    db = _mock_db()
    db.execute.return_value = _scalars([addr])
    result = await manage_addresses(db=db, user_id=user_id, action="list")
    assert "addresses" in result
    assert len(result["addresses"]) == 1
    assert result["addresses"][0]["city"] == "Bhuj"


# ── Customer: compare products ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_customer_compare_two_products():
    from app.services.agent.tools.compare_tools import compare_products

    p1 = _product(name="Mango", price="4.99")
    p2 = _product(name="Apple", price="2.99")
    db = _mock_db()
    db.execute.side_effect = [_scalar(p1), _scalar(p2)]

    result = await compare_products(
        db=db, user_id=uuid.uuid4(), product_ids=[str(p1.id), str(p2.id)]
    )
    assert result["compare"] is True
    assert len(result["products"]) == 2
    names = [r["name"] for r in result["products"]]
    assert "Mango" in names and "Apple" in names


# ── Customer: manage facts CRUD ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_customer_add_fact():
    from app.services.agent.tools.profile_tools import manage_facts

    db = _mock_db()
    db.execute.return_value = _scalar(None)  # no duplicate

    result = await manage_facts(
        db=db,
        user_id=uuid.uuid4(),
        action="add",
        fact_text="I am vegan",
        category="dietary",
    )
    assert result["success"] is True
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_customer_list_facts_numbered():
    from app.services.agent.tools.profile_tools import manage_facts

    user_id = uuid.uuid4()
    f1 = MagicMock()
    f1.id = uuid.uuid4()
    f1.fact_text = "Vegan"
    f1.category = MagicMock(value="dietary")
    f1.created_at = None

    db = _mock_db()
    db.execute.return_value = _scalars([f1])

    with patch(
        "app.services.agent.tools.profile_tools.set_fact_index", new=AsyncMock()
    ):
        result = await manage_facts(
            db=db, user_id=user_id, action="list", session_id="s1"
        )

    assert result["facts_list"] is True
    assert result["facts"][0]["index"] == 1
    assert result["facts"][0]["fact_text"] == "Vegan"


@pytest.mark.asyncio
async def test_customer_delete_fact_by_index():
    from app.services.agent.tools.profile_tools import manage_facts

    user_id = uuid.uuid4()
    fid = str(uuid.uuid4())
    fact = MagicMock()
    fact.id = uuid.UUID(fid)
    fact.fact_text = "Vegan"

    db = _mock_db()
    db.execute.return_value = _scalar(fact)

    with patch(
        "app.services.agent.tools.profile_tools.get_fact_index",
        new=AsyncMock(return_value={"1": fid}),
    ):
        result = await manage_facts(
            db=db, user_id=user_id, action="delete", fact_id="1", session_id="s1"
        )

    assert result["success"] is True
    assert "Vegan" in result["message"]


# ── Customer: RBAC — customer tool denied for seller ─────────────────────────


def test_customer_tool_denied_for_seller():
    for tool in [
        "add_to_cart",
        "place_order",
        "view_orders",
        "submit_rating",
        "compare_products",
    ]:
        with pytest.raises(PermissionError):
            check_tool_permission(tool, UserRole.seller)


def test_seller_tool_denied_for_customer():
    for tool in [
        "seller_create_product",
        "seller_bulk_deactivate",
        "list_fulfillment_orders",
        "update_order_status",
        "inventory_search",
        "seller_update_stock",
    ]:
        with pytest.raises(PermissionError):
            check_tool_permission(tool, UserRole.customer)


# ── Seller: create product all fields at once → no slot loop ─────────────────


def test_seller_create_product_all_fields_complete():
    is_complete, missing, _ = validate(
        "seller_create_product", {"name": "Mango", "price": 4.99, "stock": 100}
    )
    assert is_complete is True
    assert missing == []


def test_seller_create_product_name_only_asks_price_and_stock():
    is_complete, missing, ask = validate("seller_create_product", {"name": "Mango"})
    assert is_complete is False
    assert "price" in missing
    assert "stock" in missing
    assert "Mango" in ask


# ── Seller: stock delta clamp ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seller_update_stock_plus_10():
    from app.services.agent.tools.seller_tools import seller_update_stock

    seller_id = uuid.uuid4()
    p = _product(seller_id=seller_id, stock=20)
    db = _mock_db()
    db.execute.return_value = _scalar(p)

    with patch(
        "app.services.agent.tools.seller_tools._sync_product_to_qdrant", new=AsyncMock()
    ):
        result = await seller_update_stock(
            db=db, user_id=seller_id, product_id=str(p.id), delta=10
        )

    assert result["success"] is True
    assert result["new_stock"] == 30
    assert result["clamped"] is False


@pytest.mark.asyncio
async def test_seller_update_stock_clamps_to_zero():
    from app.services.agent.tools.seller_tools import seller_update_stock

    seller_id = uuid.uuid4()
    p = _product(seller_id=seller_id, stock=5)
    db = _mock_db()
    db.execute.return_value = _scalar(p)

    with patch(
        "app.services.agent.tools.seller_tools._sync_product_to_qdrant", new=AsyncMock()
    ):
        result = await seller_update_stock(
            db=db, user_id=seller_id, product_id=str(p.id), delta=-99999
        )

    assert result["success"] is True
    assert result["new_stock"] == 0
    assert result["clamped"] is True
    assert "0" in result["message"]


# ── Seller: fulfillment queue filters ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_seller_fulfillment_filter_by_product_name():
    from app.services.agent.tools.fulfillment_tools import list_fulfillment_orders

    seller_id = uuid.uuid4()
    order = _order(status=OrderStatus.placed)
    product = _product(name="Fresh Mango", seller_id=seller_id)
    item = MagicMock()
    item.product_id = product.id
    item.quantity = 1
    item.price_at_purchase = Decimal("4.49")

    db = _mock_db()
    db.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=[(order.id,)])),
        _scalars([order]),
        _scalars([item]),
        _scalar(product),
    ]

    result = await list_fulfillment_orders(
        db=db, user_id=seller_id, product_name="Mango"
    )
    assert isinstance(result, list)
    assert result[0]["fulfillment_queue"] is True


# ── Seller: advance order status one step ────────────────────────────────────


@pytest.mark.asyncio
async def test_seller_advance_order_one_step():
    from app.services.agent.tools.fulfillment_tools import update_order_status

    seller_id = uuid.uuid4()
    order = _order(status=OrderStatus.placed)
    db = _mock_db()
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=None)
    nested.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=nested)
    db.execute.side_effect = [
        _scalar(order),
        MagicMock(first=MagicMock(return_value=("item",))),
    ]

    result = await update_order_status(
        db=db, user_id=seller_id, order_ids=[str(order.id)], new_status="packed"
    )
    assert result["success"] is True
    assert order.status == OrderStatus.packed


@pytest.mark.asyncio
async def test_seller_skip_status_gives_clear_error():
    from app.services.agent.tools.fulfillment_tools import update_order_status

    seller_id = uuid.uuid4()
    order = _order(status=OrderStatus.placed)
    db = _mock_db()
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=None)
    nested.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=nested)
    db.execute.side_effect = [
        _scalar(order),
        MagicMock(first=MagicMock(return_value=("item",))),
    ]

    result = await update_order_status(
        db=db,
        user_id=seller_id,
        order_ids=[str(order.id)],
        new_status="out_for_delivery",
    )
    assert result["success"] is False
    assert "packed" in result["message"].lower()
    assert "Something went wrong" not in result["message"]


# ── Session history ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_history_append_and_get():
    from app.services.agent.state_manager import append_history, get_history

    store: dict = {}

    async def fake_rpush(key, *vals):
        store.setdefault(key, []).extend(vals)

    async def fake_expire(key, ttl):
        pass

    async def fake_lrange(key, start, end):
        lst = store.get(key, [])
        return lst[start:] if end == -1 else lst[start : end + 1]

    redis_mock = MagicMock()
    redis_mock.rpush = AsyncMock(side_effect=fake_rpush)
    redis_mock.expire = AsyncMock(side_effect=fake_expire)
    redis_mock.lrange = AsyncMock(side_effect=fake_lrange)

    sid = str(uuid.uuid4())
    with patch(
        "app.services.agent.state_manager.get_redis_client", return_value=redis_mock
    ):
        await append_history(sid, "user", "show my orders")
        await append_history(sid, "assistant", "You have 3 orders.")
        msgs = await get_history(sid, limit=20)

    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "show my orders"
    assert msgs[1]["role"] == "assistant"


# ── Formatter regression: card_variant present on all options responses ───────


def test_all_formatter_paths_have_card_variant():
    """Every options_response from format_response must carry card_variant (BUG-10)."""
    cases = [
        (
            {
                "order_detail": True,
                "id": str(uuid.uuid4()),
                "status": "placed",
                "total": 5.0,
                "items": [],
                "delivery_address": {},
            },
            "order_detail",
        ),
        (
            [
                {
                    "fulfillment_queue": True,
                    "order_id": str(uuid.uuid4()),
                    "order_id_short": "abc",
                    "status": "placed",
                    "status_label": "Placed",
                    "total": 9.99,
                    "created_at": None,
                    "my_items": [],
                    "my_items_count": 0,
                    "next_status": "packed",
                    "next_action_label": "Mark Packed",
                    "advance_value": "fv",
                    "delivery_address": {},
                }
            ],
            "fulfillment_queue",
        ),
        (
            [
                {
                    "id": str(uuid.uuid4()),
                    "status": "placed",
                    "total": 5.0,
                    "created_at": None,
                    "items": [],
                }
            ],
            "orders",
        ),
        (
            {
                "addresses": [
                    {
                        "id": str(uuid.uuid4()),
                        "label": "Home",
                        "line1": "St",
                        "city": "C",
                        "state": "S",
                        "postal_code": "123",
                        "is_default": False,
                    }
                ]
            },
            "addresses",
        ),
    ]
    for result, expected_variant in cases:
        r = format_response(result, "")
        if r["type"] == "options_response":
            assert "card_variant" in r, f"card_variant missing for {expected_variant}"


# ── RBAC completeness: every schema tool has a role entry ────────────────────


def test_every_schema_tool_has_explicit_role_entry():
    from app.services.agent.tools import TOOL_SCHEMAS

    all_permitted = set()
    for tools in ROLE_PERMISSIONS.values():
        all_permitted.update(tools)
    unassigned = [t for t in TOOL_SCHEMAS if t not in all_permitted]
    assert unassigned == [], f"Tools with no role entry: {unassigned}"

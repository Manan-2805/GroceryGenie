"""
Task 5 verification tests — new and updated tools.

All tests use mocked DB sessions (MagicMock / AsyncMock) so no live DB is needed.
Each test verifies return shape and key business rules.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_db():
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    db.add = MagicMock()
    db.refresh = AsyncMock()
    # begin_nested returns an async context manager
    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=nested_cm)
    return db


def _scalar_result(value):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=value)
    return r


def _scalars_result(values):
    r = MagicMock()
    inner = MagicMock()
    inner.all = MagicMock(return_value=values)
    r.scalars = MagicMock(return_value=inner)
    return r


def _make_product(**overrides):
    p = MagicMock()
    p.id = uuid.uuid4()
    p.name = overrides.get("name", "Test Product")
    p.description = overrides.get("description", "A test product")
    p.category = overrides.get("category", "Fruits")
    p.price = Decimal(str(overrides.get("price", "4.99")))
    p.stock = overrides.get("stock", 50)
    p.avg_rating = Decimal(str(overrides.get("avg_rating", "4.5")))
    p.sold_count = overrides.get("sold_count", 0)
    p.is_active = overrides.get("is_active", True)
    p.seller_id = overrides.get("seller_id", uuid.uuid4())
    return p


def _make_order(**overrides):
    from app.db.models.enums import OrderStatus

    o = MagicMock()
    o.id = overrides.get("id", uuid.uuid4())
    o.status = overrides.get("status", OrderStatus.delivered)
    o.customer_id = overrides.get("customer_id", uuid.uuid4())
    o.total = Decimal(str(overrides.get("total", "9.99")))
    o.created_at = None
    o.packed_at = None
    o.out_for_delivery_at = None
    o.delivered_at = None
    o.delivery_address = overrides.get(
        "delivery_address", {"city": "Mumbai", "label": "Home"}
    )
    return o


# ── 5a: compare_products ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compare_products_returns_compare_dict():
    from app.services.agent.tools.compare_tools import compare_products

    p1 = _make_product(name="Mango", price="4.99")
    p2 = _make_product(name="Apple", price="2.99")
    pid1, pid2 = str(p1.id), str(p2.id)

    db = _mock_db()
    db.execute.side_effect = [
        _scalar_result(p1),
        _scalar_result(p2),
    ]

    result = await compare_products(
        db=db, user_id=uuid.uuid4(), product_ids=[pid1, pid2]
    )

    assert result.get("compare") is True
    assert len(result["products"]) == 2
    assert result["products"][0]["name"] == "Mango"
    assert result["products"][1]["name"] == "Apple"


@pytest.mark.asyncio
async def test_compare_products_requires_at_least_two():
    from app.services.agent.tools.compare_tools import compare_products

    db = _mock_db()
    result = await compare_products(
        db=db, user_id=uuid.uuid4(), product_ids=["only-one"]
    )
    assert result.get("success") is False
    assert "2" in result["message"]


@pytest.mark.asyncio
async def test_compare_products_empty_ids():
    from app.services.agent.tools.compare_tools import compare_products

    db = _mock_db()
    result = await compare_products(db=db, user_id=uuid.uuid4(), product_ids=[])
    assert result.get("success") is False


@pytest.mark.asyncio
async def test_compare_products_invalid_uuid():
    from app.services.agent.tools.compare_tools import compare_products

    db = _mock_db()
    result = await compare_products(
        db=db, user_id=uuid.uuid4(), product_ids=["not-a-uuid", "also-not"]
    )
    assert result.get("success") is False


# ── 5b: submit_rating ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_rating_success():
    from app.services.agent.tools.rating_tools import submit_rating

    user_id = uuid.uuid4()
    order = _make_order(
        customer_id=user_id,
        status=__import__(
            "app.db.models.enums", fromlist=["OrderStatus"]
        ).OrderStatus.delivered,
    )
    product = _make_product()

    db = _mock_db()
    # execute calls: order lookup, order-item ownership, existing-rating check, product lookup, avg query
    avg_mock = MagicMock()
    avg_mock.scalar_one_or_none = MagicMock(return_value=Decimal("4.5"))

    db.execute.side_effect = [
        _scalar_result(order),  # order lookup
        _scalar_result(MagicMock()),  # order-item ownership check
        _scalar_result(None),  # no existing rating
        _scalar_result(product),  # product name lookup
        avg_mock,  # avg(stars) query
    ]

    result = await submit_rating(
        db=db,
        user_id=user_id,
        order_id=str(order.id),
        product_id=str(product.id),
        stars=5,
        comment="Great product!",
    )

    assert result.get("success") is True
    assert "Great product" in result["message"] or result["stars"] == 5
    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_submit_rating_already_rated():
    from app.db.models.enums import OrderStatus
    from app.services.agent.tools.rating_tools import submit_rating

    user_id = uuid.uuid4()
    order = _make_order(customer_id=user_id, status=OrderStatus.delivered)
    product = _make_product()

    existing_rating = MagicMock()
    existing_rating.stars = 4
    existing_rating.comment = "Was good"
    existing_rating.created_at = None

    db = _mock_db()
    db.execute.side_effect = [
        _scalar_result(order),
        _scalar_result(MagicMock()),  # ownership
        _scalar_result(existing_rating),
    ]

    result = await submit_rating(
        db=db,
        user_id=user_id,
        order_id=str(order.id),
        product_id=str(product.id),
        stars=5,
    )

    assert result.get("already_rated") is True
    assert result["stars"] == 4
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_submit_rating_not_delivered():
    from app.db.models.enums import OrderStatus
    from app.services.agent.tools.rating_tools import submit_rating

    user_id = uuid.uuid4()
    order = _make_order(customer_id=user_id, status=OrderStatus.placed)

    db = _mock_db()
    db.execute.side_effect = [_scalar_result(order)]

    result = await submit_rating(
        db=db,
        user_id=user_id,
        order_id=str(order.id),
        product_id=str(uuid.uuid4()),
        stars=4,
    )

    assert result.get("success") is False
    assert "delivered" in result["message"].lower()


@pytest.mark.asyncio
async def test_submit_rating_invalid_stars():
    from app.services.agent.tools.rating_tools import submit_rating

    db = _mock_db()
    result = await submit_rating(
        db=db,
        user_id=uuid.uuid4(),
        order_id=str(uuid.uuid4()),
        product_id=str(uuid.uuid4()),
        stars=10,
    )
    assert result.get("success") is False
    assert "1" in result["message"] and "5" in result["message"]


# ── 5c: manage_facts ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_manage_facts_list():
    from app.services.agent.tools.profile_tools import manage_facts

    fact = MagicMock()
    fact.id = uuid.uuid4()
    fact.fact_text = "Vegan"
    fact.category = MagicMock()
    fact.category.value = "dietary"
    fact.created_at = None

    db = _mock_db()
    db.execute.return_value = _scalars_result([fact])

    with patch(
        "app.services.agent.tools.profile_tools.set_fact_index", new=AsyncMock()
    ):
        result = await manage_facts(
            db=db, user_id=uuid.uuid4(), action="list", session_id="sess-1"
        )

    assert result.get("facts_list") is True
    assert len(result["facts"]) == 1
    assert result["facts"][0]["fact_text"] == "Vegan"
    assert result["facts"][0]["index"] == 1


@pytest.mark.asyncio
async def test_manage_facts_add():
    from app.services.agent.tools.profile_tools import manage_facts

    db = _mock_db()
    # No duplicate found
    db.execute.return_value = _scalar_result(None)

    result = await manage_facts(
        db=db,
        user_id=uuid.uuid4(),
        action="add",
        fact_text="Allergic to peanuts",
        category="dietary",
    )

    assert result.get("success") is True
    assert "peanuts" in result["message"].lower()
    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_manage_facts_add_duplicate():
    from app.services.agent.tools.profile_tools import manage_facts

    existing = MagicMock()
    db = _mock_db()
    db.execute.return_value = _scalar_result(existing)

    result = await manage_facts(
        db=db,
        user_id=uuid.uuid4(),
        action="add",
        fact_text="Allergic to peanuts",
    )
    assert result.get("success") is False
    assert "already" in result["message"].lower()


@pytest.mark.asyncio
async def test_manage_facts_delete_not_found():
    from app.services.agent.tools.profile_tools import manage_facts

    db = _mock_db()
    db.execute.return_value = _scalar_result(None)

    with patch(
        "app.services.agent.tools.profile_tools.get_fact_index",
        new=AsyncMock(return_value={}),
    ):
        result = await manage_facts(
            db=db,
            user_id=uuid.uuid4(),
            action="delete",
            fact_id="1",
            session_id="sess-1",
        )

    assert result.get("success") is False
    assert "couldn't find" in result["message"].lower()


@pytest.mark.asyncio
async def test_manage_facts_unknown_action():
    from app.services.agent.tools.profile_tools import manage_facts

    db = _mock_db()
    result = await manage_facts(db=db, user_id=uuid.uuid4(), action="explode")
    assert result.get("success") is False
    assert "Unknown action" in result["message"]


# ── 5d: seller_update_stock ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seller_update_stock_adds():
    from app.services.agent.tools.seller_tools import seller_update_stock

    seller_id = uuid.uuid4()
    product = _make_product(stock=10, seller_id=seller_id)

    db = _mock_db()
    db.execute.return_value = _scalar_result(product)

    with patch(
        "app.services.agent.tools.seller_tools._sync_product_to_qdrant", new=AsyncMock()
    ):
        result = await seller_update_stock(
            db=db,
            user_id=seller_id,
            product_id=str(product.id),
            delta=5,
        )

    assert result.get("success") is True
    assert product.stock == 15
    assert result["new_stock"] == 15
    assert result["old_stock"] == 10


@pytest.mark.asyncio
async def test_seller_update_stock_clamps_to_zero():
    from app.services.agent.tools.seller_tools import seller_update_stock

    seller_id = uuid.uuid4()
    product = _make_product(stock=3, seller_id=seller_id)

    db = _mock_db()
    db.execute.return_value = _scalar_result(product)

    with patch(
        "app.services.agent.tools.seller_tools._sync_product_to_qdrant", new=AsyncMock()
    ):
        result = await seller_update_stock(
            db=db,
            user_id=seller_id,
            product_id=str(product.id),
            delta=-99,
        )

    assert result.get("success") is True
    assert result["new_stock"] == 0
    assert result["clamped"] is True
    assert "0" in result["message"]


@pytest.mark.asyncio
async def test_seller_update_stock_product_not_found():
    from app.services.agent.tools.seller_tools import seller_update_stock

    db = _mock_db()
    db.execute.return_value = _scalar_result(None)

    result = await seller_update_stock(
        db=db,
        user_id=uuid.uuid4(),
        product_id=str(uuid.uuid4()),
        delta=10,
    )
    assert result.get("success") is False
    assert "not found" in result["message"].lower()


# ── 5e: seller_bulk_deactivate ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seller_bulk_deactivate_specific_ids():
    from app.services.agent.tools.seller_tools import seller_bulk_deactivate

    seller_id = uuid.uuid4()
    p1 = _make_product(seller_id=seller_id, name="Mango")
    p2 = _make_product(seller_id=seller_id, name="Apple")

    db = _mock_db()
    db.execute.side_effect = [
        _scalar_result(p1),
        _scalar_result(p2),
    ]

    with patch(
        "app.services.agent.tools.seller_tools._remove_product_from_qdrant",
        new=AsyncMock(),
    ):
        result = await seller_bulk_deactivate(
            db=db,
            user_id=seller_id,
            product_ids=[str(p1.id), str(p2.id)],
        )

    assert result.get("bulk_deactivate") is True
    assert len(result["succeeded"]) == 2
    assert len(result["failed"]) == 0
    assert p1.is_active is False
    assert p2.is_active is False


@pytest.mark.asyncio
async def test_seller_bulk_deactivate_invalid_uuid_in_list():
    from app.services.agent.tools.seller_tools import seller_bulk_deactivate

    db = _mock_db()
    result = await seller_bulk_deactivate(
        db=db,
        user_id=uuid.uuid4(),
        product_ids=["not-a-uuid"],
    )
    assert result.get("bulk_deactivate") is True
    assert len(result["failed"]) == 1
    assert "Invalid UUID" in result["failed"][0]["reason"]


@pytest.mark.asyncio
async def test_seller_bulk_deactivate_none_ids_rejected():
    from app.services.agent.tools.seller_tools import seller_bulk_deactivate

    db = _mock_db()
    result = await seller_bulk_deactivate(db=db, user_id=uuid.uuid4(), product_ids=None)
    assert result.get("success") is False


# ── 5f: view_orders with filters ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_view_orders_status_filter():
    from app.db.models.enums import OrderStatus
    from app.services.agent.tools.order_tools import view_orders

    user_id = uuid.uuid4()
    order_placed = _make_order(
        customer_id=user_id, status=OrderStatus.placed, total="5.00"
    )
    order_delivered = _make_order(
        customer_id=user_id, status=OrderStatus.delivered, total="9.00"
    )

    product = _make_product()

    item_mock = MagicMock()
    item_mock.product_id = product.id
    item_mock.quantity = 1
    item_mock.price_at_purchase = Decimal("5.00")

    db = _mock_db()
    # Responses: orders list, then items + product for each qualifying order
    db.execute.side_effect = [
        _scalars_result([order_placed, order_delivered]),  # orders query
        _scalars_result([item_mock]),  # items for placed order
        _scalar_result(product),  # product for item
    ]

    result = await view_orders(db=db, user_id=user_id, status="placed")
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["status"] == "placed"


@pytest.mark.asyncio
async def test_view_orders_empty_result():
    from app.services.agent.tools.order_tools import view_orders

    db = _mock_db()
    db.execute.return_value = _scalars_result([])

    result = await view_orders(db=db, user_id=uuid.uuid4())
    assert isinstance(result, dict)
    assert result.get("empty") is True


# ── 5g: list_fulfillment_orders filters ──────────────────────────────────────


@pytest.mark.asyncio
async def test_list_fulfillment_orders_product_name_filter():
    from app.db.models.enums import OrderStatus
    from app.services.agent.tools.fulfillment_tools import list_fulfillment_orders

    seller_id = uuid.uuid4()
    order = _make_order(status=OrderStatus.placed)

    product_match = _make_product(name="Fresh Mango", seller_id=seller_id)
    item_mock = MagicMock()
    item_mock.product_id = product_match.id
    item_mock.quantity = 2
    item_mock.price_at_purchase = Decimal("4.49")

    db = _mock_db()
    db.execute.side_effect = [
        # _get_seller_order_ids: returns one order id
        MagicMock(all=MagicMock(return_value=[(order.id,)])),
        _scalars_result([order]),  # orders query
        _scalars_result([item_mock]),  # seller's items in this order
        _scalar_result(product_match),  # product details
    ]

    result = await list_fulfillment_orders(
        db=db,
        user_id=seller_id,
        product_name="Mango",
    )

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["fulfillment_queue"] is True


@pytest.mark.asyncio
async def test_list_fulfillment_orders_customer_city_filter():
    from app.db.models.enums import OrderStatus
    from app.services.agent.tools.fulfillment_tools import list_fulfillment_orders

    seller_id = uuid.uuid4()
    order_mumbai = _make_order(
        status=OrderStatus.placed, delivery_address={"city": "Mumbai"}
    )
    order_delhi = _make_order(
        status=OrderStatus.placed, delivery_address={"city": "Delhi"}
    )

    product = _make_product(name="Milk", seller_id=seller_id)
    item_mock = MagicMock()
    item_mock.product_id = product.id
    item_mock.quantity = 1
    item_mock.price_at_purchase = Decimal("2.49")

    db = _mock_db()
    db.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=[(order_mumbai.id,), (order_delhi.id,)])),
        _scalars_result([order_mumbai, order_delhi]),
        _scalars_result([item_mock]),  # items for Mumbai order
        _scalar_result(product),
        # Delhi order is filtered out before items are fetched
    ]

    result = await list_fulfillment_orders(
        db=db,
        user_id=seller_id,
        customer_city="Mumbai",
    )

    assert isinstance(result, list)
    assert len(result) == 1


# ── 5h: update_order_status bulk ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_order_status_single_valid_transition():
    from app.db.models.enums import OrderStatus
    from app.services.agent.tools.fulfillment_tools import update_order_status

    seller_id = uuid.uuid4()
    order = _make_order(status=OrderStatus.placed)

    db = _mock_db()

    # begin_nested context manager — must work per savepoint
    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=nested_cm)

    db.execute.side_effect = [
        _scalar_result(order),  # order lookup
        MagicMock(first=MagicMock(return_value=("item-id",))),  # ownership
    ]

    result = await update_order_status(
        db=db,
        user_id=seller_id,
        order_ids=[str(order.id)],
        new_status="packed",
    )

    assert result.get("success") is True
    assert order.status == OrderStatus.packed


@pytest.mark.asyncio
async def test_update_order_status_invalid_transition():
    from app.db.models.enums import OrderStatus
    from app.services.agent.tools.fulfillment_tools import update_order_status

    seller_id = uuid.uuid4()
    order = _make_order(status=OrderStatus.placed)

    db = _mock_db()
    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=nested_cm)
    db.execute.side_effect = [
        _scalar_result(order),
        MagicMock(first=MagicMock(return_value=("item-id",))),
    ]

    # Try to skip directly to "delivered" from "placed" — invalid
    result = await update_order_status(
        db=db,
        user_id=seller_id,
        order_ids=[str(order.id)],
        new_status="delivered",
    )
    assert result.get("success") is False
    assert "packed" in result["message"].lower()


@pytest.mark.asyncio
async def test_update_order_status_bulk_partial_failure():
    from app.db.models.enums import OrderStatus
    from app.services.agent.tools.fulfillment_tools import update_order_status

    seller_id = uuid.uuid4()
    good_order = _make_order(status=OrderStatus.placed)
    bad_oid = str(uuid.uuid4())

    db = _mock_db()
    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=nested_cm)
    db.execute.side_effect = [
        # good order: found + ownership
        _scalar_result(good_order),
        MagicMock(first=MagicMock(return_value=("item-id",))),
        # bad order: not found
        _scalar_result(None),
    ]

    result = await update_order_status(
        db=db,
        user_id=seller_id,
        order_ids=[str(good_order.id), bad_oid],
        new_status="packed",
    )

    assert result.get("bulk_status_update") is True
    assert len(result["succeeded"]) == 1
    assert len(result["failed"]) == 1


@pytest.mark.asyncio
async def test_update_order_status_already_delivered():
    from app.db.models.enums import OrderStatus
    from app.services.agent.tools.fulfillment_tools import update_order_status

    seller_id = uuid.uuid4()
    order = _make_order(status=OrderStatus.delivered)

    db = _mock_db()
    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=nested_cm)
    db.execute.side_effect = [
        _scalar_result(order),
        MagicMock(first=MagicMock(return_value=("item-id",))),
    ]

    result = await update_order_status(
        db=db,
        user_id=seller_id,
        order_ids=[str(order.id)],
        new_status="delivered",
    )
    assert result.get("success") is False
    assert "already delivered" in result["message"].lower()


# ── TOOL_REGISTRY completeness check ────────────────────────────────────────


def test_all_new_tools_in_registry():
    """compare_products, submit_rating, manage_facts, seller_update_stock,
    seller_bulk_deactivate must all be callable in TOOL_REGISTRY."""
    from app.services.agent.tools import TOOL_REGISTRY

    for tool_name in [
        "compare_products",
        "submit_rating",
        "manage_facts",
        "seller_update_stock",
        "seller_bulk_deactivate",
    ]:
        assert tool_name in TOOL_REGISTRY, f"{tool_name!r} missing from TOOL_REGISTRY"
        assert callable(TOOL_REGISTRY[tool_name]), f"{tool_name!r} is not callable"


def test_rbac_tests_still_pass_after_task5():
    """Re-run key RBAC checks to confirm Task 5 didn't break Task 2."""
    # New tools obey RBAC
    import pytest as _pytest

    from app.db.models.enums import UserRole
    from app.services.agent.tools import check_tool_permission

    with _pytest.raises(PermissionError):
        check_tool_permission("submit_rating", UserRole.seller)
    with _pytest.raises(PermissionError):
        check_tool_permission("seller_bulk_deactivate", UserRole.customer)
    with _pytest.raises(PermissionError):
        check_tool_permission("seller_update_stock", UserRole.customer)
    with _pytest.raises(PermissionError):
        check_tool_permission("compare_products", UserRole.seller)

    # manage_facts is shared — both roles allowed
    check_tool_permission("manage_facts", UserRole.customer)
    check_tool_permission("manage_facts", UserRole.seller)

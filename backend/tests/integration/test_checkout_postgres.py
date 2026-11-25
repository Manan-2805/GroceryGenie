import asyncio
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.orders import advance_fulfillment
from app.commerce.cart import change_cart
from app.commerce.checkout import DeliveryAddress, confirm_checkout, create_quote
from app.db.models.cart import CartItem
from app.db.models.enums import OrderStatus, UserRole
from app.db.models.fulfillment import Fulfillment
from app.db.models.order import Order
from app.db.models.product import Product
from app.db.models.user import User

pytestmark = pytest.mark.postgres

ADDRESS = DeliveryAddress(
    line1="10 Demo Lane", city="Pune", state="Maharashtra", postal_code="411001"
)


async def setup_shop(
    sessions: async_sessionmaker[AsyncSession], *, stock: int
) -> tuple[list[UUID], list[UUID], list[UUID]]:
    async with sessions.begin() as db:
        users = [
            User(
                name=f"Test {idx}",
                google_sub=f"test:{uuid4()}",
                email="test@example.invalid",
                role=role,
            )
            for idx, role in enumerate(
                [UserRole.customer, UserRole.customer, UserRole.seller, UserRole.seller]
            )
        ]
        db.add_all(users)
        await db.flush()
        products = [
            Product(
                seller_id=user.id,
                name=f"Product {idx}",
                description="Fixture",
                category="Pantry",
                stock=stock,
                price=Decimal("49.95"),
            )
            for idx, user in enumerate(users[2:])
        ]
        db.add_all(products)
        await db.flush()
        return (
            [user.id for user in users[:2]],
            [user.id for user in users[2:]],
            [product.id for product in products],
        )


@pytest.mark.asyncio
async def test_multi_seller_checkout_scope_and_idempotency(sessions):
    customers, sellers, products = await setup_shop(sessions, stock=3)
    customer = customers[0]
    async with sessions.begin() as db:
        for product in products:
            await change_cart(db, customer, product, 2)
        quote = await create_quote(db, customer, ADDRESS, None)
        quote_id = quote.id

    key = str(uuid4())

    async def place() -> UUID:
        async with sessions.begin() as db:
            return await confirm_checkout(db, customer, quote_id, key)

    first, second = await asyncio.gather(place(), place())
    assert first == second
    async with sessions.begin() as db:
        order = await db.get(Order, first)
        assert order is not None and order.total == Decimal("199.80")
        children = list(
            await db.scalars(select(Fulfillment).where(Fulfillment.order_id == first))
        )
        assert {(child.seller_id, child.total) for child in children} == {
            (seller, Decimal("99.90")) for seller in sellers
        }
        count = await db.scalar(
            select(func.count())
            .select_from(CartItem)
            .where(CartItem.user_id == customer)
        )
        assert count == 0
        assert list(
            await db.scalars(select(Product.stock).where(Product.id.in_(products)))
        ) == [1, 1]
        child = children[0]
        other_seller = next(seller for seller in sellers if seller != child.seller_id)
        with pytest.raises(HTTPException) as error:
            await advance_fulfillment(db, other_seller, child.id, OrderStatus.packed)
        assert error.value.status_code == 404
        advanced = await advance_fulfillment(
            db, child.seller_id, child.id, OrderStatus.packed
        )
        assert advanced.status == OrderStatus.packed
        assert order.status == OrderStatus.placed


@pytest.mark.asyncio
async def test_last_unit_race_leaves_losing_cart_unchanged(sessions):
    customers, _, products = await setup_shop(sessions, stock=1)
    quotes = []
    for customer in customers:
        async with sessions.begin() as db:
            await change_cart(db, customer, products[0], 1)
            quotes.append((await create_quote(db, customer, ADDRESS, None)).id)

    async def place(customer: UUID, quote: UUID) -> UUID | None:
        try:
            async with sessions.begin() as db:
                return await confirm_checkout(db, customer, quote, str(uuid4()))
        except HTTPException as exc:
            assert exc.status_code == 409
            return None

    outcomes = await asyncio.gather(
        *(
            place(customer, quote)
            for customer, quote in zip(customers, quotes, strict=True)
        )
    )
    assert sum(order is not None for order in outcomes) == 1
    async with sessions.begin() as db:
        remaining_cart_items = await db.scalar(
            select(func.count())
            .select_from(CartItem)
            .where(CartItem.user_id.in_(customers))
        )
        assert remaining_cart_items == 1
        assert (
            await db.scalar(select(Product.stock).where(Product.id == products[0])) == 0
        )


@pytest.mark.asyncio
async def test_agent_approval_is_scoped_atomic_and_replayed(sessions, monkeypatch):
    from app.assistant import runner
    from app.assistant.schema import Cart, Plan
    from app.core.security import create_login_session
    from app.db.models.enums import ChatMode

    customers, _, products = await setup_shop(sessions, stock=5)
    buyer, other = customers
    monkeypatch.setattr(runner, "AsyncSessionFactory", sessions)

    async def fake_provider(message, _role, _context):
        return Plan(
            steps=[
                Cart(
                    tool="cart",
                    product_id=products[0],
                    quantity=2 if "two" in message else 1,
                    operation="add",
                ),
                Cart(tool="cart", product_id=products[1], quantity=1, operation="set"),
            ]
        )

    monkeypatch.setattr(runner, "interpret", fake_provider)
    async with sessions.begin() as db:
        token = create_login_session(db, await db.get(User, buyer))
        other_token = create_login_session(db, await db.get(User, other))
        chat = await runner.open_conversation(db, buyer, None, ChatMode.text)
    first = await runner.run_turn(chat, buyer, token, "Add two demo products")
    assert first.confirmation_id is not None
    async with sessions() as db:
        assert not list(
            await db.scalars(select(CartItem).where(CartItem.user_id == buyer))
        )

    with pytest.raises(HTTPException) as denied:
        await runner.run_turn(
            chat, other, other_token, "Confirm", first.confirmation_id, True
        )
    assert denied.value.status_code == 404

    second = await runner.run_turn(chat, buyer, token, "Add demo products")
    assert second.confirmation_id and second.confirmation_id != first.confirmation_id
    replaced = await runner.run_turn(
        chat, buyer, token, "Confirm", first.confirmation_id, True
    )
    assert "replaced" in replaced.text
    a, b = await asyncio.gather(
        *(
            runner.run_turn(chat, buyer, token, "Confirm", second.confirmation_id, True)
            for _ in range(2)
        )
    )
    assert a.text == b.text and a.text.startswith("Completed.")
    async with sessions() as db:
        cart = list(await db.scalars(select(CartItem).where(CartItem.user_id == buyer)))
        assert {item.product_id: item.quantity for item in cart} == {
            products[0]: 1,
            products[1]: 1,
        }

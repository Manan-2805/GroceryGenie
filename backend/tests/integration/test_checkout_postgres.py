import asyncio
import os
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set TEST_DATABASE_URL to the disposable migrated PostgreSQL database."
        )
    engine = create_async_engine(url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    finally:
        await engine.dispose()


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

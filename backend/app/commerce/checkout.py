from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.address import Address
from app.db.models.cart import CartItem
from app.db.models.checkout_quote import CheckoutQuote
from app.db.models.enums import UserRole
from app.db.models.fulfillment import Fulfillment
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.db.models.user import User

ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class DeliveryAddress(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    label: ShortText = "Delivery"
    line1: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]
    line2: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None
    ) = None
    city: ShortText
    state: ShortText
    postal_code: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=20)
    ]
    country: ShortText = "India"


class QuoteLine(BaseModel):
    product_id: UUID
    seller_id: UUID
    name: str
    package: str
    quantity: int
    price: Decimal


class QuoteSnapshot(BaseModel):
    cart_version: int
    address: DeliveryAddress
    address_id: UUID | None = None
    address_version: datetime | None = None
    lines: list[QuoteLine]
    total: Decimal


async def lock_customer(db: AsyncSession, user_id: UUID) -> User:
    user = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None or user.role != UserRole.customer:
        raise HTTPException(403, "Customer mode is required.")
    return user


async def checkout_cart(
    db: AsyncSession, customer_id: UUID
) -> tuple[list[CartItem], dict[UUID, Product]]:
    items = list(
        await db.scalars(
            select(CartItem)
            .where(CartItem.user_id == customer_id)
            .order_by(CartItem.product_id)
        )
    )
    if not items:
        raise HTTPException(409, "Your cart is empty.")
    products = {
        product.id: product
        for product in await db.scalars(
            select(Product)
            .where(Product.id.in_([item.product_id for item in items]))
            .order_by(Product.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    return items, products


def quote_lines(
    items: list[CartItem], products: dict[UUID, Product]
) -> list[QuoteLine]:
    result = []
    for item in items:
        product = products.get(item.product_id)
        if product is None or not product.is_active:
            raise HTTPException(409, "A product in your cart is no longer available.")
        if not 1 <= item.quantity <= product.stock:
            raise HTTPException(409, f"Insufficient stock for {product.name}.")
        result.append(
            QuoteLine(
                product_id=product.id,
                seller_id=product.seller_id,
                name=product.name,
                package=product.package,
                quantity=item.quantity,
                price=product.price,
            )
        )
    return result


async def get_address(db: AsyncSession, user_id: UUID, address_id: UUID) -> Address:
    address = await db.scalar(
        select(Address)
        .where(Address.id == address_id, Address.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if address is None:
        raise HTTPException(404, "Address not found.")
    return address


async def create_quote(
    db: AsyncSession,
    user_id: UUID,
    address: DeliveryAddress | None,
    address_id: UUID | None,
) -> CheckoutQuote:
    user = await lock_customer(db, user_id)
    address_version = None
    if address_id is not None:
        saved_address = await get_address(db, user_id, address_id)
        address_version = saved_address.updated_at
        address = DeliveryAddress.model_validate(saved_address)
    if address is None:
        raise HTTPException(422, "Select or enter a delivery address.")

    items, products = await checkout_cart(db, user_id)
    lines = quote_lines(items, products)
    total = sum((line.quantity * line.price for line in lines), Decimal("0"))
    quote = CheckoutQuote(
        customer_id=user_id,
        expires_at=utc_now() + timedelta(minutes=5),
        snapshot=QuoteSnapshot(
            cart_version=user.cart_version,
            address=address,
            address_id=address_id,
            address_version=address_version,
            lines=lines,
            total=total,
        ).model_dump(mode="json"),
    )
    db.add(quote)
    await db.flush()
    return quote


async def confirm_checkout(
    db: AsyncSession, user_id: UUID, quote_id: UUID, key: str
) -> UUID:
    user = await lock_customer(db, user_id)
    quote = await db.scalar(
        select(CheckoutQuote).where(
            CheckoutQuote.id == quote_id, CheckoutQuote.customer_id == user_id
        )
    )
    if quote is None:
        raise HTTPException(404, "Checkout quote not found.")
    previous = await db.scalar(
        select(Order.id).where(Order.customer_id == user_id, Order.checkout_key == key)
    )
    if previous is not None:
        if previous != quote.order_id:
            raise HTTPException(409, "That checkout key was used for another quote.")
        return previous
    if quote.order_id is not None:
        raise HTTPException(409, "This quote has already been used.")

    snapshot = QuoteSnapshot.model_validate(quote.snapshot)
    if quote.expires_at <= utc_now() or snapshot.cart_version != user.cart_version:
        raise HTTPException(409, "Your quote is stale. Review a new quote.")
    if snapshot.address_id is not None:
        address = await get_address(db, user_id, snapshot.address_id)
        if address.updated_at != snapshot.address_version:
            raise HTTPException(409, "Delivery address changed. Review a new quote.")
    items, products = await checkout_cart(db, user_id)
    if quote_lines(items, products) != snapshot.lines:
        raise HTTPException(409, "Products or prices changed. Review a new quote.")

    order = Order(
        customer_id=user_id,
        checkout_key=key,
        total=snapshot.total,
        delivery_address=snapshot.address.model_dump(),
    )
    totals: dict[UUID, Decimal] = defaultdict(Decimal)
    for line in snapshot.lines:
        totals[line.seller_id] += line.quantity * line.price
    fulfillments = {
        seller_id: Fulfillment(order=order, seller_id=seller_id, total=total)
        for seller_id, total in totals.items()
    }
    for item in items:
        product = products[item.product_id]
        order.items.append(
            OrderItem(
                fulfillment=fulfillments[product.seller_id],
                product_id=product.id,
                quantity=item.quantity,
                product_name=product.name,
                package_at_purchase=product.package,
                price_at_purchase=product.price,
                cost_at_purchase=product.cost_price,
            )
        )
        product.stock -= item.quantity
        product.sold_count += item.quantity
        await db.delete(item)
    user.cart_version += 1
    db.add(order)
    await db.flush()
    quote.order_id = order.id
    return order.id

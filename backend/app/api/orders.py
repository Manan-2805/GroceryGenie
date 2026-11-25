from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.commerce.checkout import (
    DeliveryAddress,
    QuoteSnapshot,
    confirm_checkout,
    create_quote,
)
from app.core.dependencies import get_current_customer, get_current_seller, get_db
from app.db.base import utc_now
from app.db.models.enums import OrderStatus
from app.db.models.fulfillment import Fulfillment
from app.db.models.order import Order, OrderItem
from app.db.models.rating import ProductRating
from app.db.models.user import User

router = APIRouter(prefix="/orders", tags=["Orders"])
Page = Annotated[int, Query(ge=1, le=10000)]
Limit = Annotated[int, Query(ge=1, le=100)]
ORDER_STEPS = list(OrderStatus)


class RatingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    stars: int
    comment: str | None


class OrderProductDetail(BaseModel):
    id: UUID
    name: str
    price: Decimal
    image_url: str | None


class OrderItemResponse(BaseModel):
    id: UUID
    product_id: UUID | None
    quantity: int
    price_at_purchase: Decimal
    product: OrderProductDetail | None
    rating: RatingResponse | None = None
    fulfillment_status: OrderStatus | None = None


class FulfillmentResponse(BaseModel):
    id: UUID
    seller_id: UUID
    status: OrderStatus
    total: Decimal
    items: list[OrderItemResponse]


class OrderResponse(BaseModel):
    id: UUID
    customer_id: UUID
    status: OrderStatus
    total: Decimal
    delivery_address: DeliveryAddress
    created_at: datetime
    items: list[OrderItemResponse]
    fulfillments: list[FulfillmentResponse] = []
    payment_status: str = "simulated"
    packed_at: datetime | None = None
    out_for_delivery_at: datetime | None = None
    delivered_at: datetime | None = None


class OrderPaginatedResponse(BaseModel):
    items: list[OrderResponse]
    total: int
    page: int
    limit: int
    pages: int


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address_id: UUID | None = None
    delivery_address: DeliveryAddress | None = None

    @model_validator(mode="after")
    def verify_address_choice(self) -> "QuoteRequest":
        if (self.address_id is None) == (self.delivery_address is None):
            raise ValueError("Specify one saved or new delivery address.")
        return self


class QuoteResponse(QuoteSnapshot):
    id: UUID
    expires_at: datetime
    payment_status: str = "simulated"


class PlaceOrderPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: UUID


class UpdateStatusPayload(BaseModel):
    status: OrderStatus


async def ratings_for(
    db: AsyncSession, order_ids: list[UUID]
) -> dict[tuple[UUID, UUID], ProductRating]:
    ratings = await db.scalars(
        select(ProductRating).where(ProductRating.order_id.in_(order_ids))
    )
    return {(rating.order_id, rating.product_id): rating for rating in ratings}


def order_item(
    item: OrderItem,
    ratings: dict[tuple[UUID, UUID], ProductRating],
    status: OrderStatus | None,
) -> OrderItemResponse:
    review = ratings.get((item.order_id, item.product_id)) if item.product_id else None
    product = None
    if item.product_id is not None:
        product = OrderProductDetail(
            id=item.product_id,
            name=item.product_name
            or (item.product.name if item.product else "Product"),
            price=item.price_at_purchase,
            image_url=item.product.image_url if item.product else None,
        )
    return OrderItemResponse(
        id=item.id,
        product_id=item.product_id,
        quantity=item.quantity,
        price_at_purchase=item.price_at_purchase,
        product=product,
        rating=RatingResponse.model_validate(review) if review else None,
        fulfillment_status=status,
    )


def order_projection(
    order: Order, ratings: dict[tuple[UUID, UUID], ProductRating]
) -> OrderResponse:
    child_map = {child.id: child for child in order.fulfillments}
    items = {
        item.id: order_item(
            item,
            ratings,
            child_map[item.fulfillment_id].status
            if item.fulfillment_id in child_map
            else order.status,
        )
        for item in order.items
    }
    return OrderResponse(
        id=order.id,
        customer_id=order.customer_id,
        status=order.status,
        total=order.total,
        delivery_address=DeliveryAddress.model_validate(order.delivery_address),
        created_at=order.created_at,
        items=list(items.values()),
        fulfillments=[
            FulfillmentResponse(
                id=child.id,
                seller_id=child.seller_id,
                status=child.status,
                total=child.total,
                items=[
                    items[item.id]
                    for item in order.items
                    if item.fulfillment_id == child.id
                ],
            )
            for child in order.fulfillments
        ],
        payment_status=order.payment_status,
        packed_at=order.packed_at,
        out_for_delivery_at=order.out_for_delivery_at,
        delivered_at=order.delivered_at,
    )


def seller_projection(
    child: Fulfillment, ratings: dict[tuple[UUID, UUID], ProductRating]
) -> OrderResponse:
    return OrderResponse(
        id=child.id,
        customer_id=child.order.customer_id,
        status=child.status,
        total=child.total,
        delivery_address=DeliveryAddress.model_validate(child.order.delivery_address),
        created_at=child.created_at,
        items=[order_item(item, ratings, child.status) for item in child.items],
        packed_at=child.packed_at,
        out_for_delivery_at=child.out_for_delivery_at,
        delivered_at=child.delivered_at,
    )


CUSTOMER_LOAD = (
    selectinload(Order.items).joinedload(OrderItem.product),
    selectinload(Order.fulfillments),
)
SELLER_LOAD = (
    joinedload(Fulfillment.order),
    selectinload(Fulfillment.items).joinedload(OrderItem.product),
)


@router.post("/quotes", response_model=QuoteResponse, status_code=201)
async def quote_checkout(
    payload: QuoteRequest,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> QuoteResponse:
    quote = await create_quote(
        db, user.id, payload.delivery_address, payload.address_id
    )
    await db.commit()
    return QuoteResponse(id=quote.id, expires_at=quote.expires_at, **quote.snapshot)


@router.post("", response_model=OrderResponse, status_code=201)
async def place_order(
    payload: PlaceOrderPayload,
    idempotency_key: Annotated[str, Header(min_length=8, max_length=100)],
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    order_id = await confirm_checkout(db, user.id, payload.quote_id, idempotency_key)
    await db.commit()
    return await get_order(order_id, user, db)


@router.get("", response_model=OrderPaginatedResponse)
async def list_orders(
    page: Page = 1,
    limit: Limit = 10,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> OrderPaginatedResponse:
    predicate = Order.customer_id == user.id
    total = await db.scalar(select(func.count(Order.id)).where(predicate)) or 0
    orders = list(
        await db.scalars(
            select(Order)
            .where(predicate)
            .options(*CUSTOMER_LOAD)
            .order_by(Order.created_at.desc(), Order.id)
            .offset((page - 1) * limit)
            .limit(limit)
        )
    )
    ratings = await ratings_for(db, [order.id for order in orders])
    return OrderPaginatedResponse(
        items=[order_projection(order, ratings) for order in orders],
        total=total,
        page=page,
        limit=limit,
        pages=max(1, (total + limit - 1) // limit),
    )


@router.get("/seller/queue", response_model=OrderPaginatedResponse)
async def list_seller_orders(
    page: Page = 1,
    limit: Limit = 10,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> OrderPaginatedResponse:
    predicate = Fulfillment.seller_id == seller.id
    total = await db.scalar(select(func.count(Fulfillment.id)).where(predicate)) or 0
    children = list(
        await db.scalars(
            select(Fulfillment)
            .where(predicate)
            .options(*SELLER_LOAD)
            .order_by(Fulfillment.created_at.desc(), Fulfillment.id)
            .offset((page - 1) * limit)
            .limit(limit)
        )
    )
    ratings = await ratings_for(db, [child.order_id for child in children])
    return OrderPaginatedResponse(
        items=[seller_projection(child, ratings) for child in children],
        total=total,
        page=page,
        limit=limit,
        pages=max(1, (total + limit - 1) // limit),
    )


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: UUID,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    order = await db.scalar(
        select(Order)
        .where(Order.id == order_id, Order.customer_id == user.id)
        .options(*CUSTOMER_LOAD)
    )
    if order is None:
        raise HTTPException(404, "Order not found.")
    return order_projection(order, await ratings_for(db, [order.id]))


async def advance_fulfillment(
    db: AsyncSession, seller_id: UUID, fulfillment_id: UUID, desired: OrderStatus
) -> Fulfillment:
    order_id = await db.scalar(
        select(Fulfillment.order_id).where(
            Fulfillment.id == fulfillment_id, Fulfillment.seller_id == seller_id
        )
    )
    if order_id is None:
        raise HTTPException(404, "Fulfillment not found.")
    # Lock the parent first so concurrent siblings cannot compute stale aggregates.
    order = await db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    child = await db.scalar(
        select(Fulfillment)
        .where(Fulfillment.id == fulfillment_id, Fulfillment.seller_id == seller_id)
        .options(*SELLER_LOAD)
        .execution_options(populate_existing=True)
    )
    if order is None or child is None:
        raise HTTPException(404, "Fulfillment not found.")
    if child.status == desired:
        return child
    if ORDER_STEPS.index(desired) != ORDER_STEPS.index(child.status) + 1:
        raise HTTPException(409, "Fulfillment can only advance one step.")
    child.status = desired
    timestamp_field = {
        OrderStatus.packed: "packed_at",
        OrderStatus.out_for_delivery: "out_for_delivery_at",
        OrderStatus.delivered: "delivered_at",
    }[desired]
    setattr(child, timestamp_field, utc_now())
    await db.flush()
    statuses = list(
        await db.scalars(
            select(Fulfillment.status).where(Fulfillment.order_id == order_id)
        )
    )
    aggregate = min(statuses, key=ORDER_STEPS.index)
    if aggregate != order.status:
        order.status = aggregate
        setattr(order, f"{aggregate.value}_at", utc_now())
    return child


@router.put("/{fulfillment_id}/status", response_model=OrderResponse)
async def update_order_status(
    fulfillment_id: UUID,
    payload: UpdateStatusPayload,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    child = await advance_fulfillment(db, seller.id, fulfillment_id, payload.status)
    await db.commit()
    return seller_projection(child, await ratings_for(db, [child.order_id]))

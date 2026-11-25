from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.catalog.products import seller_product
from app.commerce.checkout import lock_customer
from app.core.dependencies import get_current_customer, get_current_seller, get_db
from app.db.models.enums import OrderStatus
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.db.models.rating import ProductRating
from app.db.models.user import User

router = APIRouter(prefix="/ratings", tags=["Ratings"])


class RatingCreate(BaseModel):
    order_id: UUID
    product_id: UUID
    stars: int = Field(ge=1, le=5)
    comment: str | None = Field(None, max_length=2000)


class RatingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_id: UUID
    product_id: UUID
    user_id: UUID
    stars: int
    comment: str | None
    reply: str | None
    created_at: datetime


class PublicReview(BaseModel):
    id: UUID
    user_name: str
    stars: int
    comment: str | None
    reply: str | None
    created_at: datetime


class ReviewsPage(BaseModel):
    items: list[PublicReview]
    total: int
    page: int
    limit: int
    pages: int
    metadata: dict[str, float | int | dict[str, int]]


async def add_rating(
    db: AsyncSession, user_id: UUID, payload: RatingCreate
) -> ProductRating:
    await lock_customer(db, user_id)
    line = await db.scalar(
        select(OrderItem)
        .join(Order)
        .options(joinedload(OrderItem.fulfillment))
        .where(
            Order.customer_id == user_id,
            Order.id == payload.order_id,
            OrderItem.product_id == payload.product_id,
        )
    )
    if (
        line is None
        or line.fulfillment is None
        or line.fulfillment.status != OrderStatus.delivered
    ):
        raise HTTPException(404, "Delivered order item not found.")
    product = await db.scalar(
        select(Product).where(Product.id == payload.product_id).with_for_update()
    )
    if product is None:
        raise HTTPException(404, "Product not found.")
    rated = await db.scalar(
        select(ProductRating.id).where(
            ProductRating.order_id == payload.order_id,
            ProductRating.product_id == product.id,
            ProductRating.user_id == user_id,
        )
    )
    if rated is not None:
        raise HTTPException(409, "This order item has already been reviewed.")
    rating = ProductRating(user_id=user_id, **payload.model_dump())
    db.add(rating)
    await db.flush()
    average = await db.scalar(
        select(func.avg(ProductRating.stars)).where(
            ProductRating.product_id == product.id
        )
    )
    product.avg_rating = Decimal(str(average)).quantize(Decimal("0.01"))
    await db.flush()
    return rating


@router.post("", response_model=RatingResponse, status_code=201)
async def submit_rating(
    payload: RatingCreate,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> ProductRating:
    rating = await add_rating(db, user.id, payload)
    await db.commit()
    return rating


def public_rating(rating: ProductRating) -> PublicReview:
    return PublicReview(
        id=rating.id,
        user_name=rating.user.name.split()[0]
        if rating.user.name.split()
        else "Shopper",
        stars=rating.stars,
        comment=rating.comment,
        reply=rating.reply,
        created_at=rating.created_at,
    )


@router.get("/product/{product_id}", response_model=ReviewsPage)
async def get_product_reviews(
    product_id: UUID,
    page: Annotated[int, Query(ge=1, le=10000)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    db: AsyncSession = Depends(get_db),
) -> ReviewsPage:
    product = await db.scalar(
        select(Product).where(Product.id == product_id, Product.is_active.is_(True))
    )
    if product is None:
        raise HTTPException(404, "Product not found.")
    rule = ProductRating.product_id == product_id
    distribution = dict.fromkeys(map(str, range(1, 6)), 0)
    counts = await db.execute(
        select(ProductRating.stars, func.count())
        .where(rule)
        .group_by(ProductRating.stars)
    )
    for stars, count in counts:
        distribution[str(stars)] = count
    total = sum(distribution.values())
    ratings = await db.scalars(
        select(ProductRating)
        .where(rule)
        .options(joinedload(ProductRating.user))
        .order_by(ProductRating.created_at.desc(), ProductRating.id)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return ReviewsPage(
        items=[public_rating(rating) for rating in ratings],
        total=total,
        page=page,
        limit=limit,
        pages=max(1, (total + limit - 1) // limit),
        metadata={
            "avg_rating": float(product.avg_rating),
            "total_count": total,
            "rating_distribution": distribution,
        },
    )


class ReviewReply(BaseModel):
    reply: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]


async def reply_to_rating(
    db: AsyncSession, seller_id: UUID, rating_id: UUID, payload: ReviewReply
) -> ProductRating:
    rating = await db.scalar(
        select(ProductRating)
        .join(Product)
        .where(
            ProductRating.id == rating_id,
            Product.seller_id == seller_id,
        )
    )
    if rating is None:
        raise HTTPException(404, "Review not found.")
    await seller_product(db, seller_id, rating.product_id)
    await db.refresh(rating)
    if rating.reply is not None:
        raise HTTPException(409, "A reply already exists.")
    rating.reply = payload.reply
    await db.flush()
    return rating


@router.post("/{rating_id}/reply", response_model=RatingResponse)
async def submit_reply(
    rating_id: UUID,
    payload: ReviewReply,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> ProductRating:
    rating = await reply_to_rating(db, seller.id, rating_id, payload)
    await db.commit()
    return rating


@router.get("/seller", response_model=list[PublicReview])
async def seller_reviews(
    seller: User = Depends(get_current_seller), db: AsyncSession = Depends(get_db)
) -> list[PublicReview]:
    ratings = await db.scalars(
        select(ProductRating)
        .join(Product)
        .where(Product.seller_id == seller.id)
        .options(joinedload(ProductRating.user))
        .order_by(ProductRating.created_at.desc(), ProductRating.id)
        .limit(100)
    )
    return [public_rating(rating) for rating in ratings]

import datetime
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.dependencies import get_current_customer, get_db
from app.db.models.enums import OrderStatus
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.db.models.rating import ProductRating
from app.db.models.user import User

router = APIRouter(prefix="/ratings", tags=["Ratings"])


# Pydantic Schemas
class RatingCreate(BaseModel):
    order_id: uuid.UUID
    product_id: uuid.UUID
    stars: int = Field(..., ge=1, le=5)
    comment: str | None = None


class RatingResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    product_id: uuid.UUID
    user_id: uuid.UUID
    stars: int
    comment: str | None
    created_at: Any

    class Config:
        from_attributes = True


@router.post("", response_model=RatingResponse, status_code=status.HTTP_201_CREATED)
async def submit_rating(
    payload: RatingCreate,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> ProductRating:
    """Submit a rating for a purchased product in a delivered order."""
    # 1. Verify order exists and belongs to current user
    order_res = await db.execute(
        select(Order).where(Order.id == payload.order_id, Order.customer_id == user.id)
    )
    order = order_res.scalar_one_or_none()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found or access denied.",
        )

    # 2. Check if order status is delivered
    if order.status != OrderStatus.delivered:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can only rate products from delivered orders.",
        )

    # 3. Check if the product was part of the order
    item_res = await db.execute(
        select(OrderItem).where(
            OrderItem.order_id == payload.order_id,
            OrderItem.product_id == payload.product_id,
        )
    )
    order_item = item_res.scalar_one_or_none()
    if not order_item:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product was not part of this order.",
        )

    # 4. Check if rating already exists for this (order, product, user)
    existing_res = await db.execute(
        select(ProductRating).where(
            ProductRating.order_id == payload.order_id,
            ProductRating.product_id == payload.product_id,
            ProductRating.user_id == user.id,
        )
    )
    existing_rating = existing_res.scalar_one_or_none()
    if existing_rating:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already rated this product for this order.",
        )

    # 5. Save new ProductRating
    rating = ProductRating(
        order_id=payload.order_id,
        product_id=payload.product_id,
        user_id=user.id,
        stars=payload.stars,
        comment=payload.comment,
    )
    db.add(rating)
    await db.commit()
    await db.refresh(rating)

    # 6. Recalculate average rating of the product
    avg_res = await db.execute(
        select(func.avg(ProductRating.stars)).where(
            ProductRating.product_id == payload.product_id
        )
    )
    avg_val = avg_res.scalar()
    if avg_val is not None:
        # Update product's avg_rating
        product_res = await db.execute(
            select(Product).where(Product.id == payload.product_id)
        )
        product = product_res.scalar_one_or_none()
        if product:
            product.avg_rating = Decimal(str(round(float(avg_val), 2)))
            await db.commit()

            # Invalidate Redis product cache and list cache
            from app.services.cache import invalidate_product_cache

            await invalidate_product_cache(str(product.id))

    return rating


class ProductReviewItem(BaseModel):
    user_name: str
    stars: int
    comment: str | None
    created_at: datetime.datetime


class ProductReviewsMetadata(BaseModel):
    avg_rating: float
    total_count: int
    rating_distribution: dict[str, int]


class ProductReviewsPaginatedResponse(BaseModel):
    metadata: ProductReviewsMetadata
    items: list[ProductReviewItem]
    total: int
    page: int
    limit: int
    pages: int


@router.get("/product/{product_id}", response_model=ProductReviewsPaginatedResponse)
async def get_product_reviews(
    product_id: uuid.UUID,
    page: int = 1,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve all ratings and reviews for a specific product."""
    # 1. Verify product exists
    product_res = await db.execute(select(Product).where(Product.id == product_id))
    product = product_res.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # 2. Get all ratings to compute metadata/distribution
    ratings_res = await db.execute(
        select(ProductRating)
        .options(joinedload(ProductRating.user))
        .where(ProductRating.product_id == product_id)
        .order_by(ProductRating.created_at.desc())
    )
    all_ratings = list(ratings_res.scalars().all())

    total_count = len(all_ratings)
    avg_rating = float(product.avg_rating) if total_count > 0 else 0.0

    distribution = {str(i): 0 for i in range(1, 6)}
    for r in all_ratings:
        stars_str = str(r.stars)
        if stars_str in distribution:
            distribution[stars_str] += 1

    # 3. Paginate items
    total = len(all_ratings)
    pages = max(1, (total + limit - 1) // limit)
    start = (page - 1) * limit
    end = start + limit
    paginated_ratings = all_ratings[start:end]

    review_items = [
        ProductReviewItem(
            user_name=r.user.name,
            stars=r.stars,
            comment=r.comment,
            created_at=r.created_at,
        )
        for r in paginated_ratings
    ]

    return {
        "metadata": {
            "avg_rating": avg_rating,
            "total_count": total_count,
            "rating_distribution": distribution,
        },
        "items": review_items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages,
    }

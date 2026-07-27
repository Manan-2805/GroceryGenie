"""submit_rating tool — pure Python, no LLM calls.

Per-item transaction with per-item rollback: DB write and avg_rating update
happen in the same transaction so they are always in sync.
"""

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import OrderStatus
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.db.models.rating import ProductRating

logger = logging.getLogger(__name__)


async def submit_rating(
    db: AsyncSession,
    user_id: UUID,
    order_id: str | None = None,
    product_id: str | None = None,
    stars: int | None = None,
    comment: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Submit a star rating and optional review for a delivered order item.

    Business rules:
      - The order must have status = delivered.
      - order.customer_id must equal user_id.
      - One rating per (order_id, product_id, user_id) — unique constraint.
        If a rating already exists, return it with its timestamp and content.
      - stars must be 1–5.

    Transaction:
      - ProductRating insert + Product.avg_rating recalculation in one commit.
      - On any exception the transaction is rolled back and an error is returned.
    """
    # --- Input validation (before any DB touch) ---
    if not order_id:
        return {"success": False, "message": "Order ID is required."}
    if not product_id:
        return {"success": False, "message": "Product ID is required."}
    if stars is None:
        return {"success": False, "message": "Star rating (1–5) is required."}

    try:
        stars_int = int(stars)
    except (ValueError, TypeError):
        return {"success": False, "message": "Stars must be a number between 1 and 5."}

    if not 1 <= stars_int <= 5:
        return {
            "success": False,
            "message": f"Stars must be between 1 and 5, got {stars_int}.",
        }

    try:
        order_uuid = UUID(str(order_id))
        product_uuid = UUID(str(product_id))
    except (ValueError, AttributeError):
        return {"success": False, "message": "Invalid order or product ID format."}

    # --- Fetch & validate order ---
    order_result = await db.execute(
        select(Order).where(
            Order.id == order_uuid,
            Order.customer_id == user_id,
        )
    )
    order = order_result.scalar_one_or_none()
    if not order:
        return {
            "success": False,
            "message": "Order not found or does not belong to you.",
        }

    if order.status != OrderStatus.delivered:
        status_label = order.status.value.replace("_", " ").title()
        return {
            "success": False,
            "message": (
                f"You can only rate delivered orders. "
                f"This order is currently '{status_label}'."
            ),
        }

    # --- Check product is in this order ---
    item_result = await db.execute(
        select(OrderItem).where(
            OrderItem.order_id == order_uuid,
            OrderItem.product_id == product_uuid,
        )
    )
    if item_result.scalar_one_or_none() is None:
        return {
            "success": False,
            "message": "That product was not part of this order.",
        }

    # --- Check for existing rating ---
    existing_result = await db.execute(
        select(ProductRating).where(
            ProductRating.order_id == order_uuid,
            ProductRating.product_id == product_uuid,
            ProductRating.user_id == user_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        submitted_at = (
            existing.created_at.isoformat() if existing.created_at else "unknown date"
        )
        return {
            "already_rated": True,
            "stars": existing.stars,
            "comment": existing.comment or "",
            "submitted_at": submitted_at,
            "message": (
                f"You already reviewed this product on {submitted_at}: "
                f"{existing.stars}★"
                + (f' — "{existing.comment}"' if existing.comment else "")
                + "."
            ),
        }

    # --- Fetch product name for response ---
    product_result = await db.execute(select(Product).where(Product.id == product_uuid))
    product = product_result.scalar_one_or_none()
    product_name = product.name if product else "the product"

    # --- Write rating + update avg_rating in ONE transaction ---
    try:
        rating = ProductRating(
            order_id=order_uuid,
            product_id=product_uuid,
            user_id=user_id,
            stars=stars_int,
            comment=comment or None,
        )
        db.add(rating)

        # Recalculate avg_rating from all ratings for this product
        # (flush first so the new row is included in the aggregate)
        await db.flush()

        avg_result = await db.execute(
            select(func.avg(ProductRating.stars)).where(
                ProductRating.product_id == product_uuid
            )
        )
        new_avg: Decimal | None = avg_result.scalar_one_or_none()
        if product and new_avg is not None:
            product.avg_rating = round(Decimal(str(new_avg)), 2)

        await db.commit()

        logger.info(
            f"[RatingTools] Rating submitted: order={order_uuid}, "
            f"product={product_uuid}, user={user_id}, stars={stars_int}"
        )

        return {
            "success": True,
            "message": (
                f"Review submitted for {product_name}! "
                f"You rated it {stars_int}★."
                + (f' Comment: "{comment}"' if comment else "")
            ),
            "product_name": product_name,
            "stars": stars_int,
        }

    except Exception as exc:
        await db.rollback()
        logger.error(f"[RatingTools] Failed to submit rating: {exc}")
        return {
            "success": False,
            "message": "Failed to save your review. Please try again.",
        }

"""Fulfillment tools — seller-side order management. Pure Python, no LLM calls."""

import datetime
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import OrderStatus
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product

logger = logging.getLogger(__name__)

# Linear state machine — each status maps to the ONLY valid next status.
# Delivered is the terminal state; it maps to itself so the error message is clear.
FULFILLMENT_TRANSITIONS: dict[str, str] = {
    OrderStatus.placed: OrderStatus.packed,
    OrderStatus.packed: OrderStatus.out_for_delivery,
    OrderStatus.out_for_delivery: OrderStatus.delivered,
    OrderStatus.delivered: OrderStatus.delivered,  # terminal — cannot advance
}

# Human-readable labels for display
STATUS_LABELS: dict[str, str] = {
    "placed": "Placed",
    "packed": "Packed",
    "out_for_delivery": "Out for Delivery",
    "delivered": "Delivered",
}

# Button labels for the NEXT transition (shown on each row)
NEXT_ACTION_LABELS: dict[str, str] = {
    "placed": "Mark Packed",
    "packed": "Mark Out for Delivery",
    "out_for_delivery": "Mark Delivered",
}


async def _get_seller_order_ids(db: AsyncSession, seller_id: UUID) -> list[UUID]:
    """Return IDs of all orders that contain at least one product by this seller."""
    result = await db.execute(
        select(OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(Product.seller_id == seller_id)
        .distinct()
    )
    return [row[0] for row in result.all()]


async def list_fulfillment_orders(
    db: AsyncSession,
    user_id: UUID,
    status: str | None = None,
    min_total: float | None = None,
    max_total: float | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]] | dict[str, Any]:
    """List orders that contain this seller's products, with optional filters.

    Returns only the seller's own line items per order (not items from other sellers).
    Filters (all optional):
      status     — exact OrderStatus value e.g. "placed", "packed"
      min_total  — order total >= this value
      max_total  — order total <= this value
      date_from  — ISO date string "YYYY-MM-DD", inclusive
      date_to    — ISO date string "YYYY-MM-DD", inclusive
    """
    order_ids = await _get_seller_order_ids(db, user_id)
    if not order_ids:
        return {"empty": True, "message": "You have no orders to fulfill yet."}

    # Fetch all matching orders
    query = (
        select(Order).where(Order.id.in_(order_ids)).order_by(Order.created_at.desc())
    )
    result = await db.execute(query)
    orders = list(result.scalars().all())

    # Apply Python-side filters
    filtered = []
    for order in orders:
        if status and order.status.value != status:
            continue
        if min_total is not None and float(order.total) < min_total:
            continue
        if max_total is not None and float(order.total) > max_total:
            continue
        if date_from:
            try:
                from_dt = datetime.date.fromisoformat(date_from)
                if order.created_at and order.created_at.date() < from_dt:
                    continue
            except ValueError:
                pass
        if date_to:
            try:
                to_dt = datetime.date.fromisoformat(date_to)
                if order.created_at and order.created_at.date() > to_dt:
                    continue
            except ValueError:
                pass
        filtered.append(order)

    if not filtered:
        return {"empty": True, "message": "No orders match your filters."}

    # Build result — only include this seller's line items per order
    rows: list[dict[str, Any]] = []
    for order in filtered:
        items_result = await db.execute(
            select(OrderItem)
            .join(Product, Product.id == OrderItem.product_id)
            .where(
                OrderItem.order_id == order.id,
                Product.seller_id == user_id,
            )
        )
        my_items = list(items_result.scalars().all())

        item_list = []
        for item in my_items:
            p_res = await db.execute(
                select(Product).where(Product.id == item.product_id)
            )
            product = p_res.scalar_one_or_none()
            item_list.append(
                {
                    "product_name": product.name if product else "Unknown",
                    "quantity": item.quantity,
                    "price_at_purchase": float(item.price_at_purchase),
                }
            )

        current_status = order.status.value
        next_status = FULFILLMENT_TRANSITIONS.get(OrderStatus(current_status))
        next_status_value = next_status.value if next_status else None
        # Don't show advance button for terminal state
        can_advance = current_status != "delivered"

        rows.append(
            {
                "fulfillment_queue": True,  # discriminator for formatter
                "order_id": str(order.id),
                "order_id_short": str(order.id)[:8],
                "status": current_status,
                "status_label": STATUS_LABELS.get(current_status, current_status),
                "total": float(order.total),
                "created_at": order.created_at.isoformat()
                if order.created_at
                else None,
                "my_items": item_list,
                "my_items_count": len(item_list),
                "next_status": next_status_value,
                "next_action_label": NEXT_ACTION_LABELS.get(current_status)
                if can_advance
                else None,
                "advance_value": (
                    f"fulfillment_status_{order.id}_{next_status_value}"
                    if can_advance and next_status_value
                    else None
                ),
            }
        )

    return rows


async def update_order_status(
    db: AsyncSession,
    user_id: UUID,
    order_id: str,
    new_status: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Advance an order's status through the fulfillment state machine.

    Enforces the linear transition: placed → packed → out_for_delivery → delivered.
    Only a seller who owns at least one item in the order may update it.
    Executes immediately — no confirmation required (per design decision).
    """
    try:
        order_uuid = UUID(order_id)
    except (ValueError, AttributeError):
        return {"success": False, "message": "Invalid order ID."}

    # Validate new_status is a known value
    try:
        target_status = OrderStatus(new_status)
    except ValueError:
        valid = ", ".join(s.value for s in OrderStatus)
        return {
            "success": False,
            "message": f"Unknown status '{new_status}'. Valid: {valid}",
        }

    # Fetch order
    order_result = await db.execute(select(Order).where(Order.id == order_uuid))
    order = order_result.scalar_one_or_none()
    if not order:
        return {"success": False, "message": "Order not found."}

    # Ownership check — seller must have at least one item in this order
    ownership_result = await db.execute(
        select(OrderItem.id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(
            OrderItem.order_id == order_uuid,
            Product.seller_id == user_id,
        )
        .limit(1)
    )
    if ownership_result.first() is None:
        return {"success": False, "message": "You don't have any items in this order."}

    # State machine validation
    current = order.status
    expected_next = FULFILLMENT_TRANSITIONS.get(current)

    if current == OrderStatus.delivered:
        return {
            "success": False,
            "message": "This order is already delivered — no further updates possible.",
        }

    if expected_next is None or target_status != expected_next:
        next_label = (
            STATUS_LABELS.get(expected_next.value, expected_next.value)
            if expected_next
            else "none"
        )
        return {
            "success": False,
            "message": (
                f"Cannot transition from '{STATUS_LABELS.get(current.value, current.value)}' "
                f"to '{STATUS_LABELS.get(new_status, new_status)}'. "
                f"Next valid status is '{next_label}'."
            ),
        }

    # Apply transition
    now = datetime.datetime.now(datetime.UTC)
    order.status = target_status

    if target_status == OrderStatus.packed:
        order.packed_at = now
    elif target_status == OrderStatus.out_for_delivery:
        order.out_for_delivery_at = now
    elif target_status == OrderStatus.delivered:
        order.delivered_at = now

    await db.commit()

    status_label = STATUS_LABELS.get(target_status.value, target_status.value)
    return {
        "success": True,
        "message": f"Order #{str(order_uuid)[:8]}… marked as **{status_label}**.",
        "order_id": str(order_uuid),
        "new_status": target_status.value,
    }

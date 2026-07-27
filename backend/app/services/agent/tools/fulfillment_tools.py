"""Fulfillment tools — seller-side order management. Pure Python, no LLM calls.

All DB-writing operations use per-item transactions with per-item rollback
so partial failure in a bulk op never leaves DB and state out of sync.
"""

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

# ── State machine ────────────────────────────────────────────────────────────
# Linear: placed → packed → out_for_delivery → delivered (terminal)
FULFILLMENT_TRANSITIONS: dict[OrderStatus, OrderStatus] = {
    OrderStatus.placed: OrderStatus.packed,
    OrderStatus.packed: OrderStatus.out_for_delivery,
    OrderStatus.out_for_delivery: OrderStatus.delivered,
    OrderStatus.delivered: OrderStatus.delivered,  # terminal
}

STATUS_LABELS: dict[str, str] = {
    "placed": "Placed",
    "packed": "Packed",
    "out_for_delivery": "Out for Delivery",
    "delivered": "Delivered",
}

NEXT_ACTION_LABELS: dict[str, str] = {
    "placed": "Mark Packed",
    "packed": "Mark Out for Delivery",
    "out_for_delivery": "Mark Delivered",
}


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _get_seller_order_ids(db: AsyncSession, seller_id: UUID) -> list[UUID]:
    """Return IDs of all orders that contain at least one product by this seller."""
    result = await db.execute(
        select(OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(Product.seller_id == seller_id)
        .distinct()
    )
    return [row[0] for row in result.all()]


# ── list_fulfillment_orders ──────────────────────────────────────────────────


async def list_fulfillment_orders(
    db: AsyncSession,
    user_id: UUID,
    status: str | None = None,
    min_total: float | None = None,
    max_total: float | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    product_name: str | None = None,
    customer_city: str | None = None,
    customer_name: str | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]] | dict[str, Any]:
    """List orders that contain this seller's products, with optional filters.

    Returns only the seller's own line items per order.

    Filters (all optional):
        status        — exact OrderStatus value
        min_total     — order total >= value
        max_total     — order total <= value
        date_from     — ISO date string "YYYY-MM-DD", inclusive
        date_to       — ISO date string "YYYY-MM-DD", inclusive
        product_name  — show only orders containing a seller product whose
                        name contains this substring (case-insensitive)
        customer_city — filter by city in the order's delivery_address JSONB
        customer_name — filter by customer name substring in delivery_address JSONB
    """
    order_ids = await _get_seller_order_ids(db, user_id)
    if not order_ids:
        return {"empty": True, "message": "You have no orders to fulfill yet."}

    query = (
        select(Order).where(Order.id.in_(order_ids)).order_by(Order.created_at.desc())
    )
    result = await db.execute(query)
    orders = list(result.scalars().all())

    rows: list[dict[str, Any]] = []
    for order in orders:
        # ── Scalar filters ───────────────────────────────────────────────
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

        # ── Delivery address filters (JSONB) ──────────────────────────────
        addr: dict[str, Any] = order.delivery_address or {}
        if customer_city:
            city_val = str(addr.get("city", "")).lower()
            if customer_city.lower() not in city_val:
                continue
        if customer_name:
            # delivery_address may store 'name' or 'label' — check both
            name_val = (
                str(addr.get("name", "")).lower()
                + " "
                + str(addr.get("label", "")).lower()
            )
            if customer_name.lower() not in name_val:
                continue

        # ── Fetch this seller's line items for the order ─────────────────
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
                    "product_id": str(item.product_id) if item.product_id else None,
                    "quantity": item.quantity,
                    "price_at_purchase": float(item.price_at_purchase),
                }
            )

        # ── product_name filter (after items are loaded) ──────────────────
        if product_name:
            pn_lower = product_name.lower()
            if not any(
                pn_lower in (i["product_name"] or "").lower() for i in item_list
            ):
                continue

        # ── Build row ────────────────────────────────────────────────────
        current_status = order.status.value
        next_status_enum = FULFILLMENT_TRANSITIONS.get(OrderStatus(current_status))
        next_status_value = next_status_enum.value if next_status_enum else None
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
                "delivery_address": addr,
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

    if not rows:
        return {"empty": True, "message": "No orders match your filters."}

    return rows


# ── update_order_status (bulk, per-item transaction) ────────────────────────


async def update_order_status(
    db: AsyncSession,
    user_id: UUID,
    order_ids: list[str] | str | None = None,
    new_status: str | None = None,
    # Legacy single-ID param kept for fast-path compatibility
    order_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Advance one or more orders through the fulfilment state machine.

    Accepts either:
        order_ids: list[str]   (new bulk form)
        order_id: str          (legacy single-ID form from fast-path buttons)

    Each order is advanced exactly ONE step from its current status.
    If new_status is multiple steps away, the order is advanced only one step
    and a per-order explanation is included in the response.

    Per-item transaction: each order uses a savepoint; failure on one order
    rolls back only that order — the others continue.
    """
    if not new_status:
        return {"success": False, "message": "new_status is required."}

    # Normalise to a list
    ids_to_process: list[str] = []
    if order_ids:
        ids_to_process = [order_ids] if isinstance(order_ids, str) else list(order_ids)
    elif order_id:
        ids_to_process = [order_id]

    if not ids_to_process:
        return {"success": False, "message": "At least one order ID is required."}

    # Validate target status
    try:
        target_status_enum = OrderStatus(new_status)
    except ValueError:
        valid = ", ".join(s.value for s in OrderStatus)
        return {
            "success": False,
            "message": f"Unknown status '{new_status}'. Valid values: {valid}",
        }

    # Single-order fast path — preserve original return shape for fast-path buttons
    if len(ids_to_process) == 1:
        return await _advance_single_order(
            db, user_id, ids_to_process[0], target_status_enum
        )

    # Bulk path
    succeeded: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    for oid in ids_to_process:
        result = await _advance_single_order(db, user_id, oid, target_status_enum)
        if result.get("success"):
            succeeded.append({"id": oid, "message": result.get("message", "")})
        else:
            failed.append({"id": oid, "reason": result.get("message", "Unknown error")})

    total = len(succeeded) + len(failed)
    msg = f"Updated {len(succeeded)} of {total} orders."
    if failed:
        msg += " Failed: " + "; ".join(
            f"#{f['id'][:8]}… — {f['reason']}" for f in failed
        )

    return {
        "bulk_status_update": True,
        "succeeded": succeeded,
        "failed": failed,
        "message": msg,
    }


async def _advance_single_order(
    db: AsyncSession,
    seller_id: UUID,
    order_id: str,
    target_status: OrderStatus,
) -> dict[str, Any]:
    """Advance a single order one step. Uses a savepoint for per-item isolation."""
    try:
        order_uuid = UUID(str(order_id))
    except (ValueError, AttributeError):
        return {"success": False, "message": "Invalid order ID."}

    try:
        async with db.begin_nested():
            order_result = await db.execute(select(Order).where(Order.id == order_uuid))
            order = order_result.scalar_one_or_none()
            if not order:
                return {"success": False, "message": "Order not found."}

            # Ownership check
            ownership_result = await db.execute(
                select(OrderItem.id)
                .join(Product, Product.id == OrderItem.product_id)
                .where(
                    OrderItem.order_id == order_uuid,
                    Product.seller_id == seller_id,
                )
                .limit(1)
            )
            if ownership_result.first() is None:
                return {
                    "success": False,
                    "message": "You don't have any items in this order.",
                }

            current = order.status

            if current == OrderStatus.delivered:
                return {
                    "success": False,
                    "message": "This order is already delivered — no further updates possible.",
                }

            expected_next = FULFILLMENT_TRANSITIONS.get(current)
            if expected_next is None or target_status != expected_next:
                next_label = (
                    STATUS_LABELS.get(expected_next.value, expected_next.value)
                    if expected_next
                    else "none"
                )
                current_label = STATUS_LABELS.get(current.value, current.value)
                target_label = STATUS_LABELS.get(
                    target_status.value, target_status.value
                )
                return {
                    "success": False,
                    "message": (
                        f"Cannot go from '{current_label}' to '{target_label}'. "
                        f"Next valid status is '{next_label}'."
                    ),
                }

            now = datetime.datetime.now(datetime.UTC)
            order.status = target_status
            if target_status == OrderStatus.packed:
                order.packed_at = now
            elif target_status == OrderStatus.out_for_delivery:
                order.out_for_delivery_at = now
            elif target_status == OrderStatus.delivered:
                order.delivered_at = now
            # Savepoint commits here

        await db.commit()
        status_label = STATUS_LABELS.get(target_status.value, target_status.value)
        return {
            "success": True,
            "message": f"Order #{str(order_uuid)[:8]}… marked as **{status_label}**.",
            "order_id": str(order_uuid),
            "new_status": target_status.value,
        }

    except Exception as exc:
        logger.error(
            f"[FulfillmentTools] _advance_single_order failed for {order_id}: {exc}"
        )
        return {
            "success": False,
            "message": f"Failed to update order: {exc}",
        }

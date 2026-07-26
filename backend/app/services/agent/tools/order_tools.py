"""Order tools - pure Python, no LLM calls."""

import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.address import Address
from app.db.models.cart import CartItem
from app.db.models.enums import OrderStatus
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product


async def get_order_detail(
    db: AsyncSession,
    user_id: UUID,
    order_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Fetch full detail for a single order owned by the user.

    Returns items with quantities/prices, current status, delivery address
    snapshot, and status timestamps (placed_at, packed_at, etc.).
    """
    try:
        order_uuid = UUID(order_id)
    except (ValueError, AttributeError):
        return {"success": False, "message": "Invalid order ID."}

    order_result = await db.execute(
        select(Order).where(
            Order.id == order_uuid,
            Order.customer_id == user_id,
        )
    )
    order = order_result.scalar_one_or_none()
    if not order:
        return {"success": False, "message": "Order not found."}

    items_result = await db.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )
    items = list(items_result.scalars().all())
    item_list = []
    for item in items:
        p_res = await db.execute(select(Product).where(Product.id == item.product_id))
        product = p_res.scalar_one_or_none()
        item_list.append(
            {
                "product_name": product.name if product else "Unknown",
                "quantity": item.quantity,
                "price_at_purchase": float(item.price_at_purchase),
                "subtotal": float(item.price_at_purchase) * item.quantity,
            }
        )

    def _fmt_ts(ts: datetime.datetime | None) -> str | None:
        return ts.isoformat() if ts else None

    return {
        "order_detail": True,  # discriminator for the formatter
        "id": str(order.id),
        "status": order.status.value,
        "total": float(order.total),
        "created_at": _fmt_ts(order.created_at),
        "packed_at": _fmt_ts(order.packed_at),
        "out_for_delivery_at": _fmt_ts(order.out_for_delivery_at),
        "delivered_at": _fmt_ts(order.delivered_at),
        "delivery_address": order.delivery_address or {},
        "items": item_list,
    }


async def view_orders(
    db: AsyncSession,
    user_id: UUID,
    **kwargs: Any,
) -> list[dict[str, Any]] | dict[str, Any]:
    """View user's order history."""

    order_result = await db.execute(
        select(Order)
        .where(Order.customer_id == user_id)
        .order_by(Order.created_at.desc())
    )
    orders = list(order_result.scalars().all())

    if not orders:
        return {"empty": True, "message": "You have no orders yet."}

    result = []
    for order in orders:
        items_result = await db.execute(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )
        items = list(items_result.scalars().all())
        item_list = []
        for item in items:
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

        result.append(
            {
                "id": str(order.id),
                "status": order.status.value,
                "total": float(order.total),
                "created_at": order.created_at.isoformat()
                if order.created_at
                else None,
                "items": item_list,
            }
        )

    return result


async def place_order(
    db: AsyncSession,
    user_id: UUID,
    **kwargs: Any,
) -> dict[str, Any]:
    """Place an order using current cart and default address."""
    from decimal import Decimal

    # Get cart items
    cart_result = await db.execute(select(CartItem).where(CartItem.user_id == user_id))
    cart_items = list(cart_result.scalars().all())

    if not cart_items:
        return {"success": False, "message": "Cart is empty."}

    # Get default address
    addr_result = await db.execute(
        select(Address).where(
            Address.user_id == user_id,
            Address.is_default,
        )
    )
    address = addr_result.scalar_one_or_none()
    if not address:
        return {
            "success": False,
            "message": "No default address found. Please add an address first.",
        }

    # Build delivery_address JSONB snapshot from the Address record
    delivery_address_snapshot: dict[str, Any] = {
        "label": address.label,
        "line1": address.line1,
        "line2": address.line2 or "",
        "city": address.city,
        "state": address.state,
        "postal_code": address.postal_code,
        "country": address.country,
    }

    # Calculate total and validate stock
    total = Decimal("0.00")
    order_items_data = []
    for cart_item in cart_items:
        p_res = await db.execute(
            select(Product).where(Product.id == cart_item.product_id)
        )
        product = p_res.scalar_one_or_none()
        if product and product.stock >= cart_item.quantity:
            item_total = product.price * cart_item.quantity
            total += item_total
            order_items_data.append(
                {
                    "product_id": product.id,
                    "quantity": cart_item.quantity,
                    "price_at_purchase": product.price,
                    "product_name": product.name,
                }
            )
            product.stock -= cart_item.quantity
        elif product:
            return {
                "success": False,
                "message": f"Insufficient stock for {product.name}. Only {product.stock} available.",
            }

    # Create order with correct field names matching the Order model
    order = Order(
        customer_id=user_id,
        status=OrderStatus.placed,
        total=total,
        delivery_address=delivery_address_snapshot,
    )
    db.add(order)
    await db.flush()

    for item_data in order_items_data:
        order_item = OrderItem(
            order_id=order.id,
            product_id=item_data["product_id"],
            quantity=item_data["quantity"],
            price_at_purchase=item_data["price_at_purchase"],
        )
        db.add(order_item)

    # Clear cart
    for cart_item in cart_items:
        await db.delete(cart_item)

    await db.commit()
    return {
        "success": True,
        "message": f"Order placed successfully! Total: ${float(total):.2f}",
        "order_id": str(order.id),
    }

"""Order tools - pure Python, no LLM calls."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.address import Address
from app.db.models.cart import CartItem
from app.db.models.enums import OrderStatus
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product


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
        return {"empty": True, "message": "No orders found."}

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
                    "price": float(product.price),
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

    # Calculate total
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
                    "price": product.price,
                }
            )
            product.stock -= cart_item.quantity
        elif product:
            return {
                "success": False,
                "message": f"Insufficient stock for {product.name}. Only {product.stock} available.",
            }

    # Create order
    order = Order(
        user_id=user_id,
        address_id=address.id,
        status=OrderStatus.placed,
        total_amount=total,
    )
    db.add(order)
    await db.flush()

    for item_data in order_items_data:
        order_item = OrderItem(
            order_id=order.id,
            product_id=item_data["product_id"],
            quantity=item_data["quantity"],
            price=item_data["price"],
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

"""Cart tools - pure Python CRUD, no LLM calls."""

import re
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.cart import CartItem
from app.db.models.product import Product

# UUID format pattern
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _is_valid_uuid(value: str) -> bool:
    """Check if the string is a valid UUID format."""
    return bool(UUID_PATTERN.match(value.strip()))


async def add_to_cart(
    db: AsyncSession,
    user_id: UUID,
    product_id: str,
    quantity: int = 1,
    **kwargs: Any,
) -> dict[str, Any]:
    """Add a product to cart. Returns result message."""
    # Validate UUID format first
    if not _is_valid_uuid(str(product_id)):
        return {
            "success": False,
            "message": "I couldn't find that product. Please search for it first and select from the results.",
        }

    product_uuid = UUID(product_id)
    p_res = await db.execute(select(Product).where(Product.id == product_uuid))
    product = p_res.scalar_one_or_none()
    if not product:
        return {"success": False, "message": "Product not found."}
    if product.stock < quantity:
        return {"success": False, "message": f"Only {product.stock} in stock."}

    cart_res = await db.execute(
        select(CartItem).where(
            CartItem.user_id == user_id,
            CartItem.product_id == product_uuid,
        )
    )
    cart_item = cart_res.scalar_one_or_none()
    if cart_item:
        cart_item.quantity += quantity
    else:
        cart_item = CartItem(
            user_id=user_id, product_id=product_uuid, quantity=quantity
        )
        db.add(cart_item)

    await db.commit()
    return {
        "success": True,
        "message": f"Added {quantity}x {product.name} to cart.",
        "product_name": product.name,
    }


async def remove_from_cart(
    db: AsyncSession,
    user_id: UUID,
    product_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Remove a product from cart."""
    if not _is_valid_uuid(str(product_id)):
        return {"success": False, "message": "Invalid product identifier."}

    product_uuid = UUID(product_id)
    await db.execute(
        delete(CartItem).where(
            CartItem.user_id == user_id,
            CartItem.product_id == product_uuid,
        )
    )
    await db.commit()
    return {"success": True, "message": "Removed item from cart."}


async def update_cart_quantity(
    db: AsyncSession,
    user_id: UUID,
    product_id: str,
    quantity: int = 1,
    **kwargs: Any,
) -> dict[str, Any]:
    """Update cart item quantity."""
    if not _is_valid_uuid(str(product_id)):
        return {"success": False, "message": "Invalid product identifier."}

    product_uuid = UUID(product_id)
    cart_res = await db.execute(
        select(CartItem).where(
            CartItem.user_id == user_id,
            CartItem.product_id == product_uuid,
        )
    )
    cart_item = cart_res.scalar_one_or_none()
    if not cart_item:
        return {"success": False, "message": "Item not in cart."}

    cart_item.quantity = quantity
    await db.commit()
    return {"success": True, "message": f"Updated quantity to {quantity}."}


async def get_cart(
    db: AsyncSession,
    user_id: UUID,
    **kwargs: Any,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Get current cart contents."""
    cart_result = await db.execute(select(CartItem).where(CartItem.user_id == user_id))
    items = list(cart_result.scalars().all())

    if not items:
        return {"empty": True, "message": "Your cart is empty."}

    result = []
    for item in items:
        p_res = await db.execute(select(Product).where(Product.id == item.product_id))
        product = p_res.scalar_one_or_none()
        if product:
            result.append(
                {
                    "product_id": str(item.product_id),
                    "name": product.name,
                    "price": float(product.price),
                    "quantity": item.quantity,
                    "total": float(product.price) * item.quantity,
                }
            )

    total = sum(item["total"] for item in result)
    return {"items": result, "total": round(total, 2)}

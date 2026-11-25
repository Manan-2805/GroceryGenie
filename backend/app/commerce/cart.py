from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commerce.checkout import lock_customer
from app.db.models.cart import CartItem
from app.db.models.product import Product


async def change_cart(
    db: AsyncSession,
    user_id: UUID,
    product_id: UUID,
    quantity: int,
    *,
    add: bool = False,
) -> None:
    user = await lock_customer(db, user_id)
    item = await db.scalar(
        select(CartItem).where(
            CartItem.user_id == user_id, CartItem.product_id == product_id
        )
    )
    if quantity == 0 and not add:
        if item is not None:
            await db.delete(item)
            user.cart_version += 1
            await db.flush()
        return

    product = await db.scalar(
        select(Product)
        .where(Product.id == product_id, Product.is_active.is_(True))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if product is None:
        raise HTTPException(404, "Product is unavailable.")
    updated_quantity = (
        quantity + item.quantity if add and item is not None else quantity
    )
    if quantity <= 0 or not 1 <= updated_quantity <= min(product.stock, 1000):
        raise HTTPException(409, "Requested quantity is not available.")
    if item is None:
        db.add(
            CartItem(user_id=user_id, product_id=product_id, quantity=updated_quantity)
        )
    else:
        item.quantity = updated_quantity
    user.cart_version += 1
    await db.flush()

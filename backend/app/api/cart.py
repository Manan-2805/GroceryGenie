import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from app.core.dependencies import get_current_customer, get_db
from app.db.models.cart import CartItem
from app.db.models.product import Product
from app.db.models.user import User

router = APIRouter(prefix="/cart", tags=["Cart"])


# Schemas
class CartProductDetail(BaseModel):
    id: uuid.UUID
    name: str
    price: Decimal
    image_url: str | None
    stock: int


class CartItemResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    product: CartProductDetail

    class Config:
        from_attributes = True


class AddCartItemPayload(BaseModel):
    product_id: uuid.UUID
    quantity: int = 1


class UpdateCartItemPayload(BaseModel):
    quantity: int


@router.get("", response_model=list[CartItemResponse])
async def get_cart(
    user: User = Depends(get_current_customer), db: AsyncSession = Depends(get_db)
) -> list[CartItem]:
    result = await db.execute(
        select(CartItem)
        .options(joinedload(CartItem.product))
        .where(CartItem.user_id == user.id)
    )
    return list(result.scalars().all())


@router.post("", response_model=CartItemResponse, status_code=status.HTTP_201_CREATED)
async def add_to_cart(
    payload: AddCartItemPayload,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> CartItem:
    # Verify product exists and has stock
    product_result = await db.execute(
        select(Product).where(Product.id == payload.product_id, Product.is_active)
    )
    product = product_result.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found or inactive",
        )

    if product.stock < payload.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient stock. Available: {product.stock}",
        )

    # Check if item is already in cart
    cart_result = await db.execute(
        select(CartItem)
        .options(joinedload(CartItem.product))
        .where(CartItem.user_id == user.id, CartItem.product_id == payload.product_id)
    )
    cart_item = cart_result.scalar_one_or_none()

    if cart_item:
        # Update quantity
        cart_item.quantity += payload.quantity
        if product.stock < cart_item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for updated quantity. Available: {product.stock}",
            )
    else:
        # Create new cart item
        cart_item = CartItem(
            user_id=user.id,
            product_id=payload.product_id,
            quantity=payload.quantity,
        )
        db.add(cart_item)

    await db.commit()

    # Eager load relationships for response mapping
    result = await db.execute(
        select(CartItem)
        .options(joinedload(CartItem.product))
        .where(CartItem.id == cart_item.id)
    )
    return result.scalar_one()


@router.put("/{product_id}", response_model=CartItemResponse)
async def update_cart_quantity(
    product_id: uuid.UUID,
    payload: UpdateCartItemPayload,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> CartItem:
    if payload.quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quantity must be greater than zero",
        )

    # Check if product exists and stock
    product_result = await db.execute(select(Product).where(Product.id == product_id))
    product = product_result.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if product.stock < payload.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient stock. Available: {product.stock}",
        )

    # Find the cart item
    cart_result = await db.execute(
        select(CartItem)
        .options(joinedload(CartItem.product))
        .where(CartItem.user_id == user.id, CartItem.product_id == product_id)
    )
    cart_item = cart_result.scalar_one_or_none()
    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found in cart",
        )

    cart_item.quantity = payload.quantity
    await db.commit()
    return cart_item


@router.delete("/{product_id}")
async def remove_from_cart(
    product_id: uuid.UUID,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    stmt = select(CartItem).where(
        CartItem.user_id == user.id, CartItem.product_id == product_id
    )
    res = await db.execute(stmt)
    cart_item = res.scalar_one_or_none()

    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found in cart",
        )

    await db.delete(cart_item)
    await db.commit()

    return {"status": "success", "detail": "Item removed from cart."}

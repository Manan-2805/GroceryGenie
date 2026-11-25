import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from app.commerce.cart import change_cart
from app.core.dependencies import get_current_customer, get_db
from app.db.models.cart import CartItem
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
    quantity: int = Field(1, ge=1, le=1000)


class UpdateCartItemPayload(BaseModel):
    quantity: int = Field(ge=1, le=1000)


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


async def _get_cart_item(
    db: AsyncSession, user_id: uuid.UUID, product_id: uuid.UUID
) -> CartItem:
    item = await db.scalar(
        select(CartItem)
        .options(joinedload(CartItem.product))
        .where(CartItem.user_id == user_id, CartItem.product_id == product_id)
    )
    if item is None:
        raise HTTPException(404, "Cart item not found.")
    return item


@router.post("", response_model=CartItemResponse, status_code=status.HTTP_201_CREATED)
async def add_to_cart(
    payload: AddCartItemPayload,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> CartItem:
    await change_cart(db, user.id, payload.product_id, payload.quantity, add=True)
    await db.commit()
    return await _get_cart_item(db, user.id, payload.product_id)


@router.put("/{product_id}", response_model=CartItemResponse)
async def update_cart_quantity(
    product_id: uuid.UUID,
    payload: UpdateCartItemPayload,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> CartItem:
    await change_cart(db, user.id, product_id, payload.quantity)
    await db.commit()
    return await _get_cart_item(db, user.id, product_id)


@router.delete("/{product_id}")
async def remove_from_cart(
    product_id: uuid.UUID,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await change_cart(db, user.id, product_id, 0)
    await db.commit()
    return {"status": "success", "detail": "Item removed from cart."}

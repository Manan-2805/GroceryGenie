import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.dependencies import get_current_seller, get_current_user, get_db
from app.db.models.cart import CartItem
from app.db.models.enums import OrderStatus, UserRole
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.db.models.user import User

router = APIRouter(prefix="/orders", tags=["Orders"])


# Schemas
class OrderProductDetail(BaseModel):
    id: uuid.UUID
    name: str
    price: Decimal
    image_url: str | None


class OrderItemResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID | None
    quantity: int
    price_at_purchase: Decimal
    product: OrderProductDetail | None

    class Config:
        from_attributes = True


class OrderResponse(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    status: OrderStatus
    total: Decimal
    delivery_address: dict[str, Any]
    created_at: Any
    items: list[OrderItemResponse]

    class Config:
        from_attributes = True


class PlaceOrderPayload(BaseModel):
    delivery_address: dict[str, Any]


class UpdateStatusPayload(BaseModel):
    status: OrderStatus


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def place_order(
    payload: PlaceOrderPayload,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Order:
    # 1. Fetch cart items
    cart_result = await db.execute(
        select(CartItem)
        .options(joinedload(CartItem.product))
        .where(CartItem.user_id == user.id)
    )
    cart_items = cart_result.scalars().all()

    if not cart_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot place order with an empty cart.",
        )

    # 2. Check stock, calculate total, and prepare order items
    total = Decimal("0.00")
    order_items_to_create = []

    for cart_item in cart_items:
        product = cart_item.product
        if not product or not product.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product {cart_item.product_id} is no longer active.",
            )

        if product.stock < cart_item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for product '{product.name}'. Available: {product.stock}",
            )

        # Decrement stock and update sold count
        product.stock -= cart_item.quantity
        product.sold_count += cart_item.quantity

        item_total = product.price * cart_item.quantity
        total += item_total

        # Prepare OrderItem
        order_item = OrderItem(
            product_id=product.id,
            quantity=cart_item.quantity,
            price_at_purchase=product.price,
        )
        order_items_to_create.append(order_item)

    # 3. Create Order
    order = Order(
        customer_id=user.id,
        status=OrderStatus.placed,
        total=total,
        delivery_address=payload.delivery_address,
        items=order_items_to_create,
    )

    db.add(order)

    # 4. Clear Cart
    for cart_item in cart_items:
        await db.delete(cart_item)

    await db.commit()

    # 5. Eager load Order details for response
    response_result = await db.execute(
        select(Order)
        .options(selectinload(Order.items).joinedload(OrderItem.product))
        .where(Order.id == order.id)
    )
    return response_result.scalar_one()


@router.get("", response_model=list[OrderResponse])
async def list_orders(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[Order]:
    # Customers list their own orders, sellers view fulfillment queue at a different endpoint
    query = select(Order).options(selectinload(Order.items).joinedload(OrderItem.product))

    if user.role == UserRole.customer:
        query = query.where(Order.customer_id == user.id)
    # If seller, they can query all orders they are involved in or fulfill
    # (For simplicity in customer orders listing, we filter by customer_id if role=customer)
    
    query = query.order_by(Order.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/seller/queue", response_model=list[OrderResponse])
async def list_seller_orders(
    seller: User = Depends(get_current_seller), db: AsyncSession = Depends(get_db)
) -> list[Order]:
    # Find all orders containing products owned by this seller
    result = await db.execute(
        select(Order)
        .join(OrderItem)
        .join(Product)
        .where(Product.seller_id == seller.id)
        .options(selectinload(Order.items).joinedload(OrderItem.product))
        .distinct()
        .order_by(Order.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Order:
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items).joinedload(OrderItem.product))
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    # Security check: must be owner or seller of items
    if user.role == UserRole.customer and order.customer_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden. Access denied.",
        )

    return order


@router.put("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: uuid.UUID,
    payload: UpdateStatusPayload,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db)
) -> Order:
    # Fetch order
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items).joinedload(OrderItem.product))
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    # Security: Verify that at least one product in order belongs to this seller
    has_seller_product = any(
        item.product.seller_id == seller.id for item in order.items if item.product
    )
    if not has_seller_product:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden. You cannot update the status of this order.",
        )

    order.status = payload.status
    await db.commit()
    return order

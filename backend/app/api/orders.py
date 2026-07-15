import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.dependencies import (
    get_current_customer,
    get_current_seller,
    get_current_user,
    get_db,
)
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


class OrderItemRatingResponse(BaseModel):
    stars: int
    comment: str | None

    class Config:
        from_attributes = True


class OrderItemResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID | None
    quantity: int
    price_at_purchase: Decimal
    product: OrderProductDetail | None
    rating: OrderItemRatingResponse | None = None

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
    packed_at: Any = None
    out_for_delivery_at: Any = None
    delivered_at: Any = None

    class Config:
        from_attributes = True


class OrderPaginatedResponse(BaseModel):
    items: list[OrderResponse]
    total: int
    page: int
    limit: int
    pages: int


class PlaceOrderPayload(BaseModel):
    delivery_address: dict[str, Any]


class UpdateStatusPayload(BaseModel):
    status: OrderStatus


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def place_order(
    payload: PlaceOrderPayload,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
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
    failed_items = []

    for cart_item in cart_items:
        product = cart_item.product
        if not product or not product.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product {cart_item.product_id} is no longer active.",
            )

        # Atomic conditional update
        stmt = (
            update(Product)
            .where(Product.id == product.id)
            .where(Product.stock >= cart_item.quantity)
            .values(
                stock=Product.stock - cart_item.quantity,
                sold_count=Product.sold_count + cart_item.quantity,
            )
            .returning(Product.id)
        )
        result = await db.execute(stmt)

        updated = result.scalar_one_or_none()

        if updated is None:
            # Fetch current stock to display a helpful message
            check_res = await db.execute(
                select(Product.stock, Product.name).where(Product.id == product.id)
            )
            row = check_res.first()
            current_stock = row[0] if row else 0
            product_name = row[1] if row else "Unknown Product"
            failed_items.append(
                {
                    "product_id": str(product.id),
                    "name": product_name,
                    "requested": cart_item.quantity,
                    "available": current_stock,
                }
            )
        else:
            item_total = product.price * cart_item.quantity
            total += item_total

            # Prepare OrderItem
            order_item = OrderItem(
                product_id=product.id,
                quantity=cart_item.quantity,
                price_at_purchase=product.price,
            )
            order_items_to_create.append(order_item)

    if failed_items:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "insufficient_stock",
                "message": "Some items in your cart do not have enough stock.",
                "items": failed_items,
            },
        )

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

    # Invalidate product cache and products list cache in Redis
    from app.services.cache import (
        invalidate_all_products_lists,
        invalidate_product_cache,
    )

    for cart_item in cart_items:
        await invalidate_product_cache(str(cart_item.product_id))
    await invalidate_all_products_lists()

    # 5. Eager load Order details for response
    response_result = await db.execute(
        select(Order)
        .options(selectinload(Order.items).joinedload(OrderItem.product))
        .where(Order.id == order.id)
    )
    return response_result.scalar_one()


@router.get("", response_model=OrderPaginatedResponse)
async def list_orders(
    page: int = 1,
    limit: int = 10,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Count total
    count_stmt = select(func.count(Order.id)).where(Order.customer_id == user.id)
    count_res = await db.execute(count_stmt)
    total = count_res.scalar() or 0

    # Fetch items
    query = (
        select(Order)
        .options(selectinload(Order.items).joinedload(OrderItem.product))
        .where(Order.customer_id == user.id)
        .order_by(Order.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(query)
    items = list(result.scalars().all())

    # Batch fetch ratings for all fetched orders
    order_ids = [o.id for o in items]
    if order_ids:
        from app.db.models.rating import ProductRating

        ratings_res = await db.execute(
            select(ProductRating).where(ProductRating.order_id.in_(order_ids))
        )
        ratings_map = {
            (str(r.order_id), str(r.product_id)): r for r in ratings_res.scalars().all()
        }
        for o in items:
            for item in o.items:
                if item.product_id:
                    item.rating = ratings_map.get((str(o.id), str(item.product_id)))

    pages = max(1, (total + limit - 1) // limit)
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages,
    }


@router.get("/seller/queue", response_model=OrderPaginatedResponse)
async def list_seller_orders(
    page: int = 1,
    limit: int = 10,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Count total unique orders for this seller
    count_stmt = (
        select(func.count(Order.id.distinct()))
        .join(OrderItem)
        .join(Product)
        .where(Product.seller_id == seller.id)
    )
    count_res = await db.execute(count_stmt)
    total = count_res.scalar() or 0

    # Fetch items
    result = await db.execute(
        select(Order)
        .join(OrderItem)
        .join(Product)
        .where(Product.seller_id == seller.id)
        .options(selectinload(Order.items).joinedload(OrderItem.product))
        .distinct()
        .order_by(Order.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    items = list(result.scalars().all())

    # Batch fetch ratings for all fetched orders
    order_ids = [o.id for o in items]
    if order_ids:
        from app.db.models.rating import ProductRating

        ratings_res = await db.execute(
            select(ProductRating).where(ProductRating.order_id.in_(order_ids))
        )
        ratings_map = {
            (str(r.order_id), str(r.product_id)): r for r in ratings_res.scalars().all()
        }
        for o in items:
            for item in o.items:
                if item.product_id:
                    item.rating = ratings_map.get((str(o.id), str(item.product_id)))

    pages = max(1, (total + limit - 1) // limit)
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages,
    }


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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

    # Fetch ratings for this order
    from app.db.models.rating import ProductRating

    ratings_res = await db.execute(
        select(ProductRating).where(ProductRating.order_id == order_id)
    )
    ratings = {str(r.product_id): r for r in ratings_res.scalars().all()}
    for item in order.items:
        if item.product_id:
            item.rating = ratings.get(str(item.product_id))

    return order


@router.put("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: uuid.UUID,
    payload: UpdateStatusPayload,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
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

    # Set status change timestamp
    import datetime

    now = datetime.datetime.utcnow()
    if payload.status == OrderStatus.packed:
        order.packed_at = now
    elif payload.status == OrderStatus.out_for_delivery:
        order.out_for_delivery_at = now
    elif payload.status == OrderStatus.delivered:
        order.delivered_at = now

    await db.commit()

    # Fetch ratings for this order
    from app.db.models.rating import ProductRating

    ratings_res = await db.execute(
        select(ProductRating).where(ProductRating.order_id == order_id)
    )
    ratings = {str(r.product_id): r for r in ratings_res.scalars().all()}
    for item in order.items:
        if item.product_id:
            item.rating = ratings.get(str(item.product_id))

    return order

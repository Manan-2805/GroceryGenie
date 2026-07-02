import uuid
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.dependencies import get_current_seller, get_db
from app.db.models.product import Product
from app.db.models.user import User

router = APIRouter(prefix="/products", tags=["Products"])


# Schemas
class ProductResponse(BaseModel):
    id: uuid.UUID
    seller_id: uuid.UUID
    name: str
    description: str
    category: str
    price: Decimal
    stock: int
    image_url: str | None
    avg_rating: Decimal
    sold_count: int
    is_active: bool

    class Config:
        from_attributes = True


class ProductCreate(BaseModel):
    name: str
    description: str
    category: str
    price: Decimal
    stock: int
    image_url: str | None = None


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    price: Decimal | None = None
    stock: int | None = None
    image_url: str | None = None
    is_active: bool | None = None


# Background Tasks
async def trigger_product_indexing(product_id: uuid.UUID) -> None:
    from app.db.base import AsyncSessionFactory
    from app.services.rag.graph import link_product_to_aisle
    from app.services.rag.retriever import index_product_in_qdrant

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Product).where(Product.id == product_id)
            )
            product = result.scalar_one_or_none()
            if not product:
                return

            # Index in Qdrant
            await index_product_in_qdrant(
                product.id,
                product.name,
                product.description,
                product.category,
                float(product.price),
                product.is_active,
            )

            # Index in Neo4j
            link_product_to_aisle(
                product.id,
                product.name,
                product.category,
            )
    except Exception as e:
        # Safe fallback print for background worker logging
        import sys
        sys.stderr.write(f"Error in background product indexing task: {e}\n")


@router.get("", response_model=list[ProductResponse])
async def list_products(
    category: str | None = None,
    featured: bool | None = None,
    db: AsyncSession = Depends(get_db)
) -> list[Product]:
    query = select(Product).where(Product.is_active)

    if category:
        query = query.where(Product.category == category)

    # Simple mock for featured (e.g. highest avg rating or first few items)
    if featured:
        query = query.order_by(Product.avg_rating.desc()).limit(10)
    else:
        query = query.order_by(Product.name.asc())

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> Product:
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )
    return product


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    background_tasks: BackgroundTasks,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db)
) -> Product:
    product = Product(
        seller_id=seller.id,
        name=payload.name,
        description=payload.description,
        category=payload.category,
        price=payload.price,
        stock=payload.stock,
        image_url=payload.image_url,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)

    # Trigger async indexing tasks
    background_tasks.add_task(trigger_product_indexing, product.id)

    return product


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    background_tasks: BackgroundTasks,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db)
) -> Product:
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.seller_id == seller.id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found or not owned by you.",
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)

    await db.commit()
    await db.refresh(product)

    # Re-trigger indexing
    background_tasks.add_task(trigger_product_indexing, product.id)

    return product


@router.delete("/{product_id}")
async def delete_product(
    product_id: uuid.UUID,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.seller_id == seller.id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found or not owned by you.",
        )

    # Soft delete: set is_active=False
    product.is_active = False
    await db.commit()

    return {"status": "success", "detail": "Product deactivated."}

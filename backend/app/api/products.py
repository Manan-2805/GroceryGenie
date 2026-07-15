import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_seller, get_db
from app.db.models.product import Product
from app.db.models.user import User
from app.services.cache import (
    get_cached_product,
    get_cached_products_list,
    invalidate_all_products_lists,
    invalidate_product_cache,
    set_cached_product,
    set_cached_products_list,
)

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


class ProductPaginatedResponse(BaseModel):
    items: list[ProductResponse]
    total: int
    page: int
    limit: int
    pages: int


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


@router.get("", response_model=ProductPaginatedResponse)
async def list_products(
    category: str | None = None,
    featured: bool | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    min_rating: Decimal | None = None,
    only_in_stock: bool | None = None,
    search: str | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    page: int = 1,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Try fetching from cache
    cached_list = await get_cached_products_list(category, featured)
    products_to_filter: list[dict[str, Any]] = []
    if cached_list is not None:
        products_to_filter = cached_list
    else:
        query = select(Product).where(Product.is_active)

        if category:
            query = query.where(Product.category == category)

        # Simple mock for featured (e.g. highest avg rating or first few items)
        if featured:
            query = query.order_by(Product.avg_rating.desc()).limit(10)
        else:
            query = query.order_by(Product.name.asc())

        result = await db.execute(query)
        db_products = list(result.scalars().all())

        # Cache list
        serialized = []
        for p in db_products:
            serialized.append(
                {
                    "id": str(p.id),
                    "seller_id": str(p.seller_id),
                    "name": p.name,
                    "description": p.description,
                    "category": p.category,
                    "price": str(p.price),
                    "stock": p.stock,
                    "image_url": p.image_url,
                    "avg_rating": str(p.avg_rating),
                    "sold_count": p.sold_count,
                    "is_active": p.is_active,
                }
            )
        await set_cached_products_list(category, featured, serialized)
        products_to_filter = serialized

    # Apply advanced filtering in Python
    filtered_list: list[dict[str, Any]] = []
    for prod in products_to_filter:
        price_val = Decimal(str(prod["price"]))
        rating_val = Decimal(str(prod["avg_rating"]))

        if min_price is not None and price_val < min_price:
            continue
        if max_price is not None and price_val > max_price:
            continue
        if min_rating is not None and rating_val < min_rating:
            continue
        if only_in_stock and int(str(prod["stock"])) <= 0:
            continue
        if search:
            q = search.lower()
            if (
                q not in str(prod["name"]).lower()
                and q not in str(prod["description"]).lower()
            ):
                continue
        filtered_list.append(prod)

    # Apply sorting
    s_by = sort_by or "name"
    s_dir = sort_dir or "asc"

    def get_sort_key(item: dict[str, Any]) -> Any:
        if s_by == "price":
            return Decimal(item["price"])
        if s_by == "avg_rating":
            return Decimal(item["avg_rating"])
        if s_by == "sold_count":
            return int(item["sold_count"])
        return item["name"].lower()

    reverse = s_dir.lower() == "desc"
    filtered_list.sort(key=get_sort_key, reverse=reverse)

    # Paginate
    total = len(filtered_list)
    pages = max(1, (total + limit - 1) // limit)
    start = (page - 1) * limit
    end = start + limit
    items = filtered_list[start:end]

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages,
    }


@router.get("/seller", response_model=ProductPaginatedResponse)
async def list_seller_products(
    category: str | None = None,
    is_active: bool | None = None,
    stock_level: str | None = None,
    page: int = 1,
    limit: int = 20,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all products owned by the logged in seller (both active and inactive)."""
    query = select(Product).where(Product.seller_id == seller.id)

    if category and category != "All":
        query = query.where(Product.category == category)

    if is_active is not None:
        query = query.where(Product.is_active == is_active)

    if stock_level == "low":
        query = query.where(Product.stock < 10)
    elif stock_level == "out":
        query = query.where(Product.stock == 0)

    # Count total
    count_stmt = select(func.count(Product.id)).select_from(query.subquery())
    count_res = await db.execute(count_stmt)
    total = count_res.scalar() or 0

    # Fetch items
    query = query.order_by(Product.name.asc()).offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    items = list(result.scalars().all())

    pages = max(1, (total + limit - 1) // limit)
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages,
    }


@router.post("/upload")
async def upload_product_image(
    file: UploadFile = File(...),
    _: User = Depends(get_current_seller),
) -> dict[str, str]:
    """Saves uploaded image file to UPLOADS_DIR and returns local web URL."""
    from app.core.config import UPLOADS_DIR

    # 1. Proper file validation (type and size)
    if file.content_type not in ["image/jpeg", "image/png", "image/gif", "image/webp"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Only JPEG, PNG, GIF, and WEBP images are allowed.",
        )

    # Limit file size to 5MB
    max_size = 5 * 1024 * 1024
    content = await file.read()
    if len(content) > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size exceeds maximum limit of 5MB.",
        )
    await file.seek(0)

    # Ensure uploads dir exists
    upload_dir = UPLOADS_DIR
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique file name
    ext = Path(file.filename or "").suffix or ".jpg"
    filename = f"{uuid.uuid4()}{ext}"
    file_path = upload_dir / filename

    try:
        with open(file_path, "wb") as f:
            f.write(content)
        return {"url": f"http://localhost:8000/uploads/{filename}"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save uploaded image: {e}",
        ) from e


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> Product | dict[str, Any]:
    # Try fetching from cache
    cached_product = await get_cached_product(str(product_id))
    if cached_product is not None:
        return cached_product

    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Cache product
    serialized = {
        "id": str(product.id),
        "seller_id": str(product.seller_id),
        "name": product.name,
        "description": product.description,
        "category": product.category,
        "price": str(product.price),
        "stock": product.stock,
        "image_url": product.image_url,
        "avg_rating": str(product.avg_rating),
        "sold_count": product.sold_count,
        "is_active": product.is_active,
    }
    await set_cached_product(str(product_id), serialized)

    return product


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    background_tasks: BackgroundTasks,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
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

    # Invalidate all lists cache
    await invalidate_all_products_lists()

    # Trigger async indexing tasks
    background_tasks.add_task(trigger_product_indexing, product.id)

    return product


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    background_tasks: BackgroundTasks,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
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

    # Invalidate specific product cache and all lists
    await invalidate_product_cache(str(product.id))

    # Re-trigger indexing
    background_tasks.add_task(trigger_product_indexing, product.id)

    return product


@router.delete("/{product_id}")
async def delete_product(
    product_id: uuid.UUID,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
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

    # Invalidate specific product cache and all lists
    await invalidate_product_cache(str(product.id))

    return {"status": "success", "detail": "Product deactivated."}


class ProductQAPayload(BaseModel):
    question: str


@router.post("/{product_id}/qa")
async def product_qa(
    product_id: uuid.UUID,
    payload: ProductQAPayload,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Provides product-scoped RAG QA text delta streaming (SSE)."""
    import asyncio
    import json
    from collections.abc import AsyncGenerator

    from fastapi.responses import StreamingResponse

    from app.services.agent.llm import call_llm

    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    system_prompt = (
        "You are an expert product advisor for GroceryGenie.\n"
        "Your task is to answer user questions about a specific product based on its details.\n"
        "Here are the product details:\n"
        f"Name: {product.name}\n"
        f"Description: {product.description}\n"
        f"Category: {product.category}\n"
        f"Price: EUR {product.price}\n"
        f"Stock: {product.stock} units\n\n"
        "Rules:\n"
        "1. Be concise, helpful, and polite.\n"
        "2. If the user asks about allergies, dietary restrictions, or safety, always answer based ONLY on the provided description/ingredients, and explicitly append: 'Please check the label or consult staff for medical safety.'\n"
        "3. Answer ONLY regarding the product details provided."
    )

    full_text = await call_llm(system_prompt, payload.question)

    async def product_qa_generator() -> AsyncGenerator[str, None]:
        words = full_text.split(" ")
        for i, word in enumerate(words):
            chunk = word + (" " if i < len(words) - 1 else "")
            data = {"type": "delta", "text": chunk}
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(0.04)

    return StreamingResponse(product_qa_generator(), media_type="text/event-stream")

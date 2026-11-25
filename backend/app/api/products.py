import asyncio
import io
import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.products import (
    FoodFacts,
    ProductCreate,
    ProductUpdate,
    SearchFilters,
    create_product,
    product_query,
    seller_product,
    write_product,
)
from app.core.config import UPLOADS_DIR
from app.core.dependencies import get_current_seller, get_current_user, get_db
from app.db.models.product import Product
from app.db.models.user import User

router = APIRouter(prefix="/products", tags=["Products"])
Page = Annotated[int, Query(ge=1, le=10000)]
Limit = Annotated[int, Query(ge=1, le=100)]
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000


class ProductResponse(FoodFacts):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    category: str
    brand: str
    package: str
    price: Decimal
    image_url: str | None
    stock: int
    avg_rating: Decimal
    sold_count: int
    is_active: bool
    seller_id: UUID


class SellerProductResponse(ProductResponse):
    cost_price: Decimal


class ProductPaginatedResponse[ProductShape](BaseModel):
    items: list[ProductShape]
    total: int
    page: int
    limit: int
    pages: int


async def pagination(
    db: AsyncSession, stmt: Select[tuple[Product]], page: int, limit: int
) -> tuple[list[Product], int, int]:
    total = (
        await db.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )
        or 0
    )
    items = list(await db.scalars(stmt.offset((page - 1) * limit).limit(limit)))
    return items, total, max(1, (total + limit - 1) // limit)


@router.get("", response_model=ProductPaginatedResponse[ProductResponse])
async def list_products(
    category: Annotated[str | None, Query(max_length=100)] = None,
    featured: bool = False,
    min_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    min_rating: Annotated[Decimal | None, Query(ge=0, le=5)] = None,
    only_in_stock: bool = False,
    search: Annotated[str | None, Query(max_length=160)] = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    page: Page = 1,
    limit: Limit = 20,
    db: AsyncSession = Depends(get_db),
) -> ProductPaginatedResponse[ProductResponse]:
    filters = SearchFilters(
        query=search or "",
        category=category,
        min_price=min_price,
        max_price=max_price,
        min_rating=min_rating,
        stock_quantity=1 if only_in_stock else None,
    )
    stmt = product_query(filters, ranked=sort_by is None and not featured)
    sort_fields = {
        "name": Product.name,
        "price": Product.price,
        "avg_rating": Product.avg_rating,
        "sold_count": Product.sold_count,
    }
    field = sort_fields.get(sort_by or "name", Product.name)
    if featured:
        stmt = stmt.order_by(Product.avg_rating.desc())
    stmt = stmt.order_by(
        field.desc() if sort_dir == "desc" else field.asc(), Product.id
    )
    items, total, pages = await pagination(db, stmt, page, limit)
    return ProductPaginatedResponse(
        items=[ProductResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )


@router.get("/seller", response_model=ProductPaginatedResponse[SellerProductResponse])
async def list_seller_products(
    category: Annotated[str | None, Query(max_length=100)] = None,
    is_active: bool | None = None,
    stock_level: str | None = None,
    page: Page = 1,
    limit: Limit = 20,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> ProductPaginatedResponse[SellerProductResponse]:
    stmt = select(Product).where(Product.seller_id == seller.id)
    if category:
        stmt = stmt.where(Product.category == category)
    if is_active is not None:
        stmt = stmt.where(Product.is_active == is_active)
    if stock_level == "low":
        stmt = stmt.where(Product.stock.between(1, 10))
    if stock_level == "out":
        stmt = stmt.where(Product.stock == 0)
    items, total, pages = await pagination(
        db, stmt.order_by(Product.name, Product.id), page, limit
    )
    return ProductPaginatedResponse(
        items=[SellerProductResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )


def encode_upload(data: bytes) -> str:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise HTTPException(413, "Image dimensions are too large.")
            image.thumbnail((1400, 1400))
            converted = image.convert("RGB")
            name = f"{uuid4()}.jpg"
            UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            converted.save(UPLOADS_DIR / name, format="JPEG")
            return name
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(415, "Upload a valid JPEG, PNG, or WebP image.") from exc


@router.post("/upload")
async def upload_product_image(
    file: UploadFile = File(...),
    _: User = Depends(get_current_seller),
) -> dict[str, str]:
    async with file:
        data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image is larger than 5 MB.")
    return {"url": f"/uploads/{await asyncio.to_thread(encode_upload, data)}"}


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: UUID, db: AsyncSession = Depends(get_db)) -> Product:
    product = await db.scalar(
        select(Product).where(Product.id == product_id, Product.is_active.is_(True))
    )
    if product is None:
        raise HTTPException(404, "Product not found.")
    return product


@router.post("", response_model=SellerProductResponse, status_code=201)
async def create_product_route(
    payload: ProductCreate,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Product:
    product = create_product(seller.id, payload)
    db.add(product)
    await db.commit()
    return product


@router.put("/{product_id}", response_model=SellerProductResponse)
async def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Product:
    product = await seller_product(db, seller.id, product_id)
    write_product(product, payload)
    await db.commit()
    return product


class StockAddition(BaseModel):
    quantity: int = Field(gt=0, le=100_000)


@router.post("/{product_id}/stock", response_model=SellerProductResponse)
async def add_stock(
    product_id: UUID,
    payload: StockAddition,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Product:
    product = await seller_product(db, seller.id, product_id)
    if product.stock + payload.quantity > 1_000_000:
        raise HTTPException(409, "Stock limit exceeded.")
    product.stock += payload.quantity
    await db.commit()
    return product


@router.delete("/{product_id}")
async def delete_product(
    product_id: UUID,
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    product = await seller_product(db, seller.id, product_id)
    product.is_active = False
    await db.commit()
    return {"status": "success"}


class ProductQAPayload(BaseModel):
    question: str = Field(min_length=1, max_length=300)


def product_answer(product: Product, question: str) -> str:
    question = question.lower()
    source = product.label_source or "store product record"
    if any(word in question for word in ("allerg", "safe", "contain", "intoler")):
        if product.allergens is None:
            return "Allergen information is unavailable. Check the package label before use."
        value = ", ".join(product.allergens) or "none listed"
        return (
            f"Recorded allergens: {value}. Source: {source}. Check the package label."
        )
    if "ingredient" in question:
        return (
            f"Ingredients: {product.ingredients}. Source: {source}."
            if product.ingredients
            else "Ingredient information is unavailable."
        )
    if any(word in question for word in ("nutri", "protein", "calorie", "sugar")):
        values = ", ".join(f"{k}: {v}" for k, v in (product.nutrition or {}).items())
        return (
            f"Nutrition: {values}. Source: {source}."
            if values
            else "Nutrition information is unavailable."
        )
    if any(word in question for word in ("vegetarian", "vegan", "diet")):
        tags = ", ".join(product.dietary_tags or [])
        return (
            f"Recorded dietary labels: {tags}. Source: {source}."
            if tags
            else "Dietary information is unavailable."
        )
    return f"{product.name}, {product.package}, ₹{product.price:.2f}. Available packages: {product.stock}."


@router.post("/{product_id}/qa")
async def product_qa(
    product_id: UUID,
    payload: ProductQAPayload,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    product = await get_product(product_id, db)
    answer = product_answer(product, payload.question)

    async def response() -> AsyncIterator[str]:
        yield f"data: {json.dumps({'type': 'delta', 'text': answer})}\n\n"

    return StreamingResponse(response(), media_type="text/event-stream")

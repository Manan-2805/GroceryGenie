from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Select, Text, func, literal_column, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import cast

from app.db.models.enums import UserRole
from app.db.models.product import SEARCH_DOCUMENT, Product
from app.db.models.user import User

Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
Label = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
Money = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
Stock = Annotated[int, Field(ge=0, le=1_000_000)]


class FoodFacts(BaseModel):
    ingredients: Annotated[str, Field(max_length=3000)] | None = None
    dietary_tags: Annotated[list[Label], Field(max_length=20)] | None = None
    allergens: Annotated[list[Label], Field(max_length=30)] | None = None
    nutrition: Annotated[dict[Label, Label], Field(max_length=30)] | None = None
    label_source: Label | None = None


class ProductCreate(FoodFacts):
    model_config = ConfigDict(extra="forbid")
    name: Name
    description: Annotated[str, Field(max_length=3000)] = ""
    category: Label
    brand: Annotated[str, Field(max_length=100)] = ""
    package: Label = "1 pack"
    price: Money
    cost_price: Money = Decimal("0")
    stock: Stock = 0
    image_url: Annotated[str, Field(max_length=1024)] | None = None


class ProductUpdate(FoodFacts):
    model_config = ConfigDict(extra="forbid")
    name: Name | None = None
    description: Annotated[str, Field(max_length=3000)] | None = None
    category: Label | None = None
    brand: Annotated[str, Field(max_length=100)] | None = None
    package: Label | None = None
    price: Money | None = None
    cost_price: Money | None = None
    stock: Stock | None = None
    expected_stock: Stock | None = None
    image_url: Annotated[str, Field(max_length=1024)] | None = None
    is_active: bool | None = None


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: Annotated[str, Field(max_length=160)] = ""
    category: Label | None = None
    brand: Label | None = None
    package: Label | None = None
    dietary_tag: Label | None = None
    stock_quantity: Annotated[int, Field(ge=1, le=1000)] | None = None
    min_price: Money | None = None
    max_price: Money | None = None
    min_rating: Annotated[Decimal, Field(ge=0, le=5)] | None = None
    sort: Literal["relevance", "cheapest"] = "relevance"


def product_query(
    filters: SearchFilters, *, ranked: bool = True
) -> Select[tuple[Product]]:
    stmt = select(Product).where(Product.is_active.is_(True))
    if filters.category:
        stmt = stmt.where(func.lower(Product.category) == filters.category.lower())
    if filters.brand:
        stmt = stmt.where(func.lower(Product.brand) == filters.brand.lower())
    if filters.package:
        stmt = stmt.where(Product.package.icontains(filters.package, autoescape=True))
    if filters.dietary_tag:
        stmt = stmt.where(
            cast(Product.dietary_tags, JSONB).contains([filters.dietary_tag.lower()])
        )
    if filters.stock_quantity:
        stmt = stmt.where(Product.stock >= filters.stock_quantity)
    if filters.min_price is not None:
        stmt = stmt.where(Product.price >= filters.min_price)
    if filters.max_price is not None:
        stmt = stmt.where(Product.price <= filters.max_price)
    if filters.min_rating is not None:
        stmt = stmt.where(Product.avg_rating >= filters.min_rating)
    if filters.sort == "cheapest":
        stmt = stmt.order_by(Product.price.asc())
    query = filters.query.strip()
    if query:
        fts_config = literal_column("'simple'::regconfig", Text())
        document = literal_column(SEARCH_DOCUMENT, Text())
        needle = func.plainto_tsquery(fts_config, query)
        stmt = stmt.where(document.bool_op("@@")(needle))
        if ranked:
            stmt = stmt.order_by(
                (func.lower(Product.name) == query.lower()).desc(),
                func.ts_rank(document, needle).desc(),
            )
    return stmt


async def search_products(
    db: AsyncSession, filters: SearchFilters, *, limit: int = 10
) -> list[Product]:
    return list(
        await db.scalars(
            product_query(filters).order_by(Product.name, Product.id).limit(limit)
        )
    )


async def seller_product(
    db: AsyncSession, seller_id: UUID, product_id: UUID
) -> Product:
    seller = await db.scalar(
        select(User)
        .where(User.id == seller_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if seller is None or seller.role != UserRole.seller:
        raise HTTPException(403, "Seller mode is required.")
    product = await db.scalar(
        select(Product)
        .where(Product.id == product_id, Product.seller_id == seller_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if product is None:
        raise HTTPException(404, "Product not found.")
    return product


def write_product(product: Product, payload: ProductUpdate) -> None:
    fields = payload.model_dump(exclude_unset=True, exclude={"expected_stock"})
    nonnullable = {
        "name",
        "description",
        "category",
        "brand",
        "package",
        "price",
        "cost_price",
        "stock",
        "is_active",
    }
    if any(value is None and key in nonnullable for key, value in fields.items()):
        raise HTTPException(422, "Required product fields cannot be cleared.")
    if (
        "stock" in fields
        and fields["stock"] != product.stock
        and product.stock != payload.expected_stock
    ):
        raise HTTPException(
            409, "Stock changed. Refresh the product before replacing stock."
        )
    if isinstance(fields.get("dietary_tags"), list):
        fields["dietary_tags"] = [tag.lower() for tag in fields["dietary_tags"]]
    for key, value in fields.items():
        setattr(product, key, value)


def create_product(seller_id: UUID, payload: ProductCreate) -> Product:
    values = payload.model_dump()
    if payload.dietary_tags is not None:
        values["dietary_tags"] = [tag.lower() for tag in payload.dietary_tags]
    return Product(seller_id=seller_id, **values)


def increase_stock(product: Product, quantity: int) -> None:
    if not 1 <= quantity <= 100_000:
        raise HTTPException(422, "Enter a positive quantity up to 100,000.")
    if product.stock + quantity > 1_000_000:
        raise HTTPException(409, "Stock limit exceeded.")
    product.stock += quantity

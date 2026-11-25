from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.products import SearchFilters
from app.catalog.products import search_products as search_catalog
from app.db.models.product import Product


async def search_products(
    db: AsyncSession,
    query_text: str,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 10,
) -> list[Product]:
    return await search_catalog(
        db,
        SearchFilters(
            query=query_text,
            category=category,
            min_price=Decimal(str(min_price)) if min_price is not None else None,
            max_price=Decimal(str(max_price)) if max_price is not None else None,
        ),
        limit=limit,
    )

"""Product search and compare tools — pure Python, no LLM calls."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.search import search_products as search_products_service

# Maximum products to return per search (no narrowing flow — removed per plan Q1)
_FETCH_LIMIT = 10


async def search_products(
    db: AsyncSession,
    user_id: Any = None,
    query: str | None = None,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_rating: float | None = None,
    in_stock_only: bool = False,  # default False — show all unless user asks
    **kwargs: Any,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Search products with optional filters.

    Returns a list of up to _FETCH_LIMIT products serialised as dicts.
    Never returns a 'too_many' dict — the narrowing flow was removed.
    """
    products = await search_products_service(
        db=db,
        query_text=query or "",
        category=category,
        min_price=min_price,
        max_price=max_price,
        limit=_FETCH_LIMIT,
    )

    results: list[dict[str, Any]] = []
    for p in products:
        if in_stock_only and p.stock <= 0:
            continue
        if min_rating is not None and float(p.avg_rating) < min_rating:
            continue
        results.append(
            {
                "id": str(p.id),
                "name": p.name,
                "description": p.description,
                "category": p.category,
                "price": float(p.price),
                "stock": p.stock,
                "avg_rating": float(p.avg_rating),
                "sold_count": p.sold_count,
                "is_active": p.is_active,
            }
        )

    return results

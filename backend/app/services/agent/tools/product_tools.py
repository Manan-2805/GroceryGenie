"""Product search tool - pure Python, no LLM calls."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.search import search_products as search_products_service

# Maximum products to show before asking the user to narrow down
_TOO_MANY_THRESHOLD = 8
# Fetch at most this many from the hybrid search
_FETCH_LIMIT = 5


async def search_products(
    db: AsyncSession,
    user_id: Any = None,
    query: str | None = None,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_rating: float | None = None,
    in_stock_only: bool = True,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Search products with optional filters. Returns serialized product list.

    If too many results (>_TOO_MANY_THRESHOLD), returns a dict with `too_many: True`
    so the orchestrator can ask the user to narrow down their search.
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
        if min_rating and float(p.avg_rating) < min_rating:
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
            }
        )

    # If too many results, return a narrowing request with product summaries
    if len(results) > _TOO_MANY_THRESHOLD:
        categories = list({r["category"] for r in results})
        prices = [float(r["price"]) for r in results]
        price_min = min(prices)
        price_max = max(prices)

        return {
            "too_many": True,
            "count": len(results),
            "products": results[:5],  # Send top 5 for context
            "categories": categories,
            "price_range": {"min": price_min, "max": price_max},
            "product_names": [r["name"] for r in results[:10]],
            "message": f"Found {len(results)} products. The user needs to narrow down their search.",
        }

    return results

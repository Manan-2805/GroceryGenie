"""Inventory tools — seller-side stock view with rich filtering. Pure Python, no LLM calls."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.product import Product


def _classify_stock(stock: int) -> str:
    """Return a stock status label for a given stock level."""
    if stock == 0:
        return "out_of_stock"
    if stock <= 10:
        return "low_stock"
    return "in_stock"


async def inventory_search(
    db: AsyncSession,
    user_id: UUID,
    stock_filter: str | None = None,
    min_rating: float | None = None,
    min_sold: int | None = None,
    max_sold: int | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    category: str | None = None,
    sort_by: str | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Search/filter the seller's own products as an inventory view.

    All parameters are optional — called with no params returns the full inventory.

    Args:
        stock_filter: "in_stock" (stock > 10), "low_stock" (1-10), "out_of_stock" (0)
        min_rating:   Only products with avg_rating >= this value
        min_sold:     Only products with sold_count >= this value
        max_sold:     Only products with sold_count <= this value
        min_price:    Only products with price >= this value
        max_price:    Only products with price <= this value
        category:     Exact category string match (case-insensitive)
        sort_by:      One of: stock_asc, stock_desc, rating_desc, sold_desc,
                      price_asc, price_desc (default: name_asc)
    """
    result = await db.execute(select(Product).where(Product.seller_id == user_id))
    all_products = list(result.scalars().all())

    if not all_products:
        return {"empty": True, "message": "You have no products in your inventory yet."}

    # Classify each product and apply filters in Python
    rows: list[dict[str, Any]] = []
    for p in all_products:
        stock_status = _classify_stock(p.stock)

        # stock_filter
        if stock_filter and stock_status != stock_filter:
            continue
        # min_rating
        if min_rating is not None and float(p.avg_rating) < min_rating:
            continue
        # sold counts
        if min_sold is not None and p.sold_count < min_sold:
            continue
        if max_sold is not None and p.sold_count > max_sold:
            continue
        # price range
        if min_price is not None and float(p.price) < min_price:
            continue
        if max_price is not None and float(p.price) > max_price:
            continue
        # category
        if category and p.category.lower() != category.lower():
            continue

        rows.append(
            {
                "stock_status": stock_status,  # discriminator for formatter
                "id": str(p.id),
                "name": p.name,
                "category": p.category,
                "price": float(p.price),
                "stock": p.stock,
                "avg_rating": float(p.avg_rating),
                "sold_count": p.sold_count,
                "is_active": p.is_active,
            }
        )

    if not rows:
        return {"empty": True, "message": "No products match your inventory filters."}

    # Sort
    sort_key = {
        "stock_asc": lambda r: r["stock"],
        "stock_desc": lambda r: -r["stock"],
        "rating_desc": lambda r: -r["avg_rating"],
        "sold_desc": lambda r: -r["sold_count"],
        "price_asc": lambda r: r["price"],
        "price_desc": lambda r: -r["price"],
    }
    if sort_by and sort_by in sort_key:
        rows.sort(key=sort_key[sort_by])
    else:
        rows.sort(key=lambda r: r["name"].lower())

    # Prepend a summary header row so the formatter can display aggregate stats
    in_stock_count = sum(1 for r in rows if r["stock_status"] == "in_stock")
    low_stock_count = sum(1 for r in rows if r["stock_status"] == "low_stock")
    oos_count = sum(1 for r in rows if r["stock_status"] == "out_of_stock")

    summary_row: dict[str, Any] = {
        "_summary": True,
        "stock_status": "summary",  # keeps discriminator active
        "total_skus": len(rows),
        "in_stock_count": in_stock_count,
        "low_stock_count": low_stock_count,
        "out_of_stock_count": oos_count,
    }

    return [summary_row, *rows]

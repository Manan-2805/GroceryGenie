"""compare_products tool — pure Python, no LLM calls."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.product import Product


async def compare_products(
    db: AsyncSession,
    user_id: Any,
    product_ids: list[str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Fetch 2–3 products and return a structured comparison dict.

    Args:
        product_ids: List of 2–3 product UUID strings.

    Returns:
        {"compare": True, "products": [...]} on success.
        {"success": False, "message": "..."} on error.
    """
    if not product_ids:
        return {
            "success": False,
            "message": "Please provide 2 or 3 product IDs to compare.",
        }

    if len(product_ids) < 2:
        return {
            "success": False,
            "message": "I need at least 2 products to compare. Please provide 2 or 3 product IDs.",
        }

    if len(product_ids) > 3:
        product_ids = product_ids[:3]

    products = []
    for pid in product_ids:
        try:
            product_uuid = UUID(str(pid))
        except (ValueError, AttributeError):
            return {
                "success": False,
                "message": f"Invalid product ID format: {pid}",
            }

        result = await db.execute(select(Product).where(Product.id == product_uuid))
        product = result.scalar_one_or_none()
        if not product:
            return {
                "success": False,
                "message": f"Product not found: {pid}",
            }
        products.append(
            {
                "id": str(product.id),
                "name": product.name,
                "category": product.category,
                "price": float(product.price),
                "stock": product.stock,
                "avg_rating": float(product.avg_rating),
                "sold_count": product.sold_count,
                "description": product.description or "",
                "is_active": product.is_active,
            }
        )

    return {"compare": True, "products": products}

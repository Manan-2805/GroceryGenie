"""Seller tools - pure Python CRUD, no LLM calls."""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.product import Product

logger = logging.getLogger(__name__)


async def _sync_product_to_qdrant(product: Product) -> None:
    """Upsert a single product into the Qdrant vector store (fire-and-forget safe)."""
    try:
        from decimal import Decimal

        from qdrant_client import models as qmodels

        from app.services.rag.embedder import embed_text
        from app.services.rag.retriever import COLLECTION_NAME, get_qdrant_client

        text = f"{product.name} {product.description} {product.category}"
        vector = embed_text(text)
        client = get_qdrant_client()
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                qmodels.PointStruct(
                    id=str(product.id),
                    vector=vector,
                    payload={
                        "id": str(product.id),
                        "name": product.name,
                        "description": product.description,
                        "category": product.category,
                        "price": float(product.price)
                        if isinstance(product.price, Decimal)
                        else product.price,
                        "stock": product.stock,
                        "is_active": product.is_active,
                    },
                )
            ],
        )
        logger.info(f"[QDRANT SYNC] Upserted product {product.id} ({product.name})")
    except Exception as e:
        logger.warning(f"[QDRANT SYNC] Failed to upsert product {product.id}: {e}")


async def _remove_product_from_qdrant(product_id: UUID) -> None:
    """Remove a product from Qdrant (called on deactivation)."""
    try:
        from app.services.rag.retriever import COLLECTION_NAME, get_qdrant_client

        client = get_qdrant_client()
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=[str(product_id)],
        )
        logger.info(f"[QDRANT SYNC] Removed product {product_id} from Qdrant")
    except Exception as e:
        logger.warning(f"[QDRANT SYNC] Failed to remove product {product_id}: {e}")


async def seller_list_products(
    db: AsyncSession,
    user_id: UUID,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """List seller's own products."""
    result = await db.execute(
        select(Product).where(Product.seller_id == user_id).order_by(Product.name)
    )
    products = list(result.scalars().all())
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "category": p.category,
            "price": float(p.price),
            "stock": p.stock,
            "is_active": p.is_active,
            "sold_count": p.sold_count,
        }
        for p in products
    ]


async def seller_create_product(
    db: AsyncSession,
    user_id: UUID,
    name: str,
    description: str = "",
    category: str = "General",
    price: float = 0.0,
    stock: int = 0,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a new product as seller and auto-sync to Qdrant."""
    from decimal import Decimal

    product = Product(
        seller_id=user_id,
        name=name,
        description=description,
        category=category,
        price=Decimal(str(price)),
        stock=stock,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)

    # Event-driven Qdrant sync
    await _sync_product_to_qdrant(product)

    return {
        "success": True,
        "message": f"Product '{name}' created and indexed for search.",
        "product_id": str(product.id),
    }


async def seller_update_product(
    db: AsyncSession,
    user_id: UUID,
    product_id: str,
    name: str | None = None,
    description: str | None = None,
    category: str | None = None,
    price: float | None = None,
    stock: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Update a product as seller and auto-sync to Qdrant."""
    from decimal import Decimal

    prod_uuid = UUID(product_id)
    result = await db.execute(
        select(Product).where(Product.id == prod_uuid, Product.seller_id == user_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return {"success": False, "message": "Product not found or not yours."}

    if name is not None:
        product.name = name
    if description is not None:
        product.description = description
    if category is not None:
        product.category = category
    if price is not None:
        product.price = Decimal(str(price))
    if stock is not None:
        product.stock = stock

    await db.commit()
    await db.refresh(product)

    # Event-driven Qdrant sync
    await _sync_product_to_qdrant(product)

    return {
        "success": True,
        "message": f"Product '{product.name}' updated and re-indexed.",
    }


async def seller_delete_product(
    db: AsyncSession,
    user_id: UUID,
    product_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Deactivate a product as seller (soft delete) and remove from Qdrant."""
    prod_uuid = UUID(product_id)
    result = await db.execute(
        select(Product).where(Product.id == prod_uuid, Product.seller_id == user_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return {"success": False, "message": "Product not found or not yours."}

    product.is_active = False
    await db.commit()

    # Event-driven Qdrant removal
    await _remove_product_from_qdrant(prod_uuid)

    return {
        "success": True,
        "message": f"Product '{product.name}' deactivated and removed from search.",
    }

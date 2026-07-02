
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.product import Product
from app.services.rag.retriever import hybrid_search_products


async def search_products(
    db: AsyncSession,
    query_text: str,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 10,
) -> list[Product]:
    """Exposes hybrid product search (BM25 keyword + Qdrant dense vector embedding search)."""
    return await hybrid_search_products(
        db=db,
        query_text=query_text,
        category=category,
        min_price=min_price,
        max_price=max_price,
        limit=limit,
    )

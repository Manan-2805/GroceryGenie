import logging
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.db.models.product import Product
from app.services.rag.embedder import embed_text

logger = logging.getLogger("app.services.rag.retriever")

COLLECTION_NAME = "products"
VECTOR_SIZE = 384  # BAAI/bge-small-en-v1.5 has 384 dimensions

_qdrant_client: QdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        logger.info(f"Connecting to Qdrant at {settings.QDRANT_URL}...")
        _qdrant_client = QdrantClient(url=settings.QDRANT_URL)
        # Ensure collection exists
        try:
            collections = _qdrant_client.get_collections().collections
            exists = any(c.name == COLLECTION_NAME for c in collections)
            if not exists:
                logger.info(f"Creating Qdrant collection: {COLLECTION_NAME}...")
                _qdrant_client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=qmodels.VectorParams(
                        size=VECTOR_SIZE,
                        distance=qmodels.Distance.COSINE,
                    ),
                )
        except Exception as e:
            logger.error(f"Error initializing Qdrant collection: {e}")
    return _qdrant_client


async def index_product_in_qdrant(
    product_id: uuid.UUID,
    name: str,
    description: str,
    category: str,
    price: float,
    is_active: bool,
) -> None:
    try:
        client = get_qdrant_client()
        # Create text for embedding
        text_to_embed = f"{name} {description} {category}"
        vector = embed_text(text_to_embed)

        payload = {
            "id": str(product_id),
            "name": name,
            "description": description,
            "category": category,
            "price": price,
            "is_active": is_active,
        }

        client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                qmodels.PointStruct(
                    id=str(product_id),
                    vector=vector,
                    payload=payload,
                )
            ],
        )
        logger.info(f"Successfully indexed product {product_id} in Qdrant.")
    except Exception as e:
        logger.error(f"Failed to index product {product_id} in Qdrant: {e}")


async def hybrid_search_products(
    db: AsyncSession,
    query_text: str,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 10,
) -> list[Product]:
    # 1. Vector Search from Qdrant
    vector_hits = []
    try:
        client = get_qdrant_client()
        query_vector = embed_text(query_text)

        # Filters
        must_filters: list[Any] = [
            qmodels.FieldCondition(
                key="is_active", match=qmodels.MatchValue(value=True)
            )
        ]

        if category:
            must_filters.append(
                qmodels.FieldCondition(
                    key="category", match=qmodels.MatchValue(value=category)
                )
            )

        if min_price is not None:
            must_filters.append(
                qmodels.FieldCondition(key="price", range=qmodels.Range(gt=min_price))
            )
        if max_price is not None:
            must_filters.append(
                qmodels.FieldCondition(key="price", range=qmodels.Range(lt=max_price))
            )

        qdrant_filter = qmodels.Filter(must=must_filters) if must_filters else None

        search_results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=qdrant_filter,
            limit=limit * 2,  # Fetch more to allow merging
        ).points
        vector_hits = [
            uuid.UUID(hit.payload["id"]) for hit in search_results if hit.payload
        ]
    except Exception as e:
        logger.error(f"Qdrant vector search failed: {e}")

    # 2. Keyword/BM25 Search (Database query using ILIKE)
    # Match in name, description, or category
    words = query_text.split()
    db_query = select(Product).where(Product.is_active)

    if category:
        db_query = db_query.where(Product.category == category)
    if min_price is not None:
        db_query = db_query.where(Product.price >= min_price)
    if max_price is not None:
        db_query = db_query.where(Product.price <= max_price)

    # Simple text filter combining all words
    for word in words:
        db_query = db_query.where(
            Product.name.ilike(f"%{word}%")
            | Product.description.ilike(f"%{word}%")
            | Product.category.ilike(f"%{word}%")
        )

    db_query = db_query.limit(limit * 2)
    db_result = await db.execute(db_query)
    keyword_products = db_result.scalars().all()
    keyword_hits = [p.id for p in keyword_products]

    # 3. Merge results using a simple rank fusion
    # We want to keep items that match both high in the order, followed by vector-only and keyword-only
    merged_ids: list[uuid.UUID] = []

    # First, items present in both lists
    common_hits = [pid for pid in vector_hits if pid in keyword_hits]
    merged_ids.extend(common_hits)

    # Next, items present only in vector search
    vector_only = [pid for pid in vector_hits if pid not in common_hits]
    merged_ids.extend(vector_only)

    # Finally, items present only in keyword search
    keyword_only = [pid for pid in keyword_hits if pid not in common_hits]
    merged_ids.extend(keyword_only)

    # Crop to limit
    final_ids = merged_ids[:limit]

    if not final_ids:
        return []

    # 4. Fetch the full Product records in the merged order
    products_result = await db.execute(select(Product).where(Product.id.in_(final_ids)))
    products_map = {p.id: p for p in products_result.scalars().all()}

    # Preserve the merged/ranked ordering
    return [products_map[pid] for pid in final_ids if pid in products_map]

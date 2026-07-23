import contextlib
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


def cleanup_stale_qdrant_vectors(db_ids: set[uuid.UUID]) -> None:
    """Remove Qdrant points whose product IDs no longer exist in the database.
    This prevents stale results when the DB is reset/re-seeded.
    """
    client = get_qdrant_client()
    try:
        # Get all point IDs from Qdrant collection
        scroll_result = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=10000,  # Fetch up to 10k points
            with_payload=False,
            with_vectors=False,
        )
        qdrant_ids = set()
        for point in scroll_result[0]:
            with contextlib.suppress(ValueError, AttributeError):
                qdrant_ids.add(uuid.UUID(str(point.id)))

        stale_ids = qdrant_ids - db_ids
        if stale_ids:
            logger.info(
                f"Found {len(stale_ids)} stale product vectors in Qdrant. Cleaning up..."
            )
            client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=qmodels.PointIdsList(
                    points=[str(pid) for pid in stale_ids]
                ),
            )
            logger.info(f"Cleaned up {len(stale_ids)} stale vectors from Qdrant.")
        else:
            logger.debug("No stale vectors found in Qdrant.")
    except Exception as e:
        logger.warning(f"Failed to cleanup stale Qdrant vectors: {e}")


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
            score_threshold=0.55,  # Filter out low-similarity noise vectors
            limit=limit * 2,  # Fetch candidate pool for RRF
        ).points
        vector_hits = [
            uuid.UUID(hit.payload["id"])
            for hit in search_results
            if hit.payload and getattr(hit, "score", 1.0) >= 0.55
        ]
    except Exception as e:
        logger.error(f"Qdrant vector search failed: {e}")

    # 2. Keyword/BM25 Search (Database query using ILIKE)
    # Match in name, description, or category
    words = [w.strip() for w in query_text.split() if len(w.strip()) > 1]
    db_query = select(Product).where(Product.is_active)

    if category:
        db_query = db_query.where(Product.category == category)
    if min_price is not None:
        db_query = db_query.where(Product.price >= min_price)
    if max_price is not None:
        db_query = db_query.where(Product.price <= max_price)

    # Text filter combining matching words
    if words:
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

    # 3. Merge results using Reciprocal Rank Fusion (RRF with k=60)
    rrf_scores: dict[uuid.UUID, float] = {}
    k_constant = 60.0

    for rank, pid in enumerate(vector_hits):
        rrf_scores[pid] = rrf_scores.get(pid, 0.0) + (1.0 / (k_constant + rank + 1))

    for rank, pid in enumerate(keyword_hits):
        rrf_scores[pid] = rrf_scores.get(pid, 0.0) + (1.0 / (k_constant + rank + 1))

    sorted_ids = sorted(
        rrf_scores.keys(), key=lambda pid: rrf_scores[pid], reverse=True
    )
    final_ids = sorted_ids[:limit]

    if not final_ids:
        return []

    # 4. Fetch the full Product records in the merged order
    products_result = await db.execute(select(Product).where(Product.id.in_(final_ids)))
    products_map = {p.id: p for p in products_result.scalars().all()}

    # 5. Check for stale Qdrant vectors: IDs from vector search not present in DB
    vector_hit_set = set(vector_hits)
    missing_ids = [
        pid for pid in final_ids if pid in vector_hit_set and pid not in products_map
    ]
    if missing_ids and len(missing_ids) > len(final_ids) * 0.5:
        # More than 50% of vector results are stale — trigger background cleanup
        logger.warning(
            f"Detected {len(missing_ids)} stale Qdrant vectors out of {len(final_ids)} results. "
            "Triggering Qdrant cleanup..."
        )
        all_db_result = await db.execute(select(Product.id))
        all_db_ids = {row[0] for row in all_db_result.fetchall()}
        cleanup_stale_qdrant_vectors(all_db_ids)

    # Preserve the RRF-ranked ordering (skip missing IDs)
    return [products_map[pid] for pid in final_ids if pid in products_map]

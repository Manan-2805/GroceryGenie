import json
import logging
import uuid
from typing import Any

import numpy as np
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.db.models.enums import FactCategory
from app.db.models.memory import PersistentFact
from app.services.rag.embedder import embed_text

logger = logging.getLogger("app.services.memory")

_redis_client: aioredis.Redis | None = None


def get_redis_client() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        logger.info(f"Connecting to Redis at {settings.REDIS_URL}...")
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


async def append_message_to_session(session_id: str, role: str, content: str) -> None:
    """Appends a message to the Redis session list and resets its TTL to 3600 seconds."""
    try:
        client = get_redis_client()
        key = f"chat:session:{session_id}:messages"

        message_data = {
            "role": role,
            "content": content,
        }

        # Push message to Redis list
        await client.rpush(key, json.dumps(message_data))
        # Reset TTL
        await client.expire(key, settings.CHAT_SESSION_TTL_SECONDS)
        logger.debug(
            f"Appended message to Redis key '{key}' with TTL {settings.CHAT_SESSION_TTL_SECONDS}s."
        )
    except Exception as e:
        logger.error(f"Error appending message to Redis session {session_id}: {e}")


async def get_session_history(session_id: str) -> list[dict[str, str]]:
    """Retrieves list of previous messages in the session."""
    try:
        client = get_redis_client()
        key = f"chat:session:{session_id}:messages"

        raw_messages = await client.lrange(key, 0, -1)
        messages = []
        for msg in raw_messages:
            try:
                messages.append(json.loads(msg))
            except json.JSONDecodeError:
                messages.append({"role": "user", "content": msg})
        return messages
    except Exception as e:
        logger.error(f"Error retrieving Redis history for session {session_id}: {e}")
        return []


class Mem0:
    """Memory client bridging to PostgreSQL PersistentFact storage.
    Replaces the previous no-op stub with real PersistentFact-backed operations.
    """

    def __init__(self, db: AsyncSession, user_id: str | uuid.UUID | None = None):
        self.db = db
        if user_id is not None and not isinstance(user_id, uuid.UUID):
            self.user_id = uuid.UUID(str(user_id)) if user_id else None
        else:
            self.user_id = user_id

    async def add(
        self,
        text: str,
        user_id: str | uuid.UUID | None = None,
        category: str = "other",
    ) -> dict[str, Any]:
        """Store a fact/memory in PostgreSQL PersistentFact table.
        Deduplicates via case-insensitive text matching.
        """
        uid = self._resolve_user_id(user_id)
        logger.info(f"Mem0 adding fact: '{text}' for user '{uid}'")

        try:
            cat_enum = FactCategory(category) if category else FactCategory.other
        except ValueError:
            cat_enum = FactCategory.other

        # Deduplicate
        dup_query = select(PersistentFact).where(
            PersistentFact.user_id == uid,
            PersistentFact.fact_text.ilike(text.strip()),
        )
        dup_result = await self.db.execute(dup_query)
        if dup_result.scalar_one_or_none():
            return {"status": "duplicate", "message": "Fact already exists in memory"}

        fact = PersistentFact(
            user_id=uid,
            fact_text=text.strip(),
            category=cat_enum,
        )
        self.db.add(fact)
        await self.db.commit()
        await self.db.refresh(fact)

        return {
            "status": "success",
            "message": "Fact added to memory",
            "memory_id": str(fact.id),
        }

    async def get_all(
        self, user_id: str | uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        """Retrieve all facts for the given user."""
        uid = self._resolve_user_id(user_id)
        logger.debug(f"Mem0 fetching all facts for user '{uid}'")

        result = await self.db.execute(
            select(PersistentFact)
            .where(PersistentFact.user_id == uid)
            .order_by(PersistentFact.created_at.desc())
        )
        facts = list(result.scalars().all())
        return [
            {
                "id": str(f.id),
                "fact_text": f.fact_text,
                "category": f.category.value
                if hasattr(f.category, "value")
                else str(f.category),
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in facts
        ]

    async def search(
        self,
        query: str,
        user_id: str | uuid.UUID | None = None,
        limit: int = 3,
        similarity_threshold: float = 0.35,
    ) -> list[dict[str, Any]]:
        """Search facts by semantic similarity to query."""
        uid = self._resolve_user_id(user_id)
        logger.debug(f"Mem0 searching facts with query '{query}' for user '{uid}'")

        all_facts_result = await self.db.execute(
            select(PersistentFact)
            .where(PersistentFact.user_id == uid)
            .order_by(PersistentFact.created_at.desc())
        )
        all_facts = list(all_facts_result.scalars().all())

        if not all_facts:
            return []

        if not query or not query.strip():
            # No query: return most recent up to limit
            return [
                {
                    "id": str(f.id),
                    "fact_text": f.fact_text,
                    "category": f.category.value
                    if hasattr(f.category, "value")
                    else str(f.category),
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                    "score": 0.0,
                }
                for f in all_facts[:limit]
            ]

        # Embed query and compute cosine similarity
        try:
            query_vec = np.array(embed_text(query.strip()), dtype=np.float32)
            query_norm = np.linalg.norm(query_vec)
            if query_norm == 0:
                return [
                    {
                        "id": str(f.id),
                        "fact_text": f.fact_text,
                        "category": f.category.value
                        if hasattr(f.category, "value")
                        else str(f.category),
                        "created_at": f.created_at.isoformat()
                        if f.created_at
                        else None,
                        "score": 0.0,
                    }
                    for f in all_facts[:limit]
                ]

            scored: list[tuple[float, PersistentFact]] = []
            for fact in all_facts:
                fact_vec = np.array(embed_text(fact.fact_text), dtype=np.float32)
                fact_norm = np.linalg.norm(fact_vec)
                if fact_norm > 0:
                    sim = float(np.dot(query_vec, fact_vec) / (query_norm * fact_norm))
                else:
                    sim = 0.0
                scored.append((sim, fact))

            scored.sort(key=lambda x: x[0], reverse=True)
            relevant = [
                (sim, fact) for sim, fact in scored if sim >= similarity_threshold
            ]

            if not relevant:
                # Fall back to most recent if no semantic matches
                relevant = scored[:limit]

            return [
                {
                    "id": str(f.id),
                    "fact_text": f.fact_text,
                    "category": f.category.value
                    if hasattr(f.category, "value")
                    else str(f.category),
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                    "score": round(sim, 4),
                }
                for sim, f in relevant[:limit]
            ]
        except Exception as e:
            logger.warning(f"Error in Mem0.search: {e}")
            return [
                {
                    "id": str(f.id),
                    "fact_text": f.fact_text,
                    "category": f.category.value
                    if hasattr(f.category, "value")
                    else str(f.category),
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                    "score": 0.0,
                }
                for f in all_facts[:limit]
            ]

    async def delete(self, memory_id: str) -> bool:
        """Delete a fact by its UUID."""
        logger.info(f"Mem0 deleting fact with ID: '{memory_id}'")
        try:
            fid = uuid.UUID(memory_id)
            result = await self.db.execute(
                select(PersistentFact).where(PersistentFact.id == fid)
            )
            fact = result.scalar_one_or_none()
            if fact:
                await self.db.delete(fact)
                await self.db.commit()
                return True
            return False
        except (ValueError, Exception) as e:
            logger.warning(f"Failed to delete memory {memory_id}: {e}")
            return False

    def _resolve_user_id(self, user_id: str | uuid.UUID | None) -> uuid.UUID:
        """Resolve the effective user ID."""
        if user_id is not None:
            if isinstance(user_id, uuid.UUID):
                return user_id
            return uuid.UUID(str(user_id))
        if self.user_id is not None:
            if isinstance(self.user_id, uuid.UUID):
                return self.user_id
            return uuid.UUID(str(self.user_id))
        raise ValueError("No user_id provided")

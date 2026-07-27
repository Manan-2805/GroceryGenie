"""
agent/memory.py — session history and user facts helpers.

Dead functions removed (Task 13):
  - classify_and_store_fact()  — replaced by Mem0.add() called from orchestrator
  - get_relevant_user_facts()  — replaced by Mem0.search() in services/memory.py

Only get_user_facts() is kept as a thin helper used by the Mem0 bridge.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models.memory import PersistentFact

logger = logging.getLogger("app.services.agent.memory")


async def get_user_facts(db: AsyncSession, user_id: uuid.UUID) -> list[PersistentFact]:
    """Retrieve all persistent facts for a given user (most recent first)."""
    result = await db.execute(
        select(PersistentFact)
        .where(PersistentFact.user_id == user_id)
        .order_by(PersistentFact.created_at.desc())
    )
    return list(result.scalars().all())

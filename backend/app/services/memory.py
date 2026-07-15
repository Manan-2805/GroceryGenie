import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

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
    """Mock/Stub wrapper client for Mem0 to fulfill PRD specification."""

    def __init__(self, user_id: str | None = None):
        self.user_id = user_id

    def add(self, text: str, user_id: str | None = None) -> dict[str, Any]:
        logger.info(
            f"Mem0 adding fact text: '{text}' for user '{user_id or self.user_id}'"
        )
        return {"status": "success", "message": "Fact added to Mem0 memory client"}

    def get_all(self, user_id: str | None = None) -> list[dict[str, Any]]:
        logger.debug(f"Mem0 fetching all facts for user '{user_id or self.user_id}'")
        return []

    def search(self, query: str, user_id: str | None = None) -> list[dict[str, Any]]:
        logger.debug(
            f"Mem0 searching facts with query '{query}' for user '{user_id or self.user_id}'"
        )
        return []

    def delete(self, memory_id: str) -> bool:
        logger.info(f"Mem0 deleting fact memory with ID: '{memory_id}'")
        return True

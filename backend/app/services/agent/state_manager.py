"""
StateManager — unified Redis pending-state layer for the GroceryGenie agent.

Replaces 8 separate Redis key patterns with a single key per session:
    chat:session:{sid}:pending

Concurrency safety:
    set_pending() uses a Redis lock (SETNX-based via redis-py's Lock) so that
    two concurrent messages on the same session cannot corrupt pending state.
    If the lock cannot be acquired within LOCK_TIMEOUT_MS milliseconds the
    caller receives a ConcurrentMessageError and should return a "please wait"
    response to the user without touching state.

Key namespace (all session-scoped):
    chat:session:{sid}:pending          — active pending state (TTL: PENDING_TTL_S)
    chat:session:{sid}:pending_lock     — distributed lock (TTL: LOCK_TTL_S)
    chat:session:{sid}:messages         — history list (TTL: HISTORY_TTL_S)
    chat:session:{sid}:last_options     — last options_request payload (TTL: OPTIONS_TTL_S)
    chat:session:{sid}:fact_index       — fact index map for manage_facts (TTL: FACT_INDEX_TTL_S)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from app.services.memory import get_redis_client

if TYPE_CHECKING:
    from app.services.agent.orchestrator import AgentOrchestrator

logger = logging.getLogger("app.services.agent.state_manager")

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------
PENDING_TTL_S: int = 300  # 5 minutes — pending state expires
LOCK_TTL_S: int = 10  # 10 seconds — lock auto-expires (prevents deadlocks)
LOCK_TIMEOUT_MS: int = 200  # wait at most 200 ms to acquire lock
HISTORY_TTL_S: int = 3600  # 1 hour — session message history
OPTIONS_TTL_S: int = 300  # 5 minutes — last options_request payload
FACT_INDEX_TTL_S: int = 600  # 10 minutes — fact numeric index map


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConcurrentMessageError(RuntimeError):
    """Raised when a second message arrives before the first finishes."""


# ---------------------------------------------------------------------------
# PendingState dataclass
# ---------------------------------------------------------------------------


@dataclass
class PendingState:
    """Represents a suspended multi-turn flow stored in Redis.

    Attributes:
        flow:       Identifies the suspended flow type.
                    Values: "slot_fill" | "address_add" | "address_update"
                            | "address_update_confirm" | "role_switch"
        data:       Arbitrary flow-specific payload (e.g. partial params,
                    address id, original tool name + params).
        created_at: Unix timestamp when the state was stored.
    """

    flow: str
    data: dict[str, Any]
    created_at: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str | bytes) -> PendingState:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        d = json.loads(raw)
        return cls(
            flow=d["flow"],
            data=d["data"],
            created_at=d.get("created_at", 0.0),
        )


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------


def _pending_key(session_id: str) -> str:
    return f"chat:session:{session_id}:pending"


def _lock_key(session_id: str) -> str:
    return f"chat:session:{session_id}:pending_lock"


def _history_key(session_id: str) -> str:
    return f"chat:session:{session_id}:messages"


def _options_key(session_id: str) -> str:
    return f"chat:session:{session_id}:last_options"


def _fact_index_key(session_id: str) -> str:
    return f"chat:session:{session_id}:fact_index"


# ---------------------------------------------------------------------------
# Pending state operations
# ---------------------------------------------------------------------------


async def get_pending(session_id: str) -> PendingState | None:
    """Return the active pending state for the session, or None."""
    client = get_redis_client()
    raw = await client.get(_pending_key(session_id))
    if not raw:
        return None
    try:
        return PendingState.from_json(raw)
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning(
            f"[StateManager] Corrupt pending state for {session_id}: {exc}. Clearing."
        )
        await client.delete(_pending_key(session_id))
        return None


async def set_pending(
    session_id: str,
    flow: str,
    data: dict[str, Any],
    ttl: int = PENDING_TTL_S,
) -> None:
    """Atomically write pending state for the session.

    Uses a Redis lock so concurrent messages cannot interleave writes.

    Raises:
        ConcurrentMessageError: if the lock cannot be acquired within
                                 LOCK_TIMEOUT_MS milliseconds.
    """
    client = get_redis_client()
    lock = client.lock(
        _lock_key(session_id),
        timeout=LOCK_TTL_S,
        blocking_timeout=LOCK_TIMEOUT_MS / 1000,
    )
    acquired = await lock.acquire()
    if not acquired:
        raise ConcurrentMessageError(
            f"Could not acquire pending-state lock for session {session_id} "
            f"within {LOCK_TIMEOUT_MS}ms. Another message is still being processed."
        )
    try:
        state = PendingState(flow=flow, data=data)
        await client.set(_pending_key(session_id), state.to_json(), ex=ttl)
        logger.debug(
            f"[StateManager] set_pending flow={flow!r} for session {session_id}"
        )
    finally:
        try:
            await lock.release()
        except Exception as exc:
            logger.warning(
                f"[StateManager] Failed to release lock for {session_id}: {exc}"
            )


async def clear_pending(session_id: str) -> None:
    """Delete the pending state for the session (atomic DEL)."""
    client = get_redis_client()
    await client.delete(_pending_key(session_id))
    logger.debug(f"[StateManager] clear_pending for session {session_id}")


# ---------------------------------------------------------------------------
# History operations
# ---------------------------------------------------------------------------


async def append_history(session_id: str, role: str, content: str) -> None:
    """Append a message to the session history list and reset TTL."""
    client = get_redis_client()
    key = _history_key(session_id)
    message = json.dumps({"role": role, "content": content})
    await client.rpush(key, message)
    await client.expire(key, HISTORY_TTL_S)
    logger.debug(
        f"[StateManager] append_history role={role!r} for session {session_id}"
    )


async def get_history(session_id: str, limit: int = 20) -> list[dict[str, str]]:
    """Return the last *limit* messages for the session (oldest first)."""
    client = get_redis_client()
    key = _history_key(session_id)
    # LRANGE with -limit to -1 gives the last N entries
    if limit <= 0:
        raw_messages = await client.lrange(key, 0, -1)
    else:
        raw_messages = await client.lrange(key, -limit, -1)
    messages: list[dict[str, str]] = []
    for raw in raw_messages:
        try:
            messages.append(json.loads(raw))
        except json.JSONDecodeError:
            messages.append({"role": "user", "content": str(raw)})
    return messages


# ---------------------------------------------------------------------------
# Last-options cache (for fuzzy matching in FastPath)
# ---------------------------------------------------------------------------


async def set_last_options(session_id: str, options: list[dict[str, Any]]) -> None:
    """Cache the most recent options_request options for fuzzy selection matching."""
    client = get_redis_client()
    await client.set(
        _options_key(session_id),
        json.dumps(options),
        ex=OPTIONS_TTL_S,
    )


async def get_last_options(session_id: str) -> list[dict[str, Any]]:
    """Return the cached options from the last options_request, or []."""
    client = get_redis_client()
    raw = await client.get(_options_key(session_id))
    if not raw:
        return []
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        return []


# ---------------------------------------------------------------------------
# Fact index cache (for manage_facts delete/update by number)
# ---------------------------------------------------------------------------


async def set_fact_index(session_id: str, index_map: dict[str, str]) -> None:
    """Store {str(1-based-index): fact_id_uuid} map for the session."""
    client = get_redis_client()
    await client.set(
        _fact_index_key(session_id),
        json.dumps(index_map),
        ex=FACT_INDEX_TTL_S,
    )


async def get_fact_index(session_id: str) -> dict[str, str]:
    """Return the fact index map, or {} if not set / expired."""
    client = get_redis_client()
    raw = await client.get(_fact_index_key(session_id))
    if not raw:
        return {}
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# StateRouter — resume a suspended flow
# ---------------------------------------------------------------------------


async def resume(
    pending: PendingState,
    user_message: str,
    orchestrator: AgentOrchestrator,
) -> dict[str, Any]:
    """Route a pending state to its resumption handler.

    Each flow maps to a specific handler method on the orchestrator.
    The handlers are responsible for clearing pending state themselves
    (or setting a new one if more turns are needed).

    Raises:
        ValueError: if the flow name is unrecognised (should never happen in
                    production — indicates a code bug).
    """
    flow = pending.flow
    data = pending.data
    logger.info(
        f"[StateManager] Resuming flow={flow!r} for session {orchestrator.session_id}"
    )

    if flow == "slot_fill":
        # Generic slot-fill: orchestrator.slot_validator handles merge + re-validate
        from app.services.agent.slot_validator import merge as sv_merge
        from app.services.agent.slot_validator import validate as sv_validate

        tool_name: str = data.get("tool", "")
        partial: dict[str, Any] = data.get("partial", {})
        retry_count: int = data.get("retry_count", 0)

        # Merge new user message into existing partial params
        merged = await sv_merge(tool_name, partial, user_message)

        # Re-validate
        is_complete, missing, ask_text = sv_validate(tool_name, merged)
        if not is_complete:
            # Check for max retries to prevent infinite loop
            max_slot_fill_retries = 3
            if retry_count >= max_slot_fill_retries:
                await clear_pending(str(orchestrator.session_id))
                logger.warning(
                    f"[StateManager] Slot-fill for '{tool_name}' exceeded {max_slot_fill_retries} retries. "
                    f"Clearing pending state for session {orchestrator.session_id}."
                )
                return {
                    "type": "response",
                    "text": (
                        "I'm having trouble understanding the details I need. "
                        "Please try again with a clearer description, or type 'cancel' to start over."
                    ),
                    "options": None,
                }

            # Still missing fields — update partial in Redis with incremented retry count
            await set_pending(
                str(orchestrator.session_id),
                "slot_fill",
                {
                    "tool": tool_name,
                    "partial": merged,
                    "original_message": data.get("original_message", user_message),
                    "retry_count": retry_count + 1,
                },
            )
            return {"type": "response", "text": ask_text, "options": None}

        # All slots filled — clear pending and execute
        await clear_pending(str(orchestrator.session_id))
        result = await orchestrator._execute_tool(tool_name, merged)
        response = orchestrator._format_response_sync(user_message, result)
        await append_history(str(orchestrator.session_id), "user", user_message)
        await append_history(
            str(orchestrator.session_id), "assistant", response.get("text", "")
        )
        return response

    if flow == "address_add":
        # Address slot-fill: handled by address collect flow
        return await orchestrator._handle_address_collect_response(user_message, data)

    if flow == "address_update":
        # Address update delta: user is providing changes
        return await orchestrator._handle_address_update_response(user_message, data)

    if flow == "address_update_confirm":
        # User is confirming or cancelling the address update diff
        msg_lower = user_message.strip().lower()
        is_confirm = (
            msg_lower
            in (
                "yes",
                "confirm",
                "sure",
                "ok",
                "do it",
                "proceed",
                "yeah",
                "yep",
                "confirm_address_update",
            )
            or user_message.strip() == "confirm_address_update"
        )
        is_deny = msg_lower in (
            "no",
            "cancel",
            "stop",
            "never mind",
            "nah",
            "dont",
            "don't",
        )
        await clear_pending(str(orchestrator.session_id))
        if is_confirm:
            result = await orchestrator._execute_tool(
                "manage_addresses",
                {
                    "action": "update",
                    "address_id": data.get("address_id"),
                    "address_data": data.get("updated", {}),
                },
            )
            return await orchestrator._format_response(user_message, result)
        if is_deny:
            return {
                "type": "response",
                "text": "Address update cancelled.",
                "options": None,
            }
        # Treat as a new delta — re-enter address_update flow with updated base
        await set_pending(
            str(orchestrator.session_id),
            "address_update",
            {"address_id": data.get("address_id"), "current": data.get("updated", {})},
        )
        return await orchestrator._handle_address_update_response(
            user_message,
            {"address_id": data.get("address_id"), "current": data.get("updated", {})},
        )

    if flow == "role_switch":
        # User is responding to the role-switch offer
        msg_lower = user_message.strip().lower()
        is_confirm = msg_lower in (
            "yes",
            "sure",
            "ok",
            "do it",
            "proceed",
            "confirm",
            "yeah",
            "yep",
        ) or user_message.startswith("switch_role:")
        is_deny = msg_lower in (
            "no",
            "stop",
            "cancel",
            "never mind",
            "don't",
            "dont",
            "nah",
        )

        needed_role: str = data.get("needed_role", "seller")
        if user_message.startswith("switch_role:"):
            needed_role = user_message.split("switch_role:")[1].strip()

        await clear_pending(str(orchestrator.session_id))

        if is_confirm:
            switch_result = await orchestrator._execute_tool(
                "switch_role", {"role": needed_role}
            )
            if isinstance(switch_result, dict) and switch_result.get("success"):
                import contextlib

                from app.db.models.enums import UserRole

                with contextlib.suppress(ValueError):
                    orchestrator.user_role = UserRole(needed_role)

                tool_name = data.get("tool_name", "")
                original_message = data.get("original_message", "")
                original_params = data.get("original_params", {})
                if tool_name:
                    result = await orchestrator._execute_tool(
                        tool_name, original_params
                    )
                    response = await orchestrator._format_response(
                        original_message, result
                    )
                    response["text"] = (
                        f"Switched to '{needed_role}' role. " + response.get("text", "")
                    )
                    return response
            return {
                "type": "response",
                "text": f"Switched to '{needed_role}' role. How can I help?",
                "options": None,
            }

        if is_deny:
            return {
                "type": "response",
                "text": "No problem. Let me know if there's anything else I can help with.",
                "options": None,
            }

        # Not yes/no — fall through: clear pending and process as a new turn
        return await orchestrator.run_turn(user_message)

    raise ValueError(f"[StateManager] Unknown pending flow: {flow!r}")

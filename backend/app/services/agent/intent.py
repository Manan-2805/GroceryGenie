"""
IntentClassifier — single LLM call that returns tool + params + fact.

Public API:
    classify(user_message, user_role, session_id, db, user_id)
        → IntentResult

The classifier:
  - Builds a role-scoped tool description list (customer sees no seller tools,
    seller never sees view_orders)
  - Injects the last 4 turns of session history
  - Injects up to 3 semantically-relevant persistent facts
  - Returns an IntentResult dataclass

Role-aware session greeting:
  - If the session history is empty (first message), the orchestrator should
    prepend GREETING_CUSTOMER or GREETING_SELLER to the response text.
  - classify() signals this via IntentResult.is_first_message = True.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import UserRole
from app.services.agent.llm import call_llm, extract_json_from_response
from app.services.agent.prompts import (
    GREETING_CUSTOMER,
    GREETING_SELLER,
    INTENT_PROMPT,
    TOOL_HINTS_CUSTOMER,
    TOOL_HINTS_SELLER,
)
from app.services.agent.state_manager import get_history
from app.services.agent.tools import ROLE_PERMISSIONS, TOOL_DESCRIPTIONS
from app.services.memory import Mem0

logger = logging.getLogger("app.services.agent.intent")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class IntentResult:
    tool: str  # tool name, "out_of_scope", "follow_up", or "toggle_theme"
    params: dict[
        str, Any
    ]  # extracted parameters (may be incomplete — SlotValidator checks)
    fact_to_remember: str | None = None  # durable fact extracted from user message
    fact_category: str | None = None  # category for the fact
    is_first_message: bool = False  # True on first turn of a new session
    greeting: str = ""  # pre-built greeting string if first message


# ---------------------------------------------------------------------------
# Role-scoped tool descriptions
# ---------------------------------------------------------------------------


def _build_tool_descriptions(user_role: UserRole) -> str:
    """Return tool description lines for tools this role can use.

    Customer: all customer tools + shared tools (no seller tools).
    Seller:   all seller tools + shared tools (no customer-only tools,
              view_orders explicitly excluded).
    """
    allowed = set(ROLE_PERMISSIONS.get(user_role, []))
    lines = []
    for name, desc in TOOL_DESCRIPTIONS.items():
        if name in allowed:
            lines.append(f"  - {name}: {desc}")
    return "\n".join(lines)


def _get_tool_hints(user_role: UserRole) -> str:
    if user_role == UserRole.seller:
        return TOOL_HINTS_SELLER
    return TOOL_HINTS_CUSTOMER


# ---------------------------------------------------------------------------
# Main classify function
# ---------------------------------------------------------------------------


async def classify(
    user_message: str,
    user_role: UserRole,
    session_id: str | uuid.UUID,
    db: AsyncSession,
    user_id: uuid.UUID,
) -> IntentResult:
    """Classify user intent with one LLM call.

    Returns an IntentResult with tool, params, and optional fact.
    Never raises — returns a safe "out_of_scope" result on any error.
    """
    sid = str(session_id)

    # ── Session history ───────────────────────────────────────────────────
    history_msgs = await get_history(sid, limit=8)
    # Only use last 4 turns (user+assistant pairs)
    recent = history_msgs[-8:]
    history_str = "\n".join(f"{m['role']}: {m['content']}" for m in recent) or "None"
    is_first_message = len(history_msgs) == 0

    # ── Persistent facts ──────────────────────────────────────────────────
    facts_str = "None"
    try:
        mem0 = Mem0(db=db, user_id=user_id)
        facts = await mem0.search(query=user_message, limit=3)
        if facts:
            facts_str = "; ".join(f["fact_text"] for f in facts)
    except Exception as exc:
        logger.warning(f"[Intent] Failed to load facts: {exc}")

    # ── Build prompt ──────────────────────────────────────────────────────
    tool_descriptions = _build_tool_descriptions(user_role)
    tool_hints = _get_tool_hints(user_role)

    prompt = INTENT_PROMPT.format(
        tool_descriptions=tool_descriptions,
        tool_hints=tool_hints,
        facts=facts_str,
        history=history_str,
        user_message=user_message,
    )

    # ── LLM call ──────────────────────────────────────────────────────────
    raw = await call_llm(
        system_prompt="You are a precise intent classifier. Output ONLY valid JSON.",
        user_prompt=prompt,
        temperature=0.0,
        max_tokens=512,
        call_type="intent_classifier",
    )

    if not raw:
        logger.warning(
            "[Intent] LLM returned empty response — falling back to out_of_scope"
        )
        return _fallback(is_first_message, user_role)

    intent_data = _parse_intent(raw)
    if intent_data is None:
        # Retry once with an explicit JSON reminder
        logger.warning("[Intent] JSON parse failed on first attempt, retrying")
        raw2 = await call_llm(
            system_prompt="You are a precise intent classifier. Output ONLY raw JSON, no markdown.",
            user_prompt=prompt,
            temperature=0.0,
            max_tokens=512,
            call_type="intent_classifier_retry",
        )
        intent_data = _parse_intent(raw2 or "")
        if intent_data is None:
            return _fallback(is_first_message, user_role)

    tool = str(intent_data.get("tool", "out_of_scope")).strip()
    params: dict[str, Any] = intent_data.get("params") or {}
    fact_to_remember: str | None = intent_data.get("fact_to_remember") or None
    fact_category: str | None = intent_data.get("fact_category") or None

    # Sanitise: strip None/empty from params
    params = {k: v for k, v in params.items() if v is not None}

    # Coerce seller "my orders" → list_fulfillment_orders if LLM slips through
    if user_role == UserRole.seller and tool == "view_orders":
        logger.info(
            "[Intent] Seller said 'view_orders' — remapping to list_fulfillment_orders"
        )
        tool = "list_fulfillment_orders"

    # Resolve greeting
    greeting = ""
    if is_first_message:
        greeting = (
            GREETING_SELLER if user_role == UserRole.seller else GREETING_CUSTOMER
        )

    return IntentResult(
        tool=tool,
        params=params,
        fact_to_remember=fact_to_remember
        if fact_to_remember and fact_to_remember.strip()
        else None,
        fact_category=fact_category,
        is_first_message=is_first_message,
        greeting=greeting,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_intent(raw: str) -> dict[str, Any] | None:
    """Try to parse raw LLM output as intent JSON. Returns None on failure."""
    if not raw or not raw.strip():
        return None
    try:
        cleaned = extract_json_from_response(raw)
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            return None
        return data
    except (json.JSONDecodeError, ValueError):
        return None


def _fallback(is_first_message: bool, user_role: UserRole) -> IntentResult:
    """Return a safe fallback result when the LLM fails entirely."""
    greeting = GREETING_SELLER if user_role == UserRole.seller else GREETING_CUSTOMER
    return IntentResult(
        tool="out_of_scope",
        params={},
        is_first_message=is_first_message,
        greeting=greeting if is_first_message else "",
    )

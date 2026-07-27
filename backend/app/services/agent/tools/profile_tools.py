"""Profile tools — switch_role and manage_facts. Pure Python, no LLM calls."""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import FactCategory, UserRole
from app.db.models.memory import PersistentFact
from app.db.models.user import User
from app.services.agent.state_manager import get_fact_index, set_fact_index

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# switch_role
# ---------------------------------------------------------------------------


async def switch_role(
    db: AsyncSession,
    user_id: UUID,
    role: str = "customer",
    **kwargs: Any,
) -> dict[str, Any]:
    """Switch user role between customer and seller."""
    try:
        new_role = UserRole(role)
    except ValueError:
        return {
            "success": False,
            "message": f"Invalid role: '{role}'. Use 'customer' or 'seller'.",
        }

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        return {"success": False, "message": "User not found."}

    user.role = new_role
    await db.commit()
    return {"success": True, "message": f"Switched to '{new_role.value}' role."}


# ---------------------------------------------------------------------------
# manage_facts — full CRUD replacing the old read-only get_facts
# ---------------------------------------------------------------------------


async def manage_facts(
    db: AsyncSession,
    user_id: UUID,
    action: str = "list",
    fact_text: str | None = None,
    fact_id: str | None = None,
    category: str | None = None,
    session_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """CRUD operations for persistent user facts/preferences.

    Actions:
        list    — return all facts with 1-based numeric index; caches index map
                  in Redis (session_id required for caching — optional but recommended).
        add     — insert a new fact (deduplicates by case-insensitive text).
        delete  — remove a fact by UUID or 1-based index number or text match.
        update  — replace fact_text (and optionally category) by UUID, index, or text match.
    """
    if action == "list":
        return await _list_facts(db, user_id, session_id)
    if action == "add":
        return await _add_fact(db, user_id, fact_text, category)
    if action == "delete":
        return await _delete_fact(db, user_id, fact_id, fact_text, session_id)
    if action == "update":
        return await _update_fact(db, user_id, fact_id, fact_text, category, session_id)

    return {
        "success": False,
        "message": f"Unknown action '{action}'. Use list / add / delete / update.",
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _list_facts(
    db: AsyncSession,
    user_id: UUID,
    session_id: str | None,
) -> dict[str, Any]:
    result = await db.execute(
        select(PersistentFact)
        .where(PersistentFact.user_id == user_id)
        .order_by(PersistentFact.created_at.asc())
    )
    facts = list(result.scalars().all())

    if not facts:
        return {
            "facts_list": True,
            "facts": [],
            "message": "You have no saved preferences or facts yet.",
        }

    fact_dicts = []
    index_map: dict[str, str] = {}

    for i, f in enumerate(facts, start=1):
        fact_dicts.append(
            {
                "index": i,
                "id": str(f.id),
                "fact_text": f.fact_text,
                "category": f.category.value
                if hasattr(f.category, "value")
                else str(f.category),
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
        )
        index_map[str(i)] = str(f.id)

    # Cache the index map so delete/update by number works within the session
    if session_id:
        await set_fact_index(session_id, index_map)

    return {
        "facts_list": True,
        "facts": fact_dicts,
        "count": len(fact_dicts),
    }


async def _add_fact(
    db: AsyncSession,
    user_id: UUID,
    fact_text: str | None,
    category: str | None,
) -> dict[str, Any]:
    if not fact_text or not fact_text.strip():
        return {
            "success": False,
            "message": "Fact text is required to add a preference.",
        }

    clean_text = fact_text.strip()

    # Deduplicate
    dup = await db.execute(
        select(PersistentFact).where(
            PersistentFact.user_id == user_id,
            PersistentFact.fact_text.ilike(clean_text),
        )
    )
    if dup.scalar_one_or_none():
        return {
            "success": False,
            "message": f'That preference is already saved: "{clean_text}".',
        }

    try:
        cat = FactCategory(category) if category else FactCategory.other
    except ValueError:
        cat = FactCategory.other

    fact = PersistentFact(user_id=user_id, fact_text=clean_text, category=cat)
    db.add(fact)
    await db.commit()

    return {
        "success": True,
        "message": f'Saved preference: "{clean_text}".',
    }


async def _resolve_fact(
    db: AsyncSession,
    user_id: UUID,
    fact_id: str | None,
    fact_text: str | None,
    session_id: str | None,
) -> PersistentFact | None:
    """Resolve a fact by UUID, 1-based numeric index, or text substring match."""
    if not fact_id and not fact_text:
        return None

    # Try by index number first (e.g. "1", "2")
    if fact_id and fact_id.strip().isdigit() and session_id:
        index_map = await get_fact_index(session_id)
        resolved_uuid = index_map.get(fact_id.strip())
        if resolved_uuid:
            fact_id = resolved_uuid

    # Try by UUID
    if fact_id:
        try:
            fid = UUID(str(fact_id).strip())
            result = await db.execute(
                select(PersistentFact).where(
                    PersistentFact.id == fid,
                    PersistentFact.user_id == user_id,
                )
            )
            return result.scalar_one_or_none()
        except (ValueError, AttributeError):
            pass

    # Try by text substring match
    if fact_text:
        result = await db.execute(
            select(PersistentFact).where(
                PersistentFact.user_id == user_id,
                PersistentFact.fact_text.ilike(f"%{fact_text.strip()}%"),
            )
        )
        return result.scalar_one_or_none()

    return None


async def _delete_fact(
    db: AsyncSession,
    user_id: UUID,
    fact_id: str | None,
    fact_text: str | None,
    session_id: str | None,
) -> dict[str, Any]:
    fact = await _resolve_fact(db, user_id, fact_id, fact_text, session_id)
    if not fact:
        return {
            "success": False,
            "message": "I couldn't find that preference. Use 'list facts' to see your saved preferences.",
        }

    deleted_text = fact.fact_text
    await db.execute(delete(PersistentFact).where(PersistentFact.id == fact.id))
    await db.commit()

    return {
        "success": True,
        "message": f'Deleted preference: "{deleted_text}".',
    }


async def _update_fact(
    db: AsyncSession,
    user_id: UUID,
    fact_id: str | None,
    fact_text: str | None,
    category: str | None,
    session_id: str | None,
) -> dict[str, Any]:
    """Update an existing fact's text and/or category."""
    # fact_id is the locator; fact_text is the NEW text
    # Disambiguate: if only fact_text given, treat first half as locator and
    # expect the caller to pass fact_id separately. Both can't be the new text.
    fact = await _resolve_fact(db, user_id, fact_id, None, session_id)
    if not fact:
        return {
            "success": False,
            "message": "I couldn't find that preference. Use 'list facts' to see your saved preferences.",
        }

    if fact_text and fact_text.strip():
        fact.fact_text = fact_text.strip()

    if category:
        try:
            fact.category = FactCategory(category)
        except ValueError as e:
            logger.warning("Value error in _update_fact:%s", str(e))

    await db.commit()

    return {
        "success": True,
        "message": f'Updated preference to: "{fact.fact_text}".',
    }


# ---------------------------------------------------------------------------
# Backward-compat shim — old orchestrator imports get_facts
# ---------------------------------------------------------------------------


async def get_facts(
    db: AsyncSession,
    user_id: UUID,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Legacy read-only accessor. Returns flat list for backward compat."""
    result = await db.execute(
        select(PersistentFact)
        .where(PersistentFact.user_id == user_id)
        .order_by(PersistentFact.created_at.desc())
    )
    facts = list(result.scalars().all())
    return [
        {
            "fact_text": f.fact_text,
            "category": f.category.value
            if hasattr(f.category, "value")
            else str(f.category),
        }
        for f in facts
    ]

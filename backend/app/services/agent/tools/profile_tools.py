"""Profile tools - pure Python, no LLM calls."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import UserRole
from app.db.models.user import User
from app.services.agent.memory import get_user_facts


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
            "message": f"Invalid role: {role}. Use 'customer' or 'seller'.",
        }

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        return {"success": False, "message": "User not found."}

    user.role = new_role
    await db.commit()
    return {"success": True, "message": f"Switched to '{new_role.value}' role."}


async def get_facts(
    db: AsyncSession,
    user_id: UUID,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Get user's stored facts/preferences."""
    facts = await get_user_facts(db, user_id)
    return [{"fact_text": f.fact_text, "category": f.category.value} for f in facts]

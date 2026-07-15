import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.dependencies import get_current_user, get_db
from app.db.models.enums import UserRole
from app.db.models.memory import PersistentFact
from app.db.models.user import User

router = APIRouter(prefix="/users", tags=["Users / Facts"])


class FactResponse(BaseModel):
    id: uuid.UUID
    fact_text: str
    category: str

    class Config:
        from_attributes = True


class RoleSwitchRequest(BaseModel):
    role: str


@router.patch("/me/role")
async def switch_user_role(
    body: RoleSwitchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Switch the current user's active role between customer and seller."""
    if body.role not in ("customer", "seller"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be 'customer' or 'seller'.",
        )
    user.role = UserRole(body.role)
    await db.commit()
    return {"role": body.role}


@router.get("/facts", response_model=list[FactResponse])
async def list_user_facts(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[PersistentFact]:
    """Retrieve all persistent facts that the agent remembers about the user."""
    result = await db.execute(
        select(PersistentFact)
        .where(PersistentFact.user_id == user.id)
        .order_by(PersistentFact.created_at.desc())
    )
    return list(result.scalars().all())


@router.delete("/facts/{fact_id}")
async def delete_user_fact(
    fact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Deletes a specific persistent fact from the agent's memory."""
    fact = await db.get(PersistentFact, fact_id)
    if not fact or fact.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fact not found in user memory.",
        )

    await db.delete(fact)
    await db.commit()

    return {"status": "success", "detail": "Fact forgotten successfully."}

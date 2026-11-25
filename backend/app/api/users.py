import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.db.models.enums import UserRole
from app.db.models.memory import PersistentFact
from app.db.models.user import User

router = APIRouter(prefix="/users", tags=["Users / Facts"])


class FactResponse(BaseModel):
    id: uuid.UUID
    fact_text: str
    category: str

    model_config = ConfigDict(from_attributes=True)


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
    role = UserRole(body.role)
    await db.execute(
        update(User)
        .where(User.id == user.id, User.role != role)
        .values(role=role, mode_version=User.mode_version + 1)
    )
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


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    fact_text: str = Field(min_length=1, max_length=200)


@router.put("/facts/{fact_id}", response_model=FactResponse)
async def update_fact(
    fact_id: uuid.UUID,
    payload: PreferenceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersistentFact:
    fact = (
        await db.scalars(
            select(PersistentFact).where(
                PersistentFact.id == fact_id, PersistentFact.user_id == user.id
            )
        )
    ).one_or_none()
    if fact is None:
        raise HTTPException(404, "Preference not found.")
    fact.fact_text = payload.fact_text
    await db.commit()
    return fact

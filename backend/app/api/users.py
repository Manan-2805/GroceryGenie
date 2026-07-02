import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.dependencies import get_current_user, get_db
from app.db.models.memory import PersistentFact
from app.db.models.user import User

router = APIRouter(prefix="/users", tags=["Users / Facts"])


class FactResponse(BaseModel):
    id: uuid.UUID
    fact_text: str
    category: str

    class Config:
        from_attributes = True


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
    db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """Deletes a specific persistent fact from the agent's memory."""
    result = await db.execute(
        delete(PersistentFact).where(
            PersistentFact.id == fact_id, PersistentFact.user_id == user.id
        )
    )
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fact not found in user memory.",
        )

    return {"status": "success", "detail": "Fact forgotten successfully."}

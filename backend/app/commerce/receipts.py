from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.mutation import MutationReceipt
from app.db.models.user import User


async def prior_result[Result: BaseModel](
    db: AsyncSession,
    user_id: UUID,
    key: UUID,
    intent: str,
    result_type: type[Result],
) -> Result | None:
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())
    prior = (
        await db.scalars(
            select(MutationReceipt).where(
                MutationReceipt.user_id == user_id, MutationReceipt.key == key
            )
        )
    ).one_or_none()
    if prior is None:
        return None
    if prior.intent != intent:
        raise HTTPException(
            409, "This request key was already used for a different change."
        )
    return result_type.model_validate(prior.result)


def record_result(
    db: AsyncSession,
    user_id: UUID,
    key: UUID,
    intent: str,
    result: BaseModel,
) -> None:
    db.add(
        MutationReceipt(
            user_id=user_id,
            key=key,
            intent=intent,
            result=result.model_dump(mode="json"),
        )
    )

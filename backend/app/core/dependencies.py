from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import SESSION_COOKIE, authenticated_user
from app.db.base import AsyncSessionFactory
from app.db.models.enums import UserRole
from app.db.models.user import User


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def require_same_origin(request: Request) -> None:
    if request.headers.get("origin") not in settings.parsed_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Request origin not allowed.")


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_same_origin(request)
    user = await authenticated_user(db, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    return user


async def get_current_seller(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.seller:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden. Seller role required.",
        )
    return user


async def get_current_customer(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.customer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden. Customer role required.",
        )
    return user

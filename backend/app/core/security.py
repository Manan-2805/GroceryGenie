import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.login_session import LoginSession
from app.db.models.user import User

SESSION_COOKIE = "session_token"
SESSION_LIFETIME = timedelta(days=7)


def session_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_login_session(db: AsyncSession, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            user_id=user.id,
            token_hash=session_hash(token),
            expires_at=utc_now() + SESSION_LIFETIME,
        )
    )
    return token


async def authenticated_user(db: AsyncSession, token: str | None) -> User | None:
    if not token or len(token) != 43:
        return None
    return (
        await db.scalars(
            select(User)
            .join(LoginSession, LoginSession.user_id == User.id)
            .where(
                LoginSession.token_hash == session_hash(token),
                LoginSession.expires_at > utc_now(),
            )
            .execution_options(populate_existing=True)
        )
    ).one_or_none()

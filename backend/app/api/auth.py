from typing import cast

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db, require_same_origin
from app.core.security import (
    SESSION_COOKIE,
    SESSION_LIFETIME,
    create_login_session,
    session_hash,
)
from app.db.base import utc_now
from app.db.models.enums import UserRole
from app.db.models.login_session import LoginSession
from app.db.models.user import User

router = APIRouter(prefix="/auth", tags=["Authentication"])
oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
)


class UserMeResponse(BaseModel):
    id: str
    email: str
    name: str
    role: UserRole


class GoogleIdentity(BaseModel):
    model_config = ConfigDict(strict=True)

    sub: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    email_verified: bool
    name: str = Field(default="", max_length=255)

    @field_validator("email_verified")
    @classmethod
    def check_verified(cls, verified: bool) -> bool:
        if not verified:
            raise ValueError("Google account must have a verified email")
        return verified


@router.get("/me", response_model=UserMeResponse)
async def get_me(user: User = Depends(get_current_user)) -> UserMeResponse:
    return UserMeResponse(
        id=str(user.id), email=user.email, name=user.name, role=user.role
    )


@router.post("/logout", dependencies=[Depends(require_same_origin)])
async def logout(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    token = request.cookies.get(SESSION_COOKIE)
    if token and len(token) == 43:
        await db.execute(
            delete(LoginSession).where(LoginSession.token_hash == session_hash(token))
        )
        await db.commit()
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        samesite="strict",
        secure=settings.secure_cookies,
    )
    return {"status": "success"}


@router.get("/google/login")
async def google_login(request: Request) -> RedirectResponse:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Google sign-in is not configured.")
    client = oauth.create_client("google")
    return cast(
        RedirectResponse,
        await client.authorize_redirect(request, settings.GOOGLE_REDIRECT_URI),
    )


@router.get("/google/callback")
async def google_callback(
    request: Request, db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    client = oauth.create_client("google")
    try:
        # Authlib verifies state, nonce, signature, audience and issuer when
        # exchanging the authorization code for the OpenID Connect identity.
        token = await client.authorize_access_token(request)
        identity = GoogleIdentity.model_validate(token.get("userinfo"))
    except ValidationError:
        return RedirectResponse("/login?error=unverified_identity")
    except Exception:
        return RedirectResponse("/login?error=oauth_failed")

    name = identity.name or identity.email.split("@", 1)[0]
    user_insert = insert(User).values(
        google_sub=identity.sub, email=identity.email, name=name, role=UserRole.customer
    )
    user = (
        await db.scalars(
            user_insert.on_conflict_do_update(
                index_elements=[User.google_sub],
                set_={"email": identity.email, "name": name, "updated_at": utc_now()},
            ).returning(User)
        )
    ).one()
    old_token = request.cookies.get(SESSION_COOKIE)
    if old_token and len(old_token) == 43:
        await db.execute(
            delete(LoginSession).where(
                LoginSession.token_hash == session_hash(old_token)
            )
        )
    session_token = create_login_session(db, user)
    await db.commit()

    response = RedirectResponse("/")
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        samesite="strict",
        secure=settings.secure_cookies,
    )
    return response

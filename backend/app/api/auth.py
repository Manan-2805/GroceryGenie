from typing import Any

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from starlette.requests import Request

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.core.security import create_access_token
from app.db.models.enums import UserRole
from app.db.models.user import User

router = APIRouter(prefix="/auth", tags=["Authentication"])


class UserMeResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    role: UserRole


@router.get("/me", response_model=UserMeResponse)
async def get_me(request_user: User = Depends(get_current_user)) -> UserMeResponse:
    return UserMeResponse(
        id=str(request_user.id),
        email=request_user.email,
        name=request_user.name,
        role=request_user.role.value,
    )


@router.post("/login")
async def login(
    payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    if settings.ENV_MODE != "development":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email/Password authentication is only available in development mode.",
        )

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user:
        result = await db.execute(
            select(User).where(User.google_sub == f"local_{payload.email}")
        )
        user = result.scalar_one_or_none()

    # Backwards-compatibility for seeded users
    if not user:
        if payload.email == "test_seller@GroceryGenie.com":
            result = await db.execute(
                select(User).where(User.google_sub == "mock_seller_sub")
            )
            user = result.scalar_one_or_none()
        elif payload.email == "test_customer@GroceryGenie.com":
            result = await db.execute(
                select(User).where(User.google_sub == "mock_customer_sub")
            )
            user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    access_token = create_access_token(data={"sub": user.google_sub})
    response.set_cookie(
        key="session_token",
        value=access_token,
        httponly=True,
        max_age=3600 * 24 * 7,
        expires=3600 * 24 * 7,
        samesite="strict",
        secure=settings.ENV_MODE == "production",
    )

    return {"status": "success", "role": user.role.value, "name": user.name}


@router.post("/dev-bypass")
async def dev_bypass(
    response: Response, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    if settings.ENV_MODE != "development":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev bypass is only available in development mode.",
        )

    result = await db.execute(select(User).where(User.email == "dev@GroceryGenie.com"))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dev user not seeded in database.",
        )

    access_token = create_access_token(data={"sub": user.google_sub})
    response.set_cookie(
        key="session_token",
        value=access_token,
        httponly=True,
        max_age=3600 * 24 * 7,
        expires=3600 * 24 * 7,
        samesite="strict",
        secure=settings.ENV_MODE == "production",
    )

    return {"status": "success", "role": user.role.value, "name": user.name}


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    response.set_cookie(
        key="session_token",
        value="",
        httponly=True,
        max_age=0,
        expires=0,
        samesite="strict",
        secure=settings.ENV_MODE == "production",
    )
    return {"status": "success"}


# Google OAuth Client Setup

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


@router.get("/google/login")
async def google_login(request: Request) -> Any:
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(
    request: Request, db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=oauth_failed")

    user_info = token.get("userinfo")
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to retrieve Google user info.",
        )

    email = user_info.get("email")
    name = user_info.get("name", "")
    google_sub = user_info.get("sub")

    # Check if user exists
    result = await db.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()

    if not user:
        # Default new google logins as customer unless email contains 'seller'
        role = UserRole.customer
        if email and "seller" in email.lower():
            role = UserRole.seller

        user = User(
            google_sub=google_sub,
            email=email,
            name=name,
            role=role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # Generate JWT
    access_token = create_access_token(data={"sub": user.google_sub})

    # Redirect to frontend and set httpOnly cookie
    redirect_res = RedirectResponse(url=settings.FRONTEND_URL)
    redirect_res.set_cookie(
        key="session_token",
        value=access_token,
        httponly=True,
        max_age=3600 * 24 * 7,  # 7 days
        expires=3600 * 24 * 7,
        samesite="strict",
        secure=settings.ENV_MODE == "production",
    )
    return redirect_res

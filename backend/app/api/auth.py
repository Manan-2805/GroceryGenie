
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

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


class MockLoginRequest(BaseModel):
    role: UserRole


@router.get("/me", response_model=UserMeResponse)
async def get_me(request_user: User = Depends(get_current_user)) -> UserMeResponse:
    return UserMeResponse(
        id=str(request_user.id),
        email=request_user.email,
        name=request_user.name,
        role=request_user.role.value,
    )


@router.post("/mock-login")
async def mock_login(
    payload: MockLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    if settings.ENV_MODE != "development":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Mock login is only available in development mode.",
        )

    # Determine details based on role
    if payload.role == UserRole.seller:
        email = "test_seller@grocergo.com"
        name = "Test Seller"
        google_sub = "mock_seller_sub"
    else:
        email = "test_customer@grocergo.com"
        name = "Test Customer"
        google_sub = "mock_customer_sub"

    # Check if user exists
    result = await db.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()

    if not user:
        # Create new deterministic test user
        user = User(
            google_sub=google_sub,
            email=email,
            name=name,
            role=payload.role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # Generate JWT
    access_token = create_access_token(data={"sub": user.google_sub})

    # Set httpOnly cookie
    response.set_cookie(
        key="session_token",
        value=access_token,
        httponly=True,
        max_age=3600 * 24 * 7,  # 7 days
        expires=3600 * 24 * 7,
        samesite="strict",
        secure=settings.ENV_MODE == "production",
    )

    return {"status": "success", "role": user.role.value, "name": user.name}


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(
        key="session_token",
        httponly=True,
        samesite="strict",
        secure=settings.ENV_MODE == "production",
    )
    return {"status": "success"}


# Placeholder for Google OAuth
@router.get("/google/login")
async def google_login() -> dict[str, str]:
    # In a real setup, this redirects to Google OAuth
    # For now, return a placeholder URL or message
    return {"auth_url": "/api/v1/auth/mock-login"}


@router.get("/google/callback")
async def google_callback() -> dict[str, str]:
    # In a real setup, this handles Google's redirect, fetches info, and issues cookie
    return {"status": "mocked"}


# Make sure get_current_user is imported at runtime (circular import prevention)

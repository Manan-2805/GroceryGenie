import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.sessions import SessionMiddleware

from app.api.addresses import router as addresses_router
from app.api.auth import router as auth_router
from app.api.cart import router as cart_router
from app.api.chat import router as chat_router
from app.api.orders import router as orders_router
from app.api.products import router as products_router
from app.api.ratings import router as ratings_router
from app.api.reports import router as reports_router
from app.api.routes import router as routes_router
from app.api.users import router as users_router
from app.api.ws import router as ws_router
from app.core.config import UPLOADS_DIR, settings
from app.core.limiter import limiter
from app.db.base import AsyncSessionFactory, engine
from app.middleware.error_handler import ErrorHandlerMiddleware

# Configure logging
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("app.main")
# Ensure uploads directory exists at startup
os.makedirs(str(UPLOADS_DIR), exist_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    # Models and cloud providers must never block the core app from booting.
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(
    title="GroceryGenie API",
    version="1.0.0",
    lifespan=lifespan,
)

# Register rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, cast(Any, _rate_limit_exceeded_handler))

# Global CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.parsed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception logging middleware
app.add_middleware(ErrorHandlerMiddleware)

# Session middleware for Google OAuth state
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.JWT_SECRET_KEY,
    https_only=settings.secure_cookies,
    max_age=600,
)

# API v1 Router Registration
app.include_router(auth_router, prefix="/api/v1")
app.include_router(addresses_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")
app.include_router(cart_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(orders_router, prefix="/api/v1")
app.include_router(ratings_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(routes_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(ws_router, prefix="/api/v1")

# Static Files Mount for Product Image Uploads
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": settings.ENV_MODE}


@app.get("/api/health")
@app.get("/api/v1/health")
async def api_health_check(request: Request) -> dict[str, Any]:
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except SQLAlchemyError:
        db_ok = False

    return {
        "status": "healthy" if db_ok else "degraded",
        "db_ok": db_ok,
        "voice_ok": getattr(request.app.state, "voice_ok", False),
        "llm_ok": getattr(request.app.state, "llm_ok", False),
    }


@app.get("/health/ready")
async def readiness(response: Response) -> dict[str, str]:
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(text("SELECT 1 FROM alembic_version LIMIT 1"))
    except SQLAlchemyError:
        response.status_code = 503
        return {"status": "unready"}
    return {"status": "ready"}

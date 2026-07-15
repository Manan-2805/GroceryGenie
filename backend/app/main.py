import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.api.addresses import router as addresses_router
from app.api.auth import router as auth_router
from app.api.cart import router as cart_router
from app.api.chat import router as chat_router
from app.api.orders import router as orders_router
from app.api.products import router as products_router
from app.api.ratings import router as ratings_router
from app.api.users import router as users_router
from app.api.ws import router as ws_router
from app.core.config import UPLOADS_DIR, settings
from app.core.limiter import limiter
from app.db.base import AsyncSessionFactory
from app.middleware.error_handler import ErrorHandlerMiddleware
from app.services.memory import get_redis_client
from app.services.rag.graph import get_neo4j_driver
from app.services.rag.retriever import get_qdrant_client

# Configure logging
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("app.main")
# Ensure uploads directory exists at startup
os.makedirs(str(UPLOADS_DIR), exist_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting GroceryGenie application backend...")
    try:
        from app.services.rag.embedder import get_embedder
        from app.services.rag.graph import seed_store_layout
        from app.services.rag.retriever import get_qdrant_client

        # Load embedding model singleton
        get_embedder()

        # Seed Neo4j store layout only in dev
        if settings.ENV_MODE == "development":
            seed_store_layout()

        # Connect to Qdrant client to ensure collection is created
        get_qdrant_client()

        # Load ASR model singleton
        from app.services.voice.asr import get_asr_model

        get_asr_model()

        # Load TTS model singleton
        from app.services.voice.tts import get_piper_voice

        get_piper_voice()

        # Run startup voice self-test (TTS -> ASR round-trip)
        from app.services.voice.asr import transcribe_pcm_chunk
        from app.services.voice.tts import synthesize_text_to_pcm

        logger.info("Running startup voice self-test (TTS -> ASR round-trip)...")
        try:
            test_pcm = synthesize_text_to_pcm("test", emotion="neutral")
            transcript = transcribe_pcm_chunk(test_pcm, sample_rate=16000)
            if transcript is not None:
                logger.info(
                    f"Startup voice self-test passed successfully. Transcript: '{transcript}'"
                )
                _app.state.voice_ok = True
            else:
                logger.warning("Startup voice self-test failed: transcript is None.")
                _app.state.voice_ok = False
        except Exception as ve:
            logger.error(f"Startup voice self-test failed with exception: {ve}")
            _app.state.voice_ok = False
    except Exception as e:
        logger.error(f"Error during lifespan startup initialization: {e}")
        _app.state.voice_ok = False

    yield

    logger.info("Stopping GroceryGenie application backend...")
    try:
        from app.services.rag.graph import close_neo4j_driver

        close_neo4j_driver()
    except Exception as e:
        logger.error(f"Error during lifespan shutdown cleanup: {e}")


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
)

# API v1 Router Registration
app.include_router(auth_router, prefix="/api/v1")
app.include_router(addresses_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")
app.include_router(cart_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(orders_router, prefix="/api/v1")
app.include_router(ratings_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(ws_router, prefix="/api/v1")

# Static Files Mount for Product Image Uploads
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": settings.ENV_MODE}


@app.get("/api/health")
async def api_health_check(request: Request) -> dict[str, Any]:
    # Check DB
    db_ok = False
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        logger.debug(f"DB health check failed: {e}")

    # Check Redis
    redis_ok = False
    try:
        redis_client = get_redis_client()
        await redis_client.ping()
        redis_ok = True
    except Exception as e:
        logger.debug(f"Redis health check failed: {e}")

    # Check Qdrant
    qdrant_ok = False
    try:
        get_qdrant_client().get_collections()
        qdrant_ok = True
    except Exception as e:
        logger.debug(f"Qdrant health check failed: {e}")

    # Check Neo4j
    neo4j_ok = False
    try:
        get_neo4j_driver().verify_connectivity()
        neo4j_ok = True
    except Exception as e:
        logger.debug(f"Neo4j health check failed: {e}")

    # Check LLM
    llm_ok = False
    try:
        from app.services.agent.llm import call_llm

        # Fast 2-token completion check
        await call_llm(
            system_prompt="System check.",
            user_prompt="OK",
            max_tokens=2,
        )
        llm_ok = True
    except Exception as e:
        logger.debug(f"LLM health check failed: {e}")

    voice_ok = getattr(request.app.state, "voice_ok", False)

    status_str = (
        "healthy"
        if (db_ok and redis_ok and qdrant_ok and neo4j_ok and llm_ok and voice_ok)
        else "degraded"
    )

    return {
        "status": status_str,
        "db_ok": db_ok,
        "redis_ok": redis_ok,
        "qdrant_ok": qdrant_ok,
        "neo4j_ok": neo4j_ok,
        "llm_ok": llm_ok,
        "voice_ok": voice_ok,
    }


@app.get("/api/v1/health")
async def api_v1_health_check(request: Request) -> dict[str, Any]:
    return await api_health_check(request)

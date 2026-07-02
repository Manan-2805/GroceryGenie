import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.auth import router as auth_router
from app.api.cart import router as cart_router
from app.api.chat import router as chat_router
from app.api.orders import router as orders_router
from app.api.products import router as products_router
from app.api.users import router as users_router
from app.api.ws import router as ws_router
from app.core.config import settings
from app.core.limiter import limiter
from app.middleware.error_handler import ErrorHandlerMiddleware

# Configure logging
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting GroceryGenie application backend...")
    try:
        from app.services.rag.embedder import get_embedder
        from app.services.rag.graph import seed_store_layout
        from app.services.rag.retriever import get_qdrant_client
        
        # Load embedding model singleton
        get_embedder()
        
        # Seed Neo4j store layout
        seed_store_layout()
        
        # Connect to Qdrant client to ensure collection is created
        get_qdrant_client()

        # Load ASR model singleton
        from app.services.voice.asr import get_asr_model
        get_asr_model()
        
        # Load TTS model singleton
        from app.services.voice.tts import get_piper_voice
        get_piper_voice()
    except Exception as e:
        logger.error(f"Error during lifespan startup initialization: {e}")
        
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
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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

# API v1 Router Registration
app.include_router(auth_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")
app.include_router(cart_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(orders_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(ws_router, prefix="/api/v1")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": settings.ENV_MODE}

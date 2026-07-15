import asyncio
import logging
import os
import subprocess  # nosec
import sys
from pathlib import Path

from sqlalchemy import text

from app.core.config import settings
from app.db.base import AsyncSessionFactory
from app.db.seed import seed_data
from app.services.memory import get_redis_client
from app.services.rag.graph import get_neo4j_driver
from app.services.rag.retriever import get_qdrant_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.prestart")


async def check_db() -> None:
    logger.info("Checking database connection...")
    for attempt in range(15):
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(text("SELECT 1"))
            logger.info("Database connection successful.")
            return
        except Exception as e:
            logger.warning(f"Database connection attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(2)
    raise RuntimeError("Failed to connect to database after 15 attempts.")


async def check_redis() -> None:
    logger.info("Checking Redis connection...")
    for attempt in range(15):
        try:
            client = get_redis_client()
            await client.ping()
            logger.info("Redis connection successful.")
            return
        except Exception as e:
            logger.warning(f"Redis connection attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(2)
    raise RuntimeError("Failed to connect to Redis after 15 attempts.")


async def check_qdrant() -> None:
    logger.info("Checking Qdrant connection...")
    for attempt in range(15):
        try:
            get_qdrant_client()
            logger.info("Qdrant connection and collection check successful.")
            return
        except Exception as e:
            logger.warning(f"Qdrant connection attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(2)
    raise RuntimeError("Failed to connect to Qdrant after 15 attempts.")


async def check_neo4j() -> None:
    logger.info("Checking Neo4j connection...")
    for attempt in range(15):
        try:
            driver = get_neo4j_driver()
            driver.verify_connectivity()
            logger.info("Neo4j connection successful.")
            return
        except Exception as e:
            logger.warning(f"Neo4j connection attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(2)
    raise RuntimeError("Failed to connect to Neo4j after 15 attempts.")


def run_migrations() -> None:
    logger.info("Running database migrations...")
    try:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)  # nosec
        logger.info("Migrations completed successfully.")
    except Exception as e:
        logger.error(f"Error running database migrations: {e}")
        raise


async def check_nim_api() -> None:
    logger.info("Testing connection to NIM API keys (sending check message)...")
    try:
        from app.services.agent.llm import call_llm

        # Fast completion check: max_tokens=5
        response = await call_llm(
            system_prompt="You are a system check agent.",
            user_prompt="Respond with 'OK' if you can read this.",
            max_tokens=5,
        )
        logger.info(f"NIM API connection test passed. Response: {response}")
    except Exception as e:
        logger.error(f"NIM API connection test failed: {e}")
        raise RuntimeError(
            "NIM API key is invalid or connection failed. Stopping application."
        ) from None


def check_models() -> None:
    logger.info("Checking ASR, TTS, and embedding models...")
    models_dir = Path(settings.PIPER_VOICE_MODEL).parent

    tts_model_path = Path(settings.PIPER_VOICE_MODEL)
    tts_config_path = Path(settings.PIPER_VOICE_CONFIG)
    embedding_path = models_dir / "BAAI" / "bge-small-en-v1.5"

    # 1. TTS check
    try:
        from piper import PiperVoice

        PiperVoice.load(str(tts_model_path), config_path=str(tts_config_path))
        logger.info("TTS voice model loaded successfully.")
    except Exception as e:
        logger.error(
            f"TTS voice model validation failed: {e}. Please run download_and_test.py first."
        )
        sys.exit(1)

    # 2. Embedding check
    try:
        from sentence_transformers import SentenceTransformer

        SentenceTransformer(str(embedding_path))
        logger.info("Embedding model loaded successfully.")
    except Exception as e:
        logger.error(
            f"Embedding model validation failed: {e}. Please run download_and_test.py first."
        )
        sys.exit(1)

    # 3. STT check
    try:
        import onnx_asr

        onnx_asr.load_model(
            "nemo-parakeet-tdt-0.6b-v3", providers=settings.parsed_asr_providers
        )
        logger.info("ASR/STT model loaded successfully.")
    except Exception as e:
        logger.error(
            f"ASR/STT model validation failed: {e}. Please run download_and_test.py first."
        )
        sys.exit(1)


async def main() -> None:
    logger.info("Starting database and service connectivity checks...")
    await check_db()
    await check_redis()
    await check_qdrant()
    await check_neo4j()

    run_migrations()

    if settings.ENV_MODE == "development":
        logger.info("Seeding database...")
        await seed_data()

    check_models()
    await check_nim_api()

    logger.info("All pre-startup checks completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        args = sys.argv[1:]
        logger.info(f"Prestart checks complete. Executing server command: {args}")
        os.execvp(cmd, args)  # nosec
    else:
        logger.info("Prestart checks complete. No server command provided.")

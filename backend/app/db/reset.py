import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Import all models to ensure they are registered with Base.metadata
import app.db.models  # noqa: F401
from app.core.config import settings
from app.db.base import Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.db.reset")


async def reset_db() -> None:
    logger.info("Connecting to Postgres database to reset...")
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        logger.info("Dropping all tables registered with metadata...")
        await conn.run_sync(Base.metadata.drop_all)

        logger.info("Dropping alembic_version and custom enum types...")
        try:
            await conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE;"))
            await conn.execute(text("DROP TYPE IF EXISTS orderstatus CASCADE;"))
            await conn.execute(text("DROP TYPE IF EXISTS userrole CASCADE;"))
            await conn.execute(text("DROP TYPE IF EXISTS factcategory CASCADE;"))
        except Exception as e:
            logger.warning(f"Error executing custom drops: {e}")

    # Wipe Qdrant vector collection
    try:
        from app.services.rag.retriever import COLLECTION_NAME, get_qdrant_client

        qclient = get_qdrant_client()
        qclient.delete_collection(collection_name=COLLECTION_NAME)
        logger.info("Deleted Qdrant products collection.")
    except Exception as e:
        logger.warning(f"Could not delete Qdrant collection during reset: {e}")

    logger.info("Database reset completed successfully.")


if __name__ == "__main__":
    asyncio.run(reset_db())

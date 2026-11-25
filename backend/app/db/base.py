import datetime
import uuid

from sqlalchemy import DateTime, MetaData, String, Text
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


# Explicit metadata naming convention for Alembic migration names
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=convention)


class Base(AsyncAttrs, DeclarativeBase):
    metadata = metadata

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, index=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    updated_by: Mapped[str] = mapped_column(
        String(255), default="system", nullable=False
    )
    action_taken: Mapped[str] = mapped_column(Text, default="action", nullable=False)


# Async database engine and session maker
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=5,
    pool_timeout=3,
    connect_args={
        "server_settings": {"statement_timeout": "8000", "lock_timeout": "4000"}
    },
    future=True,
)

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

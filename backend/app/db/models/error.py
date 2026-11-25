from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppError(Base):
    __tablename__ = "app_errors"
    __table_args__ = (Index("ix_app_errors_created_at", "created_at"),)

    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    request_id: Mapped[UUID]
    endpoint: Mapped[str] = mapped_column(String(255))
    error_code: Mapped[str] = mapped_column(String(50))
    detail: Mapped[str] = mapped_column(Text)
    stack_trace: Mapped[str] = mapped_column(Text)

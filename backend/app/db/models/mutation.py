from typing import Any
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MutationReceipt(Base):
    __tablename__ = "mutation_receipts"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_mutation_receipts_user_key"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[UUID]
    intent: Mapped[str] = mapped_column(String(200))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)

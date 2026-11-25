from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CheckoutQuote(Base):
    __tablename__ = "checkout_quotes"

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id"), unique=True)

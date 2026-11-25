from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import OrderStatus

if TYPE_CHECKING:
    from app.db.models.order import Order, OrderItem


class Fulfillment(Base):
    __tablename__ = "fulfillments"
    __table_args__ = (
        UniqueConstraint("order_id", "seller_id", name="uq_fulfillments_order_seller"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    seller_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(default=OrderStatus.placed)
    total: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    packed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    out_for_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order: Mapped["Order"] = relationship(back_populates="fulfillments")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="fulfillment")

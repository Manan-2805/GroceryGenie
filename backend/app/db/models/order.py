from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import OrderStatus
from app.db.models.product import Product

if TYPE_CHECKING:
    from app.db.models.fulfillment import Fulfillment
    from app.db.models.rating import ProductRating


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("customer_id", "checkout_key", name="uq_orders_checkout_key"),
    )

    checkout_key: Mapped[str | None] = mapped_column(String(100))
    payment_status: Mapped[str] = mapped_column(
        String(20), default="simulated", server_default=text("'simulated'")
    )

    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[OrderStatus] = mapped_column(default=OrderStatus.placed, index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    delivery_address: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    packed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    out_for_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fulfillments: Mapped[list["Fulfillment"]] = relationship(back_populates="order")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __allow_unmapped__ = True

    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    fulfillment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("fulfillments.id"), index=True
    )
    product_name: Mapped[str | None] = mapped_column(String(255))
    package_at_purchase: Mapped[str | None] = mapped_column(String(100))
    cost_at_purchase: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0"), server_default=text("0")
    )
    product_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL")
    )
    quantity: Mapped[int]
    price_at_purchase: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    fulfillment: Mapped["Fulfillment | None"] = relationship(back_populates="items")
    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product | None] = relationship()
    rating: "ProductRating | None" = None

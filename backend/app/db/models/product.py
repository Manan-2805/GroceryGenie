from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SEARCH_DOCUMENT = "to_tsvector('simple'::regconfig, (((((name::text || ' '::text) || brand::text) || ' '::text) || category::text) || ' '::text) || description)"


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_search", text(SEARCH_DOCUMENT), postgresql_using="gin"),
        Index("ix_products_category_is_active", "category", "is_active"),
        CheckConstraint("price >= 0 AND cost_price >= 0", name="nonnegative_price"),
        CheckConstraint("stock >= 0", name="nonnegative_stock"),
    )

    seller_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    brand: Mapped[str] = mapped_column(
        String(100), default="", server_default=text("''")
    )
    package: Mapped[str] = mapped_column(
        String(100), default="1 pack", server_default=text("'1 pack'")
    )
    cost_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0"), server_default=text("0")
    )
    ingredients: Mapped[str | None] = mapped_column(Text)
    dietary_tags: Mapped[list[str] | None] = mapped_column(JSON)
    allergens: Mapped[list[str] | None] = mapped_column(JSON)
    nutrition: Mapped[dict[str, str] | None] = mapped_column(JSON)
    label_source: Mapped[str | None] = mapped_column(String(100))
    stock: Mapped[int] = mapped_column(default=0)
    image_url: Mapped[str | None] = mapped_column(String(1024))
    avg_rating: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0"))
    sold_count: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)

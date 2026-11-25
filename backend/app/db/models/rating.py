from uuid import UUID

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.user import User


class ProductRating(Base):
    __tablename__ = "product_ratings"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "product_id",
            "user_id",
            name="uq_product_ratings_order_product_user",
        ),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    stars: Mapped[int]
    reply: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    user: Mapped[User] = relationship()

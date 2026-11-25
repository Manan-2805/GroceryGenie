from sqlalchemy import String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import UserRole


class User(Base):
    __tablename__ = "users"

    google_sub: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(default=UserRole.customer)
    mode_version: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    cart_version: Mapped[int] = mapped_column(default=0, server_default=text("0"))

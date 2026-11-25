from uuid import UUID

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import FactCategory


class PersistentFact(Base):
    __tablename__ = "persistent_facts"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    fact_text: Mapped[str] = mapped_column(Text)
    category: Mapped[FactCategory] = mapped_column(default=FactCategory.other)

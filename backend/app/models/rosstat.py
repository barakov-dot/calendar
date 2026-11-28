from datetime import date, datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.user import Timestamp


class RosstatForm(Base):
    """Форма статистической отчётности, которую организация должна сдать."""

    __tablename__ = "rosstat_forms"
    __table_args__ = (UniqueConstraint("company_id", "key", name="uq_rosstat_forms_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    key: Mapped[str] = mapped_column(String(300))
    index: Mapped[str] = mapped_column(String(64), default="", server_default="")
    name: Mapped[str] = mapped_column(Text, default="", server_default="")
    okud: Mapped[str] = mapped_column(String(32), default="", server_default="")
    periodicity: Mapped[str] = mapped_column(String(100), default="", server_default="")
    period: Mapped[str] = mapped_column(String(200), default="", server_default="")
    # срок как прислал Росстат; дата — если её удалось прочитать
    deadline: Mapped[str] = mapped_column(String(200), default="", server_default="")
    due_date: Mapped[date | None]
    comment: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())

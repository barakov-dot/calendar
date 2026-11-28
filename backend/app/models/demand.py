from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.user import Timestamp


class DemandStep(StrEnum):
    RECEIPT = "receipt"  # подписать квитанцию о приёме
    RESPONSE = "response"  # ответить, уплатить или явиться


class Demand(Base):
    """Требование или уведомление инспекции по организации."""

    __tablename__ = "demands"
    __table_args__ = (CheckConstraint("amount_kopecks >= 0", name="amount"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    # код формы; пусто — не определён
    knd: Mapped[str] = mapped_column(String(7), default="", server_default="")
    number: Mapped[str] = mapped_column(String(64), default="", server_default="")
    doc_date: Mapped[date]
    sent_date: Mapped[date]
    receipt_date: Mapped[date]
    # дата введена вручную, а не посчитана
    receipt_set: Mapped[bool] = mapped_column(default=False, server_default="false")
    response_workdays: Mapped[int | None]
    # пусто — по документу ничего делать не нужно (решение о взыскании)
    response_date: Mapped[date | None]
    response_set: Mapped[bool] = mapped_column(default=False, server_default="false")
    amount_kopecks: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    filename: Mapped[str] = mapped_column(String(255), default="", server_default="")
    content_type: Mapped[str] = mapped_column(String(64), default="", server_default="")
    data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())

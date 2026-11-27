from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.user import Timestamp, one_of


class EntityType(StrEnum):
    OOO = "ooo"
    IP = "ip"


class Regime(StrEnum):
    OSNO = "osno"
    USN6 = "usn6"
    USN15 = "usn15"
    AUSN_INCOME = "ausn_income"
    AUSN_INCOME_EXPENSE = "ausn_income_expense"


class ProfitAdvances(StrEnum):
    QUARTERLY = "quarterly"
    MONTHLY_BY_QUARTER = "monthly_by_quarter"
    MONTHLY_ACTUAL = "monthly_actual"


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(one_of("entity_type", EntityType), name="entity_type"),
        CheckConstraint(one_of("main_regime", Regime), name="main_regime"),
        CheckConstraint(
            one_of("profit_advances_mode", ProfitAdvances), name="profit_advances_mode"
        ),
        CheckConstraint("advance_day BETWEEN 1 AND 31", name="advance_day"),
        CheckConstraint("salary_day BETWEEN 1 AND 31", name="salary_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    inn: Mapped[str] = mapped_column(String(12), unique=True)
    kpp: Mapped[str] = mapped_column(String(9), default="", server_default="")
    ogrn: Mapped[str] = mapped_column(String(15), default="", server_default="")
    # дата регистрации ИП: с неё считаются взносы за себя
    registration_date: Mapped[date | None]
    name: Mapped[str] = mapped_column(String(1000))
    short_name: Mapped[str] = mapped_column(String(500), default="", server_default="")
    address: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    okved: Mapped[str] = mapped_column(String(16), default="", server_default="")
    director_name: Mapped[str] = mapped_column(String(500), default="", server_default="")
    dadata_raw: Mapped[dict | None] = mapped_column(JSONB)
    dadata_updated_at: Mapped[datetime | None] = mapped_column(Timestamp)

    entity_type: Mapped[str] = mapped_column(String(8))
    main_regime: Mapped[str] = mapped_column(String(32))
    nds_payer: Mapped[bool] = mapped_column(default=False, server_default="false")
    has_employees: Mapped[bool] = mapped_column(default=False, server_default="false")
    # сотрудники есть (взносы платятся), но выплат им нет: без зарплаты и НДФЛ
    no_salary: Mapped[bool] = mapped_column(default=False, server_default="false")
    profit_advances_mode: Mapped[str | None] = mapped_column(String(32))
    # имущество: по среднегодовой стоимости (декларация) и по кадастровой
    has_property_avg: Mapped[bool] = mapped_column(default=False, server_default="false")
    has_property_cadastral: Mapped[bool] = mapped_column(default=False, server_default="false")
    # авансы по имуществу, транспорту и земле установлены не везде
    has_property_advances: Mapped[bool] = mapped_column(default=False, server_default="false")
    has_transport_tax: Mapped[bool] = mapped_column(default=False, server_default="false")
    has_land_tax: Mapped[bool] = mapped_column(default=False, server_default="false")
    has_trade_fee: Mapped[bool] = mapped_column(default=False, server_default="false")
    has_tourist_tax: Mapped[bool] = mapped_column(default=False, server_default="false")
    has_dsv: Mapped[bool] = mapped_column(default=False, server_default="false")
    # числа месяца, в которые компания платит аванс и зарплату
    advance_day: Mapped[int | None]
    salary_day: Mapped[int | None]
    # нужны ли задачи по НДФЛ на АУСН (налог может перечислять банк)
    ausn_ndfl_tasks: Mapped[bool] = mapped_column(default=True, server_default="true")

    # с какой даты ведётся календарь: более ранние сроки не считаются пропущенными
    calendar_start: Mapped[date | None]
    region_code: Mapped[str] = mapped_column(String(2), default="", server_default="")
    accountant_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    is_archived: Mapped[bool] = mapped_column(default=False, server_default="false")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class Patent(Base):
    __tablename__ = "patents"
    __table_args__ = (
        CheckConstraint("date_end >= date_start", name="dates"),
        CheckConstraint("cost_kopecks >= 0", name="cost"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    number: Mapped[str] = mapped_column(String(64), default="", server_default="")
    region: Mapped[str] = mapped_column(String(255), default="", server_default="")
    date_start: Mapped[date]
    date_end: Mapped[date]
    cost_kopecks: Mapped[int | None] = mapped_column(BigInteger)


class CompanyMember(Base):
    """Привязка клиента к компании."""

    __tablename__ = "company_members"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)
    is_primary: Mapped[bool] = mapped_column(default=False, server_default="false")
    can_mark_paid: Mapped[bool] = mapped_column(default=False, server_default="false")
    receive_reminders: Mapped[bool] = mapped_column(default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())

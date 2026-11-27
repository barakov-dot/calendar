"""Схемы компаний. Клиенту отдаются только схемы с префиксом Client."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import EntityType, ProfitAdvances, Regime
from app.services.inn import is_valid_inn

# Наибольшее значение, которое без потерь переживает передачу через JavaScript.
MAX_KOPECKS = 2**53 - 1


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PatentIn(Input):
    number: str = Field("", max_length=64)
    region: str = Field("", max_length=255)
    date_start: date
    date_end: date
    cost_kopecks: int | None = Field(None, ge=0, le=MAX_KOPECKS)

    @model_validator(mode="after")
    def within_one_year(self) -> "PatentIn":
        if self.date_end < self.date_start:
            raise ValueError("дата окончания патента раньше даты начала")
        # п. 5 ст. 346.45 НК РФ: патент действует в пределах календарного года
        if self.date_end.year != self.date_start.year:
            raise ValueError("патент действует в пределах одного календарного года")
        return self


class PatentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    region: str
    date_start: date
    date_end: date
    cost_kopecks: int | None


class CompanyData(Input):
    """Полное состояние редактируемых полей. Несовместимые признаки сбрасываются."""

    inn: str
    kpp: str = Field("", pattern=r"^(\d{4}[0-9A-Z]{2}\d{3})?$")
    ogrn: str = Field("", pattern=r"^(\d{13}|\d{15})?$")
    # только у ИП
    registration_date: date | None = Field(None, ge=date(1991, 1, 1), le=date(2100, 12, 31))
    name: str = Field(min_length=1, max_length=1000)
    short_name: str = Field("", max_length=500)
    address: str = Field("", max_length=1000)
    okved: str = Field("", max_length=16)
    director_name: str = Field("", max_length=500)
    region_code: str = Field("", pattern=r"^(\d{2})?$")
    calendar_start: date | None = Field(None, ge=date(2020, 1, 1), le=date(2100, 12, 31))
    entity_type: EntityType
    main_regime: Regime
    nds_payer: bool | None = None
    has_employees: bool = False
    no_salary: bool = False
    profit_advances_mode: ProfitAdvances | None = None
    has_property_avg: bool = False
    has_property_cadastral: bool = False
    has_property_advances: bool = False
    has_transport_tax: bool = False
    has_land_tax: bool = False
    has_trade_fee: bool = False
    has_tourist_tax: bool = False
    has_dsv: bool = False
    ausn_ndfl_tasks: bool = True
    advance_day: int | None = Field(None, ge=1, le=31)
    salary_day: int | None = Field(None, ge=1, le=31)
    notes: str = Field("", max_length=10000)

    @field_validator("inn")
    @classmethod
    def check_inn(cls, value: str) -> str:
        if not is_valid_inn(value):
            raise ValueError("неверный ИНН: проверьте цифры")
        return value

    @model_validator(mode="after")
    def consistent(self) -> "CompanyData":
        is_ooo = self.entity_type == EntityType.OOO
        if len(self.inn) != (10 if is_ooo else 12):
            raise ValueError("у ООО ИНН из 10 цифр, у ИП — из 12")
        ausn = self.main_regime in (Regime.AUSN_INCOME, Regime.AUSN_INCOME_EXPENSE)
        if ausn:
            self.nds_payer = False
        elif self.nds_payer is None:
            self.nds_payer = self.main_regime == Regime.OSNO
        if is_ooo and self.main_regime == Regime.OSNO:
            self.profit_advances_mode = (
                self.profit_advances_mode or ProfitAdvances.MONTHLY_BY_QUARTER
            )
        else:
            self.profit_advances_mode = None
        if is_ooo:
            self.registration_date = None
        if not is_ooo:
            self.kpp = ""
            self.director_name = ""
            # транспорт и земля бывают и у ИП (по налоговому уведомлению)
            self.has_property_avg = self.has_property_cadastral = False
            self.has_property_advances = False
        if not ausn:
            self.ausn_ndfl_tasks = True
        if not self.has_employees:
            self.no_salary = False
        if not self.has_employees or self.no_salary:
            self.advance_day = self.salary_day = None
        elif (self.advance_day is None) != (self.salary_day is None):
            raise ValueError("укажите оба дня выплаты: и аванса, и зарплаты")
        elif self.salary_day is not None and (self.advance_day <= 15) == (self.salary_day <= 15):
            # ст. 136 ТК РФ: не реже чем каждые полмесяца
            raise ValueError("одна выплата должна приходиться на 1–15 число, другая — на 16–31")
        self.region_code = self.region_code or self.inn[:2]
        return self


class CompanyCreate(Input):
    company: dict
    accountant_id: int | None = None
    patents: list[PatentIn] = Field(default_factory=list, max_length=50)


class CompanyPatch(Input):
    """Только изменяемые поля. Итоговое состояние проверяется как CompanyData."""

    company: dict = Field(default_factory=dict)
    is_archived: bool | None = None


class ReassignIn(Input):
    accountant_id: int


class MemberPatch(Input):
    can_mark_paid: bool | None = None
    receive_reminders: bool | None = None


class ClientInviteIn(Input):
    can_mark_paid: bool = False


class MemberOut(BaseModel):
    user_id: int
    first_name: str
    last_name: str
    username: str
    is_primary: bool
    can_mark_paid: bool
    receive_reminders: bool
    bot_blocked: bool


class CompanyListItem(BaseModel):
    id: int
    inn: str
    name: str
    short_name: str
    entity_type: str
    main_regime: str
    nds_payer: bool
    has_employees: bool
    is_archived: bool
    accountant_id: int | None
    accountant_name: str
    patents_count: int
    members_count: int
    has_blocked_member: bool
    # есть платежи без суммы со сроком в ближайшие 30 дней
    has_missing_amount: bool


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    inn: str
    kpp: str
    ogrn: str
    registration_date: date | None
    calendar_start: date | None
    name: str
    short_name: str
    address: str
    okved: str
    director_name: str
    region_code: str
    entity_type: str
    main_regime: str
    nds_payer: bool
    has_employees: bool
    no_salary: bool
    profit_advances_mode: str | None
    has_property_avg: bool
    has_property_cadastral: bool
    has_property_advances: bool
    has_transport_tax: bool
    has_land_tax: bool
    has_trade_fee: bool
    has_tourist_tax: bool
    has_dsv: bool
    ausn_ndfl_tasks: bool
    advance_day: int | None
    salary_day: int | None
    notes: str
    is_archived: bool
    accountant_id: int | None
    dadata_updated_at: datetime | None
    created_at: datetime
    accountant_name: str = ""
    patents: list[PatentOut] = Field(default_factory=list)
    members: list[MemberOut] = Field(default_factory=list)


class ClientCompanyOut(BaseModel):
    """То, что видит клиент: без заметок, режимов, участников и сырых данных."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    inn: str
    name: str
    short_name: str


class PartyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    inn: str
    kpp: str
    ogrn: str
    registration_date: date | None
    name: str
    short_name: str
    address: str
    okved: str
    director_name: str
    entity_type: str
    region_code: str
    status: str


class SuggestOut(BaseModel):
    enabled: bool
    suggestions: list[PartyOut] = Field(default_factory=list)

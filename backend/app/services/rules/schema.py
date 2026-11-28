"""Формат файлов rules/<год>.yaml."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import EntityType, ProfitAdvances, Regime, TaskKind


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Day = Annotated[int, Field(ge=1, le=31)]
Month = Annotated[int, Field(ge=1, le=12)]
Quarter = Annotated[int, Field(ge=1, le=4)]


class Monthly(Strict):
    """День day месяца, смещённого на month_offset от отчётного."""

    type: Literal["monthly"]
    day: Day
    month_offset: int = Field(ge=0, le=12)
    months: list[Month] = Field(default_factory=lambda: list(range(1, 13)), min_length=1)


class Quarterly(Strict):
    """День day месяца, смещённого на month_offset от конца квартала."""

    type: Literal["quarterly"]
    quarters: list[Quarter] = Field(min_length=1)
    day: Day
    month_offset: int = Field(ge=1, le=12)
    # cumulative: «I квартал, полугодие, 9 месяцев»; quarter: «I, II, III квартал»
    naming: Literal["quarter", "cumulative"] = "quarter"


class Yearly(Strict):
    type: Literal["yearly"]
    day: Day
    month: Month
    year_offset: int = Field(1, ge=0, le=2)


class NdsThirds(Strict):
    """Квартальная сумма тремя платежами в каждом из трёх следующих месяцев."""

    type: Literal["nds_thirds"]
    day: Day


class Payday(Strict):
    """Выплата в день, заданный в карточке компании. С выходного переносится назад.

    advance — аванс за месяц, платится в этом же месяце. salary — зарплата за месяц:
    день 1–15 означает следующий месяц, 16–31 — тот же.
    """

    type: Literal["payday"]
    payment: Literal["advance", "salary"]


class Handler(Strict):
    """Расчёт на Python для сроков, которые не описываются шаблоном."""

    type: Literal["handler"]
    name: Literal["patent_payments", "ndfl_december"]


Schedule = Annotated[
    Monthly | Quarterly | Yearly | NdsThirds | Payday | Handler, Field(discriminator="type")
]


class Applies(Strict):
    """Все перечисленные условия должны выполняться; список — любое из значений."""

    entity_type: list[EntityType] | None = None
    main_regime: list[Regime] | None = None
    profit_advances_mode: list[ProfitAdvances] | None = None
    nds_payer: bool | None = None
    has_employees: bool | None = None
    no_salary: bool | None = None
    has_property_avg: bool | None = None
    has_property_cadastral: bool | None = None
    has_property_advances: bool | None = None
    has_transport_tax: bool | None = None
    has_land_tax: bool | None = None
    has_trade_fee: bool | None = None
    has_tourist_tax: bool | None = None
    has_dsv: bool | None = None
    ausn_ndfl_tasks: bool | None = None

    def matches(self, company: object) -> bool:
        for name, expected in self:
            if expected is None:
                continue
            actual = getattr(company, name)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif bool(actual) != expected:
                return False
        return True


class Rule(Strict):
    code: str = Field(pattern=r"^[a-z0-9_]{3,64}$")
    title: str = Field(min_length=1, max_length=300)
    # для экрана задач: что сделать и за какой период (отдельной строкой)
    action: str = Field("", max_length=200)
    period: str = Field("за {period_name}", max_length=100)
    kind: TaskKind
    applies: Applies = Field(default_factory=Applies)
    schedule: Schedule
    needs_amount: bool = False
    # годовая сумма по закону, ₽: за неполный первый год — пропорционально дате регистрации
    annual_amount: int | None = Field(None, ge=1)
    # у компании без деятельности этот платёж равен нулю
    zero_when_inactive: bool = False
    # за годы до года регистрации задача не создаётся
    from_registration: bool = False
    client_visible: bool = True
    source: str = Field(min_length=1, max_length=500)
    # пояснение для бухгалтера, например что нужно проверить
    description: str = ""


class RuleFile(Strict):
    year: int = Field(ge=2025, le=2100)
    checked: str = Field(min_length=1)
    rules: list[Rule] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_codes(self) -> "RuleFile":
        codes = [rule.code for rule in self.rules]
        if repeated := sorted({code for code in codes if codes.count(code) > 1}):
            raise ValueError(f"повторяются коды правил: {', '.join(repeated)}")
        return self

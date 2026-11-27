"""Разбор XML декларации (формат ФНС): НДС (КНД 1151001) и прибыль (КНД 1151006).

Результат — суммы платежей: какому правилу и периоду какая сумма. Суммы налога берутся
из декларации, сервис их не считает.
"""

import re
from dataclasses import dataclass
from xml.etree import ElementTree
from xml.parsers import expat

from app.services.rules.engine import split_in_three

# книги покупок и продаж передаются отдельными файлами и бывают большими
MAX_BYTES = 5 * 1024 * 1024
NDS_KND = "1151001"
PROFIT_KND = "1151006"
# код налогового периода → квартал; 5х — последний период при реорганизации и ликвидации
QUARTERS = {"21": 1, "22": 2, "23": 3, "24": 4, "51": 1, "54": 2, "55": 3, "56": 4}
# прибыль: отчётные периоды нарастающим итогом
PROFIT_QUARTERS = {"21": 1, "31": 2, "33": 3}
PROFIT_YEAR = ("34", "46")  # 46 — год у плательщиков по фактической прибыли
PROFIT_MONTHS = {str(34 + month): month for month in range(1, 12)}  # 35…45
MONTHS = ("январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь").split()
ROMAN = ("I", "II", "III", "IV")
CUMULATIVE = ("I квартал", "полугодие", "9 месяцев")


class DeclarationError(Exception):
    """Текст показывается пользователю."""


@dataclass(frozen=True)
class Item:
    """Сумма одного платежа: ключ задачи без организации."""

    rule_code: str
    period_key: str
    part: int
    amount_kopecks: int
    label: str


@dataclass(frozen=True)
class Declaration:
    inn: str
    taxpayer: str
    title: str
    correction: int
    items: tuple[Item, ...]
    # итоги декларации для показа: (что, сумма)
    totals: tuple[tuple[str, int], ...]
    warnings: tuple[str, ...]


def _reject_doctype(*_: object) -> None:
    raise DeclarationError("Файл содержит DTD: это не декларация из учётной программы")


def _root(data: bytes) -> ElementTree.Element:
    if not data:
        raise DeclarationError("Файл пустой")
    if len(data) > MAX_BYTES:
        raise DeclarationError(
            "Файл больше 5 МБ. Нужен основной файл декларации, а не книги покупок и продаж"
        )
    # в декларациях нет DTD, а с его помощью можно раздуть файл до всей памяти сервера
    guard = expat.ParserCreate()
    guard.StartDoctypeDeclHandler = _reject_doctype
    try:
        guard.Parse(data, True)
        return ElementTree.fromstring(data)
    except (expat.ExpatError, ElementTree.ParseError, ValueError, LookupError):
        raise DeclarationError("Файл не читается как XML") from None


def _rubles(element: ElementTree.Element, name: str, signed: bool = False) -> int:
    text = element.get(name, "0")
    if not re.fullmatch(r"-?\d{1,15}" if signed else r"\d{1,15}", text):
        raise DeclarationError("Сумма в декларации записана не целым числом рублей")
    return int(text)


def _taxpayer(document: ElementTree.Element) -> tuple[str, str]:
    """(ИНН, название) организации или предпринимателя."""
    company = document.find("СвНП/НПЮЛ")
    if company is not None:
        inn, name = company.get("ИННЮЛ", ""), company.get("НаимОрг", "")
    else:
        person = document.find("СвНП/НПФЛ")
        if person is None:
            raise DeclarationError("В декларации не указан налогоплательщик")
        inn = person.get("ИННФЛ", "")
        parts = person.find("ФИО")
        name = (
            ""
            if parts is None
            else " ".join(parts.get(key, "") for key in ("Фамилия", "Имя", "Отчество"))
        )
    if not re.fullmatch(r"\d{10}|\d{12}", inn):
        raise DeclarationError("В декларации нет правильного ИНН налогоплательщика")
    return inn, name.strip()


def _bad_period() -> DeclarationError:
    return DeclarationError("Не удалось определить налоговый период декларации")


def _nds(
    nds: ElementTree.Element, code: str, year: int
) -> tuple[str, list[Item], list[tuple[str, int]], list[str]]:
    quarter = QUARTERS.get(code)
    if quarter is None:
        raise _bad_period()
    # раздел 1: строка 040 — к уплате, делится на три срока (п. 1 ст. 174 НК РФ)
    sections = nds.findall("СумУплНП")
    if not sections:
        raise DeclarationError("В декларации нет раздела 1 с суммой налога")
    total = sum(_rubles(section, "СумПУ_173.1") for section in sections) * 100

    warnings = []
    # уплата по п. 5 ст. 173 идёт одним сроком (п. 4 ст. 174 НК РФ)
    single = sum(_rubles(section, "СумПУ_173.5") for section in sections)
    if single:
        warnings.append(
            f"В строке 030 раздела 1 есть ещё {single} ₽ (п. 5 ст. 173 НК РФ). Эта сумма "
            "платится целиком и в три платежа не включена."
        )
    if nds.find("СумУплНА") is not None:
        warnings.append(
            "Есть раздел 2 (налоговый агент). Его суммы в платежи не включены, добавьте их сами."
        )
    if total == 0:
        warnings.append("Налога к уплате по строке 040 нет: платежи станут нулевыми.")

    items = [
        Item("nds_payment", f"{year}-Q{quarter}", part, amount, f"платёж {part} из 3")
        for part, amount in enumerate(split_in_three(total), start=1)
    ]
    title = f"НДС за {ROMAN[quarter - 1]} квартал {year}"
    return title, items, [("К уплате за квартал", total)], warnings


def _budgets(block: ElementTree.Element, name: str, signed: bool = False) -> int:
    """Сумма по федеральному и региональным бюджетам (подразделений может быть несколько)."""
    lines = [*block.findall("ФедБдж"), *block.findall("СубБдж")]
    return sum(_rubles(line, name, signed) for line in lines)


def _monthly_quarter(block: ElementTree.Element, code: str, year: int) -> tuple[int, int]:
    """(год, квартал), за который платятся ежемесячные авансы блока раздела 1.2."""
    stated = block.get("КвИсчислАв")
    if stated is None:
        return year, PROFIT_QUARTERS[code] + 1
    if stated not in ("21", "22", "23", "24"):
        raise DeclarationError("Не удалось определить квартал ежемесячных авансов")
    quarter = QUARTERS[stated]
    # в декларации за 9 месяцев авансы I квартала относятся к следующему году
    return (year + 1 if code == "33" and quarter == 1 else year), quarter


def _profit(
    profit: ElementTree.Element, code: str, year: int
) -> tuple[str, list[Item], list[tuple[str, int]], list[str]]:
    section = profit.find("НалПУ")
    if section is None:
        raise DeclarationError("В декларации нет раздела 1 с суммами налога")
    if code in PROFIT_QUARTERS:
        quarter = PROFIT_QUARTERS[code]
        name = f"{CUMULATIVE[quarter - 1]} {year}"
        rule, key = "profit_advance", f"{year}-Q{quarter}"
    elif code in PROFIT_YEAR:
        name = f"{year} год"
        rule, key = "profit_year", str(year)
    elif code in PROFIT_MONTHS:
        month = PROFIT_MONTHS[code]
        name = f"отчётный период по {MONTHS[month - 1]} {year}"
        rule, key = "profit_actual_advance", f"{year}-{month:02d}"
    else:
        raise _bad_period()

    items: list[Item] = []
    totals: list[tuple[str, int]] = []
    warnings: list[str] = []

    # раздел 1.1: доплата (плюс) или уменьшение (минус) за отчётный или налоговый период
    own = section.findall("НалПУАв")
    due = sum(_budgets(block, "НалПУ", signed=True) for block in own) * 100
    if own:
        totals.append(("К доплате" if due >= 0 else "К уменьшению", abs(due)))
        lines = [line for block in own for line in block]
        if due >= 0 and any(_rubles(line, "НалПУ", signed=True) < 0 for line in lines):
            warnings.append(
                "По одному бюджету налог к доплате, по другому к уменьшению: в платёж "
                "взята разница."
            )
        items.append(Item(rule, key, 1, max(due, 0), f"налог за {name}"))

    # раздел 1.2: ежемесячные авансы следующего квартала
    monthly: dict[tuple[int, int], list[int]] = {}
    for block in section.findall("НалПУМес"):
        if code not in PROFIT_QUARTERS:
            raise _bad_period()
        amounts = monthly.setdefault(_monthly_quarter(block, code, year), [0, 0, 0])
        for index in range(3):
            amounts[index] += _budgets(block, f"АвПлат{index + 1}") * 100
    for (due_year, quarter), amounts in sorted(monthly.items()):
        total = sum(amounts)
        totals.append((f"Ежемесячные авансы за {ROMAN[quarter - 1]} квартал {due_year}", total))
        # платим равными частями, каждая округляется до рубля вверх
        for index, amount in enumerate(split_in_three(total)):
            month = (quarter - 1) * 3 + index + 1
            label = f"ежемесячный аванс, {MONTHS[month - 1]} {due_year}"
            items.append(Item("profit_monthly", f"{due_year}-{month:02d}", 1, amount, label))

    known = {"НалПУАв", "НалПУМес"}
    if any(child.tag not in known for child in section):
        warnings.append(
            "В разделе 1 есть и другие суммы (например, налог с дивидендов или процентов). "
            "Они в платежи не включены, добавьте их сами."
        )
    if not items:
        raise DeclarationError("В разделе 1 нет сумм авансовых платежей или налога")
    return f"Налог на прибыль за {name}", items, totals, warnings


def parse(data: bytes) -> Declaration:
    root = _root(data)
    document = root.find("Документ")
    if root.tag != "Файл" or document is None:
        raise DeclarationError("Это не файл декларации в формате ФНС")
    kinds = {NDS_KND: ("НДС", _nds), PROFIT_KND: ("Прибыль", _profit)}
    kind = kinds.get(document.get("КНД", ""))
    if kind is None:
        raise DeclarationError("Поддерживаются только декларации по НДС и по прибыли")
    tag, read = kind
    body = document.find(tag)
    if body is None:
        raise DeclarationError("Это приложение к декларации. Нужен её основной файл")

    year = document.get("ОтчетГод", "")
    correction = document.get("НомКорр", "0")
    if not re.fullmatch(r"20\d\d", year) or not correction.isdigit():
        raise _bad_period()
    inn, taxpayer = _taxpayer(document)
    title, items, totals, warnings = read(body, document.get("Период", ""), int(year))
    return Declaration(
        inn=inn,
        taxpayer=taxpayer,
        title=title,
        correction=int(correction),
        items=tuple(items),
        totals=tuple(totals),
        warnings=tuple(warnings),
    )

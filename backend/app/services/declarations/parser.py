"""Разбор XML декларации (формат ФНС). Пока только НДС, КНД 1151001."""

import re
from dataclasses import dataclass
from xml.etree import ElementTree
from xml.parsers import expat

# книги покупок и продаж передаются отдельными файлами и бывают большими
MAX_BYTES = 5 * 1024 * 1024
NDS_KND = "1151001"
PROFIT_KND = "1151006"
# код налогового периода → квартал; 5х — последний период при реорганизации и ликвидации
QUARTERS = {"21": 1, "22": 2, "23": 3, "24": 4, "51": 1, "54": 2, "55": 3, "56": 4}


class DeclarationError(Exception):
    """Текст показывается пользователю."""


@dataclass(frozen=True)
class NdsDeclaration:
    inn: str
    taxpayer: str
    year: int
    quarter: int
    correction: int
    total_kopecks: int
    warnings: tuple[str, ...]

    @property
    def period_key(self) -> str:
        return f"{self.year}-Q{self.quarter}"


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


def _rubles(element: ElementTree.Element, name: str) -> int:
    text = element.get(name, "0")
    if not re.fullmatch(r"\d{1,15}", text):
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


def parse(data: bytes) -> NdsDeclaration:
    root = _root(data)
    document = root.find("Документ")
    if root.tag != "Файл" or document is None:
        raise DeclarationError("Это не файл декларации в формате ФНС")
    knd = document.get("КНД", "")
    if knd == PROFIT_KND:
        raise DeclarationError("Декларации по прибыли пока не поддерживаются")
    if knd != NDS_KND:
        raise DeclarationError("Поддерживается только декларация по НДС (КНД 1151001)")
    nds = document.find("НДС")
    if nds is None:
        raise DeclarationError("Это приложение к декларации. Нужен её основной файл")

    quarter = QUARTERS.get(document.get("Период", ""))
    year = document.get("ОтчетГод", "")
    correction = document.get("НомКорр", "0")
    if quarter is None or not re.fullmatch(r"20\d\d", year) or not correction.isdigit():
        raise DeclarationError("Не удалось определить налоговый период декларации")
    inn, taxpayer = _taxpayer(document)

    # раздел 1: строка 040 — к уплате, делится на три срока (п. 1 ст. 174 НК РФ)
    sections = nds.findall("СумУплНП")
    if not sections:
        raise DeclarationError("В декларации нет раздела 1 с суммой налога")
    total = sum(_rubles(section, "СумПУ_173.1") for section in sections)

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

    return NdsDeclaration(
        inn=inn,
        taxpayer=taxpayer,
        year=int(year),
        quarter=quarter,
        correction=int(correction),
        total_kopecks=total * 100,
        warnings=tuple(warnings),
    )

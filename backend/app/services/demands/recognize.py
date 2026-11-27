"""Чтение реквизитов из PDF требования. Текст нигде не сохраняется и не логируется."""

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date

from pypdf import PdfReader

# реквизиты и сроки — на первых страницах, дальше перечни документов и сноски
PAGES = 6
MONTHS = (
    "января февраля марта апреля мая июня июля августа сентября октября ноября декабря"
).split()
WORDS = {"пяти": 5, "восьми": 8, "десяти": 10, "двадцати": 20}

# pypdf пишет предупреждения о мелких дефектах файлов ФНС
logging.getLogger("pypdf").setLevel(logging.ERROR)


@dataclass
class Found:
    knd: str = ""
    number: str = ""
    doc_date: date | None = None
    # все ИНН по порядку: первым обычно идёт получатель
    inns: list[str] = field(default_factory=list)
    response_workdays: int | None = None
    response_date: date | None = None
    amount_kopecks: int | None = None
    note: str = ""


def pdf_text(data: bytes) -> str:
    """Текст первых страниц; пустая строка, если это скан или файл не читается."""
    try:
        pages = PdfReader(io.BytesIO(data)).pages
        text = " ".join(pages[i].extract_text() or "" for i in range(min(PAGES, len(pages))))
    except Exception:  # повреждённый файл не должен ронять запрос
        return ""
    return " ".join(text.split())


def _date(day: str, month: str, year: str) -> date | None:
    try:
        return date(
            int(year), MONTHS.index(month.lower()) + 1 if month.isalpha() else int(month), int(day)
        )
    except ValueError:
        return None


def _term(text: str) -> int | None:
    """«В течение пяти рабочих дней со дня получения»."""
    match = re.search(r"[Вв] течение (\d+|[а-я]+) (?:рабочих )?дней со дня получения", text)
    if match is None:
        return None
    value = match[1]
    if not value.isdigit():
        return WORDS.get(value)
    number = int(value)
    # номер сноски прилипает к числу: «5» со сноской 4 читается как «54»
    if number > 30:
        number //= 10
    return number if 1 <= number <= 30 else None


def read(text: str) -> Found:
    found = Found()
    if match := re.search(r"КНД\s*(\d{7})", text):
        found.knd = match[1]
    if match := re.search(r"(?:Требование|Уведомление)\s*№\s*([0-9A-Za-zА-Яа-я/\-_.]{1,64})", text):
        found.number = match[1].rstrip(".")
    # у требования об уплате дата — «по состоянию на», у остальных — первая в тексте
    state = re.search(r"по состоянию на\s*«(\d{1,2})»\s*([а-я]+)\s*(\d{4})", text)
    if state:
        found.doc_date = _date(*state.groups())
    elif match := re.search(r"(?<!\d)(\d{2})\.(\d{2})\.(20\d\d)(?!\d)", text):
        found.doc_date = _date(*match.groups())
    found.inns = re.findall(r"(?<!\d)(\d{12}|\d{10})(?!\d)", text)

    if found.knd == "1160001":
        if match := re.search(r"в срок до\s*«(\d{1,2})»\s*([а-я]+)\s*(\d{4})", text):
            found.response_date = _date(*match.groups())
        if match := re.search(r"Сумма\s*(\d{1,13})[.,](\d\d)(?!\d)", text):
            found.amount_kopecks = int(match[1]) * 100 + int(match[2])
    elif found.knd == "1165009":
        # дата явки стоит перед подписью поля; часто там только приёмные часы
        before, mark, _ = text.partition("(дата и время")
        if mark:
            line = before.rsplit("(адрес и номер кабинета)", 1)[-1].strip(" ;")
            if match := re.search(r"(?<!\d)(\d{2})\.(\d{2})\.(20\d\d)", line):
                found.response_date = _date(*match.groups())
            if "(адрес и номер кабинета)" in before and line:
                found.note = f"Приём: {line[:200]}"
    else:
        found.response_workdays = _term(text)
    return found

"""Календарь тестовых компаний в Excel для ручной сверки: python -m app.export_calendar 2026.

База не используется: компании берутся из seed-dev, календарь — из data/calendar.
"""

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import yaml
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.core.config import get_config
from app.seed_dev import DEV_COMPANIES, PATENT_OWNER, dev_company_data, dev_patent
from app.services.calendar.workdays import WorkCalendar, read_calendar_file
from app.services.rules.engine import RuleBook, load_rules, occurrences

KINDS = {"payment": "Платёж", "report": "Отчёт", "notice": "Уведомление", "other": "Другое"}
WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
REGIMES = {
    "osno": "ОСНО",
    "usn6": "УСН 6%",
    "usn15": "УСН 15%",
    "ausn_income": "АУСН «Доходы»",
    "ausn_income_expense": "АУСН «Доходы минус расходы»",
}
PROFIT = {
    "quarterly": "прибыль поквартально",
    "monthly_by_quarter": "прибыль: ежемесячные авансы по прошлому кварталу",
    "monthly_actual": "прибыль помесячно по факту",
}
FLAGS = {
    "nds_payer": "плательщик НДС",
    "has_employees": "есть сотрудники",
    "has_property_tax": "налог на имущество",
    "has_transport_tax": "транспортный налог",
    "has_land_tax": "земельный налог",
    "has_trade_fee": "торговый сбор",
    "has_tourist_tax": "туристический налог",
}
HEADER_FILL = PatternFill("solid", fgColor="DDEBF7")
SHIFT_FILL = PatternFill("solid", fgColor="FFF2CC")
NOTE_FILL = PatternFill("solid", fgColor="FCE4D6")


def test_companies(year: int) -> list[tuple[object, list]]:
    result = []
    for number, (base, _, _, fields) in enumerate(DEV_COMPANIES, start=1):
        data = dev_company_data(base, fields)
        patents = []
        if base == PATENT_OWNER:
            patents.append(SimpleNamespace(id=number, **dev_patent(year)))
        result.append((data, patents))
    return result


def describe(company, patents) -> str:
    parts = [
        "ООО" if company.entity_type == "ooo" else "ИП",
        REGIMES[company.main_regime],
        *(title for name, title in FLAGS.items() if getattr(company, name)),
    ]
    if company.profit_advances_mode:
        parts.append(PROFIT[company.profit_advances_mode])
    for patent in patents:
        parts.append(
            f"патент {patent.date_start:%d.%m.%Y}–{patent.date_end:%d.%m.%Y}, "
            f"{patent.cost_kopecks / 100:,.2f} ₽".replace(",", " ")
        )
    return ", ".join(parts)


def _table(sheet, headers: list[tuple[str, int]], first_row: int = 1) -> None:
    for column, (title, width) in enumerate(headers, start=1):
        cell = sheet.cell(first_row, column, title)
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        sheet.column_dimensions[cell.column_letter].width = width
    # адресом, а не ячейкой: обращение к ячейке создаёт пустую строку
    sheet.freeze_panes = f"A{first_row + 1}"


def _wrap(sheet, first_row: int) -> None:
    for row in sheet.iter_rows(min_row=first_row):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")


def build_workbook(
    year: int, book: RuleBook, work_calendar: WorkCalendar, questions: list[dict]
) -> Workbook:
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Компании"
    _table(summary, [("Лист", 8), ("Компания", 28), ("Параметры", 90), ("Сроков", 10)])

    for number, (company, patents) in enumerate(test_companies(year), start=1):
        items = [
            item
            for item in occurrences(
                book, company, patents, work_calendar, date(year, 1, 1), date(year, 12, 31)
            )
            if item.due_date.year == year
        ]
        summary.append([number, company.name, describe(company, patents), len(items)])

        sheet = workbook.create_sheet(f"{number}")
        sheet.append([company.name])
        sheet["A1"].font = Font(bold=True, size=14)
        sheet.append([describe(company, patents)])
        _table(
            sheet,
            [
                ("Срок", 12),
                ("День", 6),
                ("По закону (если перенесён)", 16),
                ("Тип", 14),
                ("Что", 62),
                ("Сумма, ₽", 13),
                ("Основание", 34),
                ("Примечание", 40),
                ("Верно? (да/нет)", 12),
                ("Замечание", 34),
            ],
            first_row=3,
        )
        for item in items:
            shifted = item.due_date != item.original_due_date
            sheet.append(
                [
                    item.due_date,
                    WEEKDAYS[item.due_date.weekday()],
                    item.original_due_date if shifted else None,
                    KINDS[item.kind],
                    item.title,
                    None if item.amount_kopecks is None else item.amount_kopecks / 100,
                    item.source_ref,
                    item.description or None,
                ]
            )
            row = sheet.max_row
            for column in (1, 3):
                sheet.cell(row, column).number_format = "DD.MM.YYYY"
            sheet.cell(row, 6).number_format = "#,##0.00"
            if shifted:
                sheet.cell(row, 3).fill = SHIFT_FILL
            if item.description:
                sheet.cell(row, 8).fill = NOTE_FILL
        _wrap(sheet, 4)
        sheet.auto_filter.ref = f"A3:J{sheet.max_row}"
    _wrap(summary, 2)

    rules = workbook.create_sheet("Правила")
    _table(
        rules,
        [("Код", 28), ("Название", 62), ("Тип", 14), ("Расписание", 50), ("Основание", 40)],
    )
    for rule in book.for_period_year(year).rules:
        schedule = rule.schedule.model_dump(exclude_none=True)
        kind = schedule.pop("type")
        details = ", ".join(f"{key}={value}" for key, value in schedule.items())
        rules.append([rule.code, rule.title, KINDS[rule.kind], f"{kind}: {details}", rule.source])
    _wrap(rules, 2)

    asked = workbook.create_sheet("Вопросы")
    _table(asked, [("№", 5), ("Тема", 32), ("Вопрос", 80), ("Как сейчас", 46), ("Ответ", 40)])
    for number, question in enumerate(questions, start=1):
        asked.append([number, question["topic"], question["question"], question["now"]])
    _wrap(asked, 2)

    for sheet in workbook.worksheets:
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
    return workbook


def main(year: int) -> Path:
    config = get_config()
    data, rules = Path(config.data_path), Path(config.rules_path)
    days = {}
    for path in sorted((data / "calendar").glob("[0-9][0-9][0-9][0-9].json")):
        days |= read_calendar_file(path).days()
    work_calendar = WorkCalendar(days)
    if year not in work_calendar.years:
        sys.exit(f"Нет производственного календаря на {year} год")
    questions_file = rules / f"questions-{year}.yaml"
    questions = (
        yaml.safe_load(questions_file.read_text(encoding="utf-8"))["questions"]
        if questions_file.exists()
        else []
    )
    workbook = build_workbook(year, load_rules(rules), work_calendar, questions)
    target = data / "exports" / f"calendar-{year}-test-companies.xlsx"
    target.parent.mkdir(exist_ok=True)
    workbook.save(target)
    return target


if __name__ == "__main__":
    path = main(int(sys.argv[1]) if len(sys.argv) > 1 else date.today().year)
    print(f"Готово: data/{path.relative_to(get_config().data_path)}")

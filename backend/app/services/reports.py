"""Отчёт о выполненном за период: по компаниям и ответственным бухгалтерам."""

import io
from dataclasses import astuple, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fpdf import FPDF
from fpdf.fonts import FontFace
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import accessible_company_ids_query
from app.core.settings_store import get_settings
from app.models import ChangedBy, Company, Task, TaskKind, TaskStatus, User
from app.services.companies import person_name
from app.services.notify.messages import money
from app.services.task_state import before_start_condition

FONTS = Path("/usr/share/fonts/truetype/dejavu")
NO_ACCOUNTANT = "Не назначен"
KINDS = {
    TaskKind.PAYMENT: "Платёж",
    TaskKind.REPORT: "Отчёт",
    TaskKind.NOTICE: "Уведомление",
    TaskKind.OTHER: "Другое",
}
STATUSES = {
    TaskStatus.PAID: "Оплачено",
    TaskStatus.DONE: "Сдано",
    TaskStatus.NOT_REQUIRED: "Не требуется",
}
NOTE = (
    "Своевременность определяется по дате отметки в сервисе, а не по дате платежа "
    "или отправки отчёта. «Просрочено» — задачи со сроком в периоде, не отмеченные до сих пор."
)
SUMMARY_HEADER = (
    "Бухгалтер",
    "Компания",
    "Выполнено в срок",
    "С опозданием",
    "Не требуется",
    "Просрочено",
    "Оплачено, ₽",
)
DETAIL_HEADER = (
    "Бухгалтер",
    "Компания",
    "Задача",
    "Тип",
    "Срок",
    "Статус",
    "Отмечено",
    "Кто отметил",
    "Своевременность",
    "Сумма, ₽",
)


@dataclass
class Row:
    accountant: str
    company: str
    title: str
    kind: str
    due: date
    status: str
    marked: date | None
    marked_by: str
    timing: str
    amount_kopecks: int | None


@dataclass
class Summary:
    accountant: str
    company: str
    on_time: int = 0
    late: int = 0
    not_required: int = 0
    overdue: int = 0
    paid_kopecks: int = 0


@dataclass
class Report:
    date_from: date
    date_to: date
    rows: list[Row] = field(default_factory=list)
    summary: list[Summary] = field(default_factory=list)

    @property
    def title(self) -> str:
        return f"Отчёт о выполненном за {self.date_from:%d.%m.%Y} — {self.date_to:%d.%m.%Y}"

    def filename(self, extension: str) -> str:
        return f"report-{self.date_from}-{self.date_to}.{extension}"


async def build(
    db: AsyncSession,
    user: User,
    date_from: date,
    date_to: date,
    current: date,
    company_id: int | None = None,
    accountant_id: int | None = None,
) -> Report:
    """Только компании, доступные пользователю; архивные тоже (это история)."""
    zone = ZoneInfo(get_settings().company.timezone)
    companies = [Company.id.in_(accessible_company_ids_query(user))]
    if company_id is not None:
        companies.append(Company.id == company_id)
    if accountant_id is not None:
        companies.append(Company.accountant_id == accountant_id)
    users = {item.id: item for item in await db.scalars(select(User))}

    def query(*conditions):
        return (
            select(Task, Company)
            .join(Company, Company.id == Task.company_id)
            .where(*companies, *conditions)
        )

    start = datetime.combine(date_from, time.min, zone)
    end = datetime.combine(date_to + timedelta(days=1), time.min, zone)
    done = await db.execute(
        query(
            Task.status != TaskStatus.PLANNED,
            # «Не требуется», выставленное генерацией, — не чья-то работа
            Task.status_changed_by_role != ChangedBy.SYSTEM,
            Task.status_changed_at >= start,
            Task.status_changed_at < end,
        )
    )
    missed = await db.execute(
        query(
            Task.status == TaskStatus.PLANNED,
            Company.is_archived.is_(False),
            Task.due_date >= date_from,
            Task.due_date <= min(date_to, current - timedelta(days=1)),
            ~before_start_condition(),
        )
    )

    report = Report(date_from, date_to)
    totals: dict[int, Summary] = {}

    def total_for(company: Company) -> Summary:
        accountant = users.get(company.accountant_id)
        return totals.setdefault(
            company.id,
            Summary(person_name(accountant) or NO_ACCOUNTANT, company.short_name or company.name),
        )

    for task, company in [*done, *missed]:
        total = total_for(company)
        marked = None
        if task.status == TaskStatus.PLANNED:
            total.overdue += 1
            status, timing = "Не отмечено", "Просрочено"
        else:
            status = STATUSES[task.status]
            marked = task.status_changed_at.astimezone(zone).date()
            late = (marked - task.due_date).days
            if task.status == TaskStatus.NOT_REQUIRED:
                total.not_required += 1
                timing = "—"
            elif late > 0:
                total.late += 1
                timing = f"С опозданием на {late} дн."
            else:
                total.on_time += 1
                timing = "В срок"
            if task.status == TaskStatus.PAID:
                total.paid_kopecks += task.amount_kopecks or 0
        report.rows.append(
            Row(
                total.accountant,
                total.company,
                task.title,
                KINDS[task.kind],
                task.due_date,
                status,
                marked,
                person_name(users.get(task.status_changed_by)) if marked else "",
                timing,
                task.amount_kopecks,
            )
        )
    report.rows.sort(key=lambda row: (row.accountant, row.company, row.due, row.title))
    report.summary = sorted(totals.values(), key=lambda row: (row.accountant, row.company))
    return report


def to_xlsx(report: Report) -> bytes:
    book = Workbook()

    def fill(sheet, header, rows, widths) -> None:
        sheet.append([report.title])
        sheet["A1"].font = Font(bold=True, size=13)
        sheet.append([NOTE])
        sheet.append([])
        sheet.append(list(header))
        for cell in sheet[4]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        for row in rows:
            sheet.append(row)
            for cell in sheet[sheet.max_row]:
                # названия из базы не должны превращаться в формулы
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                elif isinstance(cell.value, date):
                    cell.number_format = "DD.MM.YYYY"
                elif isinstance(cell.value, float):
                    cell.number_format = "#,##0.00"
        for number, width in enumerate(widths):
            sheet.column_dimensions[chr(ord("A") + number)].width = width
        sheet.freeze_panes = "A5"

    summary = book.active
    summary.title = "Итоги"
    fill(
        summary,
        SUMMARY_HEADER,
        [[*astuple(row)[:-1], row.paid_kopecks / 100] for row in report.summary],
        (24, 32, 14, 14, 14, 14, 16),
    )
    fill(
        book.create_sheet("Задачи"),
        DETAIL_HEADER,
        [
            [
                *astuple(row)[:-1],
                None if row.amount_kopecks is None else row.amount_kopecks / 100,
            ]
            for row in report.rows
        ],
        (22, 28, 48, 14, 12, 14, 12, 20, 24, 14),
    )
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _day(value: date | None) -> str:
    return "" if value is None else f"{value:%d.%m.%Y}"


def to_pdf(report: Report) -> bytes:
    pdf = FPDF(orientation="landscape", format="A4")
    pdf.add_font("DejaVu", "", FONTS / "DejaVuSans.ttf")
    pdf.add_font("DejaVu", "B", FONTS / "DejaVuSans-Bold.ttf")
    pdf.set_margins(10, 10)
    pdf.add_page()
    pdf.set_font("DejaVu", "B", 13)
    pdf.multi_cell(0, 7, report.title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 8)
    pdf.multi_cell(0, 4, NOTE, new_x="LMARGIN", new_y="NEXT")

    def table(title: str, header, rows, widths) -> None:
        pdf.ln(3)
        pdf.set_font("DejaVu", "B", 10)
        pdf.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("DejaVu", "", 7)
        with pdf.table(
            col_widths=widths,
            text_align="LEFT",
            line_height=3.6,
            headings_style=FontFace(emphasis="BOLD"),
        ) as grid:
            for values in (header, *rows):
                line = grid.row()
                for value in values:
                    line.cell(str(value))

    if not report.rows:
        pdf.ln(4)
        pdf.cell(0, 6, "За этот период нет ни выполненных, ни просроченных задач.")
        return bytes(pdf.output())
    table(
        "Итоги",
        SUMMARY_HEADER,
        [[*astuple(row)[:-1], money(row.paid_kopecks)] for row in report.summary],
        (22, 30, 10, 10, 10, 10, 14),
    )
    table(
        "Задачи",
        DETAIL_HEADER,
        [
            [
                row.accountant,
                row.company,
                row.title,
                row.kind,
                _day(row.due),
                row.status,
                _day(row.marked),
                row.marked_by,
                row.timing,
                "" if row.amount_kopecks is None else money(row.amount_kopecks),
            ]
            for row in report.rows
        ],
        (13, 17, 27, 10, 9, 10, 9, 12, 13, 13),
    )
    return bytes(pdf.output())

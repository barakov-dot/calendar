"""Тексты и кнопки сообщений. Без разметки: названия из базы не интерпретируются."""

from collections.abc import Iterable
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.core.settings_store import AppSettings
from app.models import Company, Task

MESSAGE_LIMIT = 4000
LINES_PER_SECTION = 15


def money(kopecks: int) -> str:
    rubles = f"{kopecks // 100:,}".replace(",", " ")
    return f"{rubles},{kopecks % 100:02d} ₽"


def company_name(company: Company | None) -> str:
    return (company.short_name or company.name) if company else "Личное"


def short(day: date) -> str:
    return f"{day:%d.%m}"


def task_line(task: Task, company: Company | None, with_date: bool = True) -> str:
    parts = [f"{company_name(company)}: {task.title}"]
    if with_date:
        parts[0] += f" (до {short(task.due_date)})"
    if task.amount_kopecks is not None:
        parts.append(money(task.amount_kopecks))
    return " — ".join(parts)


def section(title: str, rows: Iterable[tuple[Task, Company | None]]) -> str:
    rows = list(rows)
    lines = [f"• {task_line(task, company)}" for task, company in rows[:LINES_PER_SECTION]]
    if len(rows) > LINES_PER_SECTION:
        lines.append(f"…и ещё {len(rows) - LINES_PER_SECTION}")
    return f"{title}: {len(rows)}\n" + "\n".join(lines)


def clip(text: str) -> str:
    return text if len(text) <= MESSAGE_LIMIT else text[: MESSAGE_LIMIT - 1] + "…"


def overview(header: str, rows: list[tuple[Task, Company | None]], current: date) -> str | None:
    """Просроченное, сегодня и ближайшие дни. None — сообщать нечего."""
    groups = (
        ("Просрочено", [row for row in rows if row[0].due_date < current]),
        ("Сегодня", [row for row in rows if row[0].due_date == current]),
        ("Ближайшие 7 дней", [row for row in rows if row[0].due_date > current]),
    )
    parts = [section(title, items) for title, items in groups if items]
    return clip("\n\n".join([header, *parts])) if parts else None


def client_reminder(task: Task, company: Company, current: date) -> str:
    if task.due_date < current:
        start = f"срок оплаты прошёл {short(task.due_date)}"
    elif task.due_date == current:
        start = f"сегодня, {short(task.due_date)}, срок оплаты"
    else:
        start = f"до {short(task.due_date)} оплатить"
    text = f"{company_name(company)}: {start} — {task.title}"
    if task.amount_kopecks is not None:
        text += f" — {money(task.amount_kopecks)}"
    if task.client_note:
        text += f"\n\n{task.client_note}"
    return clip(text)


def calendar_button(
    settings: AppSettings, text: str = "Открыть календарь", path: str = ""
) -> list[InlineKeyboardButton]:
    """Кнопка Mini App. Telegram открывает только https-адреса."""
    url = settings.telegram.mini_app_url
    if not url.startswith("https://"):
        return []
    return [InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url.rstrip("/") + "/" + path))]


def keyboard(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup | None:
    found = [row for row in rows if row]
    return InlineKeyboardMarkup(inline_keyboard=found) if found else None


def paid_button(task_id: int) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="Оплатил", callback_data=f"paid:{task_id}")]


def unpaid_button(task_id: int) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="Отменить отметку", callback_data=f"unpaid:{task_id}")]

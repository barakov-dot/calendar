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


def marker(due: date, current: date) -> str:
    """Цветной кружок по числу дней до срока: 7 и больше — зелёный, 2–6 — жёлтый,
    1, день срока и просрочка — красный."""
    left = (due - current).days
    if left >= 7:
        return "🟢"
    return "🟡" if left >= 2 else "🔴"


def task_line(task: Task, company: Company | None, current: date) -> str:
    parts = [
        f"{marker(task.due_date, current)} {company_name(company)}: {task.title} "
        f"(до {short(task.due_date)})"
    ]
    if task.amount_kopecks is not None:
        parts.append(money(task.amount_kopecks))
    return " — ".join(parts)


def plain_line(task: Task, company: Company) -> str:
    """Без кружка срочности: для сообщений о том, что уже сделано."""
    line = f"{company_name(company)}: {task.title} (до {short(task.due_date)})"
    if task.amount_kopecks is not None:
        line += f" — {money(task.amount_kopecks)}"
    return line


def days_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "день"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "дня"
    return "дней"


def signature_reminder(task: Task, company: Company, current: date) -> str:
    left = (task.due_date - current).days
    rest = "истекает сегодня" if left == 0 else f"осталось {left} {days_word(left)}"
    return clip(
        f"{marker(task.due_date, current)} {company_name(company)}: {task.title} — "
        f"действует до {task.due_date:%d.%m.%Y}, {rest}"
    )


def demand_reminder(task: Task, company: Company, current: date, workdays: int) -> str:
    if task.due_date == current:
        rest = "срок сегодня"
    else:
        rest = f"осталось рабочих дней: {workdays}"
    text = (
        f"{marker(task.due_date, current)} 📄 {company_name(company)}\n{task.title}\n"
        f"До {task.due_date:%d.%m.%Y}, {rest}"
    )
    if task.amount_kopecks is not None:
        text += f"\nСумма: {money(task.amount_kopecks)}"
    return clip(text)


def section(title: str, rows: Iterable[tuple[Task, Company | None]], current: date) -> str:
    rows = list(rows)
    lines = [task_line(task, company, current) for task, company in rows[:LINES_PER_SECTION]]
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
    parts = [section(title, items, current) for title, items in groups if items]
    return clip("\n\n".join([header, *parts])) if parts else None


def client_reminder(task: Task, company: Company, current: date) -> str:
    if task.due_date < current:
        start = f"срок оплаты прошёл {short(task.due_date)}"
    elif task.due_date == current:
        start = f"сегодня, {short(task.due_date)}, срок оплаты"
    else:
        start = f"до {short(task.due_date)} оплатить"
    text = f"{marker(task.due_date, current)} {company_name(company)}: {start} — {task.title}"
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

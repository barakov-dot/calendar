from aiogram import Bot
from aiogram.types import BotCommand, MenuButtonDefault, MenuButtonWebApp, WebAppInfo

from app.services.telegram.connect import REQUEST_TIMEOUT

COMMANDS = [
    BotCommand(command="today", description="Задачи на сегодня"),
    BotCommand(command="week", description="Задачи на неделю"),
]


async def set_menu(bot: Bot, mini_app_url: str) -> None:
    """Список команд и кнопка «Открыть календарь» (только для https-адреса)."""
    await bot.set_my_commands(COMMANDS, request_timeout=REQUEST_TIMEOUT)
    button = (
        MenuButtonWebApp(text="Открыть календарь", web_app=WebAppInfo(url=mini_app_url))
        if mini_app_url.startswith("https://")
        else MenuButtonDefault()
    )
    await bot.set_chat_menu_button(menu_button=button, request_timeout=REQUEST_TIMEOUT)

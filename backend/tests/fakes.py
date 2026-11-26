"""Поддельные Telegram Bot API и SOCKS5-прокси: тесты не выходят в интернет."""

import asyncio
import contextlib
import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlencode

from aiogram.client.telegram import TelegramAPIServer
from aiogram.methods import GetMe
from aiohttp import web

TOKEN = "123456:TEST-token-that-is-long-enough-0123456789"
# Имя, которое «знает» только поддельный прокси
PROXIED_HOST = "telegram.test"


async def eventually(condition: Callable[[], object], seconds: float = 5) -> None:
    async with asyncio.timeout(seconds):
        while not condition():  # noqa: ASYNC110 — состояние подделок не сообщает событиями
            await asyncio.sleep(0.01)


def signed_init_data(telegram_id: int, issued: datetime, token: str = TOKEN) -> str:
    """initData, как их присылает Telegram Mini App."""
    fields = {
        "auth_date": str(int(issued.timestamp())),
        "query_id": "AAA",
        "user": json.dumps({"id": telegram_id, "first_name": "Тест"}, ensure_ascii=False),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class FakeTelegram:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.sent: list[tuple[int, str]] = []
        self.updates: list[dict] = []
        self.port = 0
        self._runner: web.AppRunner | None = None

    async def __aenter__(self) -> "FakeTelegram":
        app = web.Application()
        app.router.add_post("/bot{token}/{method}", self._handle)
        self._runner = web.AppRunner(app, shutdown_timeout=0.1)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = self._runner.addresses[0][1]
        return self

    async def __aexit__(self, *_) -> None:
        await self._runner.cleanup()

    def api(self, host: str = PROXIED_HOST) -> TelegramAPIServer:
        return TelegramAPIServer.from_base(f"http://{host}:{self.port}")

    def send_start(self, update_id: int, user_id: int, text: str = "/start") -> None:
        user = {"id": user_id, "is_bot": False, "first_name": "Тест"}
        self.updates.append(
            {
                "update_id": update_id,
                "message": {
                    "message_id": update_id,
                    "date": 1_700_000_000,
                    "chat": {"id": user_id, "type": "private"},
                    "from": user,
                    "text": text,
                    "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
                },
            }
        )

    async def _handle(self, request: web.Request) -> web.Response:
        method = request.match_info["method"]
        data = await request.post()
        self.calls.append(method)
        result: object = True
        if method == "getMe":
            # getMe возвращает обязательные признаки возможностей бота
            fields = GetMe.__returning__.model_fields
            flags = {name: False for name, info in fields.items() if info.is_required()}
            result = flags | {
                "id": 123456,
                "is_bot": True,
                "first_name": "Bot",
                "username": "test_bot",
            }
        elif method == "getUpdates":
            offset = int(data.get("offset") or 0)
            pending = [u for u in self.updates if u["update_id"] >= offset]
            if not pending:
                await asyncio.sleep(0.02)
            result = pending
        elif method == "sendMessage":
            self.sent.append((int(data["chat_id"]), data["text"]))
            result = {
                "message_id": len(self.sent),
                "date": 1_700_000_000,
                "chat": {"id": int(data["chat_id"]), "type": "private"},
                "text": data["text"],
            }
        return web.json_response({"ok": True, "result": result})


@dataclass
class FakeSocks5:
    username: str = ""
    password: str = ""
    targets: list[str] = field(default_factory=list)
    port: int = 0
    rejected: int = 0
    _server: asyncio.Server | None = None
    _tasks: set = field(default_factory=set)

    async def __aenter__(self) -> "FakeSocks5":
        self._server = await asyncio.start_server(self._accept, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_) -> None:
        self._server.close()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            await self._serve(reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            self._tasks.discard(task)

    async def _serve(self, reader, writer) -> None:
        _, count = await reader.readexactly(2)
        methods = await reader.readexactly(count)
        method = 2 if self.username else 0
        if method not in methods:
            self.rejected += 1
            writer.write(b"\x05\xff")
            return
        writer.write(bytes([5, method]))
        if method == 2:
            _, length = await reader.readexactly(2)
            username = (await reader.readexactly(length)).decode()
            length = (await reader.readexactly(1))[0]
            password = (await reader.readexactly(length)).decode()
            if (username, password) != (self.username, self.password):
                self.rejected += 1
                writer.write(b"\x01\x01")
                return
            writer.write(b"\x01\x00")
        _, _, _, address_type = await reader.readexactly(4)
        if address_type == 3:
            length = (await reader.readexactly(1))[0]
            host = (await reader.readexactly(length)).decode()
        else:
            raw = await reader.readexactly(4 if address_type == 1 else 16)
            host = ".".join(map(str, raw))
        port = int.from_bytes(await reader.readexactly(2))
        self.targets.append(host)
        upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")

        async def pipe(source, target) -> None:
            with contextlib.suppress(ConnectionError):
                while chunk := await source.read(65536):
                    target.write(chunk)
                    await target.drain()
            target.close()

        try:
            await asyncio.gather(pipe(reader, upstream_writer), pipe(upstream_reader, writer))
        finally:
            upstream_writer.close()

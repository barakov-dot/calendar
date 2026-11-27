"""Иконка сайта, загруженная администратором. Лежит в каталоге config рядом с настройками,
поэтому попадает в резервные копии и переживает обновление."""

import os
import tempfile
from pathlib import Path

from app.core.config import get_config

MAX_BYTES = 2 * 1024 * 1024
TYPES = {
    "png": "image/png",
    "ico": "image/x-icon",
    "svg": "image/svg+xml",
    "jpg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


class IconError(Exception):
    """Текст показывается пользователю."""


def _directory() -> Path:
    return Path(get_config().settings_path).parent


def detect(data: bytes) -> str | None:
    """Расширение по содержимому: имени файла не доверяем."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\x00\x00\x01\x00"):
        return "ico"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    head = data[:1000].lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith((b"<svg", b"<?xml")) and b"<svg" in data[:4000]:
        return "svg"
    return None


def current() -> tuple[Path, str] | None:
    for extension, content_type in TYPES.items():
        path = _directory() / f"site-icon.{extension}"
        if path.is_file():
            return path, content_type
    return None


def remove() -> bool:
    removed = False
    for extension in TYPES:
        path = _directory() / f"site-icon.{extension}"
        if path.is_file():
            path.unlink()
            removed = True
    return removed


def save(data: bytes) -> str:
    """Заменяет иконку целиком. Возвращает её тип."""
    if not data:
        raise IconError("Файл пустой")
    if len(data) > MAX_BYTES:
        raise IconError("Иконка больше 2 МБ")
    extension = detect(data)
    if extension is None:
        raise IconError("Подходят картинки PNG, ICO, SVG, JPG, WEBP и GIF")
    directory = _directory()
    directory.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, prefix=".site-icon-")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        os.chmod(temporary, 0o644)
        remove()
        os.replace(temporary, directory / f"site-icon.{extension}")
    finally:
        Path(temporary).unlink(missing_ok=True)
    return TYPES[extension]

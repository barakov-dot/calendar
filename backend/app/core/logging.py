import logging
import re
import sys

# Страховка от утечки секретов в логи, в том числе из текстов чужих исключений.
_REDACTIONS = (
    # логин и пароль в любом URL: socks5://user:pass@host, postgresql://user:pass@db
    (re.compile(r"\b([a-z][a-z0-9+.-]*://)[^/\s'\"]+@", re.IGNORECASE), r"\1***@"),
    # токен бота: 123456789:AA...
    (re.compile(r"(\d{5,}):[A-Za-z0-9_-]{30,}"), r"\1:***"),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])

import logging

from app.core.logging import RedactingFormatter, redact
from tests.fakes import TOKEN


def test_redacts_credentials_and_token():
    text = redact(
        f"socks5://user:pa55@host:1080 postgresql+asyncpg://u:dbpass@db/x /bot{TOKEN}/getMe"
    )

    for secret in ("pa55", "dbpass", TOKEN.split(":")[1]):
        assert secret not in text
    assert "host:1080" in text


def test_formatter_redacts_tracebacks():
    try:
        raise OSError("socks5://user:pa55@host:1080 refused")
    except OSError as error:
        record = logging.LogRecord(
            "x", logging.ERROR, __file__, 1, "ошибка", (), (type(error), error, error.__traceback__)
        )

    assert "pa55" not in RedactingFormatter().format(record)

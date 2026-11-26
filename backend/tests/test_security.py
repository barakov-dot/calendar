import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import jwt
import pytest

from app.core.security import AuthError, create_token, read_token, validate_init_data
from tests.conftest import JWT_SECRET
from tests.fakes import TOKEN, signed_init_data

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)


def test_valid_init_data():
    data = signed_init_data(555, NOW)

    assert validate_init_data(data, TOKEN, NOW)["id"] == 555


def test_known_vector_matches_telegram_algorithm():
    fields = {"auth_date": str(int(NOW.timestamp())), "user": json.dumps({"id": 1})}
    check = f"auth_date={fields['auth_date']}\nuser={fields['user']}"
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()

    assert validate_init_data(urlencode(fields), TOKEN, NOW) == {"id": 1}


@pytest.mark.parametrize(
    "data",
    [
        signed_init_data(555, NOW).replace("555", "556"),
        signed_init_data(555, NOW, token="999999:" + "x" * 35),
        signed_init_data(555, NOW) + "&extra=1",
        signed_init_data(555, NOW) + "&user=%7B%22id%22%3A1%7D",
        signed_init_data(555, NOW).split("&hash=")[0],
        signed_init_data(555, NOW).split("&hash=")[0] + "&hash=%D1%8F",
        "garbage",
    ],
)
def test_forged_init_data_is_rejected(data):
    with pytest.raises(AuthError):
        validate_init_data(data, TOKEN, NOW)


@pytest.mark.parametrize("age", [timedelta(hours=25), timedelta(minutes=-10)])
def test_expired_or_future_init_data_is_rejected(age):
    with pytest.raises(AuthError, match="устарели"):
        validate_init_data(signed_init_data(555, NOW - age), TOKEN, NOW)


def test_token_round_trip_and_type_check():
    access = create_token(7, "access", JWT_SECRET)

    assert read_token(access, "access", JWT_SECRET) == 7
    with pytest.raises(AuthError):
        read_token(access, "refresh", JWT_SECRET)


@pytest.mark.parametrize(
    "token",
    [
        create_token(7, "access", JWT_SECRET, datetime.now(UTC) - timedelta(hours=2)),
        create_token(7, "access", "another-secret-0123456789-0123456789"),
        jwt.encode({"sub": "7", "type": "access"}, JWT_SECRET, algorithm="HS256"),
        jwt.encode({"sub": "7", "type": "access", "exp": 9999999999}, None, algorithm="none"),
        "abc",
    ],
)
def test_bad_tokens_are_rejected(token):
    with pytest.raises(AuthError):
        read_token(token, "access", JWT_SECRET)

"""Иконка сайта: загрузка администратором и раздача всем."""

import pytest

from app.models import Role
from app.services import site_icon
from tests.factories import auth, make_user

pytestmark = pytest.mark.usefixtures("secrets")

PNG = b"\x89PNG\r\n\x1a\n test"
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>'


@pytest.fixture
async def admin(db):
    return await make_user(db, 1, Role.ADMIN)


async def upload(client, user, data):
    return await client.post("/api/admin/site-icon", content=data, headers=auth(user))


async def test_admin_uploads_and_anyone_reads(client, admin):
    assert (await client.get("/api/site-icon")).status_code == 404

    for data, content_type in ((PNG, "image/png"), (SVG, "image/svg+xml")):
        response = await upload(client, admin, data)
        assert response.json() == {"content_type": content_type}
        got = await client.get("/api/site-icon")
        assert (got.content, got.headers["content-type"]) == (data, content_type)
        assert "sandbox" in got.headers["content-security-policy"]

    deleted = await client.delete("/api/admin/site-icon", headers=auth(admin))
    assert deleted.status_code == 204
    assert (await client.get("/api/site-icon")).status_code == 404


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "пустой"),
        (b"<html></html>", "Подходят картинки"),
        (b"%PDF-1.7", "Подходят картинки"),
        (PNG + b"x" * site_icon.MAX_BYTES, "больше 2 МБ"),
    ],
)
async def test_rejects_unsuitable_files(client, admin, data, message):
    response = await upload(client, admin, data)

    assert response.status_code == 422
    assert message in response.json()["detail"]


@pytest.mark.parametrize("role", [Role.CHIEF, Role.ACCOUNTANT, Role.CLIENT])
async def test_only_admin_changes(client, db, role):
    user = await make_user(db, 5, role)

    assert (await upload(client, user, PNG)).status_code == 403
    removed = await client.delete("/api/admin/site-icon", headers=auth(user))
    assert removed.status_code == 403

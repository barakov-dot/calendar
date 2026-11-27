"""Платёжки: кто может приложить, увидеть и удалить файл."""

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
from sqlalchemy import select

from app.core.settings_store import get_store
from app.models import Attachment, Notification
from app.services.attachments import MAX_BYTES, clean_name
from app.services.notify.sender import deliver
from app.services.telegram import documents
from app.services.telegram.client import TelegramClient
from tests.factories import auth
from tests.test_notifications import telegram  # noqa: F401
from tests.test_payments import make_task, world  # noqa: F401

pytestmark = pytest.mark.usefixtures("secrets")

PDF = b"%PDF-1.7 test"
JPEG = b"\xff\xd8\xff\xe0 test"


async def upload(client, user, task, data=PDF, name="Платёжка №5.pdf"):
    return await client.post(
        f"/api/tasks/{task.id}/attachments",
        content=data,
        headers=auth(user) | {"X-Filename": quote(name)},
    )


async def test_payer_attaches_and_accountant_downloads(client, db, world):  # noqa: F811
    task = world["task"]

    response = await upload(client, world["payer"], task)

    assert response.status_code == 201, response.text
    [item] = response.json()["items"]
    assert (item["filename"], item["content_type"], item["can_delete"]) == (
        "Платёжка №5.pdf",
        "application/pdf",
        True,
    )
    [note] = (await db.scalars(select(Notification))).all()
    assert (note.user_id, note.type) == (world["accountant"].id, "attachment")
    file = await client.get(f"/api/attachments/{item['id']}", headers=auth(world["accountant"]))
    assert file.content == PDF
    assert file.headers["content-disposition"].startswith("attachment;")
    assert file.headers["x-content-type-options"] == "nosniff"
    listed = await client.get("/api/tasks", headers=auth(world["accountant"]))
    assert [row["has_files"] for row in listed.json()["items"]] == [True]


@pytest.mark.parametrize(
    ("name", "status"),
    [
        ("admin", 201),
        ("accountant", 201),
        ("payer", 201),
        ("viewer", 403),
        ("helper", 403),
        ("outsider", 404),
        ("other_accountant", 404),
    ],
)
async def test_who_may_upload(client, db, world, name, status):  # noqa: F811
    response = await upload(client, world[name], world["task"])

    assert response.status_code == status
    assert (await db.scalar(select(Attachment.id)) is not None) == (status == 201)


async def test_foreign_file_is_hidden(client, db, world):  # noqa: F811
    created = await upload(client, world["payer"], world["task"])
    url = f"/api/attachments/{created.json()['items'][0]['id']}"

    for name in ("outsider", "other_accountant"):
        headers = auth(world[name])
        assert (await client.get(url, headers=headers)).status_code == 404
        assert (await client.post(f"{url}/send", headers=headers)).status_code == 404
        assert (await client.delete(url, headers=headers)).status_code == 404
    assert (await client.get(url)).status_code == 401
    # клиент без права оплаты видит файл своей компании, но удалить не может
    assert (await client.get(url, headers=auth(world["viewer"]))).status_code == 200
    assert (await client.delete(url, headers=auth(world["viewer"]))).status_code == 403


async def test_hidden_task_hides_files_from_client(client, db, world):  # noqa: F811
    created = await upload(client, world["accountant"], world["task"])
    task = world["task"]
    task.client_visible = False
    await db.commit()
    url = f"/api/attachments/{created.json()['items'][0]['id']}"

    assert (await client.get(url, headers=auth(world["payer"]))).status_code == 404
    assert (await upload(client, world["payer"], task)).status_code == 404


async def test_client_deletes_only_own_and_only_for_a_while(client, db, world):  # noqa: F811
    task, payer = world["task"], world["payer"]
    own = (await upload(client, payer, task)).json()["items"][0]["id"]
    staff = (await upload(client, world["accountant"], task)).json()["items"][1]["id"]
    headers = auth(payer)

    assert (await client.delete(f"/api/attachments/{staff}", headers=headers)).status_code == 403
    attachment = await db.get(Attachment, own)
    attachment.created_at = datetime.now(UTC) - timedelta(hours=25)
    await db.commit()
    assert (await client.delete(f"/api/attachments/{own}", headers=headers)).status_code == 403
    by_staff = await client.delete(f"/api/attachments/{own}", headers=auth(world["accountant"]))
    assert by_staff.status_code == 204


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (JPEG, 201),
        (b"<html><script>alert(1)</script>", 415),
        (b"", 422),
        (PDF + b"0" * MAX_BYTES, 413),
    ],
)
async def test_content_is_checked(client, world, data, status):  # noqa: F811
    response = await upload(client, world["payer"], world["task"], data, "x.pdf")

    assert response.status_code == status


async def test_only_payments_and_not_more_than_five(client, db, world):  # noqa: F811
    report = await make_task(db, world["company"], kind="report")
    assert (await upload(client, world["accountant"], report)).status_code == 403

    for _ in range(5):
        assert (await upload(client, world["payer"], world["task"])).status_code == 201
    assert (await upload(client, world["payer"], world["task"])).status_code == 422


@pytest.mark.parametrize(
    ("name", "content_type", "result"),
    [
        ("../../etc/passwd", "application/pdf", "passwd.pdf"),
        ("virus.html", "application/pdf", "virus.pdf"),
        ("Фото.JPEG", "image/jpeg", "Фото.jpeg"),
        ('a"b\r\n.png', "image/png", "ab.png"),
        ("", "image/png", "файл.png"),
    ],
)
def test_clean_name(name, content_type, result):
    assert clean_name(name, content_type) == result


async def test_notification_and_send_to_telegram(client, db, world, telegram, monkeypatch):  # noqa: F811
    created = await upload(client, world["payer"], world["task"])

    class LocalClient(TelegramClient):
        def __init__(self, store, config):
            super().__init__(store, config, telegram.api("127.0.0.1"))

    monkeypatch.setattr(documents, "TelegramClient", LocalClient)
    url = f"/api/attachments/{created.json()['items'][0]['id']}/send"

    assert (await client.post(url, headers=auth(world["accountant"]))).status_code == 204

    assert telegram.documents == [(world["accountant"].telegram_id, "Платёжка №5.pdf", PDF)]
    sender = LocalClient(get_store(), documents.get_config())
    try:
        await deliver(db, await sender.get_bot(), get_store().get(), datetime.now(UTC), pause=0)
    finally:
        await sender.close()
    [(chat, text)] = telegram.sent
    assert chat == world["accountant"].telegram_id
    assert text.startswith("Пётр приложил(а) файл к платежу\n")

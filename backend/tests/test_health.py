from app.api import health


async def test_health_ok_with_real_database(client):
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_health_503_when_database_unavailable(client, monkeypatch, caplog):
    class BrokenEngine:
        def connect(self):
            raise OSError("postgresql://user:secret@db/buh refused")

    monkeypatch.setattr(health, "get_engine", BrokenEngine)

    response = await client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}
    assert "secret" not in caplog.text

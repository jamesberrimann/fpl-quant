from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch, MagicMock

from sqlalchemy.exc import OperationalError


def _healthy_db():
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield mock_db

    return factory


async def test_health_returns_ok_when_db_alive(client):
    with patch("app.api.v1.health.async_session_factory", new=_healthy_db()):
        r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_health_returns_503_when_db_unreachable(client):
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=OperationalError("conn", {}, None))

    @asynccontextmanager
    async def broken_factory():
        yield mock_db

    with patch("app.api.v1.health.async_session_factory", new=broken_factory):
        r = await client.get("/api/v1/health")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"
    assert r.json()["db"] == "unreachable"


async def test_health_requires_no_api_key(client):
    with patch("app.api.v1.health.async_session_factory", new=_healthy_db()):
        r = await client.get("/api/v1/health")
    assert r.status_code == 200

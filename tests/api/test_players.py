from unittest.mock import AsyncMock, MagicMock

from app.core.db import get_db
from app.main import app


async def test_players_happy_path_returns_empty_list(client, auth):
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_db] = override
    try:
        r = await client.get("/api/v1/players", headers=auth)
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.pop(get_db, None)

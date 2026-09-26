from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

MOCK_BS = {"events": [{"id": 5, "is_current": True}], "teams": [{"id": 1, "short_name": "TST"}]}


def _mock_rated_squad():
    results = []
    for i in range(15):
        p = MagicMock()
        p.id = i
        p.web_name = f"Player{i}"
        p.position.value = "MID"
        p.team_id = 1
        results.append((p, MagicMock(), 75.0, 80.0, None))
    return results


async def test_rate_squad_missing_entry_id_returns_422(client, auth):
    r = await client.get("/api/v1/rate-squad", headers=auth)
    assert r.status_code == 422


async def test_rate_squad_happy_path(client, auth):
    mock_db = AsyncMock()

    @asynccontextmanager
    async def mock_factory():
        yield mock_db

    with patch("app.api.v1.rating.get_bootstrap_static", new=AsyncMock(return_value=MOCK_BS)), \
         patch("app.api.v1.rating.rate_squad", new=AsyncMock(return_value=_mock_rated_squad())), \
         patch("app.api.v1.rating.async_session_factory", new=mock_factory), \
         patch("app.api.v1.rating.get_planning_gameweek", new=AsyncMock(return_value=5)), \
         patch("app.api.v1.rating.get_next_fixture_labels", new=AsyncMock(return_value={})):
        r = await client.get("/api/v1/rate-squad", headers=auth, params={"entry_id": 123})

    assert r.status_code == 200
    data = r.json()
    assert len(data["players"]) == 15
    assert data["players"][0]["score"] == 75.0
    assert data["players"][0]["percentile"] == 80.0
    assert data["players"][0]["flag"] is None
    assert data["players"][0]["team_short_name"] == "TST"


async def test_rate_squad_with_regression_flag(client, auth):
    p = MagicMock()
    p.id = 1
    p.web_name = "Risky"
    p.position.value = "DEF"
    p.team_id = 1
    mock_result = [(p, MagicMock(), 60.0, 90.0, "regression_risk")]
    mock_db = AsyncMock()

    @asynccontextmanager
    async def mock_factory():
        yield mock_db

    with patch("app.api.v1.rating.get_bootstrap_static", new=AsyncMock(return_value=MOCK_BS)), \
         patch("app.api.v1.rating.rate_squad", new=AsyncMock(return_value=mock_result)), \
         patch("app.api.v1.rating.async_session_factory", new=mock_factory), \
         patch("app.api.v1.rating.get_planning_gameweek", new=AsyncMock(return_value=5)), \
         patch("app.api.v1.rating.get_next_fixture_labels", new=AsyncMock(return_value={})):
        r = await client.get("/api/v1/rate-squad", headers=auth, params={"entry_id": 99})

    assert r.status_code == 200
    assert r.json()["players"][0]["flag"] == "regression_risk"

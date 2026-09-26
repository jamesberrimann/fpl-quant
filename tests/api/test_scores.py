from unittest.mock import AsyncMock, patch

MOCK_BS = {"events": [{"id": 5, "is_current": True}]}

MOCK_TEAM_SCORE = {
    "team_id": 1,
    "team_name": "Arsenal",
    "team_short_name": "ARS",
    "gameweek": 5,
    "is_current_gameweek": True,
    "is_home": True,
    "team_score": 2,
    "opponent_id": 2,
    "opponent_name": "Chelsea",
    "opponent_short_name": "CHE",
    "opponent_score": 1,
    "fully_confirmed": True,
}

MOCK_LIVE_EVENT = {
    "player_id": 100,
    "web_name": "Salah",
    "position": "MID",
    "team_short_name": "LIV",
    "gameweek": 5,
    "is_current_gameweek": True,
    "events": {"goals_scored": 1, "assists": 0},
}


async def test_team_score_missing_team_id_returns_422(client, auth):
    r = await client.get("/api/v1/team-score", headers=auth)
    assert r.status_code == 422


async def test_team_score_not_found_returns_404(client, auth):
    with patch("app.api.v1.scores.get_bootstrap_static", new=AsyncMock(return_value=MOCK_BS)), \
         patch("app.api.v1.scores.get_latest_team_score", new=AsyncMock(return_value=None)):
        r = await client.get("/api/v1/team-score", headers=auth, params={"team_id": 999})
    assert r.status_code == 404


async def test_team_score_happy_path(client, auth):
    with patch("app.api.v1.scores.get_bootstrap_static", new=AsyncMock(return_value=MOCK_BS)), \
         patch("app.api.v1.scores.get_latest_team_score", new=AsyncMock(return_value=MOCK_TEAM_SCORE)):
        r = await client.get("/api/v1/team-score", headers=auth, params={"team_id": 1})

    assert r.status_code == 200
    data = r.json()
    assert data["team_name"] == "Arsenal"
    assert data["team_score"] == 2
    assert data["fully_confirmed"] is True


async def test_squad_scores_missing_entry_id_returns_422(client, auth):
    r = await client.get("/api/v1/squad-scores", headers=auth)
    assert r.status_code == 422


async def test_squad_scores_happy_path(client, auth):
    with patch("app.api.v1.scores.get_squad_scores", new=AsyncMock(return_value=[MOCK_TEAM_SCORE])):
        r = await client.get("/api/v1/squad-scores", headers=auth, params={"entry_id": 123})

    assert r.status_code == 200
    assert len(r.json()["scores"]) == 1
    assert r.json()["scores"][0]["team_name"] == "Arsenal"


async def test_squad_live_events_missing_entry_id_returns_422(client, auth):
    r = await client.get("/api/v1/squad-live-events", headers=auth)
    assert r.status_code == 422


async def test_squad_live_events_happy_path(client, auth):
    with patch("app.api.v1.scores.get_squad_live_events", new=AsyncMock(return_value=[MOCK_LIVE_EVENT])):
        r = await client.get("/api/v1/squad-live-events", headers=auth, params={"entry_id": 123})

    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) == 1
    assert events[0]["web_name"] == "Salah"
    assert events[0]["events"]["goals_scored"] == 1

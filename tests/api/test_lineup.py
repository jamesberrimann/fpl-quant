from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch


def _make_player(id, name, pos="MID"):
    p = MagicMock()
    p.id = id
    p.web_name = name
    p.position.value = pos
    p.team_id = 1
    p.status = "a"
    return p


def _make_stats():
    s = MagicMock()
    s.status = "a"
    s.chance_of_playing_next_round = None
    return s


def _make_lineup():
    starting = [(_make_player(i, f"P{i}"), _make_stats(), 70.0) for i in range(1, 12)]
    bench_gk = (_make_player(12, "BenchGK", "GKP"), _make_stats(), 50.0)
    bench_out = [(_make_player(i, f"B{i}"), _make_stats(), 55.0) for i in range(13, 16)]
    return {"starting_xi": starting, "bench_gk": bench_gk, "bench_outfield": bench_out}


def _make_captain_rec():
    return {
        "top_pick": {"player": _make_player(1, "P1"), "rating": 90},
        "second_pick": {"player": _make_player(2, "P2"), "rating": 80},
        "advantage_pct": 12.5,
        "tie_broken_by_ceiling": False,
        "differential_captain": None,
    }


async def test_lineup_missing_entry_id_returns_422(client, auth):
    r = await client.get("/api/v1/lineup", headers=auth)
    assert r.status_code == 422


async def test_lineup_happy_path(client, auth):
    mock_bs = {"events": [{"id": 5, "is_current": True}], "teams": [{"id": 1, "short_name": "TST"}]}
    mock_db = AsyncMock()

    @asynccontextmanager
    async def mock_factory():
        yield mock_db

    lineup = _make_lineup()
    xi_with_scores = lineup["starting_xi"]
    with patch("app.api.v1.lineup.get_bootstrap_static", new=AsyncMock(return_value=mock_bs)), \
         patch("app.api.v1.lineup.pick_best_starting_xi_for_entry", new=AsyncMock(return_value=lineup)), \
         patch("app.api.v1.lineup.async_session_factory", new=mock_factory), \
         patch("app.api.v1.lineup.score_for_captaincy", new=AsyncMock(return_value=[])), \
         patch("app.api.v1.lineup.get_planning_gameweek", new=AsyncMock(return_value=5)), \
         patch("app.api.v1.lineup.get_gameweek_fixture_multipliers", new=AsyncMock(return_value={})), \
         patch("app.api.v1.lineup.predict_points", new=AsyncMock(return_value=xi_with_scores)), \
         patch("app.api.v1.lineup.get_next_fixture_labels", new=AsyncMock(return_value={})), \
         patch("app.api.v1.lineup.get_next_fixture_is_home", new=AsyncMock(return_value={})), \
         patch("app.api.v1.lineup.get_captain_recommendation", return_value=_make_captain_rec()):
        r = await client.get("/api/v1/lineup", headers=auth, params={"entry_id": 123})

    assert r.status_code == 200
    data = r.json()
    assert len(data["starting_xi"]) == 11
    assert data["captain"]["web_name"] == "P1"
    assert data["captain"]["rating"] == 90
    assert data["vice_captain"]["web_name"] == "P2"
    assert data["captain_advantage_pct"] == 12.5
    assert data["tie_broken_by_ceiling"] is False
    assert data["bench_gk"]["web_name"] == "BenchGK"
    assert len(data["bench_outfield"]) == 3


async def test_lineup_network_error_returns_503(client, auth):
    """Timeout / connection error from the FPL API must return 503, not crash."""
    import httpx
    no_gw_bs = {"events": [{"id": 5, "is_current": True}], "teams": []}
    with patch("app.api.v1.lineup.get_bootstrap_static", new=AsyncMock(return_value=no_gw_bs)), \
         patch("app.api.v1.lineup.pick_best_starting_xi_for_entry",
               new=AsyncMock(side_effect=httpx.ConnectTimeout("timeout", request=None))):
        r = await client.get("/api/v1/lineup", headers=auth, params={"entry_id": 123})
    assert r.status_code == 503
    assert "network error" in r.json()["detail"].lower()


async def test_lineup_rate_limited_returns_429(client, auth):
    """FPL API 429 should be forwarded as 429, not a 500."""
    import httpx
    no_gw_bs = {"events": [{"id": 5, "is_current": True}], "teams": []}
    mock_response = MagicMock()
    mock_response.status_code = 429
    with patch("app.api.v1.lineup.get_bootstrap_static", new=AsyncMock(return_value=no_gw_bs)), \
         patch("app.api.v1.lineup.pick_best_starting_xi_for_entry",
               new=AsyncMock(side_effect=httpx.HTTPStatusError("rate limited", request=None, response=mock_response))):
        r = await client.get("/api/v1/lineup", headers=auth, params={"entry_id": 123})
    assert r.status_code == 429


async def test_lineup_no_active_gameweek_returns_503(client, auth):
    """When the FPL API has no is_current event (international break / season gap),
    the route must return 503 rather than crashing with StopIteration."""
    no_gw_bs = {"events": [{"id": 5, "is_current": False}], "teams": []}
    with patch("app.api.v1.lineup.get_bootstrap_static", new=AsyncMock(return_value=no_gw_bs)):
        r = await client.get("/api/v1/lineup", headers=auth, params={"entry_id": 123})
    assert r.status_code == 503
    assert "gameweek" in r.json()["detail"].lower()


async def test_lineup_tie_broken_flag_propagates(client, auth):
    mock_bs = {"events": [{"id": 5, "is_current": True}], "teams": [{"id": 1, "short_name": "TST"}]}
    mock_db = AsyncMock()
    rec = _make_captain_rec()
    rec["tie_broken_by_ceiling"] = True
    rec["advantage_pct"] = None

    @asynccontextmanager
    async def mock_factory():
        yield mock_db

    lineup = _make_lineup()
    xi_with_scores = lineup["starting_xi"]
    with patch("app.api.v1.lineup.get_bootstrap_static", new=AsyncMock(return_value=mock_bs)), \
         patch("app.api.v1.lineup.pick_best_starting_xi_for_entry", new=AsyncMock(return_value=lineup)), \
         patch("app.api.v1.lineup.async_session_factory", new=mock_factory), \
         patch("app.api.v1.lineup.score_for_captaincy", new=AsyncMock(return_value=[])), \
         patch("app.api.v1.lineup.get_planning_gameweek", new=AsyncMock(return_value=5)), \
         patch("app.api.v1.lineup.get_gameweek_fixture_multipliers", new=AsyncMock(return_value={})), \
         patch("app.api.v1.lineup.predict_points", new=AsyncMock(return_value=xi_with_scores)), \
         patch("app.api.v1.lineup.get_next_fixture_labels", new=AsyncMock(return_value={})), \
         patch("app.api.v1.lineup.get_next_fixture_is_home", new=AsyncMock(return_value={})), \
         patch("app.api.v1.lineup.get_captain_recommendation", return_value=rec):
        r = await client.get("/api/v1/lineup", headers=auth, params={"entry_id": 1})

    assert r.status_code == 200
    assert r.json()["tie_broken_by_ceiling"] is True
    assert r.json()["captain_advantage_pct"] is None

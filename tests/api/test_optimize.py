from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.player import Position
from app.services.optimizer import InfeasibleBudgetError

MOCK_BS = {"events": [{"id": 5, "is_current": True}], "teams": [{"id": 1, "short_name": "TST"}]}

POSITIONS = [Position.GKP, Position.GKP,
             Position.DEF, Position.DEF, Position.DEF, Position.DEF, Position.DEF,
             Position.MID, Position.MID, Position.MID, Position.MID, Position.MID,
             Position.FWD, Position.FWD, Position.FWD]


def _mock_squad(n=15):
    players = []
    for i in range(n):
        p = MagicMock()
        p.id = i
        p.web_name = f"Player{i}"
        p.position = POSITIONS[i % len(POSITIONS)]
        p.team_id = 1
        stats = MagicMock()
        stats.price = Decimal("7.5")
        stats.minutes = 270
        stats.status = "a"
        stats.chance_of_playing_next_round = None
        players.append((p, stats, 80.0))
    return players


def _mock_lineup(squad):
    xi = squad[:11]
    return {
        "starting_xi": xi,
        "bench_gk": squad[11],
        "bench_outfield": squad[12:],
        "total_score": 880.0,
    }


def _mock_captain_scored(xi):
    return xi


def _mock_rec():
    top = MagicMock()
    top.id = 0
    second = MagicMock()
    second.id = 1
    return {
        "top_pick": {"player": top, "rating": 90},
        "second_pick": {"player": second, "rating": 80},
        "advantage_pct": 12.5,
        "tie_broken_by_ceiling": False,
    }


def _mock_ctx():
    mock_db = AsyncMock()

    @asynccontextmanager
    async def mock_factory():
        yield mock_db

    return mock_factory


async def test_optimize_squad_happy_path(client, auth):
    squad = _mock_squad()
    with patch("app.api.v1.optimize.get_bootstrap_static", new=AsyncMock(return_value=MOCK_BS)), \
         patch("app.api.v1.optimize.build_optimal_squad", new=AsyncMock(return_value=squad)), \
         patch("app.api.v1.optimize.async_session_factory", new=_mock_ctx()), \
         patch("app.api.v1.optimize.get_planning_gameweek", new=AsyncMock(return_value=5)), \
         patch("app.api.v1.optimize.get_next_fixture_labels", new=AsyncMock(return_value={})), \
         patch("app.api.v1.optimize.get_gameweek_fixture_multipliers", new=AsyncMock(return_value={})), \
         patch("app.api.v1.optimize.predict_points", new=AsyncMock(return_value=squad)), \
         patch("app.api.v1.optimize.pick_best_starting_xi", return_value=_mock_lineup(squad)), \
         patch("app.api.v1.optimize.score_for_captaincy", new=AsyncMock(return_value=squad[:11])), \
         patch("app.api.v1.optimize.get_captain_recommendation", return_value=_mock_rec()):
        r = await client.get("/api/v1/optimize-squad", headers=auth, params={"budget": 100.0})

    assert r.status_code == 200
    data = r.json()
    assert len(data["players"]) == 15
    assert len(data["starting_xi"]) == 11
    assert len(data["bench"]) == 4
    assert "captain_id" in data
    assert "vice_captain_id" in data
    assert data["total_cost"] == pytest.approx(15 * 7.5)


async def test_optimize_squad_default_budget(client, auth):
    squad = _mock_squad()
    with patch("app.api.v1.optimize.get_bootstrap_static", new=AsyncMock(return_value=MOCK_BS)), \
         patch("app.api.v1.optimize.build_optimal_squad", new=AsyncMock(return_value=squad)) as mock, \
         patch("app.api.v1.optimize.async_session_factory", new=_mock_ctx()), \
         patch("app.api.v1.optimize.get_planning_gameweek", new=AsyncMock(return_value=5)), \
         patch("app.api.v1.optimize.get_next_fixture_labels", new=AsyncMock(return_value={})), \
         patch("app.api.v1.optimize.get_gameweek_fixture_multipliers", new=AsyncMock(return_value={})), \
         patch("app.api.v1.optimize.predict_points", new=AsyncMock(return_value=squad)), \
         patch("app.api.v1.optimize.pick_best_starting_xi", return_value=_mock_lineup(squad)), \
         patch("app.api.v1.optimize.score_for_captaincy", new=AsyncMock(return_value=squad[:11])), \
         patch("app.api.v1.optimize.get_captain_recommendation", return_value=_mock_rec()):
        await client.get("/api/v1/optimize-squad", headers=auth)
    mock.assert_awaited_once_with(budget=100.0)


async def test_optimize_squad_infeasible_budget_returns_422(client, auth):
    with patch("app.api.v1.optimize.get_bootstrap_static", new=AsyncMock(return_value=MOCK_BS)), \
         patch("app.api.v1.optimize.build_optimal_squad", new=AsyncMock(side_effect=InfeasibleBudgetError("budget too low"))):
        r = await client.get("/api/v1/optimize-squad", headers=auth, params={"budget": 10.0})

    assert r.status_code == 422
    assert "budget too low" in r.json()["detail"]

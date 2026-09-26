from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.services.squad_builder import get_budget_sensitivity


def _player(pid, pos=Position.MID, team_id=1):
    return Player(id=pid, team_id=team_id, first_name="F", second_name="L",
                  web_name=f"P{pid}", position=pos)


def _stats(pid, price="5.0"):
    return PlayerGameweekStats(
        player_id=pid, gameweek=5,
        pulled_at=datetime.now(timezone.utc),
        price=Decimal(price), form=Decimal("5.0"),
        total_points=50, minutes=450,
    )


def _squad(scores):
    return [(_player(i), _stats(i), sc) for i, sc in enumerate(scores, start=1)]


def _patch_builder(monkeypatch, squad_by_budget: dict):
    """
    Patches squad_builder dependencies so get_budget_sensitivity uses
    pre-defined squads for each budget level.
    """
    bs = {"events": [{"id": 5, "is_current": True}]}
    rows = [(_player(i), _stats(i)) for i in range(1, 20)]
    scored = [(_player(i), _stats(i), 5.0) for i in range(1, 20)]

    monkeypatch.setattr("app.services.squad_builder.get_bootstrap_static", AsyncMock(return_value=bs))
    monkeypatch.setattr("app.services.squad_builder.get_latest_stats", AsyncMock(return_value=rows))
    monkeypatch.setattr("app.services.squad_builder.filter_unavailable_players", lambda r: r)
    monkeypatch.setattr("app.services.squad_builder.filter_by_minimum_minutes", lambda r: r)
    monkeypatch.setattr("app.services.squad_builder.filter_by_recent_minutes", AsyncMock(return_value=rows))
    monkeypatch.setattr("app.services.squad_builder.get_planning_gameweek", AsyncMock(return_value=5))
    monkeypatch.setattr("app.services.squad_builder.get_fixture_counts_in_gameweek_window",
                        AsyncMock(return_value={1: 5}))
    monkeypatch.setattr("app.services.squad_builder.predict_points", AsyncMock(return_value=scored))

    def fake_optimize(scored_pool, budget):
        if budget in squad_by_budget:
            return squad_by_budget[budget]
        from app.services.optimizer import InfeasibleBudgetError
        raise InfeasibleBudgetError("too low")

    monkeypatch.setattr("app.services.squad_builder.optimize_squad", fake_optimize)


async def test_returns_one_entry_per_step(monkeypatch):
    squad_low  = _squad([5.0] * 15)
    squad_high = _squad([5.5] * 15)
    _patch_builder(monkeypatch, {100.0: squad_low, 100.5: squad_high})

    with patch("app.services.squad_builder.async_session_factory") as mf:
        db = AsyncMock()
        mf.return_value.__aenter__ = AsyncMock(return_value=db)
        mf.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await get_budget_sensitivity(base_budget=100.0, num_steps=2)

    assert len(result) == 2
    assert result[0]["budget"] == 100.0
    assert result[1]["budget"] == 100.5


async def test_marginal_gain_none_for_first_step(monkeypatch):
    squad = _squad([5.0] * 15)
    _patch_builder(monkeypatch, {100.0: squad, 100.5: squad})

    with patch("app.services.squad_builder.async_session_factory") as mf:
        db = AsyncMock()
        mf.return_value.__aenter__ = AsyncMock(return_value=db)
        mf.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await get_budget_sensitivity(base_budget=100.0, num_steps=2)

    assert result[0]["marginal_gain"] is None


async def test_marginal_gain_reflects_score_improvement(monkeypatch):
    squad_low  = _squad([5.0] * 15)
    squad_high = _squad([5.6] * 15)
    _patch_builder(monkeypatch, {100.0: squad_low, 100.5: squad_high})

    with patch("app.services.squad_builder.async_session_factory") as mf:
        db = AsyncMock()
        mf.return_value.__aenter__ = AsyncMock(return_value=db)
        mf.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await get_budget_sensitivity(base_budget=100.0, num_steps=2)

    assert result[1]["marginal_gain"] == pytest.approx(0.6, abs=0.01)


async def test_stops_early_on_infeasible_budget(monkeypatch):
    squad = _squad([5.0] * 15)
    _patch_builder(monkeypatch, {100.0: squad})  # 100.5 will raise InfeasibleBudgetError

    with patch("app.services.squad_builder.async_session_factory") as mf:
        db = AsyncMock()
        mf.return_value.__aenter__ = AsyncMock(return_value=db)
        mf.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await get_budget_sensitivity(base_budget=100.0, num_steps=3)

    assert len(result) == 1

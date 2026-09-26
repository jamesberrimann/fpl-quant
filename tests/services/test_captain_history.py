from unittest.mock import AsyncMock

import pytest

from app.services.captain_history import get_captain_accuracy


def _history(gws):
    return {"current": [{"event": gw, "points": 50} for gw in gws]}


def _picks(captain_id, other_ids):
    picks = [{"element": captain_id, "position": 1, "multiplier": 3}]
    for i, eid in enumerate(other_ids, start=2):
        picks.append({"element": eid, "position": i, "multiplier": 1})
    return {"picks": picks}


def _live(scores: dict[int, int]):
    return {"elements": [{"id": eid, "stats": {"total_points": pts}} for eid, pts in scores.items()]}


async def test_was_optimal_true_when_captain_scored_highest(monkeypatch):
    monkeypatch.setattr("app.services.captain_history.get_entry_history",
                        AsyncMock(return_value=_history([5])))
    monkeypatch.setattr("app.services.captain_history.get_entry_picks",
                        AsyncMock(return_value=_picks(10, [20, 30])))
    monkeypatch.setattr("app.services.captain_history.get_gameweek_live",
                        AsyncMock(return_value=_live({10: 12, 20: 6, 30: 8})))

    result = await get_captain_accuracy(entry_id=1, num_gameweeks=1)
    assert len(result) == 1
    assert result[0]["was_optimal"] is True
    assert result[0]["regret_pts"] == 0


async def test_was_optimal_false_when_better_scorer_existed(monkeypatch):
    monkeypatch.setattr("app.services.captain_history.get_entry_history",
                        AsyncMock(return_value=_history([5])))
    monkeypatch.setattr("app.services.captain_history.get_entry_picks",
                        AsyncMock(return_value=_picks(10, [20, 30])))
    monkeypatch.setattr("app.services.captain_history.get_gameweek_live",
                        AsyncMock(return_value=_live({10: 6, 20: 6, 30: 14})))

    result = await get_captain_accuracy(entry_id=1, num_gameweeks=1)
    assert result[0]["was_optimal"] is False
    assert result[0]["optimal_id"] == 30
    assert result[0]["regret_pts"] == 8   # 14 - 6


async def test_regret_zero_when_all_players_tie(monkeypatch):
    monkeypatch.setattr("app.services.captain_history.get_entry_history",
                        AsyncMock(return_value=_history([5])))
    monkeypatch.setattr("app.services.captain_history.get_entry_picks",
                        AsyncMock(return_value=_picks(10, [20])))
    monkeypatch.setattr("app.services.captain_history.get_gameweek_live",
                        AsyncMock(return_value=_live({10: 8, 20: 8})))

    result = await get_captain_accuracy(entry_id=1, num_gameweeks=1)
    assert result[0]["regret_pts"] == 0


async def test_multiple_gameweeks_returns_correct_count(monkeypatch):
    picks = _picks(10, [20])
    live = _live({10: 8, 20: 6})
    monkeypatch.setattr("app.services.captain_history.get_entry_history",
                        AsyncMock(return_value=_history([3, 4, 5])))
    monkeypatch.setattr("app.services.captain_history.get_entry_picks",
                        AsyncMock(return_value=picks))
    monkeypatch.setattr("app.services.captain_history.get_gameweek_live",
                        AsyncMock(return_value=live))

    result = await get_captain_accuracy(entry_id=1, num_gameweeks=3)
    assert len(result) == 3


async def test_lookback_limited_to_num_gameweeks(monkeypatch):
    """With 10 GWs played but num_gameweeks=2, only last 2 are returned."""
    picks = _picks(10, [20])
    live = _live({10: 8, 20: 6})
    monkeypatch.setattr("app.services.captain_history.get_entry_history",
                        AsyncMock(return_value=_history(list(range(1, 11)))))
    monkeypatch.setattr("app.services.captain_history.get_entry_picks",
                        AsyncMock(return_value=picks))
    monkeypatch.setattr("app.services.captain_history.get_gameweek_live",
                        AsyncMock(return_value=live))

    result = await get_captain_accuracy(entry_id=1, num_gameweeks=2)
    assert len(result) == 2
    assert result[0]["gameweek"] == 9
    assert result[1]["gameweek"] == 10

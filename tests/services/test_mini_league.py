from unittest.mock import AsyncMock

import pytest

from app.services.mini_league import get_mini_league_context


def _entry(entry_id, leagues):
    return {"leagues": {"classic": leagues}}


def _standings(rows):
    return {"standings": {"results": rows}}


def _row(entry_id, name, rank, pts):
    return {"entry": entry_id, "entry_name": name, "rank": rank, "total": pts}


async def test_returns_league_with_correct_rank_and_gap(monkeypatch):
    entry_id = 42
    leagues = [{"id": 1000, "name": "Work League", "entry_count": 10}]
    rows = [
        _row(99, "Leader",   1, 1500),
        _row(entry_id, "Me", 2, 1450),
        _row(88, "Rival",    3, 1430),
    ]
    monkeypatch.setattr("app.services.mini_league.get_entry_details",
                        AsyncMock(return_value=_entry(entry_id, leagues)))
    monkeypatch.setattr("app.services.mini_league.get_league_standings",
                        AsyncMock(return_value=_standings(rows)))

    result = await get_mini_league_context(entry_id)
    assert len(result) == 1
    lg = result[0]
    assert lg["entry_rank"] == 2
    assert lg["gap_to_leader"] == 50
    assert lg["leader_name"] == "Leader"


async def test_global_leagues_excluded(monkeypatch):
    entry_id = 42
    leagues = [
        {"id": 314, "name": "Overall",      "entry_count": 10_000_000},
        {"id": 999, "name": "Mini League",  "entry_count": 5},
    ]
    rows = [
        _row(entry_id, "Me", 1, 1500),
    ]
    monkeypatch.setattr("app.services.mini_league.get_entry_details",
                        AsyncMock(return_value=_entry(entry_id, leagues)))
    monkeypatch.setattr("app.services.mini_league.get_league_standings",
                        AsyncMock(return_value=_standings(rows)))

    result = await get_mini_league_context(entry_id)
    assert len(result) == 1
    assert result[0]["league_name"] == "Mini League"


async def test_rivals_exclude_self(monkeypatch):
    entry_id = 42
    leagues = [{"id": 1000, "name": "L", "entry_count": 5}]
    rows = [
        _row(1,        "P1", 1, 1600),
        _row(entry_id, "Me", 2, 1500),
        _row(3,        "P3", 3, 1400),
    ]
    monkeypatch.setattr("app.services.mini_league.get_entry_details",
                        AsyncMock(return_value=_entry(entry_id, leagues)))
    monkeypatch.setattr("app.services.mini_league.get_league_standings",
                        AsyncMock(return_value=_standings(rows)))

    result = await get_mini_league_context(entry_id)
    rival_ids = [r["manager"] for r in result[0]["rivals"]]
    assert "Me" not in rival_ids


async def test_gap_to_leader_zero_when_leading(monkeypatch):
    entry_id = 42
    leagues = [{"id": 1000, "name": "L", "entry_count": 3}]
    rows = [
        _row(entry_id, "Me",   1, 1600),
        _row(99,       "P2",   2, 1500),
    ]
    monkeypatch.setattr("app.services.mini_league.get_entry_details",
                        AsyncMock(return_value=_entry(entry_id, leagues)))
    monkeypatch.setattr("app.services.mini_league.get_league_standings",
                        AsyncMock(return_value=_standings(rows)))

    result = await get_mini_league_context(entry_id)
    assert result[0]["gap_to_leader"] == 0

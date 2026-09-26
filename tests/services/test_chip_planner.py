"""
Tests for chip_planner.py.

All tests mock get_all_gameweek_fixture_info_in_range so no real DB is needed.
GWs not specified in the mapping default to count=1.0, difficulty=3.0 (normal fixture,
average difficulty) for all team_ids.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.models.player import Position
from app.services.chip_planner import get_chip_windows

_DEFAULT_DIFFICULTY = 3.0


def _player(team_id, score, pos=Position.MID, name="P"):
    return {"team_id": team_id, "score": score, "position": pos, "web_name": name}


def _info(mapping: dict):
    """mapping: {gw: {team_id: {"count": float, "difficulty": float}}}.

    Unspecified GWs default to count=1.0, difficulty=3.0 for all teams.
    """
    async def fake(db, team_ids, from_gw, to_gw):
        result = {}
        for gw in range(from_gw, to_gw + 1):
            if gw in mapping:
                result[gw] = mapping[gw]
            else:
                result[gw] = {tid: {"count": 1.0, "difficulty": _DEFAULT_DIFFICULTY} for tid in team_ids}
        return result
    return fake


# ── Empty squad ───────────────────────────────────────────────────────────────

async def test_empty_squad_returns_nones():
    result = await get_chip_windows(AsyncMock(), [], current_gameweek=5)
    assert result["triple_captain"] is None
    assert result["bench_boost"] is None
    assert result["free_hit"] == []
    assert result["wildcard"] is None


# ── Triple Captain ─────────────────────────────────────────────────────────────

async def test_triple_captain_never_recommends_current_gameweek():
    # GW5 is current — TC scan starts at GW6, so GW5 must never appear
    players = [_player(team_id=1, score=8.0, name="Salah")]

    with patch("app.services.chip_planner.get_all_gameweek_fixture_info_in_range", side_effect=_info({})):
        result = await get_chip_windows(AsyncMock(), players, current_gameweek=5)

    tc = result["triple_captain"]
    assert tc is not None
    assert tc["gameweek"] > 5


async def test_triple_captain_picks_dgw_over_single_fixture():
    # DGW in GW10, normal everywhere else — GW10 must win
    players = [_player(team_id=1, score=8.0, name="Salah")]
    info = {10: {1: {"count": 2.0, "difficulty": 3.0}}}

    with patch("app.services.chip_planner.get_all_gameweek_fixture_info_in_range", side_effect=_info(info)):
        result = await get_chip_windows(AsyncMock(), players, current_gameweek=5)

    tc = result["triple_captain"]
    assert tc["gameweek"] == 10
    assert tc["is_dgw"] is True
    assert "Salah" in tc["reason"]


async def test_triple_captain_prefers_easy_fixture_over_hard_among_singles():
    # GW6 difficulty=5 (hard), GW20 difficulty=1 (easy) — both single fixtures
    # GW20 should win via difficulty tiebreak
    players = [_player(team_id=1, score=8.0, name="Salah")]
    info = {
        6:  {1: {"count": 1.0, "difficulty": 5.0}},
        20: {1: {"count": 1.0, "difficulty": 1.0}},
    }

    with patch("app.services.chip_planner.get_all_gameweek_fixture_info_in_range", side_effect=_info(info)):
        result = await get_chip_windows(AsyncMock(), players, current_gameweek=5)

    assert result["triple_captain"]["gameweek"] == 20


async def test_triple_captain_ignores_blank_gameweek():
    # GW7 is BGW — should be skipped, scan continues to GW8+
    players = [_player(team_id=1, score=8.0, name="Salah")]
    info = {7: {1: {"count": 0.0, "difficulty": 3.0}}}

    with patch("app.services.chip_planner.get_all_gameweek_fixture_info_in_range", side_effect=_info(info)):
        result = await get_chip_windows(AsyncMock(), players, current_gameweek=5)

    assert result["triple_captain"]["gameweek"] != 7


async def test_triple_captain_dgw_beats_easy_single():
    # DGW at avg difficulty vs very easy single — DGW wins (count=2 > count=1)
    players = [_player(team_id=1, score=8.0, name="Salah")]
    info = {
        10: {1: {"count": 2.0, "difficulty": 3.0}},
        20: {1: {"count": 1.0, "difficulty": 1.0}},
    }

    with patch("app.services.chip_planner.get_all_gameweek_fixture_info_in_range", side_effect=_info(info)):
        result = await get_chip_windows(AsyncMock(), players, current_gameweek=5)

    tc = result["triple_captain"]
    assert tc["gameweek"] == 10
    assert tc["is_dgw"] is True


async def test_triple_captain_top_player_with_dgw_beats_higher_scored_player_without():
    # Player A (score 10) single fixture; Player B (score 6) DGW
    # Count wins over raw score — B's DGW should be recommended
    players = [
        _player(team_id=1, score=10.0, name="PlayerA"),
        _player(team_id=2, score=6.0,  name="PlayerB"),
    ]
    info = {10: {1: {"count": 1.0, "difficulty": 3.0}, 2: {"count": 2.0, "difficulty": 3.0}}}

    with patch("app.services.chip_planner.get_all_gameweek_fixture_info_in_range", side_effect=_info(info)):
        result = await get_chip_windows(AsyncMock(), players, current_gameweek=5)

    tc = result["triple_captain"]
    assert tc["gameweek"] == 10
    assert "PlayerB" in tc["best_player_name"]


# ── Bench Boost ───────────────────────────────────────────────────────────────

async def test_bench_boost_picks_gw_with_most_dgw_teams():
    players = [_player(team_id=i, score=5.0) for i in range(1, 6)]
    info = {6: {1: {"count": 2.0, "difficulty": 3.0}, 2: {"count": 2.0, "difficulty": 3.0},
                3: {"count": 2.0, "difficulty": 3.0}, 4: {"count": 2.0, "difficulty": 3.0},
                5: {"count": 1.0, "difficulty": 3.0}}}

    with patch("app.services.chip_planner.get_all_gameweek_fixture_info_in_range", side_effect=_info(info)):
        result = await get_chip_windows(AsyncMock(), players, current_gameweek=5)

    bb = result["bench_boost"]
    assert bb is not None
    assert bb["gameweek"] == 6
    assert bb["dgw_count"] == 4


async def test_bench_boost_present_when_below_threshold():
    # Only 2 DGW teams — below _BB_DGW_THRESHOLD=3, still returned with caveat
    players = [_player(team_id=i, score=5.0) for i in range(1, 4)]
    info = {6: {1: {"count": 2.0, "difficulty": 3.0}, 2: {"count": 2.0, "difficulty": 3.0},
                3: {"count": 1.0, "difficulty": 3.0}}}

    with patch("app.services.chip_planner.get_all_gameweek_fixture_info_in_range", side_effect=_info(info)):
        result = await get_chip_windows(AsyncMock(), players, current_gameweek=5)

    bb = result["bench_boost"]
    assert bb is not None
    assert "consider waiting" in bb["reason"]


# ── Free Hit ─────────────────────────────────────────────────────────────────

async def test_free_hit_flags_gw_with_many_blanks():
    players = [_player(team_id=i, score=5.0) for i in range(1, 9)]
    info = {6: {
        1: {"count": 0.0, "difficulty": 3.0}, 2: {"count": 0.0, "difficulty": 3.0},
        3: {"count": 0.0, "difficulty": 3.0}, 4: {"count": 0.0, "difficulty": 3.0},
        5: {"count": 0.0, "difficulty": 3.0}, 6: {"count": 0.0, "difficulty": 3.0},
        7: {"count": 1.0, "difficulty": 3.0}, 8: {"count": 1.0, "difficulty": 3.0},
    }}

    with patch("app.services.chip_planner.get_all_gameweek_fixture_info_in_range", side_effect=_info(info)):
        result = await get_chip_windows(AsyncMock(), players, current_gameweek=5)

    fh = result["free_hit"]
    assert any(w["gameweek"] == 6 for w in fh)
    assert next(w for w in fh if w["gameweek"] == 6)["blank_count"] == 6


async def test_free_hit_empty_when_no_blanks():
    players = [_player(team_id=i, score=5.0) for i in range(1, 6)]

    with patch("app.services.chip_planner.get_all_gameweek_fixture_info_in_range", side_effect=_info({})):
        result = await get_chip_windows(AsyncMock(), players, current_gameweek=5)

    assert result["free_hit"] == []


# ── Wildcard ─────────────────────────────────────────────────────────────────

async def test_wildcard_flagged_before_difficulty_spike():
    players = [_player(team_id=i, score=5.0) for i in range(1, 4)]
    info = {6: {i: {"count": 0.5, "difficulty": 3.0} for i in range(1, 4)}}

    with patch("app.services.chip_planner.get_all_gameweek_fixture_info_in_range", side_effect=_info(info)):
        result = await get_chip_windows(AsyncMock(), players, current_gameweek=5)

    wc = result["wildcard"]
    assert wc is not None
    assert wc["gameweek"] == 5


async def test_wildcard_none_when_no_spike():
    players = [_player(team_id=1, score=5.0)]

    with patch("app.services.chip_planner.get_all_gameweek_fixture_info_in_range", side_effect=_info({})):
        result = await get_chip_windows(AsyncMock(), players, current_gameweek=5)

    assert result["wildcard"] is None

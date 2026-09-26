"""
Tests for rotation_risk.py

compute_rotation_risk  — pure function, no DB
get_rotation_risk_scores — async, single execute call returning rows with
                           (player_id, gameweek, minutes_this_gw) attributes
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rotation_risk import (
    ROTATION_RISK_THRESHOLD,
    compute_rotation_risk,
    get_rotation_risk_scores,
)


# ── compute_rotation_risk ─────────────────────────────────────────────────────

def test_empty_minutes_returns_zero():
    assert compute_rotation_risk([]) == 0.0


def test_full_90_always_returns_zero():
    assert compute_rotation_risk([90, 90, 90]) == pytest.approx(0.0)


def test_never_plays_returns_one():
    assert compute_rotation_risk([0, 0, 0]) == pytest.approx(1.0)


def test_single_gw_full_game():
    # Only one data point — weights [3]; avg = 90 → risk = 0.0
    assert compute_rotation_risk([90]) == pytest.approx(0.0)


def test_single_gw_zero_minutes():
    assert compute_rotation_risk([0]) == pytest.approx(1.0)


def test_two_gw_average():
    # weights [3, 2]; weighted = (60*3 + 90*2) / 5 = (180+180)/5 = 72; risk = 1 - 72/90 = 0.2
    assert compute_rotation_risk([60, 90]) == pytest.approx(0.2)


def test_three_gw_weighted_newest_first():
    # weights [3, 2, 1]; (90*3 + 45*2 + 0*1) / 6 = (270+90)/6 = 60; risk = 1 - 60/90 = 1/3
    assert compute_rotation_risk([90, 45, 0]) == pytest.approx(1 / 3, rel=1e-4)


def test_only_first_three_gws_used():
    # Extra entries beyond _LOOKBACK=3 are ignored
    assert compute_rotation_risk([90, 90, 90, 0, 0]) == pytest.approx(0.0)


def test_score_clamped_above_zero():
    # Technically can't exceed [0,1] but guard is there
    assert compute_rotation_risk([0]) >= 0.0
    assert compute_rotation_risk([0]) <= 1.0


def test_rotation_risk_threshold_flags_sub_60_average():
    # threshold=0.35 → flagged when avg < (1-0.35)*90 = 58.5 min/game
    # 55-min average: risk = 1 - 55/90 ≈ 0.389 → should be flagged
    risk_55_avg = compute_rotation_risk([55, 55, 55])
    assert risk_55_avg >= ROTATION_RISK_THRESHOLD
    # 60-min average: risk ≈ 0.333 → below threshold, not flagged
    risk_60_avg = compute_rotation_risk([60, 60, 60])
    assert risk_60_avg < ROTATION_RISK_THRESHOLD


def test_rotation_risk_threshold_not_flagged_for_90_min():
    assert compute_rotation_risk([90, 90, 90]) < ROTATION_RISK_THRESHOLD


# ── get_rotation_risk_scores ──────────────────────────────────────────────────

def _row(player_id, gameweek, minutes_this_gw):
    r = MagicMock()
    r.player_id = player_id
    r.gameweek = gameweek
    r.minutes_this_gw = minutes_this_gw
    return r


def _db(rows):
    result = MagicMock()
    result.all.return_value = rows
    session = AsyncMock()
    session.execute.return_value = result
    return session


async def test_empty_player_ids_returns_empty():
    db = AsyncMock()
    result = await get_rotation_risk_scores(db, set(), current_gameweek=5)
    assert result == {}
    db.execute.assert_not_called()


async def test_gw1_returns_zeros_without_querying():
    db = AsyncMock()
    result = await get_rotation_risk_scores(db, {1, 2}, current_gameweek=1)
    assert result == {1: 0.0, 2: 0.0}
    db.execute.assert_not_called()


async def test_no_rows_returns_zeros():
    db = _db([])
    result = await get_rotation_risk_scores(db, {10}, current_gameweek=5)
    assert result == {10: pytest.approx(0.0)}


async def test_full_90_three_gws_gives_zero_risk():
    rows = [
        _row(1, 4, 90),
        _row(1, 3, 90),
        _row(1, 2, 90),
    ]
    db = _db(rows)
    result = await get_rotation_risk_scores(db, {1}, current_gameweek=5)
    assert result[1] == pytest.approx(0.0)


async def test_zero_minutes_three_gws_gives_max_risk():
    rows = [
        _row(1, 4, 0),
        _row(1, 3, 0),
        _row(1, 2, 0),
    ]
    db = _db(rows)
    result = await get_rotation_risk_scores(db, {1}, current_gameweek=5)
    assert result[1] == pytest.approx(1.0)


async def test_partial_minutes_computes_weighted_risk():
    # GW4=60 (weight 3), GW3=90 (weight 2), GW2=0 (weight 1)
    # avg = (60*3 + 90*2 + 0*1) / 6 = 360/6 = 60 → risk = 1/3
    rows = [
        _row(1, 4, 60),
        _row(1, 3, 90),
        _row(1, 2, 0),
    ]
    db = _db(rows)
    result = await get_rotation_risk_scores(db, {1}, current_gameweek=5)
    assert result[1] == pytest.approx(1 / 3, rel=1e-4)


async def test_multiple_players_computed_independently():
    rows = [
        _row(1, 4, 90), _row(1, 3, 90), _row(1, 2, 90),
        _row(2, 4, 0),  _row(2, 3, 0),  _row(2, 2, 0),
    ]
    db = _db(rows)
    result = await get_rotation_risk_scores(db, {1, 2}, current_gameweek=5)
    assert result[1] == pytest.approx(0.0)
    assert result[2] == pytest.approx(1.0)


async def test_player_with_no_rows_gets_zero():
    # Player 99 has no data rows — should default to 0.0, not KeyError
    rows = [_row(1, 4, 90)]
    db = _db(rows)
    result = await get_rotation_risk_scores(db, {1, 99}, current_gameweek=5)
    assert result[99] == pytest.approx(0.0)


async def test_only_lookback_gws_are_used():
    # GW2 is outside the 3-GW lookback window (current=6, lookback from GW3)
    # So GW2 row should be excluded; player played 90 in GW3-5 → risk 0.0
    rows = [
        _row(1, 5, 90),
        _row(1, 4, 90),
        _row(1, 3, 90),
        # GW2 would be outside the query window — the service excludes it
    ]
    db = _db(rows)
    result = await get_rotation_risk_scores(db, {1}, current_gameweek=6)
    assert result[1] == pytest.approx(0.0)

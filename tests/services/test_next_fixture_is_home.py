"""
Tests for get_next_fixture_is_home in fixtures.py.

Uses the same mock pattern as test_fixture_heatmap.py — no real DB required.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.fixture import Fixture
from app.services.fixtures import get_next_fixture_is_home


def _fix(id, gw, home_id, away_id, finished=False, score=None):
    return Fixture(
        id=id, gameweek=gw,
        team_h_id=home_id, team_a_id=away_id,
        team_h_difficulty=3, team_a_difficulty=2,
        team_h_score=score, team_a_score=score,
        finished=finished,
    )


def _db(fixtures):
    result = MagicMock()
    result.scalars.return_value.all.return_value = fixtures
    session = AsyncMock()
    session.execute.return_value = result
    return session


# ── Basic cases ───────────────────────────────────────────────────────────────

async def test_empty_team_ids_returns_empty_without_querying():
    db = AsyncMock()
    result = await get_next_fixture_is_home(db, set(), from_gameweek=5)
    assert result == {}
    db.execute.assert_not_called()


async def test_home_team_returns_true():
    db = _db([_fix(1, gw=5, home_id=10, away_id=20)])
    result = await get_next_fixture_is_home(db, {10}, from_gameweek=5)
    assert result[10] is True


async def test_away_team_returns_false():
    db = _db([_fix(1, gw=5, home_id=10, away_id=20)])
    result = await get_next_fixture_is_home(db, {20}, from_gameweek=5)
    assert result[20] is False


async def test_both_teams_in_same_fixture():
    db = _db([_fix(1, gw=5, home_id=10, away_id=20)])
    result = await get_next_fixture_is_home(db, {10, 20}, from_gameweek=5)
    assert result[10] is True
    assert result[20] is False


async def test_team_with_no_fixture_is_absent():
    # Team 99 has no upcoming fixture — should not appear in result (blank GW)
    db = _db([_fix(1, gw=5, home_id=10, away_id=20)])
    result = await get_next_fixture_is_home(db, {10, 99}, from_gameweek=5)
    assert result[10] is True
    assert 99 not in result


async def test_dgw_returns_is_home_for_first_fixture():
    # Team 10 has two fixtures in GW5 (DGW): home vs 20, away vs 30.
    # The first encountered should be recorded (GW5, first row).
    db = _db([
        _fix(1, gw=5, home_id=10, away_id=20),
        _fix(2, gw=5, home_id=30, away_id=10),
    ])
    result = await get_next_fixture_is_home(db, {10}, from_gameweek=5)
    # First fixture encountered: team 10 is home → True
    assert result[10] is True


async def test_fixture_in_earlier_gw_takes_priority():
    # GW5 fixture exists — GW6 should not override it.
    db = _db([
        _fix(1, gw=5, home_id=10, away_id=20),
        _fix(2, gw=6, home_id=30, away_id=10),  # away in GW6
    ])
    result = await get_next_fixture_is_home(db, {10}, from_gameweek=5)
    assert result[10] is True  # GW5 home, not GW6 away


async def test_multiple_teams_independent():
    db = _db([
        _fix(1, gw=5, home_id=1, away_id=2),
        _fix(2, gw=5, home_id=3, away_id=4),
    ])
    result = await get_next_fixture_is_home(db, {1, 2, 3, 4}, from_gameweek=5)
    assert result[1] is True
    assert result[2] is False
    assert result[3] is True
    assert result[4] is False


async def test_no_fixtures_returns_empty_dict():
    db = _db([])
    result = await get_next_fixture_is_home(db, {10, 20}, from_gameweek=5)
    assert result == {}

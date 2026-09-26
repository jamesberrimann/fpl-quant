"""
Tests for get_fixture_heatmap.

All tests mock the DB — two execute calls:
  1st: returns Fixture rows for the requested window
  2nd: returns Team rows for opponent short names (skipped when no fixtures found)
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.fixture import Fixture
from app.models.team import Team
from app.services.fixture_heatmap import FixtureOpponent, GWFixtureSlot, get_fixture_heatmap


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fix(id, gw, home_id, away_id, home_fdr=2, away_fdr=4):
    return Fixture(
        id=id, gameweek=gw,
        team_h_id=home_id, team_a_id=away_id,
        team_h_difficulty=home_fdr, team_a_difficulty=away_fdr,
        team_h_score=None, team_a_score=None, finished=False,
    )


def _team(id, short_name):
    return Team(
        id=id, name=short_name, short_name=short_name,
        strength_overall_home=0, strength_overall_away=0,
        strength_attack_home=0, strength_attack_away=0,
        strength_defence_home=0, strength_defence_away=0,
    )


def _db(fixtures, teams=None):
    """AsyncSession mock: 1st execute → fixtures, 2nd execute → teams."""
    def _result(objects):
        r = MagicMock()
        r.scalars.return_value.all.return_value = objects
        return r

    session = AsyncMock()
    session.execute.side_effect = [
        _result(fixtures),
        _result(teams or []),
    ]
    return session


# ── Core behaviour ────────────────────────────────────────────────────────────

async def test_empty_team_ids_returns_empty_without_querying_db():
    db = AsyncMock()
    result = await get_fixture_heatmap(db, set(), from_gameweek=5, num_gameweeks=3)
    assert result == {}
    db.execute.assert_not_called()


async def test_result_covers_exactly_num_gameweeks():
    db = _db(fixtures=[], teams=[])
    result = await get_fixture_heatmap(db, {1}, from_gameweek=5, num_gameweeks=6)
    assert len(result[1]) == 6


async def test_slots_ordered_ascending_by_gameweek():
    db = _db(fixtures=[], teams=[])
    result = await get_fixture_heatmap(db, {1}, from_gameweek=3, num_gameweeks=4)
    gws = [s.gameweek for s in result[1]]
    assert gws == [3, 4, 5, 6]


# ── Blank gameweeks ───────────────────────────────────────────────────────────

async def test_blank_gameweek_has_no_opponents():
    # Team 1 has no fixture in GW5 — blank should appear as empty slot
    db = _db(fixtures=[], teams=[])
    result = await get_fixture_heatmap(db, {1}, from_gameweek=5, num_gameweeks=1)
    slot = result[1][0]
    assert slot.gameweek == 5
    assert slot.is_blank is True
    assert slot.opponents == []
    assert slot.avg_fdr is None


async def test_blank_gameweek_skips_team_db_query():
    """No fixtures → no opponent IDs → second DB query (team names) never called."""
    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = []
    session.execute.return_value = execute_result

    await get_fixture_heatmap(session, {1}, from_gameweek=5, num_gameweeks=1)
    assert session.execute.call_count == 1


# ── Home fixture ──────────────────────────────────────────────────────────────

async def test_home_fixture_opponent_identified_correctly():
    # Arsenal (1) hosts Chelsea (2) in GW5 — from Arsenal's perspective: home, FDR=home_fdr
    fix = _fix(1, gw=5, home_id=1, away_id=2, home_fdr=2, away_fdr=4)
    chelsea = _team(2, "CHE")

    result = await get_fixture_heatmap(_db([fix], [chelsea]), {1}, from_gameweek=5, num_gameweeks=1)
    slot = result[1][0]

    assert not slot.is_blank
    assert len(slot.opponents) == 1
    opp = slot.opponents[0]
    assert opp.team_id == 2
    assert opp.short_name == "CHE"
    assert opp.is_home is True
    assert opp.fdr == 2  # team_h_difficulty


async def test_home_fdr_comes_from_team_h_difficulty():
    fix = _fix(1, gw=5, home_id=1, away_id=2, home_fdr=1, away_fdr=5)
    db = _db([fix], [_team(2, "CHE")])
    result = await get_fixture_heatmap(db, {1}, from_gameweek=5, num_gameweeks=1)
    assert result[1][0].opponents[0].fdr == 1


# ── Away fixture ──────────────────────────────────────────────────────────────

async def test_away_fixture_is_home_false():
    # Arsenal (1) travels to Chelsea (2) — from Arsenal's perspective: away, FDR=away_fdr
    fix = _fix(1, gw=5, home_id=2, away_id=1, home_fdr=4, away_fdr=2)
    chelsea = _team(2, "CHE")

    result = await get_fixture_heatmap(_db([fix], [chelsea]), {1}, from_gameweek=5, num_gameweeks=1)
    opp = result[1][0].opponents[0]

    assert opp.is_home is False
    assert opp.fdr == 2  # team_a_difficulty
    assert opp.team_id == 2


async def test_away_fdr_comes_from_team_a_difficulty():
    fix = _fix(1, gw=5, home_id=2, away_id=1, home_fdr=5, away_fdr=1)
    db = _db([fix], [_team(2, "CHE")])
    result = await get_fixture_heatmap(db, {1}, from_gameweek=5, num_gameweeks=1)
    assert result[1][0].opponents[0].fdr == 1


# ── Double gameweek ───────────────────────────────────────────────────────────

async def test_dgw_slot_contains_two_opponents():
    fix1 = _fix(1, gw=5, home_id=1, away_id=2, home_fdr=2, away_fdr=3)
    fix2 = _fix(2, gw=5, home_id=3, away_id=1, home_fdr=4, away_fdr=3)
    teams = [_team(2, "CHE"), _team(3, "MCI")]

    result = await get_fixture_heatmap(_db([fix1, fix2], teams), {1}, from_gameweek=5, num_gameweeks=1)
    slot = result[1][0]

    assert slot.is_double is True
    assert len(slot.opponents) == 2


async def test_dgw_avg_fdr_is_mean_of_both_fixtures():
    # Arsenal (1): home vs CHE (FDR=2), away at MCI (FDR=5)
    fix1 = _fix(1, gw=5, home_id=1, away_id=2, home_fdr=2, away_fdr=3)
    fix2 = _fix(2, gw=5, home_id=3, away_id=1, home_fdr=4, away_fdr=5)
    teams = [_team(2, "CHE"), _team(3, "MCI")]

    result = await get_fixture_heatmap(_db([fix1, fix2], teams), {1}, from_gameweek=5, num_gameweeks=1)
    slot = result[1][0]

    # home FDR=2, away FDR=5 → avg = 3.5
    assert slot.avg_fdr == pytest.approx(3.5)


async def test_dgw_is_not_blank():
    fix1 = _fix(1, gw=5, home_id=1, away_id=2, home_fdr=2, away_fdr=3)
    fix2 = _fix(2, gw=5, home_id=3, away_id=1, home_fdr=4, away_fdr=2)
    teams = [_team(2, "CHE"), _team(3, "MCI")]

    result = await get_fixture_heatmap(_db([fix1, fix2], teams), {1}, from_gameweek=5, num_gameweeks=1)
    assert result[1][0].is_blank is False


# ── GWFixtureSlot properties ──────────────────────────────────────────────────

def test_slot_is_blank_no_opponents():
    slot = GWFixtureSlot(gameweek=5, opponents=[])
    assert slot.is_blank is True
    assert slot.is_double is False
    assert slot.avg_fdr is None


def test_slot_is_not_blank_with_one_opponent():
    slot = GWFixtureSlot(gameweek=5, opponents=[FixtureOpponent(1, "CHE", True, 3)])
    assert slot.is_blank is False
    assert slot.avg_fdr == 3.0


def test_slot_is_double_with_two_opponents():
    slot = GWFixtureSlot(gameweek=5, opponents=[
        FixtureOpponent(1, "CHE", True, 2),
        FixtureOpponent(2, "MCI", False, 4),
    ])
    assert slot.is_double is True
    assert slot.avg_fdr == pytest.approx(3.0)


# ── Multi-team / multi-gameweek ───────────────────────────────────────────────

async def test_multiple_teams_each_get_own_heatmap():
    # Arsenal (1) hosts Chelsea (2) in GW5; Chelsea travels to Arsenal in GW5
    fix = _fix(1, gw=5, home_id=1, away_id=2, home_fdr=2, away_fdr=3)
    teams = [_team(1, "ARS"), _team(2, "CHE")]

    result = await get_fixture_heatmap(_db([fix], teams), {1, 2}, from_gameweek=5, num_gameweeks=1)

    assert 1 in result and 2 in result
    # Arsenal sees Chelsea as opponent, is_home=True
    ars_opp = result[1][0].opponents[0]
    assert ars_opp.short_name == "CHE"
    assert ars_opp.is_home is True
    # Chelsea sees Arsenal as opponent, is_home=False
    che_opp = result[2][0].opponents[0]
    assert che_opp.short_name == "ARS"
    assert che_opp.is_home is False


async def test_blank_and_fixture_gw_in_same_window():
    """GW5: fixture; GW6: blank. Both appear in the 2-GW window."""
    fix = _fix(1, gw=5, home_id=1, away_id=2, home_fdr=2, away_fdr=3)
    db = _db([fix], [_team(2, "CHE")])

    result = await get_fixture_heatmap(db, {1}, from_gameweek=5, num_gameweeks=2)
    slots = result[1]

    assert len(slots) == 2
    assert slots[0].gameweek == 5
    assert not slots[0].is_blank
    assert slots[1].gameweek == 6
    assert slots[1].is_blank


async def test_fixture_with_null_gameweek_is_ignored():
    """Fixtures with gameweek=None (unscheduled cup ties etc.) must not appear."""
    unscheduled = _fix(1, gw=None, home_id=1, away_id=2)
    unscheduled.gameweek = None
    db = _db([unscheduled], [])

    result = await get_fixture_heatmap(db, {1}, from_gameweek=5, num_gameweeks=1)
    assert result[1][0].is_blank is True


async def test_unknown_opponent_gets_placeholder_short_name():
    """If a team isn't in the DB for some reason, show ??? rather than crashing."""
    fix = _fix(1, gw=5, home_id=1, away_id=99)
    # No team row for id=99
    db = _db([fix], [])

    result = await get_fixture_heatmap(db, {1}, from_gameweek=5, num_gameweeks=1)
    opp = result[1][0].opponents[0]
    assert opp.short_name == "???"

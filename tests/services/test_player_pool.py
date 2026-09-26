from app.services.player_pool import apply_starter_risk_adjustment
from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from decimal import Decimal
from datetime import datetime, timezone


def make_entry(id, score, team_id=9001):
    player = Player(id=id, team_id=team_id, first_name="F", second_name="L", web_name=f"P{id}", position=Position.MID)
    stats = PlayerGameweekStats(
        player_id=id, gameweek=3, pulled_at=datetime.now(timezone.utc),
        price=Decimal("5.0"), form=Decimal("5.0"), ownership_pct=Decimal("10.0"),
        total_points=10, minutes=270,
    )
    return (player, stats, score)


def test_full_minutes_no_penalty():
    entry = make_entry(1, 0.8)
    adjusted = apply_starter_risk_adjustment(
        [entry], minutes_by_player_id={1: 90}, started_by_team_id={9001: True}
    )
    assert adjusted[0][2] == 0.8


def test_partial_minutes_penalty():
    entry = make_entry(2, 0.8)
    adjusted = apply_starter_risk_adjustment(
        [entry], minutes_by_player_id={2: 20}, started_by_team_id={9001: True}
    )
    assert adjusted[0][2] == 0.8 * 0.7


def test_zero_minutes_heavy_penalty():
    entry = make_entry(3, 0.8)
    adjusted = apply_starter_risk_adjustment(
        [entry], minutes_by_player_id={3: 0}, started_by_team_id={9001: True}
    )
    assert adjusted[0][2] == 0.8 * 0.3


def test_missing_from_live_data_treated_as_zero_minutes():
    entry = make_entry(4, 0.8)
    adjusted = apply_starter_risk_adjustment(
        [entry], minutes_by_player_id={}, started_by_team_id={9001: True}
    )
    assert adjusted[0][2] == 0.8 * 0.3


def test_match_not_started_no_penalty_regardless_of_minutes():
    entry = make_entry(5, 0.8)
    adjusted = apply_starter_risk_adjustment(
        [entry], minutes_by_player_id={5: 0}, started_by_team_id={9001: False}
    )
    assert adjusted[0][2] == 0.8


import pytest
from app.services.player_pool import filter_by_recent_minutes, filter_unavailable_players


class FakePlayer:
    def __init__(self, id, team_id):
        self.id = id
        self.team_id = team_id


class FakeStats:
    pass


def _make_avail_pair(id, status="a", chance=None, team_id=1):
    player = FakePlayer(id=id, team_id=team_id)
    stats = FakeStats()
    stats.status = status
    stats.chance_of_playing_next_round = chance
    return (player, stats)


def test_filter_unavailable_removes_injured():
    rows = [
        _make_avail_pair(1, status="a"),
        _make_avail_pair(2, status="i"),
    ]
    result_ids = {p.id for p, _ in filter_unavailable_players(rows)}
    assert 1 in result_ids
    assert 2 not in result_ids


def test_filter_unavailable_removes_suspended():
    rows = [_make_avail_pair(1, status="s"), _make_avail_pair(2, status="a")]
    result_ids = {p.id for p, _ in filter_unavailable_players(rows)}
    assert 1 not in result_ids
    assert 2 in result_ids


def test_filter_unavailable_removes_status_u():
    rows = [_make_avail_pair(1, status="u"), _make_avail_pair(2, status="a")]
    result_ids = {p.id for p, _ in filter_unavailable_players(rows)}
    assert 1 not in result_ids


def test_filter_unavailable_removes_confirmed_zero_chance():
    rows = [
        _make_avail_pair(1, status="d", chance=0),
        _make_avail_pair(2, status="d", chance=50),
    ]
    result_ids = {p.id for p, _ in filter_unavailable_players(rows)}
    assert 1 not in result_ids
    assert 2 in result_ids


def test_filter_unavailable_keeps_doubtful_with_nonzero_chance():
    rows = [_make_avail_pair(1, status="d", chance=75)]
    result_ids = {p.id for p, _ in filter_unavailable_players(rows)}
    assert 1 in result_ids


def test_filter_unavailable_keeps_available_with_null_chance():
    rows = [_make_avail_pair(1, status="a", chance=None)]
    result_ids = {p.id for p, _ in filter_unavailable_players(rows)}
    assert 1 in result_ids


async def test_recent_minutes_filter_keeps_players_from_not_yet_started_teams(monkeypatch):
    async def fake_get_gameweek_live(gameweek):
        return {
            "elements": [
                {"id": 1, "stats": {"minutes": 90}},
                {"id": 2, "stats": {"minutes": 0}},
            ]
        }

    async def fake_get_started_status(gameweek):
        return {9001: True, 9002: False}

    monkeypatch.setattr("app.ingestion.fpl_client.get_gameweek_live", fake_get_gameweek_live)
    monkeypatch.setattr(
        "app.services.player_pool.get_started_status_by_team_id", fake_get_started_status
    )

    player_started_full = (FakePlayer(id=1, team_id=9001), FakeStats())
    player_started_zero = (FakePlayer(id=2, team_id=9001), FakeStats())
    player_not_started = (FakePlayer(id=3, team_id=9002), FakeStats())

    rows = [player_started_full, player_started_zero, player_not_started]

    result = await filter_by_recent_minutes(rows, gameweek=4)
    result_ids = {p.id for p, s in result}

    assert 1 in result_ids
    assert 2 not in result_ids
    assert 3 in result_ids

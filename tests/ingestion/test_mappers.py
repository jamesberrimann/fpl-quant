from datetime import datetime, timezone
from decimal import Decimal

from app.ingestion.mappers import map_team, map_player, map_player_stats, map_fixture
from app.models.player import Position

RAW_TEAM = {
    "id": 1,
    "name": "Arsenal",
    "short_name": "ARS",
    "strength_overall_home": 4,
    "strength_overall_away": 3,
    "strength_attack_home": 4,
    "strength_attack_away": 3,
    "strength_defence_home": 4,
    "strength_defence_away": 3,
}

RAW_PLAYER = {
    "id": 100,
    "team": 1,
    "first_name": "Mohamed",
    "second_name": "Salah",
    "web_name": "Salah",
    "element_type": 4,
}

RAW_STATS = {
    "id": 100,
    "now_cost": 130,
    "form": "8.5",
    "selected_by_percent": "45.2",
    "expected_goals_conceded_per_90": "0.50",
    "defensive_contribution_per_90": "0.20",
    "expected_goals_per_90": "0.80",
    "total_points": 120,
    "minutes": 2500,
}

PULLED_AT = datetime(2025, 9, 1, 12, 0, tzinfo=timezone.utc)


def test_map_team_reads_all_fields():
    team = map_team(RAW_TEAM)
    assert team.id == 1
    assert team.name == "Arsenal"
    assert team.short_name == "ARS"
    assert team.strength_overall_home == 4
    assert team.strength_overall_away == 3


def test_map_player_reads_all_fields():
    player = map_player(RAW_PLAYER)
    assert player.id == 100
    assert player.team_id == 1
    assert player.first_name == "Mohamed"
    assert player.second_name == "Salah"
    assert player.web_name == "Salah"
    assert player.position == Position.FWD


def test_map_player_position_mapping():
    for element_type, expected in [
        (1, Position.GKP),
        (2, Position.DEF),
        (3, Position.MID),
        (4, Position.FWD),
    ]:
        raw = {**RAW_PLAYER, "element_type": element_type}
        assert map_player(raw).position == expected


def test_map_player_stats_price_divided_by_ten():
    stats = map_player_stats(RAW_STATS, gameweek=5, pulled_at=PULLED_AT)
    assert stats.price == Decimal("13.0")


def test_map_player_stats_decimal_fields_no_precision_loss():
    # Decimal(str(x)) not Decimal(float) — verify the string-path is used
    stats = map_player_stats(RAW_STATS, gameweek=5, pulled_at=PULLED_AT)
    assert stats.form == Decimal("8.5")
    assert stats.expected_goals_per_90 == Decimal("0.80")
    assert stats.expected_goals_conceded_per_90 == Decimal("0.50")
    assert stats.defensive_contribution_per_90 == Decimal("0.20")


def test_map_player_stats_optional_fields_none_when_absent():
    raw = {k: v for k, v in RAW_STATS.items() if k not in (
        "expected_goals_conceded_per_90",
        "defensive_contribution_per_90",
        "expected_goals_per_90",
    )}
    stats = map_player_stats(raw, gameweek=5, pulled_at=PULLED_AT)
    assert stats.expected_goals_conceded_per_90 is None
    assert stats.defensive_contribution_per_90 is None
    assert stats.expected_goals_per_90 is None


def test_map_player_stats_optional_fields_none_when_null():
    raw = {
        **RAW_STATS,
        "expected_goals_conceded_per_90": None,
        "defensive_contribution_per_90": None,
        "expected_goals_per_90": None,
    }
    stats = map_player_stats(raw, gameweek=5, pulled_at=PULLED_AT)
    assert stats.expected_goals_conceded_per_90 is None


def test_map_player_stats_stores_gameweek_and_pulled_at():
    stats = map_player_stats(RAW_STATS, gameweek=12, pulled_at=PULLED_AT)
    assert stats.gameweek == 12
    assert stats.pulled_at == PULLED_AT


def test_map_fixture_finished_with_scores():
    raw = {
        "id": 200, "event": 5,
        "team_h": 1, "team_a": 2,
        "team_h_difficulty": 3, "team_a_difficulty": 2,
        "team_h_score": 2, "team_a_score": 1,
        "finished": True,
    }
    f = map_fixture(raw)
    assert f.id == 200
    assert f.gameweek == 5
    assert f.team_h_id == 1
    assert f.team_a_id == 2
    assert f.team_h_score == 2
    assert f.team_a_score == 1
    assert f.finished is True


def test_map_fixture_unplayed_scores_are_none():
    raw = {
        "id": 201, "event": 10,
        "team_h": 3, "team_a": 4,
        "team_h_difficulty": 2, "team_a_difficulty": 4,
        "team_h_score": None, "team_a_score": None,
        "finished": False,
    }
    f = map_fixture(raw)
    assert f.team_h_score is None
    assert f.team_a_score is None
    assert f.finished is False

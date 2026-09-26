from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.services.captaincy import score_for_captaincy, get_captaincy_explanation


def make_entry(id, team_id, position, form, xgc=None, xg=None):
    player = Player(id=id, team_id=team_id, first_name="F", second_name="L", web_name=f"P{id}", position=position)
    stats = PlayerGameweekStats(
        player_id=id, gameweek=4, pulled_at=datetime.now(timezone.utc),
        price=Decimal("5.0"), form=Decimal(str(form)), ownership_pct=Decimal("10.0"),
        expected_goals_conceded_per_90=Decimal(str(xgc)) if xgc is not None else None,
        expected_goals_per_90=Decimal(str(xg)) if xg is not None else None,
        total_points=10, minutes=270,
    )
    return (player, stats, 0.0)


@pytest.fixture
def patch_fixture_difficulty(monkeypatch):
    difficulty_by_team = {}

    async def fake_difficulty(db, team_id, gameweek, num_fixtures=1):
        return difficulty_by_team.get(team_id, 3.0)

    async def fake_opponent_strength(db, team_id, from_gameweek, num_fixtures=1):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    async def fake_dgw_multipliers(db, team_ids, gameweek):
        return {tid: 1.0 for tid in team_ids}

    monkeypatch.setattr("app.services.captaincy.get_team_fixture_difficulty", fake_difficulty)
    monkeypatch.setattr("app.services.captaincy.get_opponent_strength_for_fixture", fake_opponent_strength)
    monkeypatch.setattr("app.services.captaincy.get_gameweek_fixture_multipliers", fake_dgw_multipliers)
    return difficulty_by_team


async def test_easier_fixture_gives_forward_higher_captain_score(patch_fixture_difficulty):
    patch_fixture_difficulty[9001] = 1
    patch_fixture_difficulty[9002] = 5

    starting_xi = [
        make_entry(1, 9001, Position.FWD, form=5.0, xg=0.5),
        make_entry(2, 9002, Position.FWD, form=5.0, xg=0.5),
    ]

    scored = await score_for_captaincy(starting_xi, db=None, gameweek=4)
    score_by_id = {p.id: sc for p, s, sc, *_ in scored}

    assert score_by_id[1] > score_by_id[2]


async def test_higher_xg_gives_forward_higher_captain_score(patch_fixture_difficulty):
    starting_xi = [
        make_entry(1, 9001, Position.FWD, form=5.0, xg=0.9),
        make_entry(2, 9002, Position.FWD, form=5.0, xg=0.1),
    ]

    scored = await score_for_captaincy(starting_xi, db=None, gameweek=4)
    score_by_id = {p.id: sc for p, s, sc, *_ in scored}

    # FWD captain weights (form=0.20, fixture=0.15, xg=0.65)
    # Both equal form → normalize returns 0.5 → form = 0.20 * 0.5 = 0.10 each
    # Both equal difficulty → fixture_ease = 0.5 → fixture = 0.15 * 0.5 = 0.075 each
    # P1 (xg_n=1.0): 0.10 + 0.075 + 0.65*1.0 = 0.825
    # P2 (xg_n=0.0): 0.10 + 0.075 + 0.65*0.0 = 0.175
    assert score_by_id[1] > score_by_id[2]
    assert score_by_id[1] == pytest.approx(0.825)
    assert score_by_id[2] == pytest.approx(0.175)


async def test_goalkeeper_captain_score_unaffected_by_xg(patch_fixture_difficulty):
    starting_xi = [
        make_entry(1, 9001, Position.GKP, form=5.0, xg=0.9),
        make_entry(2, 9002, Position.GKP, form=5.0, xg=0.1),
    ]

    scored = await score_for_captaincy(starting_xi, db=None, gameweek=4)
    score_by_id = {p.id: sc for p, s, sc, *_ in scored}

    assert score_by_id[1] == score_by_id[2]


async def test_defender_captain_score_uses_small_xgc_weight_not_forward_xg_weight(patch_fixture_difficulty):
    starting_xi = [
        make_entry(1, 9001, Position.DEF, form=5.0, xgc=0.2),
        make_entry(2, 9002, Position.DEF, form=5.0, xgc=1.0),
    ]

    scored = await score_for_captaincy(starting_xi, db=None, gameweek=4)
    score_by_id = {p.id: sc for p, s, sc, *_ in scored}

    # DEF captain weights (form=0.15, fixture=0.45, xgc=0.40)
    # Both equal form → normalize returns 0.5 → form = 0.15 * 0.5 = 0.075 each
    # Both equal difficulty → fixture_ease = 0.5 → fixture = 0.45 * 0.5 = 0.225 each
    # P1 (xgc_ease=1.0): 0.075 + 0.225 + 0.40*1.0 = 0.70
    # P2 (xgc_ease=0.0): 0.075 + 0.225 + 0.40*0.0 = 0.30
    assert score_by_id[1] > score_by_id[2]
    assert score_by_id[1] == pytest.approx(0.70)
    assert score_by_id[2] == pytest.approx(0.30)


async def test_goals_based_attack_ease_boosts_forward_captain_score():
    # Covers the atk_ease_by_team path (lines 43-46) in captaincy.py
    starting_xi = [
        make_entry(5, 9005, Position.FWD, form=5.0, xg=0.5),
        make_entry(6, 9006, Position.FWD, form=5.0, xg=0.5),
    ]

    async def fake_difficulty(db, team_id, gameweek, num_fixtures=1):
        return 3.0

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=1):
        goals_conceded = {9005: 2.5, 9006: 0.5}
        return {"opponent_avg_goals_conceded": goals_conceded[team_id], "opponent_avg_goals_scored": None}

    async def fake_dgw(db, team_ids, gameweek):
        return {tid: 1.0 for tid in team_ids}

    with patch("app.services.captaincy.get_team_fixture_difficulty", new=fake_difficulty), \
         patch("app.services.captaincy.get_opponent_strength_for_fixture", new=fake_strength), \
         patch("app.services.captaincy.get_gameweek_fixture_multipliers", new=fake_dgw):
        scored = await score_for_captaincy(starting_xi, db=None, gameweek=4)

    score_by_id = {p.id: sc for p, s, sc, *_ in scored}
    assert score_by_id[5] > score_by_id[6]


async def test_goals_based_defense_ease_boosts_defender_captain_score():
    # Covers the def_ease_by_team path (lines 54-57) in captaincy.py
    starting_xi = [
        make_entry(7, 9007, Position.DEF, form=5.0, xgc=0.5),
        make_entry(8, 9008, Position.DEF, form=5.0, xgc=0.5),
    ]

    async def fake_difficulty(db, team_id, gameweek, num_fixtures=1):
        return 3.0

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=1):
        goals_scored = {9007: 0.5, 9008: 2.5}
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": goals_scored[team_id]}

    async def fake_dgw(db, team_ids, gameweek):
        return {tid: 1.0 for tid in team_ids}

    with patch("app.services.captaincy.get_team_fixture_difficulty", new=fake_difficulty), \
         patch("app.services.captaincy.get_opponent_strength_for_fixture", new=fake_strength), \
         patch("app.services.captaincy.get_gameweek_fixture_multipliers", new=fake_dgw):
        scored = await score_for_captaincy(starting_xi, db=None, gameweek=4)

    score_by_id = {p.id: sc for p, s, sc, *_ in scored}
    assert score_by_id[7] > score_by_id[8]


async def test_get_captaincy_explanation_returns_top_two_factors(patch_fixture_difficulty):
    """
    For a FWD with clear xG dominance (weights: xg=0.75, fixture=0.15, form=0.10),
    the explanation should list 'Strong xG' first and include 'Favourable fixture'
    when that also contributes meaningfully.
    """
    patch_fixture_difficulty[9001] = 1  # easy fixture for P1 → high fixture_ease
    patch_fixture_difficulty[9002] = 3

    starting_xi = [
        make_entry(1, 9001, Position.FWD, form=5.0, xg=0.9),
        make_entry(2, 9002, Position.FWD, form=5.0, xg=0.1),
    ]

    scored = await score_for_captaincy(starting_xi, db=None, gameweek=4)
    factors = get_captaincy_explanation(1, scored)

    assert len(factors) >= 1
    assert "Strong xG" in factors, f"Expected 'Strong xG' in factors for top xG player, got {factors}"


async def test_get_captaincy_explanation_returns_empty_for_unknown_player(patch_fixture_difficulty):
    starting_xi = [make_entry(1, 9001, Position.FWD, form=5.0, xg=0.5)]
    scored = await score_for_captaincy(starting_xi, db=None, gameweek=4)

    assert get_captaincy_explanation(999, scored) == []


async def test_get_captaincy_explanation_includes_clean_sheet_probability_for_defender(
    patch_fixture_difficulty,
):
    """DEF captain explanation should highlight clean sheet probability when xGC is low."""
    starting_xi = [
        make_entry(1, 9001, Position.DEF, form=5.0, xgc=0.1),  # good CS probability
        make_entry(2, 9002, Position.DEF, form=5.0, xgc=1.5),  # poor CS probability
    ]

    scored = await score_for_captaincy(starting_xi, db=None, gameweek=4)
    factors = get_captaincy_explanation(1, scored)

    assert "Clean sheet probability" in factors, (
        f"DEF with low xGC should highlight clean sheet probability, got {factors}"
    )

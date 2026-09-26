from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

import pytest

from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.services.scoring import normalize, score_players


def make_entry(id, team_id, position, points, form, xgc=None, xg=None, xa=None):
    player = Player(id=id, team_id=team_id, first_name="F", second_name="L", web_name=f"P{id}", position=position)
    stats = PlayerGameweekStats(
        player_id=id, gameweek=4, pulled_at=datetime.now(timezone.utc),
        price=Decimal("5.0"), form=Decimal(str(form)), ownership_pct=Decimal("10.0"),
        expected_goals_conceded_per_90=Decimal(str(xgc)) if xgc is not None else None,
        expected_goals_per_90=Decimal(str(xg)) if xg is not None else None,
        expected_assists_per_90=Decimal(str(xa)) if xa is not None else None,
        total_points=points, minutes=270,
    )
    return (player, stats)


@pytest.fixture
def patch_fixture_difficulty(monkeypatch):
    async def fake_difficulty(db, team_id, gameweek, num_fixtures=3):
        return 3.0

    async def fake_opponent_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    monkeypatch.setattr("app.services.fixtures.get_team_fixture_difficulty", fake_difficulty)
    monkeypatch.setattr("app.services.fixtures.get_opponent_strength_for_fixture", fake_opponent_strength)


async def test_lower_xgc_gives_defender_higher_score(patch_fixture_difficulty):
    rows = [
        make_entry(1, 9001, Position.DEF, points=10, form=5.0, xgc=0.2),
        make_entry(2, 9002, Position.DEF, points=10, form=5.0, xgc=1.0),
    ]

    scored = await score_players(rows, db=None, gameweek=4)
    score_by_id = {p.id: sc for p, s, sc in scored}

    # DEF weights (points=0.27, form=0.10, fixture=0.15, xgc=0.25, defcon=0.18, xa=0.05)
    # Both equal on points/form → 0.5 each (uniform pool midpoint).
    # Fixture: same difficulty → norm_fixture_ease = 0.5 each. defcon/xa missing → 0.5.
    # P1 (xgc_ease=1.0): 0.27*0.5 + 0.10*0.5 + 0.15*0.5 + 0.25*1.0 + 0.18*0.5 + 0.05*0.5 = 0.625
    # P2 (xgc_ease=0.0): 0.27*0.5 + 0.10*0.5 + 0.15*0.5 + 0.25*0.0 + 0.18*0.5 + 0.05*0.5 = 0.375
    assert score_by_id[1] > score_by_id[2]
    assert score_by_id[1] == pytest.approx(0.625)
    assert score_by_id[2] == pytest.approx(0.375)


async def test_higher_xg_gives_forward_higher_score(patch_fixture_difficulty):
    rows = [
        make_entry(3, 9003, Position.FWD, points=10, form=5.0, xg=0.8),
        make_entry(4, 9004, Position.FWD, points=10, form=5.0, xg=0.1),
    ]

    scored = await score_players(rows, db=None, gameweek=4)
    score_by_id = {p.id: sc for p, s, sc in scored}

    # FWD weights (points=0.22, form=0.10, fixture=0.20, defcon=0.02, xg=0.38, xa=0.08)
    # Both equal on points/form → 0.5 each (uniform pool midpoint). defcon/xa missing → 0.5.
    # Fixture: same difficulty → norm_fixture_ease = 0.5 each.
    # P3 (xg_n=1.0): 0.22*0.5 + 0.10*0.5 + 0.20*0.5 + 0.02*0.5 + 0.38*1.0 + 0.08*0.5 = 0.69
    # P4 (xg_n=0.0): 0.22*0.5 + 0.10*0.5 + 0.20*0.5 + 0.02*0.5 + 0.38*0.0 + 0.08*0.5 = 0.31
    assert score_by_id[3] > score_by_id[4]
    assert score_by_id[3] == pytest.approx(0.69)
    assert score_by_id[4] == pytest.approx(0.31)


async def test_goalkeeper_score_unaffected_by_xg_field(patch_fixture_difficulty):
    rows = [
        make_entry(5, 9005, Position.GKP, points=10, form=5.0, xgc=0.5, xg=0.9),
        make_entry(6, 9006, Position.GKP, points=10, form=5.0, xgc=0.5, xg=0.1),
    ]

    scored = await score_players(rows, db=None, gameweek=4)
    score_by_id = {p.id: sc for p, s, sc in scored}

    assert score_by_id[5] == score_by_id[6]


def _with_defcon(entry, defcon_value):
    player, stats = entry
    stats.defensive_contribution_per_90 = Decimal(str(defcon_value))
    return (player, stats)


async def test_goals_based_attack_ease_boosts_forward_with_weaker_opponent_defense():
    # Covers the atk_ease_by_team population path (lines 56-59 in scoring.py)
    rows = [
        make_entry(7, 9007, Position.FWD, points=10, form=5.0),
        make_entry(8, 9008, Position.FWD, points=10, form=5.0),
    ]

    async def fake_difficulty(db, team_id, gameweek, num_fixtures=3):
        return 3.0

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        # 9007 faces a weak defense (concedes 2.0/game = easier for attacker)
        # 9008 faces a strong defense (concedes 0.5/game = harder for attacker)
        goals_conceded = {9007: 2.0, 9008: 0.5}
        return {"opponent_avg_goals_conceded": goals_conceded[team_id], "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_team_fixture_difficulty", new=fake_difficulty), \
         patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored = await score_players(rows, db=None, gameweek=4)

    score_by_id = {p.id: sc for p, s, sc in scored}
    assert score_by_id[7] > score_by_id[8]


async def test_goals_based_defense_ease_boosts_defender_facing_weak_attack():
    # Covers the def_ease_by_team population path (lines 67-70 in scoring.py)
    rows = [
        make_entry(9, 9009, Position.DEF, points=10, form=5.0, xgc=0.5),
        make_entry(10, 9010, Position.DEF, points=10, form=5.0, xgc=0.5),
    ]

    async def fake_difficulty(db, team_id, gameweek, num_fixtures=3):
        return 3.0

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        # 9009 faces a weak attack (scores 0.5/game = easier for defender)
        # 9010 faces a strong attack (scores 2.0/game = harder for defender)
        goals_scored = {9009: 0.5, 9010: 2.0}
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": goals_scored[team_id]}

    with patch("app.services.fixtures.get_team_fixture_difficulty", new=fake_difficulty), \
         patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored = await score_players(rows, db=None, gameweek=4)

    score_by_id = {p.id: sc for p, s, sc in scored}
    assert score_by_id[9] > score_by_id[10]


async def test_defcon_component_uses_real_value_when_not_none(patch_fixture_difficulty):
    # Covers line 115 in scoring.py — the non-None defensive_contribution_per_90 path
    rows = [
        _with_defcon(make_entry(11, 9011, Position.DEF, points=10, form=5.0), defcon_value=10.0),
        _with_defcon(make_entry(12, 9012, Position.DEF, points=10, form=5.0), defcon_value=0.0),
    ]

    scored = await score_players(rows, db=None, gameweek=4)
    score_by_id = {p.id: sc for p, s, sc in scored}
    # Higher defcon → higher score for DEF (weight 0.20, log1p scaling: 1.0 vs 0.0)
    assert score_by_id[11] > score_by_id[12]


async def test_higher_xa_gives_midfielder_higher_score(patch_fixture_difficulty):
    """xA should lift creative midfielders (Bruno, KDB) above goal-only peers."""
    rows = [
        make_entry(15, 9015, Position.MID, points=10, form=5.0, xa=0.4),
        make_entry(16, 9016, Position.MID, points=10, form=5.0, xa=0.0),
    ]

    scored = await score_players(rows, db=None, gameweek=4)
    score_by_id = {p.id: sc for p, s, sc in scored}

    # MID weights (points=0.20, form=0.10, fixture=0.20, xgc=0.05, defcon=0.05, xg=0.25, xa=0.15)
    # Both equal on points/form → 0.5 each (uniform pool midpoint). xgc/defcon/xg missing → 0.5.
    # Fixture: same difficulty → norm_fixture_ease = 0.5 each.
    # P15 (xa_n=1.0): 0.20*0.5+0.10*0.5+0.20*0.5+0.05*0.5+0.05*0.5+0.25*0.5+0.15*1.0 = 0.575
    # P16 (xa_n=0.0): 0.20*0.5+0.10*0.5+0.20*0.5+0.05*0.5+0.05*0.5+0.25*0.5+0.15*0.0 = 0.425
    assert score_by_id[15] > score_by_id[16]
    assert score_by_id[15] == pytest.approx(0.575)
    assert score_by_id[16] == pytest.approx(0.425)


async def test_higher_xa_gives_forward_higher_score(patch_fixture_difficulty):
    """xA should also lift forwards who assist frequently."""
    rows = [
        make_entry(17, 9017, Position.FWD, points=10, form=5.0, xa=0.3),
        make_entry(18, 9018, Position.FWD, points=10, form=5.0, xa=0.0),
    ]

    scored = await score_players(rows, db=None, gameweek=4)
    score_by_id = {p.id: sc for p, s, sc in scored}

    assert score_by_id[17] > score_by_id[18]


async def test_higher_xa_gives_defender_higher_score(patch_fixture_difficulty):
    """Attacking fullbacks with high xA should outscore pure defensive fullbacks."""
    rows = [
        make_entry(19, 9019, Position.DEF, points=10, form=5.0, xgc=0.5, xa=0.25),
        make_entry(20, 9020, Position.DEF, points=10, form=5.0, xgc=0.5, xa=0.0),
    ]

    scored = await score_players(rows, db=None, gameweek=4)
    score_by_id = {p.id: sc for p, s, sc in scored}

    assert score_by_id[19] > score_by_id[20]


async def test_gkp_score_unaffected_by_xa(patch_fixture_difficulty):
    """GKP weights have no xA component — xa data should be ignored."""
    rows = [
        make_entry(21, 9021, Position.GKP, points=10, form=5.0, xgc=0.5, xa=0.9),
        make_entry(22, 9022, Position.GKP, points=10, form=5.0, xgc=0.5, xa=0.0),
    ]

    scored = await score_players(rows, db=None, gameweek=4)
    score_by_id = {p.id: sc for p, s, sc in scored}

    assert score_by_id[21] == pytest.approx(score_by_id[22])


async def test_elite_defcon_above_threshold_scores_higher_than_threshold_value(patch_fixture_difficulty):
    """
    An elite defender (20 defcon/90, 2× threshold) should score higher than
    one at exactly the threshold (10 defcon/90). Previously both capped at 1.0;
    now log1p scaling preserves differentiation above the threshold.
    """
    rows = [
        _with_defcon(make_entry(13, 9013, Position.DEF, points=10, form=5.0), defcon_value=20.0),
        _with_defcon(make_entry(14, 9014, Position.DEF, points=10, form=5.0), defcon_value=10.0),
    ]

    scored = await score_players(rows, db=None, gameweek=4)
    score_by_id = {p.id: sc for p, s, sc in scored}
    assert score_by_id[13] > score_by_id[14], (
        "Elite defender (20 defcon) should outscore threshold defender (10 defcon) "
        "now that the hard cap has been replaced with log1p scaling"
    )


# ---------------------------------------------------------------------------
# normalize() edge cases
# ---------------------------------------------------------------------------

def test_normalize_uniform_pool_returns_midpoint():
    """All-equal values should produce 0.5, not 0.0.

    0.0 would rank every player at the floor — making a uniform xG pool look
    like everyone has zero xG rather than average xG.  0.5 is the neutral
    midpoint and is consistent with the fallback used elsewhere (e.g. the
    `xg_norm_by_index.get(i, 0.5)` calls in score_players).
    """
    assert normalize([5.0, 5.0, 5.0]) == [0.5, 0.5, 0.5]
    assert normalize([0.0, 0.0]) == [0.5, 0.5]


def test_normalize_single_element_returns_midpoint():
    """A pool of one player can't be ranked — return the neutral midpoint."""
    assert normalize([3.7]) == [0.5]


def test_normalize_varying_pool():
    assert normalize([0.0, 1.0]) == pytest.approx([0.0, 1.0])
    assert normalize([0.0, 0.5, 1.0]) == pytest.approx([0.0, 0.5, 1.0])
    assert normalize([2.0, 4.0, 6.0]) == pytest.approx([0.0, 0.5, 1.0])

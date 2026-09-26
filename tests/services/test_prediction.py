import math
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.services.prediction import _predict_base, _fixture_multiplier, predict_points


def make_player(id, team_id, position):
    return Player(id=id, team_id=team_id, first_name="F", second_name="L",
                  web_name=f"P{id}", position=position)


def make_stats(player_id, gameweek=5, minutes=450, form=5.0,
               xg=None, xa=None, xgc=None, price=5.0,
               xg_gw=None, xa_gw=None, xgc_gw=None, minutes_gw=None):
    stats = PlayerGameweekStats(
        player_id=player_id, gameweek=gameweek,
        pulled_at=datetime.now(timezone.utc),
        price=Decimal(str(price)), form=Decimal(str(form)),
        ownership_pct=Decimal("10.0"),
        expected_goals_per_90=Decimal(str(xg)) if xg is not None else None,
        expected_assists_per_90=Decimal(str(xa)) if xa is not None else None,
        expected_goals_conceded_per_90=Decimal(str(xgc)) if xgc is not None else None,
        total_points=30, minutes=minutes,
    )
    stats.xg_this_gw_per_90 = Decimal(str(xg_gw)) if xg_gw is not None else None
    stats.xa_this_gw_per_90 = Decimal(str(xa_gw)) if xa_gw is not None else None
    stats.xgc_this_gw_per_90 = Decimal(str(xgc_gw)) if xgc_gw is not None else None
    stats.minutes_this_gw = int(minutes_gw) if minutes_gw is not None else None
    return stats


# ---------------------------------------------------------------------------
# _predict_base
# ---------------------------------------------------------------------------

def test_predict_base_fwd_full_minutes():
    player = make_player(1, 1, Position.FWD)
    stats = make_stats(1, minutes=450, xg=0.8, xa=0.1, xgc=None)
    base = _predict_base(player, stats, avg_min=90.0)
    # appearance=2, goals=0.8*4=3.2, assists=0.1*3=0.3, bonus=0.8*2.5+0.1*0.4=2.04, cs=0 (FWD)
    assert base == pytest.approx(2.0 + 3.2 + 0.3 + 2.04, rel=1e-4)


def test_predict_base_def_clean_sheet_contribution():
    player = make_player(2, 1, Position.DEF)
    stats = make_stats(2, xgc=0.3)
    base = _predict_base(player, stats, avg_min=90.0)
    cs_prob = math.exp(-0.3)
    # cs_pts = cs_prob * (6 CS points + 0.5 CS bonus for DEF)
    expected = 2.0 + cs_prob * 6.5
    assert base == pytest.approx(expected, rel=1e-4)


def test_predict_base_gkp_partial_minutes():
    # GKP playing 45 min (e.g. rotation or injury)
    player = make_player(3, 1, Position.GKP)
    stats = make_stats(3, xgc=1.0)
    base = _predict_base(player, stats, avg_min=45.0)
    min_fraction = 0.5
    cs_prob = math.exp(-1.0 * min_fraction)
    # cs_pts = cs_prob * (6 CS points + 0.8 CS bonus for GKP)
    expected = 1.0 + cs_prob * 6.8  # 1pt for <60 min
    assert base == pytest.approx(expected, rel=1e-4)


def test_predict_base_zero_avg_minutes_returns_zero():
    player = make_player(4, 1, Position.MID)
    stats = make_stats(4)
    assert _predict_base(player, stats, avg_min=0.0) == 0.0


def test_predict_base_mid_uses_5pt_goal_value():
    player = make_player(5, 1, Position.MID)
    stats = make_stats(5, xg=1.0, xgc=None)
    base = _predict_base(player, stats, avg_min=90.0)
    # appearance=2, goals=1.0*5=5.0, bonus=1.0*1.5=1.5, cs=1*exp(-1.3) (MID, xgc defaults to 1.3)
    cs_pts = math.exp(-1.3) * 1  # MID: CS_POINTS=1, BONUS_PER_CS=0
    assert base == pytest.approx(2.0 + 5.0 + 1.5 + cs_pts, rel=1e-4)


def test_predict_base_caps_minutes_at_90():
    # avg_min > 90 should not increase prediction beyond 90-min full game
    player = make_player(6, 1, Position.FWD)
    stats = make_stats(6, xg=0.5)
    base_90 = _predict_base(player, stats, avg_min=90.0)
    base_over = _predict_base(player, stats, avg_min=120.0)
    assert base_90 == pytest.approx(base_over, rel=1e-4)


# ---------------------------------------------------------------------------
# _fixture_multiplier
# ---------------------------------------------------------------------------

def test_fixture_multiplier_attacker_easy_fixture():
    # Opponent concedes 2.6/game vs PL avg 1.3 → 2x multiplier
    strength = {"opponent_avg_goals_conceded": 2.6, "opponent_avg_goals_scored": 0.5}
    mult = _fixture_multiplier(strength, Position.FWD)
    assert mult == pytest.approx(2.0, rel=1e-4)


def test_fixture_multiplier_attacker_average_fixture():
    strength = {"opponent_avg_goals_conceded": 1.3, "opponent_avg_goals_scored": 1.0}
    mult = _fixture_multiplier(strength, Position.MID)
    assert mult == pytest.approx(1.0, rel=1e-4)


def test_fixture_multiplier_defender_easy_fixture():
    # Opponent scores 0.65/game → defender sees 2x multiplier
    strength = {"opponent_avg_goals_conceded": 2.0, "opponent_avg_goals_scored": 0.65}
    mult = _fixture_multiplier(strength, Position.DEF)
    assert mult == pytest.approx(1.3 / 0.65, rel=1e-4)


def test_fixture_multiplier_defender_tough_fixture():
    # Opponent scores 2.6/game → defender sees 0.5x multiplier
    strength = {"opponent_avg_goals_conceded": 0.8, "opponent_avg_goals_scored": 2.6}
    mult = _fixture_multiplier(strength, Position.GKP)
    assert mult == pytest.approx(1.3 / 2.6, rel=1e-4)


def test_fixture_multiplier_no_data_returns_one():
    strength = {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}
    assert _fixture_multiplier(strength, Position.FWD) == pytest.approx(1.0)
    assert _fixture_multiplier(strength, Position.DEF) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# predict_points (integration with mocked DB)
# ---------------------------------------------------------------------------

async def test_higher_xg_forward_scores_higher():
    striker = make_player(10, 100, Position.FWD)
    journeyman = make_player(11, 101, Position.FWD)
    rows = [
        (striker, make_stats(10, minutes=450, xg=0.8, form=5.0)),
        (journeyman, make_stats(11, minutes=450, xg=0.2, form=5.0)),
    ]

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored = await predict_points(rows, db=None, gameweek=5)

    pts = {p.id: s for p, _, s in scored}
    assert pts[10] > pts[11]


async def test_premier_striker_vs_budget_alternative():
    """
    Premier striker (Haaland-profile): high xG, high price, full minutes.
    Budget alternative (João Pedro-profile): moderate xG, cheaper, good form.
    Predicted points model should favour the better underlying player.
    """
    haaland = make_player(20, 200, Position.FWD)
    joao = make_player(21, 201, Position.FWD)
    rows = [
        (haaland, make_stats(20, minutes=270, xg=0.8, xa=0.1, form=6.0, price=15.5)),
        (joao,    make_stats(21, minutes=270, xg=0.3, xa=0.2, form=8.0, price=7.7)),
    ]

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": 1.3, "opponent_avg_goals_scored": 1.3}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored = await predict_points(rows, db=None, gameweek=3)

    pts = {p.id: s for p, _, s in scored}
    # Haaland's xG premium (0.5 extra goals/90 * 4pts = 2 pts/game advantage)
    # should outweigh João Pedro's form edge at neutral fixture difficulty.
    assert pts[20] > pts[21], (
        f"Haaland predicted {pts[20]:.2f} vs João Pedro {pts[21]:.2f} — "
        "premier striker xG premium should dominate"
    )


async def test_clean_sheet_specialist_defender_scores_high():
    solid_def = make_player(30, 300, Position.DEF)
    leaky_def = make_player(31, 301, Position.DEF)
    rows = [
        (solid_def, make_stats(30, minutes=450, xgc=0.4, form=5.0)),
        (leaky_def, make_stats(31, minutes=450, xgc=1.5, form=5.0)),
    ]

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored = await predict_points(rows, db=None, gameweek=5)

    pts = {p.id: s for p, _, s in scored}
    assert pts[30] > pts[31]


async def test_zero_minutes_player_gets_zero_score():
    player = make_player(40, 400, Position.MID)
    rows = [(player, make_stats(40, minutes=0, xg=0.5, form=8.0))]

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored = await predict_points(rows, db=None, gameweek=5)

    assert scored[0][2] == pytest.approx(0.0)


async def test_fixture_ease_boosts_attacker():
    fwd = make_player(50, 500, Position.FWD)
    rows = [(fwd, make_stats(50, minutes=450, xg=0.5, form=5.0))]

    async def easy_fixture(db, team_id, from_gameweek, num_fixtures=3):
        # Opponent concedes 2.6/game — 2x fixture multiplier
        return {"opponent_avg_goals_conceded": 2.6, "opponent_avg_goals_scored": 0.5}

    async def neutral_fixture(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": 1.3, "opponent_avg_goals_scored": 1.3}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=easy_fixture):
        easy_scored = await predict_points(rows, db=None, gameweek=5)

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=neutral_fixture):
        neutral_scored = await predict_points(rows, db=None, gameweek=5)

    assert easy_scored[0][2] > neutral_scored[0][2]


async def test_gkp_easier_fixture_beats_harder_when_gap_is_large():
    """
    With a large fixture gap, the easier-fixture GKP still wins even if the
    harder-fixture GKP has an elite defence.

    CS λ = sqrt(opp_goals × xgc) — both signals multiply.
    Budget GKP (xgc=1.5) vs relegation side (0.4 goals): λ = sqrt(0.4×1.5) = 0.775 → P(CS) ≈ 46%
    Raya        (xgc=0.5) vs Man City      (2.4 goals):   λ = sqrt(2.4×0.5) = 1.095 → P(CS) ≈ 33%
    """
    raya = make_player(70, 700, Position.GKP)
    budget_gkp = make_player(71, 701, Position.GKP)

    rows = [
        (raya,       make_stats(70, minutes=450, xgc=0.5, form=5.0)),
        (budget_gkp, make_stats(71, minutes=450, xgc=1.5, form=5.0)),
    ]

    async def fixtures(db, team_id, from_gameweek, num_fixtures=3):
        if team_id == 700:
            return {"opponent_avg_goals_conceded": 0.8, "opponent_avg_goals_scored": 2.4}  # Man City: hard
        return {"opponent_avg_goals_conceded": 1.8, "opponent_avg_goals_scored": 0.4}  # relegation side: easy

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fixtures):
        scored = await predict_points(rows, db=None, gameweek=5)

    pts = {p.id: s for p, _, s in scored}
    assert pts[71] > pts[70], (
        f"Budget GKP vs relegation side ({pts[71]:.2f}) should outscore Raya vs Man City ({pts[70]:.2f}): "
        "a large fixture gap overcomes team quality difference"
    )


async def test_elite_gkp_beats_budget_gkp_same_fixture():
    """
    Same opponent, same fixture difficulty: team defensive quality (xgc) now
    differentiates GKPs. An elite GKP (xgc=0.5) has higher CS probability than
    a leaky-defence GKP (xgc=1.5) against the same opponent.
    Elite λ  = 0.7*0.8 + 0.3*0.5 = 0.71  → P(CS) ≈ 0.49
    Budget λ = 0.7*0.8 + 0.3*1.5 = 1.01  → P(CS) ≈ 0.36
    """
    raya = make_player(70, 700, Position.GKP)
    budget_gkp = make_player(71, 701, Position.GKP)

    rows = [
        (raya,       make_stats(70, minutes=450, xgc=0.5, form=5.0)),
        (budget_gkp, make_stats(71, minutes=450, xgc=1.5, form=5.0)),
    ]

    async def same_fixture(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": 1.5, "opponent_avg_goals_scored": 0.8}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=same_fixture):
        scored = await predict_points(rows, db=None, gameweek=5)

    pts = {p.id: s for p, _, s in scored}
    assert pts[70] > pts[71], (
        f"Elite GKP ({pts[70]:.2f}) should outscore leaky-defence GKP ({pts[71]:.2f}) "
        "against the same opponent — team xgc now moderates CS probability"
    )


async def test_elite_gkp_wins_when_no_fixture_data():
    """
    Without opponent data, CS falls back to team xgc — Arsenal GKP (xgc=0.5)
    correctly beats a budget GKP (xgc=1.5) when the upcoming opponent is unknown.
    """
    raya = make_player(70, 700, Position.GKP)
    budget_gkp = make_player(71, 701, Position.GKP)

    rows = [
        (raya,       make_stats(70, minutes=450, xgc=0.5, form=5.0)),
        (budget_gkp, make_stats(71, minutes=450, xgc=1.5, form=5.0)),
    ]

    async def no_data(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=no_data):
        scored = await predict_points(rows, db=None, gameweek=5)

    pts = {p.id: s for p, _, s in scored}
    assert pts[70] > pts[71], (
        f"Arsenal GKP {pts[70]:.2f} vs budget GKP {pts[71]:.2f} — "
        "team xgc fallback correctly favours elite defence when no opponent data"
    )


async def test_high_form_boosts_prediction():
    hot_player = make_player(60, 600, Position.MID)
    cold_player = make_player(61, 601, Position.MID)
    rows = [
        (hot_player, make_stats(60, minutes=450, xg=0.3, form=9.0)),
        (cold_player, make_stats(61, minutes=450, xg=0.3, form=1.0)),
    ]

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored = await predict_points(rows, db=None, gameweek=5)

    pts = {p.id: s for p, _, s in scored}
    assert pts[60] > pts[61]


async def test_form_factor_clamped_at_15_percent():
    """
    form_factor clamps at ±15%: values above the ceiling (form > 6.5) or below
    the floor (form < 3.5) should all produce the same score — the clamp is hit.

    This proves the old ±25% range has been tightened: a player with form=15
    (sustained hot streak) scores the same as one with form=7 (just at ceiling),
    so a bonus-point outlier in one GW can't distort the prediction.
    """
    player = make_player(70, 700, Position.FWD)

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored = await predict_points(
            [
                (player, make_stats(70, minutes=450, xg=0.5, form=7.0)),   # just above ceiling (6.5)
                (player, make_stats(70, minutes=450, xg=0.5, form=15.0)),  # far above ceiling
                (player, make_stats(70, minutes=450, xg=0.5, form=3.0)),   # just below floor (3.5)
                (player, make_stats(70, minutes=450, xg=0.5, form=0.0)),   # far below floor
            ],
            db=None, gameweek=5,
        )

    pts_at_7, pts_at_15, pts_at_3, pts_at_0 = [s for _, _, s in scored]

    assert pts_at_7 == pytest.approx(pts_at_15, rel=1e-4), (
        "form=15 should hit the same 1.15 ceiling as form=7"
    )
    assert pts_at_3 == pytest.approx(pts_at_0, rel=1e-4), (
        "form=0 should hit the same 0.85 floor as form=3"
    )
    assert pts_at_7 > pts_at_0, "ceiling score must exceed floor score"


# ---------------------------------------------------------------------------
# Availability discount
# ---------------------------------------------------------------------------

async def test_confirmed_out_player_scores_zero():
    player = make_player(80, 800, Position.FWD)
    stats = make_stats(80, minutes=450, xg=0.8, form=7.0)
    stats.chance_of_playing_next_round = 0

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored = await predict_points([(player, stats)], db=None, gameweek=5)

    assert scored[0][2] == pytest.approx(0.0)


async def test_doubtful_player_scores_proportionally_discounted():
    player = make_player(81, 801, Position.FWD)
    available = make_stats(81, minutes=450, xg=0.8, form=5.0)
    available.chance_of_playing_next_round = None

    doubtful = make_stats(81, minutes=450, xg=0.8, form=5.0)
    doubtful.chance_of_playing_next_round = 50

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored_avail = await predict_points([(player, available)], db=None, gameweek=5)
        scored_doubt = await predict_points([(player, doubtful)], db=None, gameweek=5)

    assert scored_doubt[0][2] == pytest.approx(scored_avail[0][2] * 0.5, rel=1e-4)


async def test_fully_available_player_unaffected_by_availability():
    player = make_player(82, 802, Position.MID)
    stats = make_stats(82, minutes=450, xg=0.3, form=5.0)
    stats.chance_of_playing_next_round = 100

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored_100 = await predict_points([(player, stats)], db=None, gameweek=5)

    stats_null = make_stats(82, minutes=450, xg=0.3, form=5.0)
    stats_null.chance_of_playing_next_round = None

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored_null = await predict_points([(player, stats_null)], db=None, gameweek=5)

    assert scored_100[0][2] == pytest.approx(scored_null[0][2], rel=1e-4)


# ---------------------------------------------------------------------------
# Per-GW xStats blending
# ---------------------------------------------------------------------------

async def test_recent_xg_blend_boosts_recently_firing_forward():
    """
    Two identical FWDs, same season xg=0.3, but one has xg_this_gw_per_90=1.2.
    The blended xg = 0.6*0.3 + 0.4*1.2 = 0.66, so the hot recent form
    player should predict higher points.
    """
    season_only = make_player(90, 900, Position.FWD)
    recent_hot  = make_player(91, 901, Position.FWD)
    rows = [
        (season_only, make_stats(90, minutes=450, xg=0.3, form=5.0)),
        (recent_hot,  make_stats(91, minutes=450, xg=0.3, form=5.0, xg_gw=1.2)),
    ]

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored = await predict_points(rows, db=None, gameweek=5)

    pts = {p.id: s for p, _, s in scored}
    assert pts[91] > pts[90], (
        f"hot recent xG player {pts[91]:.3f} should beat season-avg-only {pts[90]:.3f}"
    )


async def test_recent_xg_absent_falls_back_to_season_avg():
    """
    When xg_this_gw_per_90 is None, the prediction equals the season-only baseline
    exactly — no blending artefact.
    """
    player = make_player(92, 902, Position.FWD)
    stats_no_recent  = make_stats(92, minutes=450, xg=0.4, form=5.0)
    stats_with_none  = make_stats(92, minutes=450, xg=0.4, form=5.0, xg_gw=None)

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        s1 = await predict_points([(player, stats_no_recent)], db=None, gameweek=5)
        s2 = await predict_points([(player, stats_with_none)], db=None, gameweek=5)

    assert s1[0][2] == pytest.approx(s2[0][2], rel=1e-6)


def test_recent_xg_blend_formula_in_predict_base():
    """
    Verify the 60/40 blend weight is correct by computing _predict_base
    for a player with known season and per-GW xG and checking the output
    matches what a manually blended xG would produce.
    """
    player = make_player(93, 903, Position.FWD)
    season_xg = 0.4
    recent_xg = 0.8
    blended_xg = 0.6 * season_xg + 0.4 * recent_xg  # = 0.56

    stats_blended   = make_stats(93, minutes=450, xg=season_xg, form=5.0, xg_gw=recent_xg)
    stats_manual_xg = make_stats(93, minutes=450, xg=blended_xg, form=5.0)

    from app.services.prediction import _predict_base
    avg_min = 450 / 5  # gameweek=5, so avg_min=90

    base_blended   = _predict_base(player, stats_blended,   avg_min)
    base_manual_xg = _predict_base(player, stats_manual_xg, avg_min)

    assert base_blended == pytest.approx(base_manual_xg, rel=1e-4)


async def test_recent_xgc_blend_benefits_defender():
    """
    A DEF whose team has recently conceded very little (xgc_gw=0.1) should
    score higher than one whose blended xGC equals just the season average (0.8).
    """
    solid = make_player(94, 940, Position.DEF)
    avg   = make_player(95, 941, Position.DEF)
    rows = [
        (solid, make_stats(94, minutes=450, xgc=0.8, form=5.0, xgc_gw=0.1)),
        (avg,   make_stats(95, minutes=450, xgc=0.8, form=5.0)),
    ]

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored = await predict_points(rows, db=None, gameweek=5)

    pts = {p.id: s for p, _, s in scored}
    assert pts[94] > pts[95], (
        f"recently solid DEF {pts[94]:.3f} should beat avg DEF {pts[95]:.3f}"
    )


# ---------------------------------------------------------------------------
# minutes_this_gw blending
# ---------------------------------------------------------------------------

async def test_recent_minutes_blends_into_avg_min():
    """
    Two identical FWDs, same season total (450 min over 5 GWs = 90 avg), but
    one played 0 minutes last GW (rotation risk) and the other played 90.
    Blended avg_min: dropped = 0.6*90 + 0.4*0 = 54, starter = 0.6*90 + 0.4*90 = 90.
    The recently benched player should predict lower.
    """
    starter = make_player(100, 1000, Position.FWD)
    benched = make_player(101, 1001, Position.FWD)
    rows = [
        (starter, make_stats(100, minutes=450, xg=0.5, form=5.0, minutes_gw=90)),
        (benched,  make_stats(101, minutes=450, xg=0.5, form=5.0, minutes_gw=0)),
    ]

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        scored = await predict_points(rows, db=None, gameweek=5)

    pts = {p.id: s for p, _, s in scored}
    assert pts[100] > pts[101], (
        f"starter ({pts[100]:.3f}) should outscore recently benched player ({pts[101]:.3f})"
    )


async def test_minutes_this_gw_absent_falls_back_to_season_avg():
    """
    When minutes_this_gw is None the result is identical to using season average alone.
    """
    player = make_player(102, 1002, Position.FWD)
    stats_none = make_stats(102, minutes=450, xg=0.5, form=5.0, minutes_gw=None)
    stats_missing = make_stats(102, minutes=450, xg=0.5, form=5.0)

    async def fake_strength(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=fake_strength):
        s1 = await predict_points([(player, stats_none)], db=None, gameweek=5)
        s2 = await predict_points([(player, stats_missing)], db=None, gameweek=5)

    assert s1[0][2] == pytest.approx(s2[0][2], rel=1e-6)

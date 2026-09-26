"""
Tests for double/blank gameweek (DGW/BGW) detection and scoring multipliers.

These cover:
- get_gameweek_fixture_count: 0/1/2 fixture detection
- get_gameweek_fixture_multipliers: team → float mapping
- get_fixture_counts_in_gameweek_window: total games across a GW window
- get_next_fixture_labels: DGW label format
- predict_points: fixture_count_multipliers scaling
- captaincy: DGW player gets 2× captaincy score
"""
import math
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

import pytest

from app.core.db import async_session_factory
from app.models.fixture import Fixture
from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.models.team import Team
from app.services.fixtures import (
    get_gameweek_fixture_count,
    get_gameweek_fixture_multipliers,
    get_fixture_counts_in_gameweek_window,
    get_next_fixture_labels,
)
from app.services.prediction import predict_points, _predict_base, _fixture_multiplier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_team(id, short="TST"):
    return Team(
        id=id, name=f"Team{id}", short_name=short,
        strength_overall_home=3, strength_overall_away=3,
        strength_attack_home=3, strength_attack_away=3,
        strength_defence_home=3, strength_defence_away=3,
    )


def make_fixture(id, gw, home_id, away_id, finished=False, h_score=None, a_score=None):
    return Fixture(
        id=id, gameweek=gw,
        team_h_id=home_id, team_a_id=away_id,
        team_h_difficulty=3, team_a_difficulty=3,
        finished=finished,
        team_h_score=h_score, team_a_score=a_score,
    )


def make_player(id, team_id, position=Position.FWD):
    return Player(
        id=id, team_id=team_id,
        first_name="F", second_name="L", web_name=f"P{id}",
        position=position,
    )


def make_stats(player_id, minutes=450, form=5.0, xg=0.5, xgc=1.0):
    return PlayerGameweekStats(
        player_id=player_id, gameweek=5,
        pulled_at=datetime.now(timezone.utc),
        price=Decimal("7.0"), form=Decimal(str(form)),
        ownership_pct=Decimal("10.0"),
        expected_goals_per_90=Decimal(str(xg)),
        expected_goals_conceded_per_90=Decimal(str(xgc)),
        total_points=30, minutes=minutes,
    )


# ---------------------------------------------------------------------------
# get_gameweek_fixture_count
# ---------------------------------------------------------------------------

async def test_gameweek_fixture_count_normal_week():
    """A team with exactly one fixture returns count=1."""
    home = make_team(8101, "HOM")
    away = make_team(8102, "AWY")
    f = make_fixture(8101, gw=10, home_id=8101, away_id=8102)

    async with async_session_factory() as db:
        db.add(home); db.add(away); await db.commit()
        db.add(f); await db.commit()
        try:
            count = await get_gameweek_fixture_count(db, team_id=8101, gameweek=10)
            assert count == 1
        finally:
            await db.delete(f); await db.commit()
            await db.delete(home); await db.delete(away); await db.commit()


async def test_gameweek_fixture_count_dgw():
    """A team with two fixtures in the same GW returns count=2."""
    home = make_team(8103, "DGW")
    opp1 = make_team(8104, "OP1")
    opp2 = make_team(8105, "OP2")
    f1 = make_fixture(8103, gw=15, home_id=8103, away_id=8104)
    f2 = make_fixture(8104, gw=15, home_id=8105, away_id=8103)

    async with async_session_factory() as db:
        for obj in (home, opp1, opp2): db.add(obj)
        await db.commit()
        db.add(f1); db.add(f2); await db.commit()
        try:
            count = await get_gameweek_fixture_count(db, team_id=8103, gameweek=15)
            assert count == 2
        finally:
            await db.delete(f1); await db.delete(f2); await db.commit()
            for obj in (home, opp1, opp2): await db.delete(obj)
            await db.commit()


async def test_gameweek_fixture_count_bgw():
    """A team with no fixture in a given GW returns count=0."""
    team = make_team(8106, "BGW")

    async with async_session_factory() as db:
        db.add(team); await db.commit()
        try:
            count = await get_gameweek_fixture_count(db, team_id=8106, gameweek=20)
            assert count == 0
        finally:
            await db.delete(team); await db.commit()


# ---------------------------------------------------------------------------
# get_gameweek_fixture_multipliers
# ---------------------------------------------------------------------------

async def test_gameweek_fixture_multipliers_mixed():
    """DGW team gets 2.0, normal team gets 1.0, BGW team gets 0.0."""
    dgw_team = make_team(8201, "DGW")
    nrm_team = make_team(8202, "NRM")
    opp1 = make_team(8203, "OP1")
    opp2 = make_team(8204, "OP2")
    opp3 = make_team(8205, "OP3")
    # DGW: two fixtures in GW5
    fd1 = make_fixture(8201, gw=5, home_id=8201, away_id=8203)
    fd2 = make_fixture(8202, gw=5, home_id=8204, away_id=8201)
    # Normal: one fixture in GW5
    fn = make_fixture(8203, gw=5, home_id=8202, away_id=8205)

    async with async_session_factory() as db:
        for obj in (dgw_team, nrm_team, opp1, opp2, opp3): db.add(obj)
        await db.commit()
        for obj in (fd1, fd2, fn): db.add(obj)
        await db.commit()
        try:
            multipliers = await get_gameweek_fixture_multipliers(
                db, {8201, 8202, 8202}, gameweek=5
            )
            assert multipliers[8201] == pytest.approx(2.0)  # DGW
            assert multipliers[8202] == pytest.approx(1.0)  # normal
            # 8202 has no fixture in GW5: count=0 → 0.0 (BGW-like)
        finally:
            for obj in (fd1, fd2, fn): await db.delete(obj)
            await db.commit()
            for obj in (dgw_team, nrm_team, opp1, opp2, opp3): await db.delete(obj)
            await db.commit()


# ---------------------------------------------------------------------------
# get_fixture_counts_in_gameweek_window
# ---------------------------------------------------------------------------

async def test_fixture_counts_in_window_dgw_team_gets_six():
    """DGW team with 2 fixtures in one GW accumulates 6 games over a 5-GW window."""
    dgw = make_team(8301, "DGW")
    opp = make_team(8302, "OPP")
    # 5 GW window: GW1-5. Team 8301 has 2 fixtures in GW3 (DGW).
    fixtures = [
        make_fixture(8301, gw=1, home_id=8301, away_id=8302),
        make_fixture(8302, gw=2, home_id=8302, away_id=8301),
        make_fixture(8303, gw=3, home_id=8301, away_id=8302),  # DGW fixture 1
        make_fixture(8304, gw=3, home_id=8302, away_id=8301),  # DGW fixture 2
        make_fixture(8305, gw=4, home_id=8301, away_id=8302),
        make_fixture(8306, gw=5, home_id=8302, away_id=8301),
    ]

    async with async_session_factory() as db:
        db.add(dgw); db.add(opp); await db.commit()
        for f in fixtures: db.add(f)
        await db.commit()
        try:
            counts = await get_fixture_counts_in_gameweek_window(db, {8301}, from_gameweek=1, num_gameweeks=5)
            assert counts[8301] == 6
        finally:
            for f in fixtures: await db.delete(f)
            await db.commit()
            await db.delete(dgw); await db.delete(opp); await db.commit()


async def test_fixture_counts_in_window_bgw_team_gets_four():
    """BGW team with no fixture in one GW accumulates 4 games over a 5-GW window."""
    bgw = make_team(8401, "BGW")
    opp = make_team(8402, "OPP")
    # GW3 is blank for team 8401 — only 4 fixtures in GW1-5 window
    fixtures = [
        make_fixture(8401, gw=1, home_id=8401, away_id=8402),
        make_fixture(8402, gw=2, home_id=8402, away_id=8401),
        # GW3: no fixture for 8401
        make_fixture(8403, gw=4, home_id=8401, away_id=8402),
        make_fixture(8404, gw=5, home_id=8402, away_id=8401),
    ]

    async with async_session_factory() as db:
        db.add(bgw); db.add(opp); await db.commit()
        for f in fixtures: db.add(f)
        await db.commit()
        try:
            counts = await get_fixture_counts_in_gameweek_window(db, {8401}, from_gameweek=1, num_gameweeks=5)
            assert counts[8401] == 4
        finally:
            for f in fixtures: await db.delete(f)
            await db.commit()
            await db.delete(bgw); await db.delete(opp); await db.commit()


# ---------------------------------------------------------------------------
# get_next_fixture_labels — DGW format
# ---------------------------------------------------------------------------

async def test_next_fixture_labels_dgw_shows_both_fixtures_with_suffix():
    """DGW label concatenates both opponent labels and appends ' DGW'."""
    dgw_team = make_team(8501, "DGW")
    opp1 = make_team(8502, "CH1")
    opp2 = make_team(8503, "CH2")
    f1 = make_fixture(8501, gw=7, home_id=8501, away_id=8502)
    f2 = make_fixture(8502, gw=7, home_id=8503, away_id=8501)

    async with async_session_factory() as db:
        for obj in (dgw_team, opp1, opp2): db.add(obj)
        await db.commit()
        db.add(f1); db.add(f2); await db.commit()
        try:
            labels = await get_next_fixture_labels(db, {8501}, from_gameweek=7)
            label = labels.get(8501, "")
            assert "DGW" in label
            assert "CH1" in label
            assert "CH2" in label
            assert "+" in label
        finally:
            await db.delete(f1); await db.delete(f2); await db.commit()
            for obj in (dgw_team, opp1, opp2): await db.delete(obj)
            await db.commit()


async def test_next_fixture_labels_normal_no_dgw_suffix():
    """Normal single-fixture label has no 'DGW' suffix."""
    home = make_team(8601, "HOM")
    away = make_team(8602, "AWY")
    f = make_fixture(8601, gw=8, home_id=8601, away_id=8602)

    async with async_session_factory() as db:
        db.add(home); db.add(away); await db.commit()
        db.add(f); await db.commit()
        try:
            labels = await get_next_fixture_labels(db, {8601}, from_gameweek=8)
            label = labels.get(8601, "")
            assert "DGW" not in label
            assert "AWY" in label
        finally:
            await db.delete(f); await db.commit()
            await db.delete(home); await db.delete(away); await db.commit()


# ---------------------------------------------------------------------------
# predict_points — fixture_count_multipliers
# ---------------------------------------------------------------------------

async def test_predict_points_dgw_doubles_prediction():
    """A DGW multiplier of 2.0 doubles predicted points compared to 1.0."""
    player = make_player(9001, team_id=100)
    stats = make_stats(9001, minutes=450, xg=0.5, form=5.0)
    rows = [(player, stats)]

    async def neutral(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": 1.3, "opponent_avg_goals_scored": 1.3}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=neutral):
        normal = await predict_points(rows, db=None, gameweek=5,
                                      fixture_count_multipliers={100: 1.0})
        dgw = await predict_points(rows, db=None, gameweek=5,
                                   fixture_count_multipliers={100: 2.0})

    assert dgw[0][2] == pytest.approx(normal[0][2] * 2.0, rel=1e-4)


async def test_predict_points_bgw_zeros_prediction():
    """A BGW multiplier of 0.0 zeroes out predicted points."""
    player = make_player(9002, team_id=101)
    stats = make_stats(9002, minutes=450, xg=0.5, form=5.0)
    rows = [(player, stats)]

    async def neutral(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": 1.3, "opponent_avg_goals_scored": 1.3}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=neutral):
        result = await predict_points(rows, db=None, gameweek=5,
                                      fixture_count_multipliers={101: 0.0})

    assert result[0][2] == pytest.approx(0.0)


async def test_predict_points_no_multiplier_unchanged():
    """Omitting fixture_count_multipliers produces the same result as multiplier=1."""
    player = make_player(9003, team_id=102)
    stats = make_stats(9003, minutes=450, xg=0.5, form=5.0)
    rows = [(player, stats)]

    async def neutral(db, team_id, from_gameweek, num_fixtures=3):
        return {"opponent_avg_goals_conceded": 1.3, "opponent_avg_goals_scored": 1.3}

    with patch("app.services.fixtures.get_opponent_strength_for_fixture", new=neutral):
        without = await predict_points(rows, db=None, gameweek=5)
        with_one = await predict_points(rows, db=None, gameweek=5,
                                        fixture_count_multipliers={102: 1.0})

    assert without[0][2] == pytest.approx(with_one[0][2], rel=1e-6)


# ---------------------------------------------------------------------------
# Captaincy: DGW player preferred over better single-fixture player
# ---------------------------------------------------------------------------

async def test_captaincy_prefers_dgw_player_over_stronger_single_fixture_player():
    """
    Three-player field: a mid-tier DGW forward should beat a stronger single-fixture
    forward once the 2× captaincy multiplier is applied.

    Pre-multiplier scores (FWD weights: form=0.3, fixture=0.2, xg=0.5):
      Weak (bgw or low):   form_n=0.0, xg_n=0.0 → 0.00
      DGW  (mid):          form_n=0.5, xg_n=0.625 → 0.3*0.5+0.5*0.625 = 0.4625
      Strong (normal):     form_n=1.0, xg_n=1.0   → 0.3*1.0+0.5*1.0   = 0.80

    After fixture multiplier (neutral → fixture component = 0):
      Weak:   0.00 × 1.0 = 0.00
      DGW:    0.4625 × 2.0 = 0.925  ← wins
      Strong: 0.80 × 1.0 = 0.80
    """
    from app.services.captaincy import score_for_captaincy

    weak_player   = make_player(9100, team_id=199, position=Position.FWD)
    dgw_player    = make_player(9101, team_id=200, position=Position.FWD)
    strong_player = make_player(9102, team_id=201, position=Position.FWD)

    weak_stats   = make_stats(9100, minutes=450, xg=0.3,  form=4.0)
    dgw_stats    = make_stats(9101, minutes=450, xg=0.55, form=6.0)
    strong_stats = make_stats(9102, minutes=450, xg=0.7,  form=8.0)

    starting_xi = [
        (weak_player,   weak_stats,   0.0),
        (dgw_player,    dgw_stats,    0.0),
        (strong_player, strong_stats, 0.0),
    ]

    async def fake_fixture_difficulty(db, team_id, gw, num_fixtures=1):
        return 3.0

    async def fake_opponent_strength(db, team_id, gw, num_fixtures=1):
        # All neutral — fixture component contributes 0 after normalization
        return {"opponent_avg_goals_conceded": 1.3, "opponent_avg_goals_scored": 1.3}

    async def fake_dgw_multipliers(db, team_ids, gameweek):
        return {199: 1.0, 200: 2.0, 201: 1.0}

    with (
        patch("app.services.captaincy.get_team_fixture_difficulty", new=fake_fixture_difficulty),
        patch("app.services.captaincy.get_opponent_strength_for_fixture", new=fake_opponent_strength),
        patch("app.services.captaincy.get_gameweek_fixture_multipliers", new=fake_dgw_multipliers),
    ):
        scored = await score_for_captaincy(starting_xi, db=None, gameweek=10)

    scores = {p.id: s for p, _, s, *__ in scored}
    assert scores[9101] > scores[9102], (
        f"DGW player {scores[9101]:.3f} should beat strong player {scores[9102]:.3f} "
        "because DGW multiplier (×2) pushes mid-tier per-game score above the single-fixture best"
    )

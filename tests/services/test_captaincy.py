from decimal import Decimal
from datetime import datetime, timezone

from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.services.captaincy import get_captain_recommendation


def make_entry(id, position, score, team_id=9001, ownership_pct=None):
    player = Player(id=id, team_id=team_id, first_name="F", second_name="L", web_name=f"P{id}", position=position)
    if ownership_pct is not None:
        stats = PlayerGameweekStats(
            player_id=id, gameweek=5, pulled_at=datetime.now(timezone.utc),
            price=Decimal("5.0"), form=Decimal("5.0"),
            ownership_pct=Decimal(str(ownership_pct)),
            total_points=30, minutes=450,
        )
    else:
        stats = None
    return (player, stats, score)


def test_captain_recommendation_single_player_safe():
    """With only one player, second_pick, tie_broken_by_ceiling, and advantage_pct
    must still be present — the API route accesses them unconditionally."""
    scored = [make_entry(1, Position.FWD, 0.7)]
    rec = get_captain_recommendation(scored)
    assert rec["top_pick"]["player"].id == 1
    assert "second_pick" in rec
    assert "tie_broken_by_ceiling" in rec
    assert "advantage_pct" in rec
    assert rec["tie_broken_by_ceiling"] is False
    assert rec["advantage_pct"] is None


def test_higher_score_wins_captaincy_outright():
    scored = [
        make_entry(1, Position.FWD, 0.8),
        make_entry(2, Position.MID, 0.6),
    ]
    rec = get_captain_recommendation(scored)
    assert rec["top_pick"]["player"].id == 1
    assert rec["second_pick"]["player"].id == 2
    assert rec["tie_broken_by_ceiling"] is False


def test_tied_scores_broken_by_ceiling_forward_beats_defender():
    scored = [
        make_entry(1, Position.DEF, 0.7),
        make_entry(2, Position.FWD, 0.7),
    ]
    rec = get_captain_recommendation(scored)
    assert rec["top_pick"]["player"].id == 2
    assert rec["tie_broken_by_ceiling"] is True


def test_three_way_tie_flags_correctly_even_when_top_two_not_tied_with_each_other():
    scored = [
        make_entry(1, Position.FWD, 0.9),
        make_entry(2, Position.DEF, 0.7),
        make_entry(3, Position.MID, 0.7),
    ]
    rec = get_captain_recommendation(scored)
    assert rec["top_pick"]["player"].id == 1
    assert rec["second_pick"]["player"].id == 3
    assert rec["tie_broken_by_ceiling"] is True


def test_rating_scale_is_out_of_100():
    scored = [
        make_entry(1, Position.FWD, 0.784),
        make_entry(2, Position.MID, 0.5),
    ]
    rec = get_captain_recommendation(scored)
    assert rec["top_pick"]["rating"] == 78


async def test_pick_captain_wires_scoring_and_selects_top(monkeypatch):
    from app.services.captaincy import pick_captain

    async def fake_score_for_captaincy(starting_xi, db, gameweek):
        return [
            make_entry(1, Position.FWD, 0.9),
            make_entry(2, Position.MID, 0.5),
        ]

    class FakeSessionContext:
        async def __aenter__(self):
            return "fake_db"

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.services.captaincy.score_for_captaincy", fake_score_for_captaincy)
    monkeypatch.setattr("app.services.captaincy.async_session_factory", lambda: FakeSessionContext())

    top_player, top_stats, top_score = await pick_captain(starting_xi=[], gameweek=4)

    assert top_player.id == 1
    assert top_score == 0.9


def test_advantage_pct_is_none_when_second_place_score_is_zero():
    scored = [
        make_entry(1, Position.FWD, 0.5),
        make_entry(2, Position.MID, 0.0),
    ]
    rec = get_captain_recommendation(scored)
    assert rec["advantage_pct"] is None


# ---------------------------------------------------------------------------
# Differential captain option (fix #9)
# ---------------------------------------------------------------------------

def test_differential_captain_surfaces_low_owned_competitive_alternative():
    """
    When the top pick is widely owned (>15%) and another player has:
      - captaincy score ≥ 70% of the top score
      - ownership < 15%
    then differential_captain should be that player.
    """
    # Template captain: 0.8 score, 55% owned
    template = make_entry(1, Position.FWD, 0.8, ownership_pct=55.0)
    # Differential: 0.65 score (81% of 0.8 ≥ 70%), 8% owned
    diff = make_entry(2, Position.MID, 0.65, ownership_pct=8.0)
    # Other template pick: 0.5 score, 30% owned — not differential
    other = make_entry(3, Position.DEF, 0.5, ownership_pct=30.0)

    rec = get_captain_recommendation([template, diff, other])

    assert rec["top_pick"]["player"].id == 1
    assert rec["differential_captain"] is not None
    assert rec["differential_captain"][0].id == 2


def test_no_differential_when_top_pick_is_already_differential():
    """
    If the recommended captain is already low-owned (<15%), there's no need
    to surface a separate differential option.
    """
    differential_cap = make_entry(1, Position.FWD, 0.8, ownership_pct=9.0)
    runner_up = make_entry(2, Position.MID, 0.6, ownership_pct=40.0)

    rec = get_captain_recommendation([differential_cap, runner_up])

    assert rec["top_pick"]["player"].id == 1
    assert rec["differential_captain"] is None


def test_no_differential_when_low_owned_player_score_too_low():
    """
    A low-owned player with score < 70% of the top pick's score isn't
    competitive enough to surface as a differential.
    """
    template = make_entry(1, Position.FWD, 0.8, ownership_pct=55.0)
    # 0.5 / 0.8 = 62.5% < 70% threshold
    weak_diff = make_entry(2, Position.MID, 0.5, ownership_pct=5.0)

    rec = get_captain_recommendation([template, weak_diff])

    assert rec["differential_captain"] is None


def test_no_differential_when_stats_missing():
    """
    make_entry with no ownership_pct passes stats=None.
    get_captain_recommendation should not crash and returns None for differential.
    """
    scored = [
        make_entry(1, Position.FWD, 0.8),
        make_entry(2, Position.MID, 0.6),
    ]
    rec = get_captain_recommendation(scored)
    assert rec["differential_captain"] is None


def test_differential_picks_highest_scoring_qualifying_player():
    """
    When multiple players qualify as differential, the highest-scoring one
    is selected (not just the first in the list).
    """
    template = make_entry(1, Position.FWD, 0.9, ownership_pct=60.0)
    # Both qualify: score ≥ 70% of 0.9 = 0.63, ownership < 15%
    diff_weaker = make_entry(2, Position.MID, 0.65, ownership_pct=10.0)
    diff_stronger = make_entry(3, Position.MID, 0.75, ownership_pct=7.0)

    rec = get_captain_recommendation([template, diff_weaker, diff_stronger])

    assert rec["differential_captain"] is not None
    # Should pick the higher-scoring one (id=3, score=0.75 > id=2, score=0.65)
    assert rec["differential_captain"][0].id == 3

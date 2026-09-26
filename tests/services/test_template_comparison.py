"""
Tests for template_comparison.py — all pure functions, no DB required.
"""
import pytest

from app.models.player import Position
from app.services.template_comparison import (
    DIFFERENTIAL_THRESHOLD,
    TEMPLATE_THRESHOLD,
    classify_player,
    compute_template_divergence,
    build_template_comparison,
)


# ── classify_player ───────────────────────────────────────────────────────────

def test_classify_template():
    assert classify_player(20.0) == "template"
    assert classify_player(55.0) == "template"
    assert classify_player(100.0) == "template"


def test_classify_differential():
    assert classify_player(0.0) == "differential"
    assert classify_player(5.5) == "differential"
    assert classify_player(9.9) == "differential"


def test_classify_core():
    assert classify_player(10.0) == "core"
    assert classify_player(15.0) == "core"
    assert classify_player(19.9) == "core"


def test_classify_none_returns_unknown():
    assert classify_player(None) == "unknown"


def test_thresholds_are_boundary_correct():
    # Exactly at TEMPLATE_THRESHOLD → template
    assert classify_player(TEMPLATE_THRESHOLD) == "template"
    # Just below → core
    assert classify_player(TEMPLATE_THRESHOLD - 0.1) == "core"
    # Exactly at DIFFERENTIAL_THRESHOLD → core (< required for differential)
    assert classify_player(DIFFERENTIAL_THRESHOLD) == "core"
    # Just below → differential
    assert classify_player(DIFFERENTIAL_THRESHOLD - 0.1) == "differential"


# ── compute_template_divergence ───────────────────────────────────────────────

def _player(pos, ownership):
    return {"position": pos, "ownership_pct": ownership}


def test_all_template_squad_gives_low_divergence():
    players = [_player(Position.MID, 60.0)] * 5
    score = compute_template_divergence(players)
    assert score < 50.0


def test_all_differential_squad_gives_high_divergence():
    players = [_player(Position.MID, 1.0)] * 5
    score = compute_template_divergence(players)
    assert score > 90.0


def test_empty_list_returns_zero():
    assert compute_template_divergence([]) == 0.0


def test_none_ownership_players_excluded():
    players = [
        _player(Position.MID, None),
        _player(Position.MID, 5.0),
    ]
    score_with_none = compute_template_divergence(players)
    score_without_none = compute_template_divergence([_player(Position.MID, 5.0)])
    # None players are excluded from calculation, so both scores reflect only the 5% player
    assert score_with_none == pytest.approx(score_without_none)


def test_forwards_weighted_higher_than_defenders():
    # Same ownership — FWD should contribute more to divergence than DEF
    fwd = [_player(Position.FWD, 5.0)]
    def_ = [_player(Position.DEF, 5.0)]
    # Single-player squads: divergence reflects the position weight
    # DEF weight 0.8, FWD weight 1.5 — both have same raw divergence per player
    # but their contribution to the normalised score should be the same when alone
    # (normalised by that single player's weight). So scores are equal for single-player.
    # Test instead with mixed squads: FWD differential should push score higher.
    mixed_fwd_diff = [_player(Position.FWD, 5.0), _player(Position.DEF, 50.0)]
    mixed_def_diff = [_player(Position.DEF, 5.0), _player(Position.FWD, 50.0)]
    # FWD differential squad should have higher divergence score
    assert compute_template_divergence(mixed_fwd_diff) > compute_template_divergence(mixed_def_diff)


def test_score_is_between_0_and_100():
    players = [
        _player(Position.FWD, 0.5),
        _player(Position.MID, 80.0),
        _player(Position.DEF, 15.0),
    ]
    score = compute_template_divergence(players)
    assert 0.0 <= score <= 100.0


# ── build_template_comparison ─────────────────────────────────────────────────

def _squad_player(id, pos, ownership, name="P", team="TST"):
    return {
        "id": id,
        "web_name": name,
        "position": pos,
        "ownership_pct": ownership,
        "team_short_name": team,
    }


def test_build_adds_classification_to_each_player():
    players = [
        _squad_player(1, Position.MID, 5.0),   # differential
        _squad_player(2, Position.MID, 15.0),  # core
        _squad_player(3, Position.MID, 40.0),  # template
    ]
    result = build_template_comparison(players)
    classifications = {p["id"]: p["classification"] for p in result["players"]}
    assert classifications[1] == "differential"
    assert classifications[2] == "core"
    assert classifications[3] == "template"


def test_build_differentials_list_sorted_by_ownership_asc():
    players = [
        _squad_player(1, Position.MID, 8.0),
        _squad_player(2, Position.MID, 2.0),
        _squad_player(3, Position.MID, 5.0),
    ]
    result = build_template_comparison(players)
    owned = [p["ownership_pct"] for p in result["differentials"]]
    assert owned == sorted(owned)


def test_build_template_picks_sorted_by_ownership_desc():
    players = [
        _squad_player(1, Position.MID, 25.0),
        _squad_player(2, Position.MID, 60.0),
        _squad_player(3, Position.MID, 40.0),
    ]
    result = build_template_comparison(players)
    owned = [p["ownership_pct"] for p in result["template_picks"]]
    assert owned == sorted(owned, reverse=True)


def test_build_by_position_counts_correctly():
    players = [
        _squad_player(1, Position.MID, 5.0),   # differential
        _squad_player(2, Position.MID, 40.0),  # template
        _squad_player(3, Position.DEF, 15.0),  # core
    ]
    result = build_template_comparison(players)
    assert result["by_position"]["MID"]["differential"] == 1
    assert result["by_position"]["MID"]["template"] == 1
    assert result["by_position"]["DEF"]["core"] == 1


def test_build_divergence_score_present():
    players = [_squad_player(1, Position.MID, 5.0)]
    result = build_template_comparison(players)
    assert "divergence_score" in result
    assert isinstance(result["divergence_score"], float)


def test_build_empty_squad_returns_zero_divergence():
    result = build_template_comparison([])
    assert result["divergence_score"] == 0.0
    assert result["differentials"] == []
    assert result["template_picks"] == []

from app.models.player import Player, Position
from app.services.lineup import analyse_bench_coverage


def _player(pos: Position):
    return Player(id=pos.value, team_id=1, first_name="F", second_name="L",
                  web_name="X", position=pos)


def _xi(defs=4, mids=4, fwds=2):
    """Build a minimal starting XI tuple list for the given outfield counts."""
    entries = [(_player(Position.GKP), None, 5.0)]
    entries += [(_player(Position.DEF), None, 5.0)] * defs
    entries += [(_player(Position.MID), None, 5.0)] * mids
    entries += [(_player(Position.FWD), None, 5.0)] * fwds
    return entries


def test_all_positions_covered_when_bench_has_each_outfield_position():
    xi = _xi(4, 4, 2)
    bench = [
        (_player(Position.DEF), None, 3.0),
        (_player(Position.MID), None, 3.0),
        (_player(Position.FWD), None, 3.0),
    ]
    result = analyse_bench_coverage(xi, bench)
    assert result["uncovered_positions"] == []
    assert result["warning"] is None


def test_uncovered_fwd_when_bench_has_no_forward_and_xi_at_minimum():
    """XI has only 1 FWD (minimum), bench has no FWD → uncovered."""
    xi = _xi(5, 4, 1)
    bench = [
        (_player(Position.DEF), None, 3.0),
        (_player(Position.MID), None, 3.0),
    ]
    result = analyse_bench_coverage(xi, bench)
    assert "FWD" in result["uncovered_positions"]
    assert result["warning"] is not None


def test_fwd_covered_when_above_minimum_even_without_bench_fwd():
    """XI has 2 FWDs (above minimum of 1). Losing one still leaves legal formation → covered."""
    xi = _xi(4, 4, 2)
    bench = [
        (_player(Position.DEF), None, 3.0),
        (_player(Position.MID), None, 3.0),
    ]
    result = analyse_bench_coverage(xi, bench)
    assert "FWD" not in result["uncovered_positions"]


def test_uncovered_def_when_bench_has_no_defender_and_xi_at_three():
    """XI has 3 DEF (minimum), bench has no DEF → uncovered."""
    xi = _xi(3, 5, 2)
    bench = [
        (_player(Position.MID), None, 3.0),
        (_player(Position.FWD), None, 3.0),
    ]
    result = analyse_bench_coverage(xi, bench)
    assert "DEF" in result["uncovered_positions"]


def test_empty_bench_flags_positions_at_minimum():
    """An empty outfield bench should flag any position at its minimum count."""
    xi = _xi(3, 5, 2)
    result = analyse_bench_coverage(xi, [])
    assert "DEF" in result["uncovered_positions"]
    assert result["warning"] is not None

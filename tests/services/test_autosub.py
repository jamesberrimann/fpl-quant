from app.models.player import Player, Position
from app.services.autosub import simulate_autosubstitutions


def _p(pid, pos: Position):
    return Player(id=pid, team_id=1, first_name="F", second_name="L",
                  web_name=f"P{pid}", position=pos)


def _e(pid, pos):
    return (_p(pid, pos), None, 5.0)


def _xi_442():
    """1 GKP, 4 DEF, 4 MID, 2 FWD — all played."""
    return [
        _e(1,  Position.GKP),
        _e(2,  Position.DEF), _e(3,  Position.DEF), _e(4,  Position.DEF), _e(5,  Position.DEF),
        _e(6,  Position.MID), _e(7,  Position.MID), _e(8,  Position.MID), _e(9,  Position.MID),
        _e(10, Position.FWD), _e(11, Position.FWD),
    ]


def _all_played(xi, bench_gk, bench_out):
    ids = [e[0].id for e in xi]
    if bench_gk:
        ids.append(bench_gk[0].id)
    ids += [e[0].id for e in bench_out]
    return {pid: 90 for pid in ids}


def test_no_subs_when_all_starters_played():
    xi = _xi_442()
    bench_gk = _e(12, Position.GKP)
    bench_out = [_e(13, Position.DEF), _e(14, Position.MID), _e(15, Position.FWD)]
    mins = _all_played(xi, bench_gk, bench_out)

    result = simulate_autosubstitutions(xi, bench_gk, bench_out, mins)
    assert result["substitutions"] == []
    assert result["unresolved_absences"] == []
    assert len(result["effective_xi"]) == 11


def test_outfield_absent_starter_replaced_by_first_bench_player():
    xi = _xi_442()
    bench_gk = _e(12, Position.GKP)
    bench_out = [_e(13, Position.MID), _e(14, Position.MID), _e(15, Position.FWD)]
    mins = _all_played(xi, bench_gk, bench_out)
    mins[6] = 0  # MID starter absent

    result = simulate_autosubstitutions(xi, bench_gk, bench_out, mins)
    assert len(result["substitutions"]) == 1
    assert result["substitutions"][0]["out"].id == 6
    assert result["substitutions"][0]["in"].id == 13


def test_bench_player_skipped_if_also_absent():
    xi = _xi_442()
    bench_gk = _e(12, Position.GKP)
    bench_out = [_e(13, Position.MID), _e(14, Position.MID), _e(15, Position.FWD)]
    mins = _all_played(xi, bench_gk, bench_out)
    mins[6] = 0    # starter absent
    mins[13] = 0   # bench_1 also absent → skip to bench_2

    result = simulate_autosubstitutions(xi, bench_gk, bench_out, mins)
    assert result["substitutions"][0]["in"].id == 14


def test_formation_legality_prevents_sub_that_breaks_minimum_def():
    """If the starting XI has exactly 3 DEF and bench has only DEF to offer, it still works.
    But if the absent player is a DEF and bench has no DEF, the sub of a FWD would make
    only 2 DEF → illegal → skip."""
    # 3 DEF, 5 MID, 2 FWD
    xi = [
        _e(1, Position.GKP),
        _e(2, Position.DEF), _e(3, Position.DEF), _e(4, Position.DEF),
        _e(5, Position.MID), _e(6, Position.MID), _e(7, Position.MID),
        _e(8, Position.MID), _e(9, Position.MID),
        _e(10, Position.FWD), _e(11, Position.FWD),
    ]
    bench_gk = _e(12, Position.GKP)
    # Bench has only a FWD — subbing in would leave 2 DEF (illegal)
    bench_out = [_e(13, Position.FWD)]
    mins = _all_played(xi, bench_gk, bench_out)
    mins[4] = 0  # DEF absent

    result = simulate_autosubstitutions(xi, bench_gk, bench_out, mins)
    assert result["substitutions"] == []
    assert len(result["unresolved_absences"]) == 1
    assert result["unresolved_absences"][0].id == 4


def test_gkp_replaced_by_bench_gkp():
    xi = _xi_442()
    bench_gk = _e(12, Position.GKP)
    bench_out = [_e(13, Position.DEF)]
    mins = _all_played(xi, bench_gk, bench_out)
    mins[1] = 0  # starting GKP absent

    result = simulate_autosubstitutions(xi, bench_gk, bench_out, mins)
    assert any(s["out"].id == 1 and s["in"].id == 12 for s in result["substitutions"])


def test_unresolved_when_no_eligible_bench_player():
    xi = _xi_442()
    bench_gk = _e(12, Position.GKP)
    bench_out = [_e(13, Position.MID)]
    mins = _all_played(xi, bench_gk, bench_out)
    mins[10] = 0   # FWD absent
    mins[13] = 0   # only bench outfield player also absent

    result = simulate_autosubstitutions(xi, bench_gk, bench_out, mins)
    assert len(result["unresolved_absences"]) == 1
    assert result["unresolved_absences"][0].id == 10

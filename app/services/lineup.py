import math

from app.models.player import Position

VALID_FORMATIONS = [
    (3, 4, 3), (3, 5, 2),
    (4, 3, 3), (4, 4, 2), (4, 5, 1),
    (5, 2, 3), (5, 3, 2), (5, 4, 1),
]


def pick_best_starting_xi(squad):
    by_position = {Position.GKP: [], Position.DEF: [], Position.MID: [], Position.FWD: []}
    for player, stats, score in squad:
        by_position[player.position].append((player, stats, score))

    for pos in by_position:
        by_position[pos].sort(key=lambda x: x[2], reverse=True)

    gk = by_position[Position.GKP][:1]

    best_lineup = None
    best_total = -1.0

    for def_count, mid_count, fwd_count in VALID_FORMATIONS:
        if (len(by_position[Position.DEF]) < def_count
                or len(by_position[Position.MID]) < mid_count
                or len(by_position[Position.FWD]) < fwd_count):
            continue

        lineup = (
            gk
            + by_position[Position.DEF][:def_count]
            + by_position[Position.MID][:mid_count]
            + by_position[Position.FWD][:fwd_count]
        )
        total = sum(score for _, _, score in lineup)

        if total > best_total:
            best_total = total
            best_lineup = lineup

    starting_ids = {player.id for player, _, _ in best_lineup}
    bench = [(p, s, sc) for p, s, sc in squad if p.id not in starting_ids]

    bench_gk = next((entry for entry in bench if entry[0].position == Position.GKP), None)
    bench_outfield = sorted(
        (entry for entry in bench if entry[0].position != Position.GKP),
        key=lambda x: x[2],
        reverse=True,
    )

    return {
        "starting_xi": best_lineup,
        "total_score": best_total,
        "bench_gk": bench_gk,
        "bench_outfield": bench_outfield,
    }


def analyse_bench_coverage(starting_xi, bench_outfield) -> dict:
    """
    Given the starting XI and outfield bench players, returns which starting
    positions are covered (a valid substitute exists) and which are not.

    FPL's minimum legal formation is 1 GKP, 3 DEF, 2 MID, 1 FWD.  A position
    is "covered" when the bench contains at least one player of that position,
    so that any single starter absence still leaves a legal XI.

    Only outfield positions are checked — the bench GKP is always assumed present.
    """
    from collections import Counter

    start_counts = Counter(
        p.position for p, _, _ in starting_xi if p.position != Position.GKP
    )
    bench_positions = {p.position for p, _, _ in bench_outfield}

    # Minimum legal outfield counts after a player drops out
    _MIN = {Position.DEF: 3, Position.MID: 2, Position.FWD: 1}

    covered, uncovered = [], []
    for pos, count in start_counts.items():
        at_minimum = count <= _MIN.get(pos, 0)
        if at_minimum and pos not in bench_positions:
            uncovered.append(pos.value)
        else:
            covered.append(pos.value)

    warning = None
    if uncovered:
        names = " and ".join(uncovered)
        warning = f"No bench cover for {names} — an injury or suspension could leave you unable to field a legal XI."

    return {
        "covered_positions": sorted(covered),
        "uncovered_positions": sorted(uncovered),
        "warning": warning,
    }


async def _rescore_gkps_by_fixture(gkps, db, gameweek: int):
    """
    Re-score GKPs for single-GW start selection using a blended CS lambda:
    70% opponent attack (fixture ease) + 30% team xGC (defensive quality).

    Consistent with the squad scoring model — fixture dominates but a leaky
    defence lowers CS probability even against a weak opponent.
    Falls back to composite predict_points score if no fixture data is available.
    """
    from app.services.fixtures import get_opponent_strength_for_fixture

    _PL_AVG_GOALS = 1.3

    strengths = []
    for player, _, _ in gkps:
        s = await get_opponent_strength_for_fixture(db, player.team_id, gameweek, num_fixtures=1)
        strengths.append(s)

    lambdas = []
    for (player, stats, _), strength in zip(gkps, strengths):
        opp_goals = strength["opponent_avg_goals_scored"]
        if opp_goals is not None:
            raw_xgc = stats.expected_goals_conceded_per_90 if stats is not None else None
            xgc = float(raw_xgc or _PL_AVG_GOALS)
            lambdas.append(math.sqrt(max(opp_goals, 0.1) * max(xgc, 0.1)))
        else:
            lambdas.append(None)

    valid = [l for l in lambdas if l is not None]
    if not valid:
        return gkps

    lo, hi = min(valid), max(valid)

    rescored = []
    for (player, stats, composite), lam in zip(gkps, lambdas):
        if lam is not None:
            fixture_score = 1.0 - ((lam - lo) / (hi - lo) if hi > lo else 0.5)
        else:
            fixture_score = composite
        rescored.append((player, stats, fixture_score))

    return rescored


async def pick_best_starting_xi_for_entry(entry_id: int, overrides: dict[int, int] | None = None):
    from app.core.db import async_session_factory
    from app.ingestion.fpl_client import get_bootstrap_static, get_entry_picks
    from app.services.player_pool import (
        get_latest_stats,
        get_recent_minutes_by_player_id,
        get_started_status_by_team_id,
        apply_starter_risk_adjustment,
    )
    from app.services.prediction import predict_points
    from app.services.fixtures import get_planning_gameweek

    async with async_session_factory() as db:
        data = await get_bootstrap_static()
        current_event = next((e for e in data["events"] if e["is_current"]), None)
        if current_event is None:
            raise ValueError("FPL API returned no current gameweek")
        gameweek = current_event["id"]
        planning_gameweek = await get_planning_gameweek(db, gameweek)

        picks_data = await get_entry_picks(entry_id, gameweek)
        my_element_ids = {pick["element"] for pick in picks_data["picks"]}
        if overrides:
            for out_id, in_id in overrides.items():
                my_element_ids.discard(out_id)
                my_element_ids.add(in_id)

        rows = await get_latest_stats(db, gameweek)
        scored = await predict_points(rows, db, gameweek=gameweek, fixture_from_gameweek=planning_gameweek, num_fixtures=1)

        my_squad = [(p, s, sc) for p, s, sc in scored if p.id in my_element_ids]

        minutes_by_player_id = await get_recent_minutes_by_player_id(gameweek)
        started_by_team_id = await get_started_status_by_team_id(gameweek)
        risk_adjusted_squad = apply_starter_risk_adjustment(
            my_squad, minutes_by_player_id, started_by_team_id
        )

        gkps = [(p, s, sc) for p, s, sc in risk_adjusted_squad if p.position == Position.GKP]
        others = [(p, s, sc) for p, s, sc in risk_adjusted_squad if p.position != Position.GKP]
        gkps_rescored = await _rescore_gkps_by_fixture(gkps, db, planning_gameweek)

        result = pick_best_starting_xi(gkps_rescored + others)
        result["bench_coverage"] = analyse_bench_coverage(
            result["starting_xi"], result["bench_outfield"]
        )
        from app.services.autosub import simulate_autosubstitutions
        result["autosub_simulation"] = simulate_autosubstitutions(
            result["starting_xi"],
            result["bench_gk"],
            result["bench_outfield"],
            minutes_by_player_id,
        )
        return result

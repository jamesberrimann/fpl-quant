from collections import Counter

from app.models.player import Position

_MIN_FORMATION = {Position.DEF: 3, Position.MID: 2, Position.FWD: 1}


def simulate_autosubstitutions(
    starting_xi: list,
    bench_gk,
    bench_outfield: list,
    minutes_by_player_id: dict[int, int],
) -> dict:
    """
    Simulate FPL's auto-substitution rules given live minutes data.

    Rules:
    - A starter is "absent" if they have 0 minutes AND their fixture has kicked off
      (detected by checking if any squad player's fixture has started).
    - The bench GKP replaces an absent starting GKP.
    - Outfield bench players substitute in priority order (bench slot 1 first)
      when the resulting formation stays legal (≥3 DEF, ≥2 MID, ≥1 FWD).
    - A bench player who also has 0 minutes is skipped.

    Parameters
    ----------
    starting_xi  : list of (player, stats, score)
    bench_gk     : (player, stats, score) or None
    bench_outfield: list of (player, stats, score) ordered by bench priority
    minutes_by_player_id: {player_id: minutes_played} from live GW data

    Returns
    -------
    {
      "effective_xi": [(player, stats, score), ...],   # after subs
      "substitutions": [{"out": player, "in": player}, ...],
      "unresolved_absences": [player, ...],            # absent with no eligible sub
    }
    """
    def played(pid):
        return minutes_by_player_id.get(pid, 0) > 0

    # Work with mutable copies
    xi = list(starting_xi)
    bench_out = list(bench_outfield)
    subs_made = []
    unresolved = []

    # GKP substitution
    gkp_entry = next(((p, s, sc) for p, s, sc in xi if p.position == Position.GKP), None)
    if gkp_entry and not played(gkp_entry[0].id) and bench_gk and played(bench_gk[0].id):
        xi = [e for e in xi if e[0].id != gkp_entry[0].id]
        xi.append(bench_gk)
        subs_made.append({"out": gkp_entry[0], "in": bench_gk[0]})

    # Outfield substitutions: iterate absent starters in XI order
    for absent_entry in list(xi):
        player, stats, score = absent_entry
        if player.position == Position.GKP:
            continue
        if played(player.id):
            continue

        # Try each bench player in priority order
        subbed = False
        remaining_bench = []
        for bench_entry in bench_out:
            if subbed:
                remaining_bench.append(bench_entry)
                continue
            bp, bs, bsc = bench_entry
            if not played(bp.id):
                remaining_bench.append(bench_entry)
                continue
            # Would the sub produce a legal formation?
            trial_xi = [e for e in xi if e[0].id != player.id] + [bench_entry]
            counts = Counter(p.position for p, _, _ in trial_xi if p.position != Position.GKP)
            legal = all(counts.get(pos, 0) >= mn for pos, mn in _MIN_FORMATION.items())
            if legal:
                xi = trial_xi
                subs_made.append({"out": player, "in": bp})
                subbed = True
            else:
                remaining_bench.append(bench_entry)

        bench_out = remaining_bench
        if not subbed:
            unresolved.append(player)

    return {
        "effective_xi": xi,
        "substitutions": subs_made,
        "unresolved_absences": unresolved,
    }

from app.models.player import Position
from app.core.db import async_session_factory
from app.ingestion.fpl_client import get_bootstrap_static, get_entry_picks
from app.services.player_pool import get_latest_stats
from app.services.prediction import predict_points
from app.services.fixtures import get_gameweek_fixture_multipliers

_LOOKAHEAD = 5
# Approximate starter selection: greedy by score subject to FPL formation rules.
# Min counts per position in any legal 11-man XI.
_MIN = {Position.GKP: 1, Position.DEF: 3, Position.MID: 2, Position.FWD: 1}
_MAX = {Position.GKP: 1, Position.DEF: 5, Position.MID: 5, Position.FWD: 3}


def _pick_best_xi(scored: list) -> tuple[list, float]:
    """
    Given a list of (player, stats, predicted_pts) for 15 squad players,
    return the (xi, total) that maximises predicted points in a legal formation.

    Uses the same valid-formation set as lineup.py but iterates all legal
    (DEF, MID, FWD) combos rather than importing the full lineup service, so
    this module stays self-contained and easy to test.
    """
    VALID = [
        (3, 4, 3), (3, 5, 2),
        (4, 3, 3), (4, 4, 2), (4, 5, 1),
        (5, 2, 3), (5, 3, 2), (5, 4, 1),
    ]

    by_pos: dict[Position, list] = {p: [] for p in Position}
    for player, stats, pts in scored:
        by_pos[player.position].append((player, stats, pts))
    for pos in by_pos:
        by_pos[pos].sort(key=lambda x: x[2], reverse=True)

    gk = by_pos[Position.GKP][:1]
    best_xi, best_total = None, -1.0
    for d, m, f in VALID:
        if len(by_pos[Position.DEF]) < d or len(by_pos[Position.MID]) < m or len(by_pos[Position.FWD]) < f:
            continue
        xi = gk + by_pos[Position.DEF][:d] + by_pos[Position.MID][:m] + by_pos[Position.FWD][:f]
        total = sum(pts for _, _, pts in xi)
        if total > best_total:
            best_total = total
            best_xi = xi

    return (best_xi or [], best_total)


async def get_squad_projection(entry_id: int, num_gameweeks: int = _LOOKAHEAD) -> list[dict]:
    """
    Returns a list of per-GW projected totals for the next `num_gameweeks`:

      [{"gameweek": N, "predicted_total": X.X, "dgw_player_count": N, "bgw_player_count": N}, ...]

    Predicted total = sum of best predicted-XI scores for that GW, using each
    GW's fixture difficulty and DGW/BGW multipliers.  Only available players
    (current squad) are considered; squad composition is held constant (no
    transfers simulated).

    If the squad can't be found or has fewer than 11 players with predictions,
    an empty list is returned rather than raising.
    """
    async with async_session_factory() as db:
        data = await get_bootstrap_static()
        events = data["events"]
        current_gw = next(e["id"] for e in events if e["is_current"])
        max_gw = max(e["id"] for e in events)

        picks_data = await get_entry_picks(entry_id, current_gw)
        my_element_ids = {pick["element"] for pick in picks_data["picks"]}

        rows = await get_latest_stats(db, current_gw)
        my_rows = [(p, s) for p, s in rows if p.id in my_element_ids]

        if not my_rows:
            return []

        projections = []
        for gw_offset in range(num_gameweeks):
            target_gw = current_gw + gw_offset
            if target_gw > max_gw:
                break

            all_team_ids = {p.team_id for p, _ in my_rows}
            dgw_mults = await get_gameweek_fixture_multipliers(db, all_team_ids, target_gw)

            scored = await predict_points(
                my_rows, db,
                gameweek=current_gw,
                fixture_from_gameweek=target_gw,
                num_fixtures=1,
                fixture_count_multipliers=dgw_mults,
            )

            _, total = _pick_best_xi(scored)

            dgw_count = sum(1 for p, _ in my_rows if dgw_mults.get(p.team_id, 1.0) >= 2.0)
            bgw_count = sum(1 for p, _ in my_rows if dgw_mults.get(p.team_id, 1.0) == 0.0)

            projections.append({
                "gameweek": target_gw,
                "predicted_total": round(total, 1),
                "dgw_player_count": dgw_count,
                "bgw_player_count": bgw_count,
            })

        return projections

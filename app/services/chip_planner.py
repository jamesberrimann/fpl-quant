from sqlalchemy.ext.asyncio import AsyncSession

from app.services.fixtures import get_all_gameweek_fixture_info_in_range, get_all_gameweek_multipliers_in_range

# Scan the full remaining season, not just a short lookahead window.
# DGW windows for your best players can be 20+ GWs away — the whole point.
_MAX_SEASON_GW = 38

_BB_DGW_THRESHOLD = 3
_FH_BLANK_THRESHOLD = 5


async def get_chip_windows(
    db: AsyncSession,
    squad_players: list[dict],
    current_gameweek: int,
) -> dict:
    """Scan all remaining gameweeks and return optimal chip timing for the season.

    squad_players: list of dicts with keys:
        team_id (int), position (Position), score (float), web_name (str)
        — score is the player's current predicted-points score, used as a
          proxy for player quality when ranking TC candidates.

    Returns a dict with:
        triple_captain: {gameweek, reason, best_player_name, best_player_score, is_dgw}
        bench_boost:    {gameweek, reason, dgw_count}
        free_hit:       list of {gameweek, blank_count, reason}
        wildcard:       {gameweek, reason}
    """
    if not squad_players:
        return {
            "triple_captain": None,
            "bench_boost": None,
            "free_hit": [],
            "wildcard": None,
        }

    team_ids = {p["team_id"] for p in squad_players}
    fixture_info_by_gw = await get_all_gameweek_fixture_info_in_range(
        db, team_ids, current_gameweek, _MAX_SEASON_GW
    )
    multipliers_by_gw = {
        gw: {tid: v["count"] for tid, v in teams.items()}
        for gw, teams in fixture_info_by_gw.items()
    }
    gw_range = range(current_gameweek, _MAX_SEASON_GW + 1)

    # ── Triple Captain: best future GW for your top player.
    # Primary sort: fixture count (DGW=2 beats single=1).
    # Tiebreak: lower difficulty wins (easier opponent).
    # The player score is used only to rank players, not GWs — it already
    # has current-GW fixture ease baked in so we don't multiply by ease again.
    # Scan starts at current_gameweek + 1: TC is always a forward decision.
    top_scores = sorted(squad_players, key=lambda p: p.get("score", 0), reverse=True)
    best_tc_gw = None
    best_tc_key = (-1, 6.0)  # (count, -difficulty) — higher count and lower difficulty wins
    best_tc_player = None

    for gw in range(current_gameweek + 1, _MAX_SEASON_GW + 1):
        for p in top_scores[:5]:
            info = fixture_info_by_gw[gw].get(p["team_id"], {"count": 0.0, "difficulty": 3.0})
            count = info["count"]
            if count == 0.0:
                continue
            key = (count, -info["difficulty"])  # higher count first, then easier fixture
            if key > best_tc_key or best_tc_gw is None:
                best_tc_key = key
                best_tc_gw = gw
                best_tc_player = p

    triple_captain = None
    if best_tc_gw is not None and best_tc_player is not None:
        count = fixture_info_by_gw[best_tc_gw].get(best_tc_player["team_id"], {}).get("count", 0.0)
        is_dgw = count >= 2.0
        name = best_tc_player.get("web_name", "")
        triple_captain = {
            "gameweek": best_tc_gw,
            "best_player_name": name,
            "best_player_score": round(best_tc_player.get("score", 0), 1),
            "is_dgw": is_dgw,
            "reason": (
                f"{name} has a DGW in GW{best_tc_gw} — triple the ceiling with two fixtures."
                if is_dgw else
                f"{name}'s best fixture of the season is in GW{best_tc_gw} — hold your chip for then."
            ),
        }

    # ── Bench Boost: GW in the season with the most DGW players in the squad.
    # The bench contributes maximally when all 15 players play twice.
    best_bb_gw = None
    best_bb_dgw_count = -1

    for gw in gw_range:
        mults = multipliers_by_gw[gw]
        dgw_count = sum(1 for p in squad_players if mults.get(p["team_id"], 0.0) >= 2.0)
        if dgw_count > best_bb_dgw_count:
            best_bb_dgw_count = dgw_count
            best_bb_gw = gw

    bench_boost = None
    if best_bb_gw is not None and best_bb_dgw_count > 0:
        if best_bb_dgw_count >= _BB_DGW_THRESHOLD:
            reason = (
                f"GW{best_bb_gw} is your best Bench Boost window: "
                f"{best_bb_dgw_count} of your players have a double gameweek."
            )
        else:
            reason = (
                f"GW{best_bb_gw} has the most DGW players in your squad ({best_bb_dgw_count}) "
                f"but is below the ideal threshold ({_BB_DGW_THRESHOLD}) — consider waiting "
                "for a bigger DGW window or using it for a strong score week."
            )
        bench_boost = {
            "gameweek": best_bb_gw,
            "dgw_count": best_bb_dgw_count,
            "reason": reason,
        }

    # ── Free Hit: GWs where many of your players blank.
    # Guard against unscheduled GWs (all zeros in DB) being misread as blanks.
    free_hit_windows = []
    for gw in gw_range:
        mults = multipliers_by_gw[gw]
        has_any_fixture = any(mults.get(p["team_id"], 0.0) > 0 for p in squad_players)
        if not has_any_fixture:
            continue
        blank_count = sum(1 for p in squad_players if mults.get(p["team_id"], 0.0) == 0.0)
        if blank_count >= _FH_BLANK_THRESHOLD:
            free_hit_windows.append({
                "gameweek": gw,
                "blank_count": blank_count,
                "reason": (
                    f"GW{gw}: {blank_count} of your players have a blank — "
                    "Free Hit would let you field a full DGW squad instead."
                ),
            })

    # ── Wildcard: GW before fixture difficulty spikes for the squad.
    avg_mults: dict[int, float] = {}
    for gw in gw_range:
        mults = multipliers_by_gw[gw]
        vals = [mults.get(p["team_id"], 0.0) for p in squad_players]
        avg_mults[gw] = sum(vals) / len(vals) if vals else 0.0

    wildcard = None
    gw_list = list(gw_range)
    for i in range(len(gw_list) - 1):
        gw_now = gw_list[i]
        gw_next = gw_list[i + 1]
        if avg_mults[gw_now] > 0 and avg_mults[gw_next] < avg_mults[gw_now] * 0.75:
            wildcard = {
                "gameweek": gw_now,
                "reason": (
                    f"Fixture difficulty rises sharply after GW{gw_now} for your squad. "
                    f"Wildcarding in GW{gw_now} lets you bring in players with better upcoming runs."
                ),
            }
            break

    return {
        "triple_captain": triple_captain,
        "bench_boost": bench_boost,
        "free_hit": free_hit_windows,
        "wildcard": wildcard,
    }

from app.ingestion.fpl_client import get_entry_history, get_entry_picks, get_gameweek_live

_DEFAULT_LOOKBACK = 5


async def get_captain_accuracy(entry_id: int, num_gameweeks: int = _DEFAULT_LOOKBACK) -> list[dict]:
    """
    Returns a per-GW breakdown of captain decisions for the last `num_gameweeks`
    completed gameweeks:

      [{
        "gameweek": N,
        "captain_id": int,
        "captain_name": str,
        "captain_pts": int,        # raw (×1), actual FPL points that GW
        "captain_bonus": int,      # extra pts from captaincy (same as captain_pts since ×2)
        "optimal_id": int,
        "optimal_name": str,
        "optimal_pts": int,        # highest raw score among starting XI that GW
        "was_optimal": bool,
        "regret_pts": int,         # (optimal_pts - captain_pts) × 1 — missed bonus
      }, ...]

    `regret_pts` is how many extra points you'd have had if you'd captained the
    optimal player instead.  0 when captain was already optimal.

    Players with 0 points are excluded from the optimal search (didn't play).
    """
    history = await get_entry_history(entry_id)
    played_gws = [gw["event"] for gw in history.get("current", []) if gw.get("points") is not None]
    target_gws = sorted(played_gws)[-num_gameweeks:]

    results = []
    for gw in target_gws:
        picks_data = await get_entry_picks(entry_id, gw)
        picks = picks_data.get("picks", [])
        live_data = await get_gameweek_live(gw)
        live_by_id = {el["id"]: el["stats"] for el in live_data.get("elements", [])}

        # Captain has multiplier 3 (×2) or 2 (VC playing); prefer highest multiplier.
        captain_pick = max(picks, key=lambda p: p.get("multiplier", 1), default=None)
        if captain_pick is None:
            continue

        cap_id = captain_pick["element"]
        cap_stats = live_by_id.get(cap_id, {})
        cap_pts = cap_stats.get("total_points", 0)

        # Starting XI = picks where position <= 11
        starting_ids = {p["element"] for p in picks if p.get("position", 99) <= 11}

        # Find optimal captain: highest raw scorer in starting XI (excluding 0-pointers)
        best_id, best_pts = cap_id, cap_pts
        for pid in starting_ids:
            pts = live_by_id.get(pid, {}).get("total_points", 0)
            if pts > best_pts:
                best_pts = pts
                best_id = pid

        # Resolve names from picks (web_name not in live data — use element id for now;
        # caller can enrich with bootstrap element map)
        results.append({
            "gameweek": gw,
            "captain_id": cap_id,
            "captain_pts": cap_pts,
            "captain_bonus": cap_pts,       # ×1 raw; frontend doubles for display
            "optimal_id": best_id,
            "optimal_pts": best_pts,
            "was_optimal": best_id == cap_id,
            "regret_pts": max(0, best_pts - cap_pts),
        })

    return results

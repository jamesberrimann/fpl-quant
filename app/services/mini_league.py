from app.ingestion.fpl_client import get_entry_details, get_league_standings

# FPL classic leagues with IDs below this threshold are global/system leagues
# (e.g. "Overall", "GW X Top 1M") that aren't useful for head-to-head comparison.
_GLOBAL_LEAGUE_THRESHOLD = 314

# Max mini-leagues to surface — keep it tight so the response stays scannable.
_MAX_LEAGUES = 3
_MAX_RIVALS = 5


async def get_mini_league_context(entry_id: int) -> list[dict]:
    """
    Returns context for up to `_MAX_LEAGUES` of the entry's smallest mini-leagues:

      [{
        "league_id": int,
        "league_name": str,
        "entry_rank": int,
        "entry_pts": int,
        "leader_name": str,
        "leader_pts": int,
        "gap_to_leader": int,       # pts behind leader (0 if leading)
        "rivals": [{                # nearest rivals (above and below)
          "manager": str,
          "rank": int,
          "pts": int,
          "gap": int,               # pts difference vs entry (negative = behind)
        }],
      }, ...]

    Excludes global/system leagues.  Leagues are sorted ascending by size so the
    most meaningful (friends/work) leagues appear first.
    """
    entry_data = await get_entry_details(entry_id)

    leagues = [
        lg for lg in entry_data.get("leagues", {}).get("classic", [])
        if lg["id"] > _GLOBAL_LEAGUE_THRESHOLD
    ]
    # Sort by entry count ascending → smallest (most personal) first
    leagues.sort(key=lambda lg: lg.get("entry_count", 9_999_999))

    results = []
    for league in leagues[:_MAX_LEAGUES]:
        lid = league["id"]
        name = league["name"]

        standings_data = await get_league_standings(lid)
        standings = standings_data.get("standings", {}).get("results", [])
        if not standings:
            continue

        entry_row = next((r for r in standings if r["entry"] == entry_id), None)
        if entry_row is None:
            continue

        entry_rank = entry_row["rank"]
        entry_pts = entry_row["total"]

        leader = standings[0]

        # Nearest rivals: up to 2 above and 2 below in the standings list
        idx = next(i for i, r in enumerate(standings) if r["entry"] == entry_id)
        window = standings[max(0, idx - 2): idx + 3]
        rivals = [
            {
                "manager": r["entry_name"],
                "rank": r["rank"],
                "pts": r["total"],
                "gap": r["total"] - entry_pts,
            }
            for r in window
            if r["entry"] != entry_id
        ][:_MAX_RIVALS]

        results.append({
            "league_id": lid,
            "league_name": name,
            "entry_rank": entry_rank,
            "entry_pts": entry_pts,
            "leader_name": leader["entry_name"],
            "leader_pts": leader["total"],
            "gap_to_leader": max(0, leader["total"] - entry_pts),
            "rivals": rivals,
        })

    return results

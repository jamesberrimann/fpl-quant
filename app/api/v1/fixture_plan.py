import httpx
from fastapi import APIRouter, HTTPException, Query

from app.core.db import async_session_factory
from app.ingestion.fpl_client import get_bootstrap_static, get_entry_picks
from app.schemas.fixture_plan import FixturePlanOut, PlayerFixturePlanOut, GWFixtureSlotOut, FixtureOpponentOut
from app.services.fixture_heatmap import get_fixture_heatmap
from app.services.fixtures import get_planning_gameweek

router = APIRouter()

_POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


@router.get("/fixture-plan", response_model=FixturePlanOut)
async def fixture_plan_route(
    entry_id: int = Query(...),
    num_gameweeks: int = Query(default=6, ge=1, le=10),
):
    data = await get_bootstrap_static()
    gameweek = next(e["id"] for e in data["events"] if e["is_current"])

    player_info = {
        e["id"]: {
            "team_id": e["team"],
            "web_name": e["web_name"],
            "position": _POSITION_MAP.get(e["element_type"], "UNK"),
        }
        for e in data["elements"]
    }
    team_short_names = {t["id"]: t["short_name"] for t in data["teams"]}

    try:
        picks = await get_entry_picks(entry_id, gameweek)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="FPL entry not found")
        raise

    squad_ids = [pick["element"] for pick in picks["picks"]]
    squad_players = [
        {"player_id": pid, **player_info[pid]}
        for pid in squad_ids
        if pid in player_info
    ]
    team_ids = {p["team_id"] for p in squad_players}

    async with async_session_factory() as db:
        planning_gw = await get_planning_gameweek(db, gameweek)
        heatmap = await get_fixture_heatmap(db, team_ids, planning_gw, num_gameweeks)

    players_out = []
    for p in squad_players:
        slots = heatmap.get(p["team_id"], [])
        players_out.append(PlayerFixturePlanOut(
            player_id=p["player_id"],
            web_name=p["web_name"],
            position=p["position"],
            team_id=p["team_id"],
            team_short_name=team_short_names.get(p["team_id"], "UNK"),
            gameweek_slots=[
                GWFixtureSlotOut(
                    gameweek=s.gameweek,
                    opponents=[
                        FixtureOpponentOut(
                            team_id=o.team_id,
                            short_name=o.short_name,
                            is_home=o.is_home,
                            fdr=o.fdr,
                        )
                        for o in s.opponents
                    ],
                    is_blank=s.is_blank,
                    is_double=s.is_double,
                    avg_fdr=s.avg_fdr,
                )
                for s in slots
            ],
        ))

    # Sort by position order (GKP, DEF, MID, FWD) then name for consistent display
    _POS_ORDER = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
    players_out.sort(key=lambda p: (_POS_ORDER.get(p.position, 9), p.web_name))

    return FixturePlanOut(
        from_gameweek=planning_gw,
        num_gameweeks=num_gameweeks,
        players=players_out,
    )

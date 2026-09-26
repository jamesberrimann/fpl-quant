import httpx
from fastapi import APIRouter, HTTPException, Query

from app.core.db import async_session_factory
from app.ingestion.fpl_client import get_bootstrap_static, get_entry_picks
from app.services.player_pool import get_latest_stats
from app.services.prediction import predict_points
from app.services.fixtures import get_planning_gameweek
from app.services.chip_planner import get_chip_windows
from app.schemas.chip_plan import (
    ChipPlanOut, TripleCaptainWindowOut, BenchBoostWindowOut,
    FreeHitWindowOut, WildcardWindowOut,
)

router = APIRouter()


@router.get("/chip-plan", response_model=ChipPlanOut)
async def chip_plan_route(entry_id: int = Query(...)):
    try:
        data = await get_bootstrap_static()
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="FPL API unavailable")

    gameweek = next(e["id"] for e in data["events"] if e["is_current"])
    team_map = {t["id"]: t["short_name"] for t in data.get("teams", [])}

    try:
        picks_data = await get_entry_picks(entry_id, gameweek)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="FPL entry not found")
        raise

    my_element_ids = {pick["element"] for pick in picks_data["picks"]}

    async with async_session_factory() as db:
        planning_gw = await get_planning_gameweek(db, gameweek)
        rows = await get_latest_stats(db, gameweek)
        my_rows = [(p, s) for p, s in rows if p.id in my_element_ids]

        scored = await predict_points(
            my_rows, db, gameweek=gameweek,
            fixture_from_gameweek=planning_gw, num_fixtures=1,
        )

        squad_players = [
            {
                "team_id": p.team_id,
                "position": p.position,
                "web_name": p.web_name,
                "score": sc,
            }
            for p, s, sc in scored
        ]

        windows = await get_chip_windows(db, squad_players, current_gameweek=planning_gw)

    tc = windows["triple_captain"]
    bb = windows["bench_boost"]
    fh = windows["free_hit"]
    wc = windows["wildcard"]

    return ChipPlanOut(
        triple_captain=TripleCaptainWindowOut(**tc) if tc else None,
        bench_boost=BenchBoostWindowOut(**bb) if bb else None,
        free_hit=[FreeHitWindowOut(**w) for w in fh],
        wildcard=WildcardWindowOut(**wc) if wc else None,
    )

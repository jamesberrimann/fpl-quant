import httpx
from fastapi import APIRouter, HTTPException, Query

from app.services.captain_history import get_captain_accuracy
from app.schemas.captain_history import CaptainAccuracyOut, GWCaptainOut
from app.ingestion.fpl_client import get_bootstrap_static

router = APIRouter()


@router.get("/captain-history", response_model=CaptainAccuracyOut)
async def captain_history_route(entry_id: int = Query(...), gameweeks: int = Query(default=5, ge=1, le=20)):
    try:
        data = await get_bootstrap_static()
        name_by_id = {el["id"]: el["web_name"] for el in data.get("elements", [])}

        rows = await get_captain_accuracy(entry_id, num_gameweeks=gameweeks)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="FPL entry not found")
        raise

    if not rows:
        return CaptainAccuracyOut(gameweeks=[], hit_rate=0.0, total_regret_pts=0)

    gw_out = [
        GWCaptainOut(
            **row,
            captain_name=name_by_id.get(row["captain_id"], f"#{row['captain_id']}"),
            optimal_name=name_by_id.get(row["optimal_id"], f"#{row['optimal_id']}"),
        )
        for row in rows
    ]

    hit_rate = sum(1 for g in gw_out if g.was_optimal) / len(gw_out)
    total_regret = sum(g.regret_pts for g in gw_out)

    return CaptainAccuracyOut(
        gameweeks=gw_out,
        hit_rate=round(hit_rate, 2),
        total_regret_pts=total_regret,
    )

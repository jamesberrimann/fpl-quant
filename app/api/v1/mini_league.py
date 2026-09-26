import httpx
from fastapi import APIRouter, HTTPException, Query

from app.services.mini_league import get_mini_league_context
from app.schemas.mini_league import MiniLeagueContextOut, MiniLeagueOut, RivalOut

router = APIRouter()


@router.get("/mini-league", response_model=MiniLeagueContextOut)
async def mini_league_route(entry_id: int = Query(...)):
    try:
        leagues = await get_mini_league_context(entry_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="FPL entry not found")
        raise

    return MiniLeagueContextOut(
        leagues=[
            MiniLeagueOut(
                **{k: v for k, v in lg.items() if k != "rivals"},
                rivals=[RivalOut(**r) for r in lg["rivals"]],
            )
            for lg in leagues
        ]
    )

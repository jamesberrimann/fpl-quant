import httpx
from fastapi import APIRouter, HTTPException, Query

from app.services.squad_projection import get_squad_projection
from app.schemas.projection import SquadProjectionOut, GameweekProjectionOut

router = APIRouter()


@router.get("/squad-projection", response_model=SquadProjectionOut)
async def squad_projection_route(entry_id: int = Query(...), gameweeks: int = Query(default=5, ge=1, le=10)):
    try:
        projections = await get_squad_projection(entry_id, num_gameweeks=gameweeks)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="FPL entry not found")
        raise

    return SquadProjectionOut(
        gameweeks=[GameweekProjectionOut(**gw) for gw in projections]
    )

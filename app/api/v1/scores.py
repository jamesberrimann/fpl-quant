import httpx
from fastapi import APIRouter, HTTPException, Query

from app.services.scores import get_latest_team_score, get_squad_scores, get_squad_live_events
from app.ingestion.fpl_client import get_bootstrap_static
from app.schemas.scores import TeamScoreOut, SquadScoresOut, PlayerLiveEventOut, SquadLiveEventsOut

router = APIRouter()


@router.get("/team-score", response_model=TeamScoreOut)
async def team_score_route(team_id: int = Query(...)):
    data = await get_bootstrap_static()
    current_gameweek = next(e["id"] for e in data["events"] if e["is_current"])

    result = await get_latest_team_score(team_id, current_gameweek=current_gameweek)

    if result is None:
        raise HTTPException(status_code=404, detail="No finished fixtures found for this team")

    return TeamScoreOut(**result)


@router.get("/squad-scores", response_model=SquadScoresOut)
async def squad_scores_route(entry_id: int = Query(...)):
    try:
        results = await get_squad_scores(entry_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="FPL entry not found")
        raise
    return SquadScoresOut(scores=[TeamScoreOut(**r) for r in results])


@router.get("/squad-live-events", response_model=SquadLiveEventsOut)
async def squad_live_events_route(entry_id: int = Query(...)):
    try:
        results = await get_squad_live_events(entry_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="FPL entry not found")
        raise
    return SquadLiveEventsOut(events=[PlayerLiveEventOut(**r) for r in results])

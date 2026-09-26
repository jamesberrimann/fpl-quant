import httpx
from fastapi import APIRouter, HTTPException, Query

from app.services.squad_rating import rate_squad
from app.services.fixtures import get_next_fixture_labels, get_planning_gameweek
from app.core.db import async_session_factory
from app.schemas.rating import SquadRatingOut, RatedPlayerOut
from app.ingestion.fpl_client import get_bootstrap_static

router = APIRouter()


@router.get("/rate-squad", response_model=SquadRatingOut)
async def rate_squad_route(entry_id: int = Query(...)):
    data = await get_bootstrap_static()
    gameweek = next(e["id"] for e in data["events"] if e["is_current"])
    team_map = {t["id"]: t["short_name"] for t in data.get("teams", [])}

    try:
        my_players = await rate_squad(entry_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="FPL entry not found")
        raise

    async with async_session_factory() as db:
        planning_gw = await get_planning_gameweek(db, gameweek)
        team_ids = {player.team_id for player, stats, score, percentile, flag in my_players}
        fixture_labels = await get_next_fixture_labels(db, team_ids, planning_gw)

    players = [
        RatedPlayerOut(
            id=player.id,
            web_name=player.web_name,
            position=player.position.value,
            team_short_name=team_map.get(player.team_id, "UNK"),
            score=score,
            percentile=percentile,
            flag=flag,
            next_fixture=fixture_labels.get(player.team_id),
        )
        for player, stats, score, percentile, flag in my_players
    ]

    squad_score = round(sum(p.percentile for p in players) / len(players), 1) if players else 0.0
    return SquadRatingOut(players=players, squad_score=squad_score)

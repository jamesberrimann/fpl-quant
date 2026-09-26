import httpx
from fastapi import APIRouter, HTTPException, Query

from app.core.db import async_session_factory
from app.ingestion.fpl_client import get_bootstrap_static, get_entry_picks
from app.models.player import Position
from app.services.player_pool import get_latest_stats
from app.services.template_comparison import build_template_comparison
from app.schemas.template import TemplateComparisonOut, TemplatePlayerOut, PositionBreakdownOut

router = APIRouter()

_POSITION_MAP = {"1": Position.GKP, "2": Position.DEF, "3": Position.MID, "4": Position.FWD}


@router.get("/squad-template", response_model=TemplateComparisonOut)
async def squad_template_route(entry_id: int = Query(...)):
    try:
        data = await get_bootstrap_static()
    except httpx.HTTPStatusError as e:
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
        rows = await get_latest_stats(db, gameweek)

    my_rows = [(p, s) for p, s in rows if p.id in my_element_ids]

    squad_players = [
        {
            "id": p.id,
            "web_name": p.web_name,
            "position": p.position,
            "team_short_name": team_map.get(p.team_id, "UNK"),
            "ownership_pct": float(s.ownership_pct) if s.ownership_pct is not None else None,
        }
        for p, s in my_rows
    ]

    result = build_template_comparison(squad_players)

    def to_out(p):
        pos = p["position"].value if hasattr(p["position"], "value") else str(p["position"])
        return TemplatePlayerOut(
            id=p["id"],
            web_name=p["web_name"],
            position=pos,
            team_short_name=p["team_short_name"],
            ownership_pct=p.get("ownership_pct"),
            classification=p["classification"],
        )

    by_pos_out = {
        pos: PositionBreakdownOut(**counts)
        for pos, counts in result["by_position"].items()
    }

    return TemplateComparisonOut(
        players=[to_out(p) for p in result["players"]],
        divergence_score=result["divergence_score"],
        by_position=by_pos_out,
        differentials=[to_out(p) for p in result["differentials"]],
        template_picks=[to_out(p) for p in result["template_picks"]],
    )

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.services.transfers import suggest_transfers
from app.schemas.transfers import TransferSuggestionsOut, TransferSuggestionOut, TimingSignalOut
from app.ingestion.fpl_client import get_bootstrap_static

router = APIRouter()


@router.get("/suggest-transfers", response_model=TransferSuggestionsOut)
async def suggest_transfers_route(entry_id: int = Query(...), free_transfers: int = Query(default=1)):
    data = await get_bootstrap_static()
    team_map = {t["id"]: t["short_name"] for t in data.get("teams", [])}

    try:
        result = await suggest_transfers(entry_id, free_transfers=free_transfers)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="FPL entry not found")
        if e.response.status_code == 429:
            raise HTTPException(status_code=429, detail="FPL API rate limit — retry shortly")
        raise
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="FPL API unavailable — network error")

    out = []
    for s in result["suggestions"]:
        timing = s["timing_signal"]
        timing_out = TimingSignalOut(**timing) if timing else None

        out.append(TransferSuggestionOut(
            out_id=s["out"].id,
            out_web_name=s["out"].web_name,
            out_team_short_name=team_map.get(s["out"].team_id, "UNK"),
            in_id=s["in"].id,
            in_web_name=s["in"].web_name,
            in_team_short_name=team_map.get(s["in"].team_id, "UNK"),
            position=s["out"].position.value,
            improvement=s["improvement"],
            price_change=s["price_change"],
            points_cost=s["points_cost"],
            timing_signal=timing_out,
            in_dgw=s.get("in_dgw", False),
            in_ownership_pct=s.get("in_ownership_pct"),
            is_differential=s.get("is_differential", False),
            in_price_last_gw_change=s.get("in_price_last_gw_change", 0.0),
            out_price_last_gw_change=s.get("out_price_last_gw_change", 0.0),
            in_rotation_risk=s.get("in_rotation_risk", 0.0),
            in_net_transfers_this_gw=s.get("in_net_transfers_this_gw", 0),
            in_hot_form=s.get("in_hot_form", False),
            break_even_weeks=s.get("break_even_weeks"),
            in_ownership_trend=s.get("in_ownership_trend"),
            in_price_rise_likely=s.get("in_price_rise_likely", False),
            in_price_fall_likely=s.get("in_price_fall_likely", False),
            improvement_drivers=s.get("improvement_drivers", []),
            is_marginal=s.get("is_marginal", False),
        ))

    return TransferSuggestionsOut(
        suggestions=out,
        roll_recommendation=result["roll_recommendation"],
        roll_reason=result["roll_reason"],
    )

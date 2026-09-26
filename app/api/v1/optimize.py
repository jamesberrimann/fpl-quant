from fastapi import APIRouter, HTTPException, Query

from app.services.squad_builder import build_optimal_squad, get_budget_sensitivity
from app.services.optimizer import InfeasibleBudgetError
from app.services.lineup import pick_best_starting_xi
from app.services.captaincy import score_for_captaincy, get_captain_recommendation, get_captaincy_explanation
from app.services.fixtures import get_next_fixture_labels, get_planning_gameweek, get_gameweek_fixture_multipliers
from app.services.prediction import predict_points
from app.services.squad_rating import compute_ratings
from app.services.player_pool import get_latest_stats
from app.core.db import async_session_factory
from app.schemas.squad import SquadOut, SquadPlayerOut, BudgetSensitivityOut, BudgetStepOut
from app.ingestion.fpl_client import get_bootstrap_static

router = APIRouter()


@router.get("/budget-sensitivity", response_model=BudgetSensitivityOut)
async def budget_sensitivity_route(
    budget: float = Query(default=100.0),
    steps: int = Query(default=4, ge=2, le=6),
):
    results = await get_budget_sensitivity(base_budget=budget, num_steps=steps)
    return BudgetSensitivityOut(steps=[BudgetStepOut(**r) for r in results])


@router.get(
    "/optimize-squad",
    response_model=SquadOut,
    responses={422: {"description": "Budget too low to build a legal 15-man squad"}},
)
async def optimize_squad_route(budget: float = Query(default=100.0)):
    data = await get_bootstrap_static()
    gameweek = next(e["id"] for e in data["events"] if e["is_current"])
    team_map = {t["id"]: t["short_name"] for t in data.get("teams", [])}

    try:
        squad = await build_optimal_squad(budget=budget)
    except InfeasibleBudgetError as e:
        raise HTTPException(status_code=422, detail=str(e))

    async with async_session_factory() as db:
        planning_gw = await get_planning_gameweek(db, gameweek)
        team_ids = {player.team_id for player, stats, score in squad}
        fixture_labels = await get_next_fixture_labels(db, team_ids, planning_gw)

        # Re-score the squad on num_fixtures=1 for lineup selection.
        # Squad building uses a 3-fixture average to pick long-term value;
        # the starting XI decision should reflect next week's fixture only.
        squad_rows = [(player, stats) for player, stats, _ in squad]
        gw_scored_raw = await predict_points(
            squad_rows, db, gameweek=gameweek,
            fixture_from_gameweek=planning_gw, num_fixtures=1,
        )
        gw_scored = [
            (
                p, s,
                0.7 * sc + 0.3 * (
                    float(s.total_points) / max(float(s.minutes) / 90.0, 1.0)
                ),
            )
            for p, s, sc in gw_scored_raw
        ]
        lineup = pick_best_starting_xi(gw_scored)
        captain_scored = await score_for_captaincy(lineup["starting_xi"], db, planning_gw)

        # Predicted pts for captain/VC display
        xi_rows = [(p, s) for p, s, _ in lineup["starting_xi"]]
        xi_team_ids = {p.team_id for p, s in xi_rows}
        xi_dgw_mults = await get_gameweek_fixture_multipliers(db, xi_team_ids, planning_gw)
        xi_predicted = await predict_points(
            xi_rows, db, gameweek=gameweek,
            fixture_from_gameweek=planning_gw, num_fixtures=1,
            fixture_count_multipliers=xi_dgw_mults,
        )
        predicted_pts_by_id = {p.id: round(sc, 1) for p, s, sc in xi_predicted}

        # Rating: score each squad player vs the full starter pool
        all_rows = await get_latest_stats(db, gameweek)
        all_scored_for_rating = await predict_points(
            all_rows, db, gameweek=gameweek, fixture_from_gameweek=planning_gw,
        )
        squad_ids = {p.id for p, s, sc in squad}
        rated = compute_ratings(squad_ids, all_scored_for_rating, gameweek)
        ratings_by_id = {p.id: (pct, flag) for p, s, sc, pct, flag in rated}
        squad_score_percentile = round(
            sum(pct for _, pct, _ in [(p, pct, f) for p, s, sc, pct, f in rated]) / len(rated), 1
        ) if rated else None

    rec = get_captain_recommendation(captain_scored)

    def to_out(player, stats, score):
        pct, flag = ratings_by_id.get(player.id, (0.0, None))
        return SquadPlayerOut(
            id=player.id,
            web_name=player.web_name,
            position=player.position.value,
            team_short_name=team_map.get(player.team_id, "UNK"),
            price=float(stats.price),
            score=score,
            next_fixture=fixture_labels.get(player.team_id),
            status=stats.status,
            percentile=round(pct, 1),
            flag=flag,
            chance_of_playing_next_round=stats.chance_of_playing_next_round,
        )

    players = [to_out(p, s, sc) for p, s, sc in squad]
    starting_xi = [to_out(p, s, sc) for p, s, sc in lineup["starting_xi"]]

    bench = []
    if lineup["bench_gk"]:
        p, s, sc = lineup["bench_gk"]
        bench.append(to_out(p, s, sc))
    bench += [to_out(p, s, sc) for p, s, sc in lineup["bench_outfield"]]

    total_cost = sum(p.price for p in players)
    squad_score = round(sum(p.score for p in players) / len(players), 2) if players else 0.0

    ownership_by_id = {
        p.id: round(float(s.ownership_pct), 1)
        for p, s, _ in squad
        if s.ownership_pct is not None
    }

    cap_id = rec["top_pick"]["player"].id
    vc_id  = rec["second_pick"]["player"].id

    return SquadOut(
        players=players,
        total_cost=total_cost,
        squad_score=squad_score,
        starting_xi=starting_xi,
        bench=bench,
        captain_id=cap_id,
        vice_captain_id=vc_id,
        captain_predicted_pts=round(predicted_pts_by_id.get(cap_id, 0.0) * 2, 1),
        vc_predicted_pts=round(predicted_pts_by_id.get(vc_id, 0.0), 1),
        captain_ownership_pct=ownership_by_id.get(cap_id),
        vc_ownership_pct=ownership_by_id.get(vc_id),
        captain_top_factors=get_captaincy_explanation(cap_id, captain_scored) or None,
        vc_top_factors=get_captaincy_explanation(vc_id, captain_scored) or None,
        squad_score_percentile=squad_score_percentile,
    )

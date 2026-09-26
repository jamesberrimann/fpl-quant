import httpx
from fastapi import APIRouter, HTTPException, Query

from app.services.lineup import pick_best_starting_xi_for_entry
from app.services.captaincy import score_for_captaincy, get_captain_recommendation, get_captaincy_explanation, get_captain_variance
from app.services.transfers import is_hot_form
from app.services.fixtures import get_next_fixture_labels, get_next_fixture_is_home, get_planning_gameweek, get_gameweek_fixture_multipliers
from app.services.prediction import predict_points
from app.core.db import async_session_factory
from app.ingestion.fpl_client import get_bootstrap_static
from app.schemas.lineup import LineupOut, StartingPlayerOut, CaptainOptionOut, BenchCoverageOut, AutoSubOut, AutoSubSimulationOut

router = APIRouter()


def _build_autosub(sim: dict | None) -> AutoSubSimulationOut | None:
    if not sim:
        return None
    return AutoSubSimulationOut(
        substitutions=[
            AutoSubOut(
                out_id=s["out"].id, out_name=s["out"].web_name,
                in_id=s["in"].id,  in_name=s["in"].web_name,
            )
            for s in sim["substitutions"]
        ],
        unresolved_absences=[p.web_name for p in sim["unresolved_absences"]],
        effective_xi_ids=[p.id for p, _, _ in sim["effective_xi"]],
    )


@router.get("/lineup", response_model=LineupOut)
async def lineup_route(entry_id: int = Query(...), overrides: str | None = Query(default=None)):
    data = await get_bootstrap_static()
    current_event = next((e for e in data["events"] if e["is_current"]), None)
    if current_event is None:
        raise HTTPException(status_code=503, detail="No active gameweek")
    gameweek = current_event["id"]
    team_map = {t["id"]: t["short_name"] for t in data.get("teams", [])}

    override_map: dict[int, int] = {}
    if overrides:
        for pair in overrides.split(","):
            if ":" in pair:
                out_s, in_s = pair.split(":", 1)
                try:
                    override_map[int(out_s)] = int(in_s)
                except ValueError:
                    pass

    try:
        result = await pick_best_starting_xi_for_entry(entry_id, overrides=override_map or None)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="FPL entry not found")
        if e.response.status_code == 429:
            raise HTTPException(status_code=429, detail="FPL API rate limit — retry shortly")
        raise
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="FPL API unavailable — network error")
    starting_xi = result["starting_xi"]

    async with async_session_factory() as db:
        planning_gw = await get_planning_gameweek(db, gameweek)
        captain_scored = await score_for_captaincy(starting_xi, db, planning_gw)

        # Compute single-GW predicted points for the starting XI so we can show
        # actual expected pts on the captain/VC cards instead of a 0-100 rating.
        xi_rows = [(p, s) for p, s, _ in starting_xi]
        xi_team_ids = {p.team_id for p, s in xi_rows}
        xi_dgw_mults = await get_gameweek_fixture_multipliers(db, xi_team_ids, planning_gw)
        xi_predicted = await predict_points(
            xi_rows, db, gameweek=gameweek,
            fixture_from_gameweek=planning_gw, num_fixtures=1,
            fixture_count_multipliers=xi_dgw_mults,
        )
        predicted_pts_by_id = {p.id: round(sc, 1) for p, s, sc in xi_predicted}

        all_entries = [*starting_xi, *result["bench_outfield"]]
        if result["bench_gk"]:
            all_entries.append(result["bench_gk"])
        team_ids = {p.team_id for p, s, sc in all_entries}
        fixture_labels = await get_next_fixture_labels(db, team_ids, planning_gw)
        fixture_is_home = await get_next_fixture_is_home(db, team_ids, planning_gw)

    rec = get_captain_recommendation(captain_scored)

    stats_map = {entry[0].id: entry[1] for entry in all_entries}

    def to_out(player, score):
        st = stats_map.get(player.id)
        return StartingPlayerOut(
            id=player.id,
            web_name=player.web_name,
            position=player.position.value,
            score=score,
            team_short_name=team_map.get(player.team_id, "UNK"),
            next_fixture=fixture_labels.get(player.team_id),
            status=st.status if st else "a",
            chance_of_playing_next_round=st.chance_of_playing_next_round if st else None,
        )

    starting_players = [to_out(p, score) for p, s, score in starting_xi]
    bench_gk_entry = result["bench_gk"]
    bench_outfield_players = [to_out(p, score) for p, s, score in result["bench_outfield"]]

    ownership_by_id = {
        p.id: round(float(s.ownership_pct), 1)
        for p, s, _ in starting_xi
        if s.ownership_pct is not None
    }

    cap_id = rec["top_pick"]["player"].id
    vc_id  = rec["second_pick"]["player"].id
    cap_pts_raw = predicted_pts_by_id.get(cap_id, 0.0)
    vc_pts_raw  = predicted_pts_by_id.get(vc_id, 0.0)

    # Build stats lookup before any block that needs it (diff_entry, cap, vc).
    stats_by_id = {entry[0].id: entry[1] for entry in captain_scored}

    diff_entry = rec.get("differential_captain")
    if diff_entry is not None:
        diff_id = diff_entry[0].id
        diff_pts_raw = predicted_pts_by_id.get(diff_id, 0.0)
        diff_ownership = (
            float(diff_entry[1].ownership_pct)
            if diff_entry[1].ownership_pct is not None else None
        )
        diff_stats = stats_by_id.get(diff_id)
        differential_captain = CaptainOptionOut(
            id=diff_id,
            web_name=diff_entry[0].web_name,
            rating=round(diff_entry[2] * 100),
            predicted_pts=round(diff_pts_raw, 1),
            ownership_pct=diff_ownership,
            top_factors=get_captaincy_explanation(diff_id, captain_scored) or None,
            next_fixture_is_home=fixture_is_home.get(diff_entry[0].team_id),
            variance_level=get_captain_variance(diff_entry[0], diff_stats) if diff_stats else None,
            is_hot_form=is_hot_form(diff_stats, gameweek) if diff_stats else None,
        )
    else:
        differential_captain = None

    cap_player = rec["top_pick"]["player"]
    vc_player  = rec["second_pick"]["player"]
    cap_team_id = cap_player.team_id
    vc_team_id  = vc_player.team_id

    cap_stats = stats_by_id.get(cap_id)
    vc_stats  = stats_by_id.get(vc_id)

    return LineupOut(
        starting_xi=starting_players,
        captain=CaptainOptionOut(
            id=cap_id,
            web_name=cap_player.web_name,
            rating=rec["top_pick"]["rating"],
            predicted_pts=round(cap_pts_raw * 2, 1),  # ×2 for captain
            ownership_pct=ownership_by_id.get(cap_id),
            top_factors=get_captaincy_explanation(cap_id, captain_scored) or None,
            next_fixture_is_home=fixture_is_home.get(cap_team_id),
            variance_level=get_captain_variance(cap_player, cap_stats) if cap_stats else None,
            is_hot_form=is_hot_form(cap_stats, gameweek) if cap_stats else None,
        ),
        vice_captain=CaptainOptionOut(
            id=vc_id,
            web_name=vc_player.web_name,
            rating=rec["second_pick"]["rating"],
            predicted_pts=round(vc_pts_raw, 1),
            ownership_pct=ownership_by_id.get(vc_id),
            top_factors=get_captaincy_explanation(vc_id, captain_scored) or None,
            next_fixture_is_home=fixture_is_home.get(vc_team_id),
            variance_level=get_captain_variance(vc_player, vc_stats) if vc_stats else None,
            is_hot_form=is_hot_form(vc_stats, gameweek) if vc_stats else None,
        ),
        captain_advantage_pct=rec["advantage_pct"],
        tie_broken_by_ceiling=rec["tie_broken_by_ceiling"],
        bench_gk=to_out(bench_gk_entry[0], bench_gk_entry[2]) if bench_gk_entry else None,
        bench_outfield=bench_outfield_players,
        differential_captain=differential_captain,
        bench_coverage=BenchCoverageOut(**result["bench_coverage"]) if result.get("bench_coverage") else None,
        autosub_simulation=_build_autosub(result.get("autosub_simulation")),
    )

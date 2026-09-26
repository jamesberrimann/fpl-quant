import math
from itertools import combinations

from app.core.db import async_session_factory
from app.ingestion.fpl_client import get_bootstrap_static, get_entry_picks
from app.models.player import Position
from app.services.player_pool import get_latest_stats, filter_unavailable_players, filter_by_minimum_minutes, filter_by_recent_minutes, get_prev_gw_prices, get_prev_gw_ownership
from app.services.prediction import predict_points, compute_prediction_components
from app.services.rotation_risk import get_rotation_risk_scores, ROTATION_RISK_THRESHOLD
from app.services.fixtures import (
    get_fixture_timing_signal,
    get_planning_gameweek,
    get_gameweek_fixture_multipliers,
    get_opponent_strength_for_fixture,
)

POINTS_COST_PER_HIT = 4
MAX_BANKED_TRANSFERS = 5

# Gains below this are flagged as marginal when the manager could roll instead.
# 3 pts ≈ expected value of an extra banked transfer next week; above this,
# just make the transfer.
MARGINAL_GAIN_THRESHOLD = 3.0

# FPL prices change when cumulative net transfers for a player cross roughly 1%
# of total managers. We use this fraction as a same-GW proxy for direction.
_PRICE_MOVE_THRESHOLD_FRACTION = 0.01

# A player is "hot form" if their 4-GW rolling average is at least this much
# above their season average AND the absolute form is worth captaining.
_HOT_FORM_RATIO = 1.3   # 30% above season average
_HOT_FORM_MIN   = 6.0   # minimum form value to qualify (avoids flagging poor players)


def is_hot_form(stats, gameweek: int) -> bool:
    """True when recent form significantly exceeds the season average."""
    if gameweek < 4:
        return False
    season_avg = float(stats.total_points) / gameweek
    form = float(stats.form)
    return form >= season_avg * _HOT_FORM_RATIO and form >= _HOT_FORM_MIN
# Top replacement candidates to consider per outgoing slot.
# 5 × 15 = 75 pairs max → C(75,3) ≈ 67 K iterations, fast enough.
_MAX_REPLACEMENTS_PER_SLOT = 5
# Never search combinations larger than this — 1 hit beyond free transfers is
# the practical maximum worth evaluating in FPL.
_MAX_COMBO_SIZE = 3
# Discount applied to the incoming player's predicted score when the fixture
# timing signal recommends waiting (next fixture significantly harder than
# upcoming run). Suppresses marginal timing-bad transfers; large upgrades
# still surface but with honest discounted improvement.
_TIMING_DISCOUNT = 0.85


def improvement_drivers(out_components: dict, in_components: dict) -> list[str]:
    """
    Returns a list of plain-English tags explaining why the incoming player
    scores higher than the outgoing player.  Tags are only emitted when the
    difference is meaningful — small gaps are ignored to avoid noise.

    Possible tags (in descending priority):
      "Better fixture"  — incoming team has a notably easier upcoming run
      "Better form"     — incoming player's recent form is meaningfully higher
      "Higher output"   — incoming player's base xStats are notably stronger
    """
    tags = []
    # fixture_mult: >1 = easy, <1 = hard; gap > 0.15 is meaningful
    if in_components["fix_mult"] - out_components["fix_mult"] > 0.15:
        tags.append("Better fixture")
    # form_factor spans 0.85–1.15; gap > 0.08 (~one form-point worth)
    if in_components["form_factor"] - out_components["form_factor"] > 0.08:
        tags.append("Better form")
    # base_pts: raw xStats output; gap > 0.5 points is worth flagging
    if in_components["base_pts"] - out_components["base_pts"] > 0.5:
        tags.append("Higher output")
    return tags


def _valid_combo(combo, bank, team_counts, min_improvement, cost_sensitivity):
    """Return True if the (out, out_s, out_sc, in, in_s, in_sc, improvement) combo is jointly valid."""
    # No player sold or bought twice
    if len({t[0].id for t in combo}) < len(combo):
        return False
    if len({t[3].id for t in combo}) < len(combo):
        return False

    # Total bank cost across all transfers must be affordable
    if sum(float(t[4].price) - float(t[1].price) for t in combo) > bank:
        return False

    # Club limit: no team may end up with > 3 players after all transfers
    counts = dict(team_counts)
    for out_p, _, _, in_p, in_s, _, _ in combo:
        counts[out_p.team_id] = counts.get(out_p.team_id, 0) - 1
        counts[in_p.team_id] = counts.get(in_p.team_id, 0) + 1
        if counts.get(in_p.team_id, 0) > 3:
            return False

    # Each individual transfer must clear its own improvement threshold
    for out_p, out_s, _, in_p, in_s, _, improvement in combo:
        threshold = min_improvement + abs(float(in_s.price) - float(out_s.price)) * cost_sensitivity
        if improvement < threshold:
            return False

    return True


async def suggest_transfers(
    entry_id: int,
    free_transfers: int = 1,
    min_score_improvement: float = 1.5,
    cost_sensitivity: float = 0.1,
):
    async with async_session_factory() as db:
        data = await get_bootstrap_static()
        current_event = next((e for e in data["events"] if e["is_current"]), None)
        if current_event is None:
            raise ValueError("FPL API returned no current gameweek")
        gameweek = current_event["id"]

        picks_data = await get_entry_picks(entry_id, gameweek)
        my_element_ids = {pick["element"] for pick in picks_data["picks"]}
        bank = picks_data["entry_history"]["bank"] / 10

        planning_gameweek = await get_planning_gameweek(db, gameweek)
        rows = await get_latest_stats(db, gameweek)

        all_team_ids = {player.team_id for player, _ in rows}
        dgw_multipliers = await get_gameweek_fixture_multipliers(db, all_team_ids, planning_gameweek)

        scored_all = await predict_points(
            rows, db, gameweek=gameweek,
            fixture_from_gameweek=planning_gameweek,
            fixture_count_multipliers=dgw_multipliers,
        )

        reliable_rows = filter_unavailable_players(rows)
        reliable_rows = filter_by_minimum_minutes(reliable_rows)
        reliable_rows = await filter_by_recent_minutes(reliable_rows, gameweek)
        scored_candidates = await predict_points(
            reliable_rows, db, gameweek=gameweek,
            fixture_from_gameweek=planning_gameweek,
            fixture_count_multipliers=dgw_multipliers,
        )

        my_players = [
            (p, s, sc) for p, s, sc in scored_all if p.id in my_element_ids
        ]

        team_counts: dict[int, int] = {}
        for player, stats, score in my_players:
            team_counts[player.team_id] = team_counts.get(player.team_id, 0) + 1

        # ── Precompute last-GW price trajectory for all relevant players ────────
        all_relevant_ids = {p.id for p, _, _ in my_players} | {p.id for p, _, _ in scored_candidates}
        prev_prices = await get_prev_gw_prices(db, all_relevant_ids, gameweek)

        # ── Precompute prediction components for improvement breakdown ────────
        all_relevant_team_ids = {p.team_id for p, _, _ in my_players} | {p.team_id for p, _, _ in scored_candidates}
        opponent_strength_by_team = {
            tid: await get_opponent_strength_for_fixture(db, tid, planning_gameweek, num_fixtures=3)
            for tid in all_relevant_team_ids
        }
        components_by_player: dict[int, dict] = {}
        for collection in (my_players, scored_candidates):
            for player, stats, _ in collection:
                if player.id not in components_by_player:
                    opp = opponent_strength_by_team.get(player.team_id, {})
                    components_by_player[player.id] = compute_prediction_components(
                        player, stats, gameweek, opp
                    )

        # ── Net transfers this GW (price direction signal) ────────────────────
        # transfers_in_event - transfers_out_event > 0 → player is being bought
        # (price rising), < 0 → being sold (price falling).
        net_transfers_this_gw: dict[int, int] = {
            el["id"]: el.get("transfers_in_event", 0) - el.get("transfers_out_event", 0)
            for el in data["elements"]
        }
        # FPL prices move when net transfers cross ~1% of the total manager pool.
        total_managers = data.get("total_players", 10_000_000)
        _price_move_threshold = total_managers * _PRICE_MOVE_THRESHOLD_FRACTION

        # ── Precompute rotation risk for all candidate incoming players ──────
        candidate_ids = {p.id for p, _, _ in scored_candidates}
        rotation_risks = await get_rotation_risk_scores(db, candidate_ids, gameweek)

        # ── Precompute ownership trend (current vs prev GW) ──────────────────
        prev_ownership = await get_prev_gw_ownership(db, all_relevant_ids, gameweek)

        # ── Precompute fixture timing signals for all candidate team_ids ─────
        # Done once here so the combinatorial search can use discounted scores,
        # and the suggestion output can reuse the result without extra DB hits.
        candidate_team_ids = {p.team_id for p, _, _ in scored_candidates}
        timing_signal_by_team: dict[int, dict | None] = {}
        for team_id in candidate_team_ids:
            # Use a representative position (FWD) for the timing lookup —
            # the signal only distinguishes defensive vs attacking fixture ease,
            # and FWD is the most conservative (attacker facing a tough defence).
            timing_signal_by_team[team_id] = await get_fixture_timing_signal(
                db, team_id, Position.FWD, from_gameweek=gameweek
            )

        # ── Generate candidate (out, in) transfer pairs ───────────────────────
        # For each of my players find the top-N replacements by predicted score.
        # Apply a timing discount when the incoming player's next fixture is
        # significantly harder than their upcoming run — the combinatorial search
        # will naturally deprioritise or suppress these transfers.
        pair_candidates: list[tuple] = []
        for player, stats, score in my_players:
            max_price = float(stats.price) + bank
            slot_candidates = sorted(
                [
                    (new_p, new_s, new_sc)
                    for new_p, new_s, new_sc in scored_candidates
                    if new_p.position == player.position
                    and new_p.id not in my_element_ids
                    and float(new_s.price) <= max_price
                ],
                key=lambda x: x[2],
                reverse=True,
            )[:_MAX_REPLACEMENTS_PER_SLOT]
            for new_p, new_s, new_sc in slot_candidates:
                timing = timing_signal_by_team.get(new_p.team_id)
                effective_sc = new_sc * _TIMING_DISCOUNT if timing and timing.get("wait_recommended") else new_sc
                improvement = effective_sc - score
                if improvement > 0:
                    pair_candidates.append(
                        (player, stats, score, new_p, new_s, effective_sc, improvement)
                    )

        # ── Combinatorial search for the optimal subset of transfers ──────────
        # Try all valid combinations of size 1 .. min(free_transfers+1, _MAX_COMBO_SIZE).
        # Including free_transfers+1 lets us evaluate whether a single hit is worthwhile.
        # We pick the combo with the highest net improvement (total - hit penalty).
        best_combo: list | None = None
        best_net = -1e9

        max_size = min(free_transfers + 1, _MAX_COMBO_SIZE)
        for size in range(1, max_size + 1):
            hit_pts = max(0, size - free_transfers) * POINTS_COST_PER_HIT
            for combo in combinations(pair_candidates, size):
                if not _valid_combo(
                    combo, bank, team_counts, min_score_improvement, cost_sensitivity
                ):
                    continue
                net = sum(t[6] for t in combo) - hit_pts
                if net > best_net:
                    best_net = net
                    best_combo = list(combo)

        # ── Roll recommendation ───────────────────────────────────────────────
        banked_next = min(free_transfers + 1, MAX_BANKED_TRANSFERS)
        if free_transfers >= MAX_BANKED_TRANSFERS:
            # At cap — rolling wastes this week's earned transfer
            roll_recommendation = False
            roll_reason = (
                f"You have {free_transfers} banked transfers — make at least one "
                "or you waste this week's earned free transfer."
            ) if not best_combo else None
        elif not best_combo:
            roll_recommendation = True
            roll_reason = (
                f"Nothing worth transferring this week. Roll to bank "
                f"{banked_next} free transfer{'s' if banked_next > 1 else ''} for next gameweek."
            )
        else:
            roll_recommendation = False
            roll_reason = None

        if not best_combo:
            return {"suggestions": [], "roll_recommendation": roll_recommendation, "roll_reason": roll_reason}

        # ── Build suggestions from the winning combo ──────────────────────────
        # Sort by individual improvement desc; hit cost label follows position.
        best_combo.sort(key=lambda t: t[6], reverse=True)
        suggestions = []
        for i, (out_p, out_s, out_sc, in_p, in_s, in_sc, improvement) in enumerate(best_combo):
            price_change = float(in_s.price) - float(out_s.price)
            points_cost = 0 if i < free_transfers else POINTS_COST_PER_HIT
            timing_signal = timing_signal_by_team.get(in_p.team_id)
            in_dgw = dgw_multipliers.get(in_p.team_id, 1.0) >= 2.0
            in_ownership_pct = (
                float(in_s.ownership_pct) if in_s.ownership_pct is not None else None
            )
            is_differential = in_ownership_pct is not None and in_ownership_pct < 10.0

            in_prev = prev_prices.get(in_p.id)
            out_prev = prev_prices.get(out_p.id)
            in_price_last_gw_change = float(in_s.price - in_prev) if in_prev is not None else 0.0
            out_price_last_gw_change = float(out_s.price - out_prev) if out_prev is not None else 0.0

            in_rotation_risk = rotation_risks.get(in_p.id, 0.0)
            in_net_transfers = net_transfers_this_gw.get(in_p.id, 0)
            in_price_rise_likely = in_net_transfers > _price_move_threshold
            in_price_fall_likely = in_net_transfers < -_price_move_threshold
            in_hot_form = is_hot_form(in_s, gameweek)
            break_even_weeks = math.ceil(points_cost / improvement) if points_cost > 0 and improvement > 0 else None

            in_prev_own = prev_ownership.get(in_p.id)
            in_ownership_trend = (
                round(float(in_s.ownership_pct) - in_prev_own, 1)
                if in_prev_own is not None and in_s.ownership_pct is not None
                else None
            )

            drivers = improvement_drivers(
                components_by_player.get(out_p.id, {}),
                components_by_player.get(in_p.id, {}),
            )
            out_status = out_s.status if out_s.status else "a"
            out_chance = out_s.chance_of_playing_next_round
            if out_status in ("i", "s", "u") or out_chance == 0:
                drivers.insert(0, "Injured / unavailable")
            elif out_status == "d" or (out_chance is not None and out_chance < 75):
                drivers.insert(0, "Doubtful")
            elif out_chance is not None and out_chance < 100:
                drivers.insert(0, "Injury concern")

            is_marginal = (
                improvement < MARGINAL_GAIN_THRESHOLD
                and free_transfers < MAX_BANKED_TRANSFERS
            )
            suggestions.append({
                "out": out_p,
                "out_score": out_sc,
                "in": in_p,
                "in_score": in_sc,
                "improvement": improvement,
                "is_marginal": is_marginal,
                "price_change": price_change,
                "timing_signal": timing_signal,
                "in_dgw": in_dgw,
                "in_ownership_pct": in_ownership_pct,
                "is_differential": is_differential,
                "points_cost": points_cost,
                "in_price_last_gw_change": in_price_last_gw_change,
                "out_price_last_gw_change": out_price_last_gw_change,
                "in_rotation_risk": in_rotation_risk,
                "in_net_transfers_this_gw": in_net_transfers,
                "in_hot_form": in_hot_form,
                "break_even_weeks": break_even_weeks,
                "in_ownership_trend": in_ownership_trend,
                "in_price_rise_likely": in_price_rise_likely,
                "in_price_fall_likely": in_price_fall_likely,
                "improvement_drivers": drivers,
            })

        return {"suggestions": suggestions, "roll_recommendation": roll_recommendation, "roll_reason": roll_reason}

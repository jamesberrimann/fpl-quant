from decimal import Decimal
from datetime import datetime, timezone

import pytest

from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.services.transfers import suggest_transfers


def make_entry(id, team_id, position, price, score, ownership_pct="10.0"):
    player = Player(
        id=id, team_id=team_id,
        first_name="F", second_name="L", web_name=f"P{id}",
        position=position,
    )
    stats = PlayerGameweekStats(
        player_id=id, gameweek=4, pulled_at=datetime.now(timezone.utc),
        price=Decimal(str(price)), form=Decimal("5.0"),
        ownership_pct=Decimal(ownership_pct),
        total_points=10, minutes=270,
    )
    return (player, stats, score)


def _patch_all(monkeypatch, my_players, all_scored, bank_raw=0):
    """Monkeypatch all external dependencies for suggest_transfers."""
    async def fake_get_bootstrap_static():
        return {
            "events": [{"id": 4, "is_current": True}],
            "elements": [
                {"id": p.id, "transfers_in_event": 0, "transfers_out_event": 0}
                for p, _, _ in all_scored
            ],
        }

    async def fake_get_entry_picks(entry_id, gameweek):
        return {
            "picks": [{"element": p.id} for p, _, _ in my_players],
            "entry_history": {"bank": bank_raw},
        }

    async def fake_get_latest_stats(db, gameweek):
        return [(p, s) for p, s, _ in all_scored]

    def fake_filter_by_minimum_minutes(rows):
        return rows

    async def fake_filter_by_recent_minutes(rows, gameweek, min_minutes=1):
        return rows

    async def fake_predict_points(
        rows, db, gameweek, fixture_from_gameweek=None,
        num_fixtures=3, fixture_count_multipliers=None,
    ):
        return all_scored

    async def fake_get_planning_gameweek(db, current_gameweek):
        return current_gameweek

    async def fake_get_fixture_timing_signal(db, team_id, position, from_gameweek=1, gap_threshold=1.0):
        return None

    async def fake_get_gameweek_fixture_multipliers(db, team_ids, gameweek):
        return {tid: 1.0 for tid in team_ids}

    def fake_filter_unavailable_players(rows):
        return rows

    async def fake_get_prev_gw_prices(db, player_ids, current_gameweek):
        return {}

    async def fake_get_rotation_risk_scores(db, player_ids, current_gameweek):
        return {}

    async def fake_get_prev_gw_ownership(db, player_ids, current_gameweek):
        return {}

    async def fake_get_opponent_strength_for_fixture(db, team_id, from_gameweek, num_fixtures=3):
        return {}

    monkeypatch.setattr("app.services.transfers.get_bootstrap_static", fake_get_bootstrap_static)
    monkeypatch.setattr("app.services.transfers.get_entry_picks", fake_get_entry_picks)
    monkeypatch.setattr("app.services.transfers.get_latest_stats", fake_get_latest_stats)
    monkeypatch.setattr("app.services.transfers.filter_unavailable_players", fake_filter_unavailable_players)
    monkeypatch.setattr("app.services.transfers.filter_by_minimum_minutes", fake_filter_by_minimum_minutes)
    monkeypatch.setattr("app.services.transfers.filter_by_recent_minutes", fake_filter_by_recent_minutes)
    monkeypatch.setattr("app.services.transfers.predict_points", fake_predict_points)
    monkeypatch.setattr("app.services.transfers.get_planning_gameweek", fake_get_planning_gameweek)
    monkeypatch.setattr("app.services.transfers.get_fixture_timing_signal", fake_get_fixture_timing_signal)
    monkeypatch.setattr("app.services.transfers.get_gameweek_fixture_multipliers", fake_get_gameweek_fixture_multipliers)
    monkeypatch.setattr("app.services.transfers.get_prev_gw_prices", fake_get_prev_gw_prices)
    monkeypatch.setattr("app.services.transfers.get_rotation_risk_scores", fake_get_rotation_risk_scores)
    monkeypatch.setattr("app.services.transfers.get_prev_gw_ownership", fake_get_prev_gw_ownership)
    monkeypatch.setattr("app.services.transfers.get_opponent_strength_for_fixture", fake_get_opponent_strength_for_fixture)


async def test_suggest_transfers_returns_optimal_two_free_transfers(monkeypatch):
    """
    With 2 free transfers and 2 clear upgrades available (different positions),
    both should be returned as FREE suggestions sorted by improvement desc.

    Pure predicted scores: improvements are 3.5 and 3.3, both ≥ 1.5 ✓
    """
    my_p1 = make_entry(1, 9001, Position.FWD, price=5.0, score=0.0)
    my_p2 = make_entry(2, 9002, Position.MID, price=5.0, score=0.0)
    r1 = make_entry(3, 9003, Position.FWD, price=5.0, score=3.5)
    r2 = make_entry(4, 9004, Position.MID, price=5.0, score=3.3)
    all_scored = [my_p1, my_p2, r1, r2]

    _patch_all(monkeypatch, [my_p1, my_p2], all_scored, bank_raw=0)

    result = await suggest_transfers(entry_id=123, free_transfers=2)
    suggestions = result["suggestions"]

    assert len(suggestions) == 2
    # Both are free (within free_transfers allowance)
    assert suggestions[0]["points_cost"] == 0
    assert suggestions[1]["points_cost"] == 0
    # Sorted by improvement descending
    assert suggestions[0]["improvement"] >= suggestions[1]["improvement"]
    # Correct assignments
    assert suggestions[0]["in"].id == r1[0].id
    assert suggestions[1]["in"].id == r2[0].id


async def test_suggest_transfers_below_threshold_produces_no_suggestions(monkeypatch):
    """
    Transfers where improvement < 1.5 pts/GW should NOT be suggested.
    A -4pt hit needs at least ~1.5 pts/GW sustained for several weeks to break even;
    improvement = 0.9 - 0.0 = 0.9 < 1.5 → rejected.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    replacement = make_entry(2, 9002, Position.MID, price=5.0, score=0.9)
    all_scored = [my_player, replacement]

    _patch_all(monkeypatch, [my_player], all_scored)
    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 0, (
        "0.45 pt/GW improvement should be rejected by the 1.5 pt threshold — "
        "taking a -4pt hit for marginal gains loses rank long-term"
    )


async def test_combinatorial_search_beats_greedy_bank_depletion(monkeypatch):
    """
    The key regression test for Fix 7 — greedy ordering fails here.

    Setup: 2 free transfers, bank=£2m, two players to upgrade:
      P1 (FWD): best upgrade is X (+£2m, +2.0 pts) OR W (free, +1.8 pts)
      P2 (MID): best upgrade is Y (+£1.5m, +1.85 pts) OR Z (free, +1.6 pts)

    Greedy processes P1 first (2.0 > 1.85), buys X, drains bank to 0.
    P2 can no longer afford Y → falls back to Z.
    Greedy result: P1→X + P2→Z = 2.0 + 1.6 = 3.60 pts total.

    Combinatorial tries all valid pairs:
      P1→X + P2→Y: +£3.5m total > £2m bank → invalid
      P1→X + P2→Z: +£2.0m total ≤ £2m ✓ → 3.60 pts
      P1→W + P2→Y: +£1.5m total ≤ £2m ✓ → 3.65 pts  ← optimal
      P1→W + P2→Z: £0 total ✓ → 3.40 pts

    Combinatorial should return P1→W + P2→Y (total 3.65 > greedy's 3.60).
    """
    my_p1 = make_entry(1, 9001, Position.FWD, price=5.0, score=0.0)
    my_p2 = make_entry(2, 9002, Position.MID, price=5.0, score=0.0)
    # FWD replacements for P1: improvements = 4.0 and 3.6
    player_x = make_entry(3, 9003, Position.FWD, price=7.0, score=4.0)  # imp=4.0, costs £2m extra
    player_w = make_entry(4, 9004, Position.FWD, price=5.0, score=3.6)  # imp=3.6, free
    # MID replacements for P2: improvements = 3.7 and 3.2
    player_y = make_entry(5, 9005, Position.MID, price=6.5, score=3.7)  # imp=3.7, costs £1.5m extra
    player_z = make_entry(6, 9006, Position.MID, price=5.0, score=3.2)  # imp=3.2, free
    all_scored = [my_p1, my_p2, player_x, player_w, player_y, player_z]

    _patch_all(monkeypatch, [my_p1, my_p2], all_scored, bank_raw=20)  # bank=£2.0m

    result = await suggest_transfers(entry_id=123, free_transfers=2)
    suggestions = result["suggestions"]

    assert len(suggestions) == 2
    assert suggestions[0]["points_cost"] == 0
    assert suggestions[1]["points_cost"] == 0

    in_ids = {s["in"].id for s in suggestions}
    out_ids = {s["out"].id for s in suggestions}
    # Combinatorial must find W (id=4) and Y (id=5), not X (id=3) and Z (id=6)
    assert 4 in in_ids, "Should buy W (FWD, free), not X (FWD, expensive) — W+Y beats X+Z"
    assert 5 in in_ids, "Should buy Y (MID, £1.5m), not Z (MID, free) — W+Y beats X+Z"
    assert 1 in out_ids  # P1 sold
    assert 2 in out_ids  # P2 sold

    total_improvement = sum(s["improvement"] for s in suggestions)
    assert total_improvement == pytest.approx(3.6 + 3.7, abs=0.01), (
        f"Combinatorial should find W+Y (3.6+3.7=7.3), not X+Z (4.0+3.2=7.2). Got {total_improvement:.2f}"
    )


async def test_transfer_uses_predicted_score_not_season_pa(monkeypatch):
    """
    With the old 50/50 blend, a player with high season P/A (30 pts / 90 min = 30 pts/app)
    but low predicted score (1.0) would appear better than a player with low P/A
    (5 pts / 90 min) but high predicted score (4.0).

    Old blend:
      high_pa:  0.5*1.0 + 0.5*30 = 15.5
      high_pred: 0.5*4.0 + 0.5*5  = 4.5
    → old code would rank high_pa as better, suggesting the wrong transfer.

    Pure predicted (correct):
      high_pa:  1.0
      high_pred: 4.0
    → high_pred wins: improvement = 4.0 - 0.0 = 4.0 ≥ 1.5, correct suggestion.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)

    # High past points, poor predicted score (e.g. early-season flukey scorer, now out of form)
    high_pa = make_entry(2, 9002, Position.MID, price=5.0, score=1.0)
    high_pa[1].total_points = 30
    high_pa[1].minutes = 90  # 30 pts / 1 appearance = 30 pts/app

    # Low past points, excellent predicted score (e.g. new signing, great xStats)
    high_pred = make_entry(3, 9003, Position.MID, price=5.0, score=4.0)
    high_pred[1].total_points = 5
    high_pred[1].minutes = 90  # 5 pts / 1 appearance = 5 pts/app

    all_scored = [my_player, high_pa, high_pred]
    _patch_all(monkeypatch, [my_player], all_scored)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]

    assert len(suggestions) == 1
    assert suggestions[0]["in"].id == 3, (
        "high_pred (id=3, predicted=4.0) should be recommended over "
        "high_pa (id=2, predicted=1.0 despite 30 pts/app season average)"
    )


async def test_differential_flag_set_for_low_owned_incoming_player(monkeypatch):
    """
    is_differential=True only when the incoming player's ownership_pct < 10%.
    The improvement must already be ≥ 1.5 pts to appear in suggestions — ownership
    is purely an informational signal on top of a worthwhile transfer.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0, ownership_pct="20.0")
    # 7.5% owned — genuine differential with real predicted-point improvement
    replacement = make_entry(2, 9002, Position.MID, price=5.0, score=3.5, ownership_pct="7.5")
    all_scored = [my_player, replacement]

    _patch_all(monkeypatch, [my_player], all_scored)
    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]

    assert len(suggestions) == 1
    assert suggestions[0]["is_differential"] is True
    assert suggestions[0]["in_ownership_pct"] == pytest.approx(7.5)


async def test_differential_flag_not_set_for_highly_owned_incoming_player(monkeypatch):
    """
    is_differential=False when ownership_pct >= 10%, even if the transfer is worthwhile.
    Template picks shouldn't be flagged as differentials regardless of point improvement.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0, ownership_pct="20.0")
    # 10.0% — at the boundary, NOT a differential (strict < 10 required)
    replacement_boundary = make_entry(2, 9002, Position.MID, price=5.0, score=3.5, ownership_pct="10.0")
    # 30% — clearly template
    replacement_template = make_entry(3, 9003, Position.MID, price=5.0, score=3.3, ownership_pct="30.0")
    all_scored = [my_player, replacement_boundary, replacement_template]

    _patch_all(monkeypatch, [my_player], all_scored)
    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]

    assert len(suggestions) == 1
    assert suggestions[0]["is_differential"] is False
    assert suggestions[0]["in_ownership_pct"] == pytest.approx(10.0)


async def test_timing_discount_suppresses_marginal_transfer(monkeypatch):
    """
    A marginal transfer (improvement near the 1.5 threshold) should be suppressed
    when the incoming player has a bad fixture timing signal (wait_recommended=True).

    Without discount: improvement = 1.8 ≥ 1.5 → suggested
    With 15% discount: effective_sc = 1.8 * 0.85 = 1.53... wait, that's still ≥ 1.5

    Use a tighter case: raw improvement = 1.7, discounted = 1.7 * 0.85 = 1.445 < 1.5 → suppressed.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    # Without timing: improvement = 1.7 ≥ 1.5 → would be suggested
    # With timing:    1.7 * 0.85 = 1.445 < 1.5 → suppressed
    bad_timing_player = make_entry(2, 9002, Position.MID, price=5.0, score=1.7)
    all_scored = [my_player, bad_timing_player]

    bad_timing_signal = {"next_difficulty": 3.0, "rest_avg_difficulty": 1.5, "wait_recommended": True}

    async def fake_timing(db, team_id, position, from_gameweek=1, gap_threshold=1.0):
        return bad_timing_signal if team_id == 9002 else None

    _patch_all(monkeypatch, [my_player], all_scored)
    monkeypatch.setattr("app.services.transfers.get_fixture_timing_signal", fake_timing)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 0, (
        "Marginal transfer (improvement 1.7) should be suppressed by 15% timing discount "
        "(1.7 × 0.85 = 1.445 < 1.5 threshold)"
    )


async def test_timing_discount_does_not_suppress_strong_transfer(monkeypatch):
    """
    A strong transfer (large improvement) still surfaces when timing is bad,
    but with a discounted improvement value — the user sees the honest number.
    improvement = 4.0, discounted = 4.0 * 0.85 = 3.4 ≥ 1.5 → still suggested.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    strong_player = make_entry(2, 9002, Position.MID, price=5.0, score=4.0)
    all_scored = [my_player, strong_player]

    bad_timing_signal = {"next_difficulty": 3.0, "rest_avg_difficulty": 1.5, "wait_recommended": True}

    async def fake_timing(db, team_id, position, from_gameweek=1, gap_threshold=1.0):
        return bad_timing_signal if team_id == 9002 else None

    _patch_all(monkeypatch, [my_player], all_scored)
    monkeypatch.setattr("app.services.transfers.get_fixture_timing_signal", fake_timing)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1, "Strong transfer should still be suggested despite bad timing"
    assert suggestions[0]["improvement"] == pytest.approx(4.0 * 0.85, rel=1e-4), (
        "Improvement shown should reflect the timing discount"
    )
    assert suggestions[0]["timing_signal"] == bad_timing_signal


# ---------------------------------------------------------------------------
# Price trajectory (fix #8)
# ---------------------------------------------------------------------------

async def test_price_trajectory_included_in_suggestion(monkeypatch):
    """
    When the incoming player's price rose last GW, in_price_last_gw_change should be +0.1.
    When the outgoing player's price fell, out_price_last_gw_change should be -0.1.
    Both are informational — they do not affect whether the transfer is suggested.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    in_player  = make_entry(2, 9002, Position.MID, price=5.0, score=3.5)
    all_scored = [my_player, in_player]

    prev_prices_map = {
        1: Decimal("5.1"),  # out player fell 0.1 this GW
        2: Decimal("4.9"),  # in player rose 0.1 this GW
    }

    async def fake_get_prev_gw_prices(db, player_ids, current_gameweek):
        return {pid: prev_prices_map[pid] for pid in player_ids if pid in prev_prices_map}

    _patch_all(monkeypatch, [my_player], all_scored)
    monkeypatch.setattr("app.services.transfers.get_prev_gw_prices", fake_get_prev_gw_prices)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["out_price_last_gw_change"] == pytest.approx(-0.1, abs=0.01)
    assert suggestions[0]["in_price_last_gw_change"] == pytest.approx(0.1, abs=0.01)


async def test_price_trajectory_defaults_to_zero_when_no_prev_data(monkeypatch):
    """
    When there is no previous GW price data (e.g. GW1 or new player),
    both price trajectory fields default to 0.0 — no spurious signal.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    in_player  = make_entry(2, 9002, Position.MID, price=5.0, score=3.5)
    all_scored = [my_player, in_player]

    # _patch_all already patches get_prev_gw_prices to return {}
    _patch_all(monkeypatch, [my_player], all_scored)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["in_price_last_gw_change"] == pytest.approx(0.0)
    assert suggestions[0]["out_price_last_gw_change"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Rotation risk (feature #2)
# ---------------------------------------------------------------------------

async def test_rotation_risk_included_in_suggestion(monkeypatch):
    """
    When the incoming player has a computed rotation risk, it is surfaced on the
    suggestion so the user can see that the 'upgrade' may rarely start.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    in_player  = make_entry(2, 9002, Position.MID, price=5.0, score=3.5)
    all_scored = [my_player, in_player]

    async def fake_rotation_risk(db, player_ids, current_gameweek):
        return {2: 0.45}  # averaging ~49.5 min/game → flagged

    _patch_all(monkeypatch, [my_player], all_scored)
    monkeypatch.setattr("app.services.transfers.get_rotation_risk_scores", fake_rotation_risk)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["in_rotation_risk"] == pytest.approx(0.45)


async def test_rotation_risk_defaults_to_zero_when_no_data(monkeypatch):
    """
    Players with no recent minutes data (GW1, new signings) get 0.0 rotation risk —
    no spurious penalty for unknown players.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    in_player  = make_entry(2, 9002, Position.MID, price=5.0, score=3.5)
    all_scored = [my_player, in_player]

    # _patch_all patches get_rotation_risk_scores to return {} (no data)
    _patch_all(monkeypatch, [my_player], all_scored)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["in_rotation_risk"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Net transfers this GW / price direction (feature #3)
# ---------------------------------------------------------------------------

async def test_net_transfers_this_gw_positive_when_player_being_bought(monkeypatch):
    """
    When a player has more transfers in than out this GW, in_net_transfers_this_gw
    is positive — the player is trending toward a price rise.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    in_player  = make_entry(2, 9002, Position.MID, price=5.0, score=3.5)
    all_scored = [my_player, in_player]

    async def fake_bootstrap():
        return {
            "events": [{"id": 4, "is_current": True}],
            "elements": [
                {"id": 1, "transfers_in_event": 5000, "transfers_out_event": 1000},
                {"id": 2, "transfers_in_event": 80000, "transfers_out_event": 10000},
            ],
        }

    _patch_all(monkeypatch, [my_player], all_scored)
    monkeypatch.setattr("app.services.transfers.get_bootstrap_static", fake_bootstrap)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["in_net_transfers_this_gw"] == 70000


async def test_net_transfers_defaults_to_zero_when_field_absent(monkeypatch):
    """
    When the bootstrap element doesn't have transfer event fields (e.g. GW1 before
    any transfers), in_net_transfers_this_gw defaults to 0 — no spurious signal.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    in_player  = make_entry(2, 9002, Position.MID, price=5.0, score=3.5)
    all_scored = [my_player, in_player]

    async def fake_bootstrap():
        # Elements without the transfer event fields
        return {
            "events": [{"id": 4, "is_current": True}],
            "elements": [{"id": 1}, {"id": 2}],
        }

    _patch_all(monkeypatch, [my_player], all_scored)
    monkeypatch.setattr("app.services.transfers.get_bootstrap_static", fake_bootstrap)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["in_net_transfers_this_gw"] == 0


# ---------------------------------------------------------------------------
# Break-even weeks (fix #2)
# ---------------------------------------------------------------------------

async def test_break_even_weeks_set_for_hit_transfer(monkeypatch):
    """
    A -4pt hit with 2.0 pts/GW improvement should break even in 2 GWs (ceil(4/2.0)).
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    in_player  = make_entry(2, 9002, Position.MID, price=5.0, score=2.0)
    all_scored = [my_player, in_player]

    _patch_all(monkeypatch, [my_player], all_scored)

    result = await suggest_transfers(entry_id=123, free_transfers=0)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["points_cost"] == 4
    assert suggestions[0]["break_even_weeks"] == 2


async def test_break_even_weeks_none_for_free_transfer(monkeypatch):
    """Free transfers have no hit cost, so break_even_weeks is None."""
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    in_player  = make_entry(2, 9002, Position.MID, price=5.0, score=3.5)
    all_scored = [my_player, in_player]

    _patch_all(monkeypatch, [my_player], all_scored)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["points_cost"] == 0
    assert suggestions[0]["break_even_weeks"] is None


# ---------------------------------------------------------------------------
# Hot form indicator (fix #3)
# ---------------------------------------------------------------------------

async def test_hot_form_flagged_when_recent_form_exceeds_season_average(monkeypatch):
    """
    Player with 12pts form but 8pts season average is hot (12/8 = 1.5 > 1.3 threshold).
    """
    from decimal import Decimal
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    in_player  = make_entry(2, 9002, Position.MID, price=5.0, score=3.5)
    # Set form=12 and total_points=80 over 10 GWs → season avg=8 → form/avg=1.5
    in_player[1].total_points = 80
    in_player[1].form = Decimal("12.0")
    all_scored = [my_player, in_player]

    # Patch bootstrap to set gameweek=10 so season_avg = 80/10 = 8
    async def fake_bootstrap():
        return {
            "events": [{"id": 10, "is_current": True}],
            "elements": [
                {"id": p.id, "transfers_in_event": 0, "transfers_out_event": 0}
                for p, _, _ in all_scored
            ],
        }

    _patch_all(monkeypatch, [my_player], all_scored)
    monkeypatch.setattr("app.services.transfers.get_bootstrap_static", fake_bootstrap)

    # Also fake entry_picks to use gameweek 10
    async def fake_picks(entry_id, gameweek):
        return {
            "picks": [{"element": my_player[0].id}],
            "entry_history": {"bank": 0},
        }
    monkeypatch.setattr("app.services.transfers.get_entry_picks", fake_picks)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["in_hot_form"] is True


async def test_hot_form_not_flagged_for_consistent_season_form(monkeypatch):
    """Player with form matching season average is not hot."""
    from decimal import Decimal
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    in_player  = make_entry(2, 9002, Position.MID, price=5.0, score=3.5)
    in_player[1].total_points = 80
    in_player[1].form = Decimal("8.0")  # exactly matches season avg
    all_scored = [my_player, in_player]

    _patch_all(monkeypatch, [my_player], all_scored)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["in_hot_form"] is False


# ---------------------------------------------------------------------------
# Ownership trend (fix #5)
# ---------------------------------------------------------------------------

async def test_ownership_trend_positive_when_player_being_bought(monkeypatch):
    """
    Player owned by 20% last GW but 25% now → trend = +5.0.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    in_player  = make_entry(2, 9002, Position.MID, price=5.0, score=3.5, ownership_pct="25.0")
    all_scored = [my_player, in_player]

    async def fake_prev_own(db, player_ids, current_gameweek):
        return {2: 20.0}

    _patch_all(monkeypatch, [my_player], all_scored)
    monkeypatch.setattr("app.services.transfers.get_prev_gw_ownership", fake_prev_own)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["in_ownership_trend"] == pytest.approx(5.0, abs=0.1)


async def test_ownership_trend_none_when_no_prev_data(monkeypatch):
    """When no previous GW ownership data exists (GW1), trend is None."""
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    in_player  = make_entry(2, 9002, Position.MID, price=5.0, score=3.5)
    all_scored = [my_player, in_player]

    # _patch_all already patches get_prev_gw_ownership to return {}
    _patch_all(monkeypatch, [my_player], all_scored)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["in_ownership_trend"] is None


# ---------------------------------------------------------------------------
# Price change prediction (fix #2 — new feature)
# ---------------------------------------------------------------------------

async def test_price_rise_likely_when_net_transfers_exceed_threshold(monkeypatch):
    """
    When a player has net transfers > 1% of total managers (default 10M → threshold
    100K), in_price_rise_likely should be True.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    in_player  = make_entry(2, 9002, Position.MID, price=5.0, score=3.5)
    all_scored = [my_player, in_player]

    async def fake_bootstrap():
        return {
            "events": [{"id": 4, "is_current": True}],
            "total_players": 10_000_000,
            "elements": [
                {"id": 1, "transfers_in_event": 0,       "transfers_out_event": 0},
                {"id": 2, "transfers_in_event": 200_000, "transfers_out_event": 0},
            ],
        }

    _patch_all(monkeypatch, [my_player], all_scored)
    monkeypatch.setattr("app.services.transfers.get_bootstrap_static", fake_bootstrap)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["in_price_rise_likely"] is True
    assert suggestions[0]["in_price_fall_likely"] is False


async def test_price_fall_likely_when_net_transfers_below_negative_threshold(monkeypatch):
    """
    When a player is being sold (large negative net), in_price_fall_likely should
    be True and in_price_rise_likely False.
    """
    my_player = make_entry(1, 9001, Position.MID, price=5.0, score=0.0)
    in_player  = make_entry(2, 9002, Position.MID, price=5.0, score=3.5)
    all_scored = [my_player, in_player]

    async def fake_bootstrap():
        return {
            "events": [{"id": 4, "is_current": True}],
            "total_players": 10_000_000,
            "elements": [
                {"id": 1, "transfers_in_event": 0,       "transfers_out_event": 0},
                {"id": 2, "transfers_in_event": 0,       "transfers_out_event": 200_000},
            ],
        }

    _patch_all(monkeypatch, [my_player], all_scored)
    monkeypatch.setattr("app.services.transfers.get_bootstrap_static", fake_bootstrap)

    result = await suggest_transfers(entry_id=123, free_transfers=1)
    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["in_price_fall_likely"] is True
    assert suggestions[0]["in_price_rise_likely"] is False


# ---------------------------------------------------------------------------
# improvement_drivers pure function (transfer breakdown — new feature)
# ---------------------------------------------------------------------------

from app.services.transfers import improvement_drivers


def test_improvement_drivers_fixture_advantage():
    """Incoming player has notably easier fixture (fix_mult gap > 0.15)."""
    out = {"fix_mult": 0.80, "form_factor": 1.00, "base_pts": 3.0}
    inp = {"fix_mult": 1.00, "form_factor": 1.00, "base_pts": 3.0}
    tags = improvement_drivers(out, inp)
    assert "Better fixture" in tags
    assert "Better form" not in tags
    assert "Higher output" not in tags


def test_improvement_drivers_form_advantage():
    """Incoming player has meaningfully better form (form_factor gap > 0.08)."""
    out = {"fix_mult": 1.00, "form_factor": 0.90, "base_pts": 3.0}
    inp = {"fix_mult": 1.00, "form_factor": 1.05, "base_pts": 3.0}
    tags = improvement_drivers(out, inp)
    assert "Better form" in tags
    assert "Better fixture" not in tags


def test_improvement_drivers_multiple_advantages():
    """Both fixture and output advantages surfaces both tags."""
    out = {"fix_mult": 0.80, "form_factor": 1.00, "base_pts": 2.0}
    inp = {"fix_mult": 1.00, "form_factor": 1.00, "base_pts": 3.0}
    tags = improvement_drivers(out, inp)
    assert "Better fixture" in tags
    assert "Higher output" in tags


# ---------------------------------------------------------------------------
# Missing current gameweek (international break / season gap)
# ---------------------------------------------------------------------------

async def test_suggest_transfers_raises_when_no_current_gameweek(monkeypatch):
    """During international breaks the FPL API has no is_current=True event.

    Previously this silently raised StopIteration (caught by the scheduler's
    broad except-Exception but with a useless log).  Now it raises ValueError
    with an informative message so operators know why ingestion skipped.
    """
    async def fake_bootstrap_no_gw():
        return {
            "events": [{"id": 5, "is_current": False}, {"id": 6, "is_current": False}],
            "elements": [],
            "total_players": 10_000_000,
        }

    monkeypatch.setattr("app.services.transfers.get_bootstrap_static", fake_bootstrap_no_gw)

    with pytest.raises(ValueError, match="no current gameweek"):
        await suggest_transfers(entry_id=123, free_transfers=1)

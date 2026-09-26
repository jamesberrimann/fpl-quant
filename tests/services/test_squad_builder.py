import pytest
from unittest.mock import MagicMock

from app.models.player import Position
from app.services.squad_builder import build_optimal_squad, _compute_captain_premiums


def _mock_stats(total_points: int, minutes: int = 450):
    s = MagicMock()
    s.total_points = total_points
    s.minutes = minutes
    return s


async def test_build_optimal_squad_wires_pipeline_correctly(monkeypatch):
    call_log = []
    p1, p2 = MagicMock(), MagicMock()
    s1, s2 = _mock_stats(200), _mock_stats(100)

    async def fake_get_bootstrap_static():
        return {"events": [{"id": 4, "is_current": True}, {"id": 3, "is_current": False}]}

    async def fake_get_latest_stats(db, gameweek):
        call_log.append(("get_latest_stats", gameweek))
        return [(p1, s1), (p2, s2)]

    def fake_filter_by_minimum_minutes(rows):
        call_log.append(("filter_by_minimum_minutes", rows))
        return rows

    async def fake_filter_by_recent_minutes(rows, gameweek, min_minutes=60):
        call_log.append(("filter_by_recent_minutes", rows, gameweek))
        return rows

    async def fake_predict_points(rows, db, gameweek, fixture_from_gameweek=None, num_fixtures=3, fixture_count_multipliers=None):
        call_log.append(("predict_points", rows, gameweek))
        return [(p1, s1, 8.0), (p2, s2, 4.0)]

    async def fake_get_planning_gameweek(db, current_gameweek):
        return current_gameweek

    async def fake_get_fixture_counts_in_gameweek_window(db, team_ids, from_gameweek, num_gameweeks=5):
        # Default: 1 fixture/GW × 5 GWs = 5 (baseline), so scale factor = 1.0
        return {tid: 5 for tid in team_ids}

    def fake_optimize_squad(scored, budget):
        call_log.append(("optimize_squad", scored, budget))
        return ["final_squad"]

    monkeypatch.setattr("app.services.squad_builder.get_bootstrap_static", fake_get_bootstrap_static)
    monkeypatch.setattr("app.services.squad_builder.get_latest_stats", fake_get_latest_stats)
    monkeypatch.setattr("app.services.squad_builder.filter_by_minimum_minutes", fake_filter_by_minimum_minutes)
    monkeypatch.setattr("app.services.squad_builder.filter_by_recent_minutes", fake_filter_by_recent_minutes)
    monkeypatch.setattr("app.services.squad_builder.predict_points", fake_predict_points)
    monkeypatch.setattr("app.services.squad_builder.get_planning_gameweek", fake_get_planning_gameweek)
    monkeypatch.setattr("app.services.squad_builder.get_fixture_counts_in_gameweek_window", fake_get_fixture_counts_in_gameweek_window)
    monkeypatch.setattr("app.services.squad_builder.optimize_squad", fake_optimize_squad)

    result = await build_optimal_squad(budget=95.0)

    assert result == ["final_squad"]

    steps = [entry[0] for entry in call_log]
    assert steps == [
        "get_latest_stats",
        "filter_by_minimum_minutes",
        "filter_by_recent_minutes",
        "predict_points",
        "optimize_squad",
    ]

    assert call_log[0][1] == 4
    assert call_log[2][2] == 4
    assert call_log[3][2] == 4
    assert call_log[4][2] == 95.0

    # Verify scoring: predicted_score × (fixture_count / 5) × (1 + captain_premium)
    #   fixture_count = 5 → scale = 5/5 = 1.0
    #   MagicMock().position != Position.MID/FWD → _compute_captain_premiums returns {} → premium = 0.0
    # p1: 8.0 × 1.0 × 1.0 = 8.0
    # p2: 4.0 × 1.0 × 1.0 = 4.0
    scored_for_optimizer = call_log[4][1]
    assert scored_for_optimizer[0][2] == pytest.approx(8.0)
    assert scored_for_optimizer[1][2] == pytest.approx(4.0)


def test_captain_premium_concentrates_on_top_scorer():
    """
    Softmax captain premium should give the highest premium to the highest-scoring
    MID/FWD and near-zero to GKPs/DEFs, correctly reflecting how captaincy
    concentrates on premium attacking assets.
    """
    from unittest.mock import MagicMock

    def _make(position, score):
        p = MagicMock()
        p.id = id(p)
        p.position = position
        return p, MagicMock(), score

    elite_fwd = _make(Position.FWD, 9.0)
    budget_fwd = _make(Position.FWD, 5.0)
    elite_mid = _make(Position.MID, 8.0)
    gkp = _make(Position.GKP, 7.0)

    scored = [elite_fwd, budget_fwd, elite_mid, gkp]
    premiums = _compute_captain_premiums(scored)

    elite_fwd_id = elite_fwd[0].id
    budget_fwd_id = budget_fwd[0].id
    elite_mid_id = elite_mid[0].id
    gkp_id = gkp[0].id

    # GKP gets zero premium (not in attacking pool)
    assert premiums.get(gkp_id, 0.0) == 0.0

    # Elite FWD (9.0) should get a higher premium than elite MID (8.0)
    assert premiums[elite_fwd_id] > premiums[elite_mid_id]

    # Elite FWD should get a higher premium than budget FWD (5.0)
    assert premiums[elite_fwd_id] > premiums[budget_fwd_id]

    # All attacking premiums sum to 1.0 (probability distribution)
    total = sum(premiums[p[0].id] for p in [elite_fwd, budget_fwd, elite_mid])
    assert total == pytest.approx(1.0, rel=1e-6)

    # Top scorer should capture the majority of expected captaincy
    assert premiums[elite_fwd_id] > 0.5, (
        f"Elite FWD (9.0pts) should capture >50% captain probability, got {premiums[elite_fwd_id]:.2f}"
    )

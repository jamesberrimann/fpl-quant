from decimal import Decimal
from datetime import datetime, timezone

from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.services.lineup import pick_best_starting_xi_for_entry


def make_entry(id, position, score, team_id=9001):
    player = Player(id=id, team_id=team_id, first_name="F", second_name="L", web_name=f"P{id}", position=position)
    stats = PlayerGameweekStats(
        player_id=id, gameweek=4, pulled_at=datetime.now(timezone.utc),
        price=Decimal("5.0"), form=Decimal("5.0"), ownership_pct=Decimal("10.0"),
        total_points=10, minutes=270,
    )
    return (player, stats, score)


async def test_pick_best_starting_xi_for_entry_wires_full_pipeline(monkeypatch):
    all_scored = (
        [make_entry(1, Position.GKP, 0.9), make_entry(2, Position.GKP, 0.3)]
        + [make_entry(i, Position.DEF, 0.9 - i * 0.05) for i in range(3, 8)]
        + [make_entry(i, Position.MID, 0.9 - i * 0.05) for i in range(8, 13)]
        + [make_entry(i, Position.FWD, 0.9 - i * 0.05) for i in range(13, 16)]
    )

    async def fake_get_bootstrap_static():
        return {"events": [{"id": 4, "is_current": True}]}

    async def fake_get_entry_picks(entry_id, gameweek):
        return {"picks": [{"element": i} for i in range(1, 16)]}

    async def fake_get_latest_stats(db, gameweek):
        return "raw_rows"

    async def fake_predict_points(rows, db, gameweek, fixture_from_gameweek=None, num_fixtures=3):
        return all_scored

    async def fake_get_planning_gameweek(db, current_gameweek):
        return current_gameweek

    async def fake_get_recent_minutes_by_player_id(gameweek):
        return {}

    async def fake_get_started_status_by_team_id(gameweek):
        return {9001: False}

    monkeypatch.setattr("app.ingestion.fpl_client.get_bootstrap_static", fake_get_bootstrap_static)
    monkeypatch.setattr("app.ingestion.fpl_client.get_entry_picks", fake_get_entry_picks)
    monkeypatch.setattr("app.services.player_pool.get_latest_stats", fake_get_latest_stats)
    monkeypatch.setattr("app.services.prediction.predict_points", fake_predict_points)
    monkeypatch.setattr("app.services.fixtures.get_planning_gameweek", fake_get_planning_gameweek)
    monkeypatch.setattr(
        "app.services.player_pool.get_recent_minutes_by_player_id", fake_get_recent_minutes_by_player_id
    )
    monkeypatch.setattr(
        "app.services.player_pool.get_started_status_by_team_id", fake_get_started_status_by_team_id
    )

    result = await pick_best_starting_xi_for_entry(entry_id=123)

    assert len(result["starting_xi"]) == 11
    starting_ids = {p.id for p, s, sc in result["starting_xi"]}
    assert 1 in starting_ids
    assert 2 not in starting_ids

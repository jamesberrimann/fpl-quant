from decimal import Decimal
from datetime import datetime, timezone

from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.services.squad_rating import rate_squad


def make_entry(id, position, score, xgc=None):
    player = Player(id=id, team_id=9001, first_name="F", second_name="L", web_name=f"P{id}", position=position)
    stats = PlayerGameweekStats(
        player_id=id, gameweek=4, pulled_at=datetime.now(timezone.utc),
        price=Decimal("5.0"), form=Decimal("5.0"), ownership_pct=Decimal("10.0"),
        expected_goals_conceded_per_90=Decimal(str(xgc)) if xgc is not None else None,
        total_points=10, minutes=270,
    )
    return (player, stats, score)


async def test_rate_squad_wires_pipeline_and_scopes_xgc_by_position(monkeypatch):
    all_scored = [
        make_entry(1, Position.DEF, score=0.9, xgc=0.2),
        make_entry(2, Position.DEF, score=0.5, xgc=1.0),
        make_entry(3, Position.GKP, score=0.9, xgc=0.2),
        make_entry(4, Position.GKP, score=0.5, xgc=1.0),
        make_entry(5, Position.MID, score=0.5),
    ]

    async def fake_get_bootstrap_static():
        return {"events": [{"id": 4, "is_current": True}]}

    async def fake_get_entry_picks(entry_id, gameweek):
        return {"picks": [{"element": 1}, {"element": 3}, {"element": 5}]}

    async def fake_get_latest_stats(db, gameweek):
        return "raw_rows"

    async def fake_predict_points(rows, db, gameweek, fixture_from_gameweek=None):
        return all_scored

    async def fake_get_planning_gameweek(db, current_gameweek):
        return current_gameweek

    monkeypatch.setattr("app.services.squad_rating.get_bootstrap_static", fake_get_bootstrap_static)
    monkeypatch.setattr("app.services.squad_rating.get_entry_picks", fake_get_entry_picks)
    monkeypatch.setattr("app.services.squad_rating.get_latest_stats", fake_get_latest_stats)
    monkeypatch.setattr("app.services.squad_rating.predict_points", fake_predict_points)
    monkeypatch.setattr("app.services.squad_rating.get_planning_gameweek", fake_get_planning_gameweek)

    my_players = await rate_squad(entry_id=123)

    assert len(my_players) == 3

    result_by_id = {p.id: (score, percentile, flag) for p, s, score, percentile, flag in my_players}

    def_score, def_percentile, def_flag = result_by_id[1]
    assert def_percentile == 50.0
    assert def_flag is None

    gkp_score, gkp_percentile, gkp_flag = result_by_id[3]
    assert gkp_percentile == 50.0
    assert gkp_flag is None

    mid_score, mid_percentile, mid_flag = result_by_id[5]
    assert mid_percentile == 0.0
    assert mid_flag is None

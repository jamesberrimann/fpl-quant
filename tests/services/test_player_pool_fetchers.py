from app.services.player_pool import get_recent_minutes_by_player_id, get_started_status_by_team_id


async def test_get_recent_minutes_by_player_id_builds_correct_dict(monkeypatch):
    async def fake_get_gameweek_live(gameweek):
        return {
            "elements": [
                {"id": 1, "stats": {"minutes": 90}},
                {"id": 2, "stats": {"minutes": 45}},
            ]
        }

    monkeypatch.setattr("app.ingestion.fpl_client.get_gameweek_live", fake_get_gameweek_live)

    result = await get_recent_minutes_by_player_id(gameweek=4)

    assert result == {1: 90, 2: 45}


async def test_get_started_status_by_team_id_filters_by_gameweek_and_started(monkeypatch):
    async def fake_get_fixtures():
        return [
            {"event": 4, "started": True, "team_h": 1, "team_a": 2},
            {"event": 4, "started": False, "team_h": 3, "team_a": 4},
            {"event": 3, "started": True, "team_h": 5, "team_a": 6},
        ]

    monkeypatch.setattr("app.ingestion.fpl_client.get_fixtures", fake_get_fixtures)

    result = await get_started_status_by_team_id(gameweek=4)

    assert result == {1: True, 2: True}
    assert 3 not in result
    assert 5 not in result

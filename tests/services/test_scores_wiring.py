from app.services.scores import get_squad_scores, get_squad_live_events


async def test_get_squad_scores_wires_pipeline_and_dedupes_by_club(monkeypatch):
    async def fake_get_bootstrap_static():
        return {
            "events": [{"id": 4, "is_current": True}],
            "elements": [
                {"id": 1, "team": 9001},
                {"id": 2, "team": 9001},
                {"id": 3, "team": 9002},
            ],
        }

    async def fake_get_entry_picks(entry_id, gameweek):
        return {"picks": [{"element": 1}, {"element": 2}, {"element": 3}]}

    async def fake_get_latest_team_score(team_id, current_gameweek=None):
        return {"team_id": team_id, "gameweek": current_gameweek}

    monkeypatch.setattr("app.services.scores.get_bootstrap_static", fake_get_bootstrap_static)
    monkeypatch.setattr("app.ingestion.fpl_client.get_entry_picks", fake_get_entry_picks)
    monkeypatch.setattr("app.services.scores.get_latest_team_score", fake_get_latest_team_score)

    results = await get_squad_scores(entry_id=123)

    team_ids = {r["team_id"] for r in results}
    assert team_ids == {9001, 9002}
    assert len(results) == 2


async def test_get_squad_scores_skips_teams_with_no_score(monkeypatch):
    async def fake_get_bootstrap_static():
        return {
            "events": [{"id": 4, "is_current": True}],
            "elements": [{"id": 1, "team": 9001}],
        }

    async def fake_get_entry_picks(entry_id, gameweek):
        return {"picks": [{"element": 1}]}

    async def fake_get_latest_team_score(team_id, current_gameweek=None):
        return None

    monkeypatch.setattr("app.services.scores.get_bootstrap_static", fake_get_bootstrap_static)
    monkeypatch.setattr("app.ingestion.fpl_client.get_entry_picks", fake_get_entry_picks)
    monkeypatch.setattr("app.services.scores.get_latest_team_score", fake_get_latest_team_score)

    results = await get_squad_scores(entry_id=123)

    assert results == []


async def test_get_squad_live_events_flags_current_vs_stale_gameweek(monkeypatch):
    async def fake_get_bootstrap_static():
        return {
            "events": [{"id": 4, "is_current": True}],
            "elements": [
                {"id": 1, "team": 9001, "web_name": "Live Player",  "element_type": 3},
                {"id": 2, "team": 9002, "web_name": "Stale Player", "element_type": 4},
            ],
            "teams": [
                {"id": 9001, "short_name": "LP"},
                {"id": 9002, "short_name": "SP"},
            ],
        }

    async def fake_get_entry_picks(entry_id, gameweek):
        return {"picks": [{"element": 1}, {"element": 2}]}

    async def fake_get_player_live_events(player_id, team_id):
        if player_id == 1:
            return {"gameweek": 4, "stats": {"bps": 20}}
        return {"gameweek": 3, "stats": {"bps": 10}}

    monkeypatch.setattr("app.services.scores.get_bootstrap_static", fake_get_bootstrap_static)
    monkeypatch.setattr("app.ingestion.fpl_client.get_entry_picks", fake_get_entry_picks)
    monkeypatch.setattr("app.services.scores.get_player_live_events", fake_get_player_live_events)

    results = await get_squad_live_events(entry_id=123)

    result_by_id = {r["player_id"]: r for r in results}
    assert result_by_id[1]["is_current_gameweek"] is True
    assert result_by_id[2]["is_current_gameweek"] is False

from app.services.scores import get_latest_team_score, get_player_live_events


def make_fixture(event, team_h, team_a, team_h_score, team_a_score, finished_provisional=True, finished=False, stats=None):
    return {
        "event": event,
        "team_h": team_h,
        "team_a": team_a,
        "team_h_score": team_h_score,
        "team_a_score": team_a_score,
        "finished_provisional": finished_provisional,
        "finished": finished,
        "stats": stats or [],
    }


async def test_get_latest_team_score_returns_none_with_no_finished_fixtures(monkeypatch):
    async def fake_get_fixtures():
        return [make_fixture(4, 1, 2, 0, 0, finished_provisional=False)]

    monkeypatch.setattr("app.services.scores.get_fixtures", fake_get_fixtures)

    result = await get_latest_team_score(team_id=1)
    assert result is None


async def test_get_latest_team_score_picks_most_recent_gameweek(monkeypatch):
    async def fake_get_fixtures():
        return [
            make_fixture(3, 1, 2, 1, 1),
            make_fixture(4, 1, 3, 2, 0),
        ]

    async def fake_get_bootstrap_static():
        return {"teams": [
            {"id": 1, "name": "Team A", "short_name": "TA"},
            {"id": 2, "name": "Team B", "short_name": "TB"},
            {"id": 3, "name": "Team C", "short_name": "TC"},
        ]}

    monkeypatch.setattr("app.services.scores.get_fixtures", fake_get_fixtures)
    monkeypatch.setattr("app.services.scores.get_bootstrap_static", fake_get_bootstrap_static)

    result = await get_latest_team_score(team_id=1, current_gameweek=4)

    assert result["gameweek"] == 4
    assert result["is_current_gameweek"] is True
    assert result["team_name"] == "Team A"
    assert result["opponent_name"] == "Team C"
    assert result["team_score"] == 2
    assert result["opponent_score"] == 0


async def test_get_latest_team_score_correctly_reads_away_side(monkeypatch):
    async def fake_get_fixtures():
        return [make_fixture(4, 5, 1, 3, 1)]

    async def fake_get_bootstrap_static():
        return {"teams": [
            {"id": 1, "name": "Away Team", "short_name": "AWY"},
            {"id": 5, "name": "Home Team", "short_name": "HME"},
        ]}

    monkeypatch.setattr("app.services.scores.get_fixtures", fake_get_fixtures)
    monkeypatch.setattr("app.services.scores.get_bootstrap_static", fake_get_bootstrap_static)

    result = await get_latest_team_score(team_id=1)

    assert result["is_home"] is False
    assert result["team_score"] == 1
    assert result["opponent_score"] == 3
    assert result["opponent_name"] == "Home Team"


async def test_get_player_live_events_returns_empty_dict_when_no_events(monkeypatch):
    async def fake_get_fixtures():
        return [make_fixture(4, 1, 2, 0, 0, stats=[])]

    monkeypatch.setattr("app.services.scores.get_fixtures", fake_get_fixtures)

    result = await get_player_live_events(player_id=99, team_id=1)
    assert result == {}


async def test_get_player_live_events_extracts_correct_player_from_correct_side(monkeypatch):
    stats = [
        {"identifier": "goals_scored", "h": [{"element": 10, "value": 2}], "a": [{"element": 20, "value": 1}]},
        {"identifier": "assists", "h": [], "a": [{"element": 20, "value": 1}]},
    ]

    async def fake_get_fixtures():
        return [make_fixture(4, 1, 2, 2, 1, stats=stats)]

    monkeypatch.setattr("app.services.scores.get_fixtures", fake_get_fixtures)

    result = await get_player_live_events(player_id=20, team_id=2)

    assert result["gameweek"] == 4
    assert result["stats"] == {"goals_scored": 1, "assists": 1}

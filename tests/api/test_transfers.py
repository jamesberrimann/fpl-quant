from unittest.mock import AsyncMock, MagicMock, patch

MOCK_BS = {"teams": [{"id": 1, "short_name": "ARS"}, {"id": 2, "short_name": "LIV"}]}


def _make_suggestion(timing_signal=None):
    out_p = MagicMock()
    out_p.id = 1
    out_p.web_name = "Out Player"
    out_p.position.value = "MID"
    out_p.team_id = 1
    in_p = MagicMock()
    in_p.id = 2
    in_p.web_name = "In Player"
    in_p.team_id = 2
    return {
        "out": out_p,
        "in": in_p,
        "improvement": 5.0,
        "price_change": -0.5,
        "points_cost": 0,
        "timing_signal": timing_signal,
    }


async def test_suggest_transfers_missing_entry_id_returns_422(client, auth):
    r = await client.get("/api/v1/suggest-transfers", headers=auth)
    assert r.status_code == 422


async def test_suggest_transfers_happy_path_no_timing(client, auth):
    with patch("app.api.v1.transfers.get_bootstrap_static", new=AsyncMock(return_value=MOCK_BS)), \
         patch("app.api.v1.transfers.suggest_transfers", new=AsyncMock(return_value={"suggestions": [_make_suggestion()], "roll_recommendation": False, "roll_reason": None})):
        r = await client.get("/api/v1/suggest-transfers", headers=auth, params={"entry_id": 123})

    assert r.status_code == 200
    s = r.json()["suggestions"][0]
    assert s["out_web_name"] == "Out Player"
    assert s["in_web_name"] == "In Player"
    assert s["out_team_short_name"] == "ARS"
    assert s["in_team_short_name"] == "LIV"
    assert s["timing_signal"] is None
    assert s["points_cost"] == 0


async def test_suggest_transfers_with_timing_signal(client, auth):
    timing = {"next_difficulty": 1.5, "rest_avg_difficulty": 0.8, "wait_recommended": True}
    with patch("app.api.v1.transfers.get_bootstrap_static", new=AsyncMock(return_value=MOCK_BS)), \
         patch("app.api.v1.transfers.suggest_transfers", new=AsyncMock(return_value={"suggestions": [_make_suggestion(timing)], "roll_recommendation": False, "roll_reason": None})):
        r = await client.get("/api/v1/suggest-transfers", headers=auth, params={"entry_id": 123, "free_transfers": 2})

    assert r.status_code == 200
    sig = r.json()["suggestions"][0]["timing_signal"]
    assert sig["wait_recommended"] is True
    assert sig["next_difficulty"] == 1.5


async def test_suggest_transfers_network_error_returns_503(client, auth):
    """Timeout / connection error from the FPL API must return 503, not crash."""
    import httpx
    with patch("app.api.v1.transfers.get_bootstrap_static", new=AsyncMock(return_value=MOCK_BS)), \
         patch("app.api.v1.transfers.suggest_transfers",
               new=AsyncMock(side_effect=httpx.ConnectTimeout("timeout", request=None))):
        r = await client.get("/api/v1/suggest-transfers", headers=auth, params={"entry_id": 123})
    assert r.status_code == 503
    assert "network error" in r.json()["detail"].lower()


async def test_suggest_transfers_rate_limited_returns_429(client, auth):
    """FPL API 429 should be forwarded as 429, not a 500."""
    import httpx
    mock_response = MagicMock()
    mock_response.status_code = 429
    with patch("app.api.v1.transfers.get_bootstrap_static", new=AsyncMock(return_value=MOCK_BS)), \
         patch("app.api.v1.transfers.suggest_transfers",
               new=AsyncMock(side_effect=httpx.HTTPStatusError("rate limited", request=None, response=mock_response))):
        r = await client.get("/api/v1/suggest-transfers", headers=auth, params={"entry_id": 123})
    assert r.status_code == 429


async def test_suggest_transfers_hit_cost_labeled(client, auth):
    suggestion = _make_suggestion()
    suggestion["points_cost"] = 4
    with patch("app.api.v1.transfers.get_bootstrap_static", new=AsyncMock(return_value=MOCK_BS)), \
         patch("app.api.v1.transfers.suggest_transfers", new=AsyncMock(return_value={"suggestions": [suggestion], "roll_recommendation": False, "roll_reason": None})):
        r = await client.get("/api/v1/suggest-transfers", headers=auth, params={"entry_id": 1, "free_transfers": 0})

    assert r.json()["suggestions"][0]["points_cost"] == 4

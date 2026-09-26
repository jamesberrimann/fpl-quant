import pytest

PROTECTED_URLS = [
    "/api/v1/players",
    "/api/v1/optimize-squad",
    "/api/v1/rate-squad?entry_id=1",
    "/api/v1/suggest-transfers?entry_id=1",
    "/api/v1/lineup?entry_id=1",
    "/api/v1/team-score?team_id=1",
    "/api/v1/squad-scores?entry_id=1",
    "/api/v1/squad-live-events?entry_id=1",
]


@pytest.mark.parametrize("url", PROTECTED_URLS)
async def test_missing_api_key_returns_422(client, url):
    # FastAPI declares the header as required (= Header(...)), so a missing header
    # fails pydantic validation before auth logic even runs → 422
    r = await client.get(url)
    assert r.status_code == 422


@pytest.mark.parametrize("url", PROTECTED_URLS)
async def test_wrong_api_key_returns_401(client, url):
    r = await client.get(url, headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 401

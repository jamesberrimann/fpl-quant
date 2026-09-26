from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager
from decimal import Decimal
from datetime import datetime, timezone

from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats


def _player(id, pos, team_id=1):
    p = Player(id=id, team_id=team_id, first_name="F", second_name="L",
               web_name=f"P{id}", position=pos)
    return p


def _stats(player_id, ownership):
    return PlayerGameweekStats(
        player_id=player_id, gameweek=5,
        pulled_at=datetime.now(timezone.utc),
        price=Decimal("5.0"), form=Decimal("5.0"),
        ownership_pct=Decimal(str(ownership)) if ownership is not None else None,
        total_points=30, minutes=270,
    )


def _mock_bootstrap():
    return {
        "events": [{"id": 5, "is_current": True}],
        "teams": [{"id": 1, "short_name": "TST"}],
    }


def _mock_picks(player_ids):
    return {"picks": [{"element": pid} for pid in player_ids]}


async def test_squad_template_happy_path(client, auth):
    players = [
        (_player(1, Position.MID), _stats(1, 5.0)),   # differential
        (_player(2, Position.MID), _stats(2, 15.0)),  # core
        (_player(3, Position.FWD), _stats(3, 45.0)),  # template
    ]
    mock_db = AsyncMock()

    @asynccontextmanager
    async def mock_factory():
        yield mock_db

    with patch("app.api.v1.template.get_bootstrap_static", new=AsyncMock(return_value=_mock_bootstrap())), \
         patch("app.api.v1.template.get_entry_picks", new=AsyncMock(return_value=_mock_picks([1, 2, 3]))), \
         patch("app.api.v1.template.async_session_factory", new=mock_factory), \
         patch("app.api.v1.template.get_latest_stats", new=AsyncMock(return_value=players)):
        r = await client.get("/api/v1/squad-template", headers=auth, params={"entry_id": 123})

    assert r.status_code == 200
    data = r.json()
    assert "divergence_score" in data
    assert "players" in data
    assert len(data["players"]) == 3
    assert "differentials" in data
    assert "template_picks" in data
    assert "by_position" in data

    classifications = {p["id"]: p["classification"] for p in data["players"]}
    assert classifications[1] == "differential"
    assert classifications[2] == "core"
    assert classifications[3] == "template"


async def test_squad_template_missing_entry_id_returns_422(client, auth):
    r = await client.get("/api/v1/squad-template", headers=auth)
    assert r.status_code == 422


async def test_squad_template_unknown_entry_returns_404(client, auth):
    import httpx
    with patch("app.api.v1.template.get_bootstrap_static", new=AsyncMock(return_value=_mock_bootstrap())), \
         patch("app.api.v1.template.get_entry_picks",
               new=AsyncMock(side_effect=httpx.HTTPStatusError(
                   "not found", request=MagicMock(), response=MagicMock(status_code=404)))):
        r = await client.get("/api/v1/squad-template", headers=auth, params={"entry_id": 999})
    assert r.status_code == 404

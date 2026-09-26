from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.services.squad_projection import _pick_best_xi, get_squad_projection


def _player(id, pos: Position, team_id=1):
    return Player(id=id, team_id=team_id, first_name="F", second_name="L",
                  web_name=f"P{id}", position=pos)


def _stats(player_id):
    return PlayerGameweekStats(
        player_id=player_id, gameweek=5,
        pulled_at=datetime.now(timezone.utc),
        price=Decimal("5.0"), form=Decimal("5.0"),
        total_points=50, minutes=450,
    )


def _scored(id, pos, pts, team_id=1):
    p = _player(id, pos, team_id)
    return (p, _stats(id), pts)


# ── _pick_best_xi pure function ───────────────────────────────────────────────

def _squad_442():
    """15 players in a 1-4-4-2 layout with a GKP bench."""
    return [
        _scored(1,  Position.GKP, 5.0),
        _scored(2,  Position.DEF, 4.0), _scored(3,  Position.DEF, 4.0),
        _scored(4,  Position.DEF, 4.0), _scored(5,  Position.DEF, 4.0),
        _scored(6,  Position.MID, 6.0), _scored(7,  Position.MID, 6.0),
        _scored(8,  Position.MID, 6.0), _scored(9,  Position.MID, 6.0),
        _scored(10, Position.FWD, 7.0), _scored(11, Position.FWD, 7.0),
        # bench
        _scored(12, Position.GKP, 2.0),
        _scored(13, Position.DEF, 1.0),
        _scored(14, Position.MID, 1.5),
        _scored(15, Position.FWD, 1.5),
    ]


def test_pick_best_xi_returns_eleven_players():
    xi, _ = _pick_best_xi(_squad_442())
    assert len(xi) == 11


def test_pick_best_xi_includes_exactly_one_gkp():
    xi, _ = _pick_best_xi(_squad_442())
    gkps = [p for p, _, _ in xi if p.position == Position.GKP]
    assert len(gkps) == 1


def test_pick_best_xi_prefers_higher_scorers():
    """The player scored at 0.1 should not be in the best XI."""
    squad = _squad_442()
    # Replace one bench MID with a very low scorer
    squad[-2] = _scored(14, Position.MID, 0.1)
    xi, _ = _pick_best_xi(squad)
    xi_ids = {p.id for p, _, _ in xi}
    assert 14 not in xi_ids


def test_pick_best_xi_total_equals_sum_of_xi_scores():
    xi, total = _pick_best_xi(_squad_442())
    assert total == pytest.approx(sum(sc for _, _, sc in xi), abs=0.01)


def test_pick_best_xi_plays_three_fwds_when_beneficial():
    """When FWDs all score much higher, formation should shift to accommodate 3."""
    squad = [
        _scored(1,  Position.GKP, 5.0),
        _scored(2,  Position.DEF, 3.0), _scored(3, Position.DEF, 3.0),
        _scored(4,  Position.DEF, 3.0),
        _scored(5,  Position.MID, 2.0), _scored(6, Position.MID, 2.0),
        _scored(7,  Position.MID, 2.0), _scored(8, Position.MID, 2.0),
        _scored(9,  Position.FWD, 9.0), _scored(10, Position.FWD, 9.0),
        _scored(11, Position.FWD, 9.0),
        _scored(12, Position.GKP, 2.0),
        _scored(13, Position.DEF, 1.0),
        _scored(14, Position.MID, 1.0),
        _scored(15, Position.FWD, 1.0),
    ]
    xi, _ = _pick_best_xi(squad)
    fwds = [p for p, _, _ in xi if p.position == Position.FWD]
    assert len(fwds) == 3


# ── get_squad_projection integration (mocked) ────────────────────────────────

async def test_squad_projection_returns_one_entry_per_gameweek(monkeypatch):
    """Happy path: 3-GW projection returns 3 entries."""
    rows = _squad_442()
    player_stats_rows = [(p, s) for p, s, _ in rows]
    element_ids = {p.id for p, _ in player_stats_rows}

    bs = {
        "events": [
            {"id": 5, "is_current": True},
            {"id": 6, "is_current": False},
            {"id": 7, "is_current": False},
        ],
    }

    monkeypatch.setattr(
        "app.services.squad_projection.get_bootstrap_static", AsyncMock(return_value=bs)
    )
    monkeypatch.setattr(
        "app.services.squad_projection.get_entry_picks",
        AsyncMock(return_value={"picks": [{"element": eid} for eid in element_ids]}),
    )
    monkeypatch.setattr(
        "app.services.squad_projection.get_latest_stats",
        AsyncMock(return_value=player_stats_rows),
    )
    monkeypatch.setattr(
        "app.services.squad_projection.get_gameweek_fixture_multipliers",
        AsyncMock(return_value={1: 1.0}),
    )
    monkeypatch.setattr(
        "app.services.squad_projection.predict_points",
        AsyncMock(return_value=rows),
    )

    with patch("app.services.squad_projection.async_session_factory") as mock_factory:
        mock_db = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await get_squad_projection(entry_id=123, num_gameweeks=3)

    assert len(result) == 3
    for gw_data in result:
        assert "gameweek" in gw_data
        assert "predicted_total" in gw_data
        assert gw_data["predicted_total"] > 0


async def test_squad_projection_dgw_counted_correctly(monkeypatch):
    """A team with multiplier ≥ 2.0 should be counted as DGW."""
    rows = _squad_442()
    player_stats_rows = [(p, s) for p, s, _ in rows]
    element_ids = {p.id for p, _ in player_stats_rows}

    bs = {"events": [{"id": 5, "is_current": True}, {"id": 6, "is_current": False}]}

    monkeypatch.setattr("app.services.squad_projection.get_bootstrap_static", AsyncMock(return_value=bs))
    monkeypatch.setattr(
        "app.services.squad_projection.get_entry_picks",
        AsyncMock(return_value={"picks": [{"element": eid} for eid in element_ids]}),
    )
    monkeypatch.setattr("app.services.squad_projection.get_latest_stats", AsyncMock(return_value=player_stats_rows))
    monkeypatch.setattr("app.services.squad_projection.predict_points", AsyncMock(return_value=rows))
    # team_id=1 has a DGW
    monkeypatch.setattr(
        "app.services.squad_projection.get_gameweek_fixture_multipliers",
        AsyncMock(return_value={1: 2.0}),
    )

    with patch("app.services.squad_projection.async_session_factory") as mock_factory:
        mock_db = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await get_squad_projection(entry_id=123, num_gameweeks=1)

    assert result[0]["dgw_player_count"] > 0

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import pytest

from app.ingestion.ingest import (
    _compute_per_gw_xstats,
    ingest_fixtures,
    ingest_player_stats,
    ingest_teams_and_players,
)
from app.models.player_gameweek_stats import PlayerGameweekStats

BOOTSTRAP = {
    "teams": [
        {
            "id": 1, "name": "Arsenal", "short_name": "ARS",
            "strength_overall_home": 4, "strength_overall_away": 3,
            "strength_attack_home": 4, "strength_attack_away": 3,
            "strength_defence_home": 4, "strength_defence_away": 3,
        }
    ],
    "elements": [
        {
            "id": 100, "team": 1, "first_name": "Mo", "second_name": "Salah",
            "web_name": "Salah", "element_type": 4,
            "now_cost": 130, "form": "8.5", "selected_by_percent": "45.2",
            "expected_goals_conceded_per_90": "0.50",
            "defensive_contribution_per_90": "0.20",
            "expected_goals_per_90": "0.80",
            "total_points": 120, "minutes": 2500,
        }
    ],
    "events": [{"id": 5, "is_current": True}, {"id": 6, "is_current": False}],
}

FIXTURES_RAW = [
    {
        "id": 1, "event": 5, "team_h": 1, "team_a": 2,
        "team_h_difficulty": 3, "team_a_difficulty": 2,
        "team_h_score": None, "team_a_score": None, "finished": False,
    }
]


def _mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    # execute() is awaitable; its result has synchronous .scalars().all()
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = []
    session.execute.return_value = execute_result
    return session


def _mock_factory(session):
    @asynccontextmanager
    async def factory():
        yield session
    return factory


async def test_ingest_teams_and_players_merges_team_and_player():
    session = _mock_session()
    with patch("app.ingestion.ingest.get_bootstrap_static", new=AsyncMock(return_value=BOOTSTRAP)), \
         patch("app.ingestion.ingest.async_session_factory", new=_mock_factory(session)):
        await ingest_teams_and_players()

    # 1 team merge + 1 player merge
    assert session.merge.await_count == 2
    session.commit.assert_awaited_once()


async def test_ingest_player_stats_merges_team_player_then_adds_stats():
    session = _mock_session()
    with patch("app.ingestion.ingest.get_bootstrap_static", new=AsyncMock(return_value=BOOTSTRAP)), \
         patch("app.ingestion.ingest.async_session_factory", new=_mock_factory(session)):
        await ingest_player_stats()

    # merge: 1 team + 1 player; add: 1 stats row
    assert session.merge.await_count == 2
    session.flush.assert_awaited_once()
    assert session.add.call_count == 1
    session.commit.assert_awaited_once()


async def test_ingest_player_stats_uses_current_gameweek():
    session = _mock_session()
    added_stats = []
    session.add = MagicMock(side_effect=lambda s: added_stats.append(s))

    with patch("app.ingestion.ingest.get_bootstrap_static", new=AsyncMock(return_value=BOOTSTRAP)), \
         patch("app.ingestion.ingest.async_session_factory", new=_mock_factory(session)):
        await ingest_player_stats()

    assert len(added_stats) == 1
    assert added_stats[0].gameweek == 5


async def test_ingest_fixtures_merges_each_fixture():
    session = _mock_session()
    with patch("app.ingestion.ingest.get_fixtures", new=AsyncMock(return_value=FIXTURES_RAW)), \
         patch("app.ingestion.ingest.async_session_factory", new=_mock_factory(session)):
        await ingest_fixtures()

    assert session.merge.await_count == 1
    session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# _compute_per_gw_xstats
# ---------------------------------------------------------------------------

def _prev_stats(minutes, xg_per_90=None, xa_per_90=None, xgc_per_90=None) -> PlayerGameweekStats:
    return PlayerGameweekStats(
        player_id=100, gameweek=4,
        pulled_at=datetime.now(timezone.utc),
        price=Decimal("7.5"), form=Decimal("5.0"),
        ownership_pct=Decimal("10.0"),
        expected_goals_per_90=Decimal(str(xg_per_90)) if xg_per_90 is not None else None,
        expected_assists_per_90=Decimal(str(xa_per_90)) if xa_per_90 is not None else None,
        expected_goals_conceded_per_90=Decimal(str(xgc_per_90)) if xgc_per_90 is not None else None,
        total_points=30, minutes=minutes,
    )


def test_compute_per_gw_xstats_returns_none_when_no_prev():
    raw = {"minutes": 2700, "expected_goals_per_90": "0.5"}
    assert _compute_per_gw_xstats(raw, prev=None) == (None, None, None)


def test_compute_per_gw_xstats_returns_none_when_no_minute_gain():
    raw = {"minutes": 2700, "expected_goals_per_90": "0.5"}
    prev = _prev_stats(minutes=2700, xg_per_90=0.5)
    assert _compute_per_gw_xstats(raw, prev) == (None, None, None)

    # Minutes can't decrease, but guard against data corrections
    raw_less = {"minutes": 2600, "expected_goals_per_90": "0.5"}
    assert _compute_per_gw_xstats(raw_less, prev) == (None, None, None)


def test_compute_per_gw_xstats_computes_correct_delta():
    # prev: 2700 min, xg/90=0.5, xa/90=0.3, xgc/90=1.0
    # now:  2790 min, xg/90=0.51, xa/90=0.31, xgc/90=0.99
    # delta_min = 90 (1 full game)
    # cumulative xg: 0.51*(2790/90)=15.81  vs 0.5*(2700/90)=15.0  → delta=0.81 → 0.81/90*90=0.81/gw
    # cumulative xa: 0.31*31=9.61 vs 0.3*30=9.0 → delta=0.61
    # cumulative xgc: 0.99*31=30.69 vs 1.0*30=30.0 → delta=0.69
    prev = _prev_stats(minutes=2700, xg_per_90=0.5, xa_per_90=0.3, xgc_per_90=1.0)
    raw = {
        "minutes": 2790,
        "expected_goals_per_90": "0.51",
        "expected_assists_per_90": "0.31",
        "expected_goals_conceded_per_90": "0.99",
    }
    xg_gw, xa_gw, xgc_gw = _compute_per_gw_xstats(raw, prev)
    assert float(xg_gw) == pytest.approx(0.81, abs=0.01)
    assert float(xa_gw) == pytest.approx(0.61, abs=0.01)
    assert float(xgc_gw) == pytest.approx(0.69, abs=0.01)


def test_compute_per_gw_xstats_clamps_negative_delta():
    # If cumulative total dips slightly due to rounding, clamp to 0.
    # prev xg total = 0.52 * (2700/90) = 15.6; now = 0.50 * (2790/90) = 15.5 → delta < 0
    prev = _prev_stats(minutes=2700, xg_per_90=0.52, xa_per_90=0.0, xgc_per_90=0.0)
    raw = {
        "minutes": 2790,
        "expected_goals_per_90": "0.50",
        "expected_assists_per_90": "0.0",
        "expected_goals_conceded_per_90": "0.0",
    }
    xg_gw, xa_gw, xgc_gw = _compute_per_gw_xstats(raw, prev)
    assert float(xg_gw) == pytest.approx(0.0)


async def test_ingest_player_stats_raises_when_no_current_gameweek():
    """StopIteration became an opaque crash — now a ValueError with a clear message.

    This happens during international breaks or the season gap when the FPL API
    has no event with is_current=True.  The scheduler catches ValueError via
    logger.exception and continues scheduling; a plain StopIteration would have
    silently leaked through the except-Exception block with no useful log message.
    """
    no_current_gw = dict(BOOTSTRAP, events=[{"id": 5, "is_current": False}])
    with patch("app.ingestion.ingest.get_bootstrap_static", new=AsyncMock(return_value=no_current_gw)):
        with pytest.raises(ValueError, match="no current gameweek"):
            await ingest_player_stats()


def test_compute_per_gw_xstats_returns_none_when_prev_stat_is_none():
    # If the prev snapshot has no xG data, that component returns None.
    prev = _prev_stats(minutes=2700, xg_per_90=None, xa_per_90=0.3, xgc_per_90=None)
    raw = {
        "minutes": 2790,
        "expected_goals_per_90": "0.5",
        "expected_assists_per_90": "0.31",
        "expected_goals_conceded_per_90": "1.0",
    }
    xg_gw, xa_gw, xgc_gw = _compute_per_gw_xstats(raw, prev)
    assert xg_gw is None          # prev had no xG to diff against
    assert float(xa_gw) == pytest.approx(0.61, abs=0.01)
    assert xgc_gw is None         # prev had no xGC to diff against

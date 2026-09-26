from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.db import async_session_factory
from app.ingestion.fpl_client import get_bootstrap_static, get_fixtures
from app.ingestion.mappers import map_player_stats, map_player, map_team, map_fixture
from app.models.player_gameweek_stats import PlayerGameweekStats


async def ingest_teams_and_players() -> None:
    data = await get_bootstrap_static()

    async with async_session_factory() as session:
        for raw_team in data["teams"]:
            team = map_team(raw_team)
            await session.merge(team)

        for raw_player in data["elements"]:
            player = map_player(raw_player)
            await session.merge(player)

        await session.commit()


def _compute_minutes_this_gw(raw: dict, prev: PlayerGameweekStats | None) -> int | None:
    """Minutes actually played in this specific gameweek.

    Returns None when the previous snapshot is unavailable (GW1 or new signing),
    so callers can distinguish 'not started yet' from 'played 0 minutes'.
    Returns 0 when the player was in the squad but didn't play.
    """
    if prev is None:
        return None
    delta = raw.get("minutes", 0) - int(prev.minutes)
    return max(0, delta)


def _compute_per_gw_xstats(
    raw: dict,
    prev: PlayerGameweekStats | None,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """
    Derive per-GW xStats by diffing cumulative season totals between snapshots.

    The FPL API stores season-aggregate per-90 rates alongside season-aggregate
    minutes. Multiplying rate × (minutes/90) recovers the cumulative total; the
    delta between consecutive GW snapshots is what the player actually did this GW.
    """
    if prev is None:
        return None, None, None

    cur_min = raw.get("minutes", 0)
    prev_min = int(prev.minutes)
    delta_min = cur_min - prev_min
    if delta_min <= 0:
        return None, None, None

    def _delta_per_90(cur_rate_raw, prev_rate: Decimal | None) -> Decimal | None:
        if cur_rate_raw is None or prev_rate is None:
            return None
        cur_total = float(cur_rate_raw) * (cur_min / 90.0)
        prev_total = float(prev_rate) * (prev_min / 90.0)
        delta = cur_total - prev_total
        if delta < 0:
            delta = 0.0
        per_90 = delta / (delta_min / 90.0)
        return Decimal(str(round(per_90, 2)))

    xg_gw = _delta_per_90(raw.get("expected_goals_per_90"), prev.expected_goals_per_90)
    xa_gw = _delta_per_90(raw.get("expected_assists_per_90"), prev.expected_assists_per_90)
    xgc_gw = _delta_per_90(raw.get("expected_goals_conceded_per_90"), prev.expected_goals_conceded_per_90)
    return xg_gw, xa_gw, xgc_gw


async def ingest_player_stats() -> None:
    data = await get_bootstrap_static()
    current_event = next((e for e in data["events"] if e["is_current"]), None)
    if current_event is None:
        raise ValueError("FPL API returned no current gameweek — skipping player stats ingestion")
    current_gameweek = current_event["id"]
    pulled_at = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        for raw_team in data["teams"]:
            team = map_team(raw_team)
            await session.merge(team)

        for raw_player in data["elements"]:
            player = map_player(raw_player)
            await session.merge(player)

        await session.flush()

        # Batch-fetch the most-recent previous-GW snapshot for every player so
        # we can compute per-GW xStats deltas without N+1 queries.
        prev_gw = current_gameweek - 1
        prev_stats_rows: list[PlayerGameweekStats] = []
        if prev_gw >= 1:
            result = await session.execute(
                select(PlayerGameweekStats)
                .where(PlayerGameweekStats.gameweek == prev_gw)
            )
            prev_stats_rows = result.scalars().all()

        prev_by_player: dict[int, PlayerGameweekStats] = {
            row.player_id: row for row in prev_stats_rows
        }

        for raw_player in data["elements"]:
            stats = map_player_stats(raw_player, current_gameweek, pulled_at)
            prev = prev_by_player.get(raw_player["id"])
            xg_gw, xa_gw, xgc_gw = _compute_per_gw_xstats(raw_player, prev)
            stats.xg_this_gw_per_90 = xg_gw
            stats.xa_this_gw_per_90 = xa_gw
            stats.xgc_this_gw_per_90 = xgc_gw
            stats.minutes_this_gw = _compute_minutes_this_gw(raw_player, prev)
            session.add(stats)

        await session.commit()


async def ingest_fixtures() -> None:
    fixtures = await get_fixtures()

    async with async_session_factory() as session:
        for raw_fixture in fixtures:
            fixture = map_fixture(raw_fixture)
            await session.merge(fixture)

        await session.commit()

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.player import Player
from app.models.player_gameweek_stats import PlayerGameweekStats


async def get_latest_stats(db: AsyncSession, gameweek: int):
    row_number = (
        func.row_number()
        .over(
            partition_by=PlayerGameweekStats.player_id,
            order_by=PlayerGameweekStats.pulled_at.desc(),
        )
        .label("rn")
    )

    subq = (
        select(PlayerGameweekStats, row_number)
        .where(PlayerGameweekStats.gameweek == gameweek)
        .subquery()
    )

    latest_stats = aliased(PlayerGameweekStats, subq)

    stmt = (
        select(Player, latest_stats)
        .join(latest_stats, latest_stats.player_id == Player.id)
        .where(subq.c.rn == 1)
    )

    result = await db.execute(stmt)
    return result.all()


async def get_prev_gw_prices(
    db: AsyncSession,
    player_ids: set[int],
    current_gameweek: int,
) -> dict[int, Decimal]:
    """Returns {player_id: price} from the most-recent snapshot in gameweek N-1.

    Used to compute single-GW price trajectory (rising/falling) for transfer cards.
    Returns an empty dict for GW1 or when player_ids is empty.
    """
    prev_gw = current_gameweek - 1
    if prev_gw < 1 or not player_ids:
        return {}

    row_number = (
        func.row_number()
        .over(
            partition_by=PlayerGameweekStats.player_id,
            order_by=PlayerGameweekStats.pulled_at.desc(),
        )
        .label("rn")
    )

    subq = (
        select(PlayerGameweekStats.player_id, PlayerGameweekStats.price, row_number)
        .where(
            PlayerGameweekStats.gameweek == prev_gw,
            PlayerGameweekStats.player_id.in_(player_ids),
        )
        .subquery()
    )

    stmt = select(subq.c.player_id, subq.c.price).where(subq.c.rn == 1)
    result = await db.execute(stmt)
    return {row.player_id: row.price for row in result.all()}


async def get_prev_gw_ownership(
    db: AsyncSession,
    player_ids: set[int],
    current_gameweek: int,
) -> dict[int, float]:
    """Returns {player_id: ownership_pct} from the most-recent snapshot in GW N-1.

    Used to compute ownership trend (rising/falling) for transfer and template views.
    Returns an empty dict for GW1 or when player_ids is empty.
    """
    prev_gw = current_gameweek - 1
    if prev_gw < 1 or not player_ids:
        return {}

    row_number = (
        func.row_number()
        .over(
            partition_by=PlayerGameweekStats.player_id,
            order_by=PlayerGameweekStats.pulled_at.desc(),
        )
        .label("rn")
    )

    subq = (
        select(PlayerGameweekStats.player_id, PlayerGameweekStats.ownership_pct, row_number)
        .where(
            PlayerGameweekStats.gameweek == prev_gw,
            PlayerGameweekStats.player_id.in_(player_ids),
            PlayerGameweekStats.ownership_pct.isnot(None),
        )
        .subquery()
    )

    stmt = select(subq.c.player_id, subq.c.ownership_pct).where(subq.c.rn == 1)
    result = await db.execute(stmt)
    return {row.player_id: float(row.ownership_pct) for row in result.all()}


_UNAVAILABLE_STATUSES = frozenset({"i", "s", "u"})


def filter_unavailable_players(rows):
    """Remove players who are injured, suspended, unavailable, or confirmed out (chance==0)."""
    kept = []
    for player, stats in rows:
        status = getattr(stats, "status", "a") or "a"
        if status in _UNAVAILABLE_STATUSES:
            continue
        chance = getattr(stats, "chance_of_playing_next_round", None)
        if chance is not None and chance == 0:
            continue
        kept.append((player, stats))
    return kept


def filter_by_minimum_minutes(rows, min_minutes: int = 90):
    return [(player, stats) for player, stats in rows if stats.minutes >= min_minutes]


async def filter_by_recent_minutes(rows, gameweek: int, min_minutes: int = 60):
    from app.ingestion.fpl_client import get_gameweek_live

    live_data = await get_gameweek_live(gameweek)
    minutes_by_player_id = {
        element["id"]: element["stats"]["minutes"] for element in live_data["elements"]
    }

    started_by_team_id = await get_started_status_by_team_id(gameweek)

    kept = []
    for player, stats in rows:
        if not started_by_team_id.get(player.team_id, False):
            kept.append((player, stats))
            continue

        if minutes_by_player_id.get(player.id, 0) >= min_minutes:
            kept.append((player, stats))

    return kept


async def get_recent_minutes_by_player_id(gameweek: int) -> dict[int, int]:
    from app.ingestion.fpl_client import get_gameweek_live

    live_data = await get_gameweek_live(gameweek)
    return {element["id"]: element["stats"]["minutes"] for element in live_data["elements"]}


async def get_started_status_by_team_id(gameweek: int) -> dict[int, bool]:
    from app.ingestion.fpl_client import get_fixtures

    fixtures = await get_fixtures()
    started = {}
    for f in fixtures:
        if f["event"] != gameweek:
            continue
        if f["started"]:
            started[f["team_h"]] = True
            started[f["team_a"]] = True
    return started


def apply_starter_risk_adjustment(
    scored,
    minutes_by_player_id,
    started_by_team_id,
    full_minutes_threshold=60,
    partial_minutes_penalty=0.7,
    zero_minutes_penalty=0.3,
):
    adjusted = []
    for player, stats, score in scored:
        if not started_by_team_id.get(player.team_id, False):
            adjusted.append((player, stats, score))
            continue

        minutes = minutes_by_player_id.get(player.id, 0)
        if minutes >= full_minutes_threshold:
            multiplier = 1.0
        elif minutes > 0:
            multiplier = partial_minutes_penalty
        else:
            multiplier = zero_minutes_penalty
        adjusted.append((player, stats, score * multiplier))
    return adjusted

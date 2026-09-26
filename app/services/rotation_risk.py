from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.player_gameweek_stats import PlayerGameweekStats

# How many recent gameweeks to consider.
_LOOKBACK = 3

# Recency weights: most recent GW gets weight 3, next 2, oldest 1.
# Ordered newest-first so _WEIGHTS[0] applies to the most recent row.
_WEIGHTS = [3, 2, 1]

# A player averaging below this threshold per game is flagged as a rotation risk.
ROTATION_RISK_THRESHOLD = 0.35  # score ≥ 0.35 → worth flagging to the user


def compute_rotation_risk(recent_minutes: list[int]) -> float:
    """
    Return a rotation risk score ∈ [0.0, 1.0] from a list of per-GW minutes.

    recent_minutes should be ordered newest-first; at most _LOOKBACK entries are
    used. An empty list (no data) returns 0.0 — we never penalise a player for
    being new to the dataset.

    Score interpretation:
      0.0  — always plays 90 (no rotation risk)
      0.33 — averaging ~60 min/game (partial rotation)
      1.0  — never plays (extreme rotation / injury pattern)
    """
    if not recent_minutes:
        return 0.0

    values = recent_minutes[:_LOOKBACK]
    weights = _WEIGHTS[:len(values)]
    weighted_sum = sum(m * w for m, w in zip(values, weights))
    total_weight = sum(weights)
    avg_minutes = weighted_sum / total_weight
    return max(0.0, min(1.0, 1.0 - avg_minutes / 90.0))


async def get_rotation_risk_scores(
    db: AsyncSession,
    player_ids: set[int],
    current_gameweek: int,
) -> dict[int, float]:
    """
    Return {player_id: rotation_risk_score} for each requested player.

    Queries the last _LOOKBACK completed GWs of minutes_this_gw, weights
    recent GWs more heavily, and returns a score ∈ [0, 1].

    Players with no stored minutes_this_gw data (GW1, new signings, rows
    written before this column existed) receive 0.0 — no spurious penalty.
    """
    if not player_ids:
        return {}

    from_gw = current_gameweek - _LOOKBACK
    to_gw = current_gameweek - 1

    if to_gw < 1:
        return {pid: 0.0 for pid in player_ids}

    # Latest snapshot per player per gameweek — handles multiple ingest runs
    # in a single GW by taking the most recently pulled row.
    row_number = (
        func.row_number()
        .over(
            partition_by=[PlayerGameweekStats.player_id, PlayerGameweekStats.gameweek],
            order_by=PlayerGameweekStats.pulled_at.desc(),
        )
        .label("rn")
    )

    subq = (
        select(
            PlayerGameweekStats.player_id,
            PlayerGameweekStats.gameweek,
            PlayerGameweekStats.minutes_this_gw,
            row_number,
        )
        .where(
            PlayerGameweekStats.player_id.in_(player_ids),
            PlayerGameweekStats.gameweek >= from_gw,
            PlayerGameweekStats.gameweek <= to_gw,
            PlayerGameweekStats.minutes_this_gw.isnot(None),
        )
        .subquery()
    )

    stmt = (
        select(subq.c.player_id, subq.c.gameweek, subq.c.minutes_this_gw)
        .where(subq.c.rn == 1)
        .order_by(subq.c.player_id, subq.c.gameweek.desc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    # Group by player, ordered newest-first (already sorted by gameweek desc)
    minutes_by_player: dict[int, list[int]] = {pid: [] for pid in player_ids}
    for row in rows:
        minutes_by_player[row.player_id].append(row.minutes_this_gw)

    return {
        pid: compute_rotation_risk(minutes_by_player[pid])
        for pid in player_ids
    }

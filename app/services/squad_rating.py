from app.core.db import async_session_factory
from app.ingestion.fpl_client import get_bootstrap_static, get_entry_picks
from app.services.player_pool import get_latest_stats
from app.services.prediction import predict_points
from app.services.fixtures import get_planning_gameweek
from app.models.player import Position, DEFENSIVE_POSITIONS
SCORE_PERCENTILE_THRESHOLD = 70
XGC_PERCENTILE_THRESHOLD = 40


def percentile_rank(value: float, all_values: list[float]) -> float:
    below = sum(1 for v in all_values if v < value)
    return below / len(all_values) * 100


def find_best_replacement(scored_players, position, exclude_ids, max_price, team_counts=None, max_per_team=3):
    candidates = []
    for player, stats, score in scored_players:
        if player.position != position:
            continue
        if player.id in exclude_ids:
            continue
        if float(stats.price) > max_price:
            continue
        if team_counts is not None and team_counts.get(player.team_id, 0) >= max_per_team:
            continue
        candidates.append((player, stats, score))

    if not candidates:
        return None
    return max(candidates, key=lambda x: x[2])


def _get_regression_flag(player, stats, score_percentile, xgc_ease_by_id):
    if player.position not in DEFENSIVE_POSITIONS:
        return None
    if player.id not in xgc_ease_by_id:
        return None

    xgc_percentile = xgc_ease_by_id[player.id]
    if score_percentile >= SCORE_PERCENTILE_THRESHOLD and xgc_percentile <= XGC_PERCENTILE_THRESHOLD:
        return f"Fixture dependent: strong output ({score_percentile:.0f}th percentile) but weak underlying defensive numbers ({xgc_percentile:.0f}th percentile xGC)"
    return None


def compute_ratings(my_element_ids: set, all_scored: list, gameweek: int) -> list:
    """Rate a set of players against the full pool. Returns (player, stats, score, percentile, flag)."""
    min_avg_minutes = 60
    starter_pool = [
        (player, stats, score) for player, stats, score in all_scored
        if stats.minutes / max(gameweek, 1) >= min_avg_minutes
    ]

    scores_by_position = {}
    for player, stats, score in starter_pool:
        scores_by_position.setdefault(player.position, []).append(score)

    xgc_values_by_position = {}
    for player, stats, score in starter_pool:
        if player.position in DEFENSIVE_POSITIONS and stats.expected_goals_conceded_per_90 is not None:
            xgc_values_by_position.setdefault(player.position, []).append(
                -float(stats.expected_goals_conceded_per_90)
            )

    xgc_ease_by_id = {}
    for player, stats, score in starter_pool:
        if player.position in DEFENSIVE_POSITIONS and stats.expected_goals_conceded_per_90 is not None:
            all_ease_values = xgc_values_by_position[player.position]
            this_ease = -float(stats.expected_goals_conceded_per_90)
            xgc_ease_by_id[player.id] = percentile_rank(this_ease, all_ease_values)

    rated = []
    for player, stats, score in all_scored:
        if player.id not in my_element_ids:
            continue
        position_scores = scores_by_position.get(player.position, [])
        if not position_scores:
            continue
        score_percentile = percentile_rank(score, position_scores)
        flag = _get_regression_flag(player, stats, score_percentile, xgc_ease_by_id)
        rated.append((player, stats, score, score_percentile, flag))

    return rated


async def rate_squad(entry_id: int):
    async with async_session_factory() as db:
        data = await get_bootstrap_static()
        gameweek = next(e["id"] for e in data["events"] if e["is_current"])

        picks_data = await get_entry_picks(entry_id, gameweek)
        my_element_ids = {pick["element"] for pick in picks_data["picks"]}

        planning_gameweek = await get_planning_gameweek(db, gameweek)
        rows = await get_latest_stats(db, gameweek)
        scored = await predict_points(rows, db, gameweek=gameweek, fixture_from_gameweek=planning_gameweek)

        return compute_ratings(my_element_ids, scored, gameweek)

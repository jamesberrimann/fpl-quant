import math

from app.models.player import Position, DEFENSIVE_POSITIONS

GOALS_POINTS = {
    Position.GKP: 6,
    Position.DEF: 6,
    Position.MID: 5,
    Position.FWD: 4,
}

CS_POINTS = {
    Position.GKP: 6,
    Position.DEF: 6,
    Position.MID: 1,
    Position.FWD: 0,
}

# Premier League average goals per game, used to normalise fixture difficulty.
# When real goals-record data isn't available, the fixture multiplier falls back to 1.0.
_PL_AVG_GOALS = 1.3

# Expected bonus points per unit of attacking contribution.
# Fitted to empirical FPL BPS distributions: goals earn 12–24 BPS by position,
# assists earn ~9 BPS, and CS earns ~6 BPS for GKP/DEF. Coefficients represent
# expected bonus pts per unit of xG/xA/cs_prob after sharing the 3-point pool.
_BONUS_PER_XG = {Position.GKP: 0.0, Position.DEF: 0.8, Position.MID: 1.5, Position.FWD: 2.5}
_BONUS_PER_XA = {Position.GKP: 0.0, Position.DEF: 0.2, Position.MID: 0.5, Position.FWD: 0.4}
_BONUS_PER_CS = {Position.GKP: 0.8, Position.DEF: 0.5, Position.MID: 0.0, Position.FWD: 0.0}


def _fixture_multiplier(opponent_strength: dict, position: Position) -> float:
    """
    Returns a multiplier centred around 1.0 that scales predicted output up or
    down based on the quality of the upcoming fixture(s).

    Attackers benefit when opponents concede more than average.
    Defenders benefit when opponents score less than average.
    Falls back to 1.0 when real goals data isn't available yet.
    """
    if position in DEFENSIVE_POSITIONS:
        opp_scored = opponent_strength.get("opponent_avg_goals_scored")
        if opp_scored is None:
            return 1.0
        return min(_PL_AVG_GOALS / max(float(opp_scored), 0.1), 2.0)
    else:
        opp_conceded = opponent_strength.get("opponent_avg_goals_conceded")
        if opp_conceded is None:
            return 1.0
        return min(float(opp_conceded) / _PL_AVG_GOALS, 2.0)


def _split_base(player, stats, avg_min: float, opp_goals_scored_for_cs: float | None = None) -> tuple[float, float, float]:
    """
    Returns (app_pts, offensive_pts, cs_pts) so the caller can apply the fixture
    multiplier only to offensive components while keeping CS independent.

    CS probability is computed from the opponent's actual scoring rate when
    available (fixture-specific accuracy), falling back to the team's season-average
    xGC when no opponent data is present.
    """
    pos = player.position
    min_fraction = min(avg_min, 90.0) / 90.0

    if avg_min < 1:
        return (0.0, 0.0, 0.0)

    app_pts = 2.0 if avg_min >= 60 else 1.0

    # Blend season-average xStats with the most-recent GW snapshot (when available).
    # Weight: 60% season average + 40% last GW.
    _SEASON_W = 0.6
    _RECENT_W = 0.4

    season_xg = float(stats.expected_goals_per_90 or 0)
    season_xa = float(stats.expected_assists_per_90 or 0)
    season_xgc = float(stats.expected_goals_conceded_per_90 or _PL_AVG_GOALS)

    xg_gw = getattr(stats, "xg_this_gw_per_90", None)
    xa_gw = getattr(stats, "xa_this_gw_per_90", None)
    xgc_gw = getattr(stats, "xgc_this_gw_per_90", None)

    xg = _SEASON_W * season_xg + _RECENT_W * float(xg_gw) if xg_gw is not None else season_xg
    xa = _SEASON_W * season_xa + _RECENT_W * float(xa_gw) if xa_gw is not None else season_xa
    xgc = _SEASON_W * season_xgc + _RECENT_W * float(xgc_gw) if xgc_gw is not None else season_xgc

    # Offensive: goals, assists, and expected bonus from action-heavy contributions.
    # Bonus is scaled by fix_mult in predict_points (harder fixture → fewer goals → less bonus).
    goal_pts = xg * min_fraction * GOALS_POINTS[pos]
    assist_pts = xa * min_fraction * 3.0
    bonus_action = (
        xg * min_fraction * _BONUS_PER_XG[pos]
        + xa * min_fraction * _BONUS_PER_XA[pos]
    )
    offensive_pts = goal_pts + assist_pts + bonus_action

    # CS: Poisson P(CS) = e^(-λ * min_fraction).
    # λ = geometric mean of opponent attack and team defence (both required for accuracy).
    # Multiplicative: Brighton scoring 1.8/game against Rushworth's leaky team
    # does NOT mean they'll score 1.8 against Arsenal — elite defence scales down
    # even a strong opponent's threat. Falls back to xgc alone when no fixture data.
    if opp_goals_scored_for_cs is not None:
        cs_λ = math.sqrt(max(float(opp_goals_scored_for_cs), 0.1) * max(xgc, 0.1))
    else:
        cs_λ = xgc
    cs_prob = math.exp(-cs_λ * min_fraction)
    cs_pts = cs_prob * (CS_POINTS[pos] + _BONUS_PER_CS[pos])

    return (app_pts, offensive_pts, cs_pts)


def _predict_base(player, stats, avg_min: float, opp_goals_scored_for_cs: float | None = None) -> float:
    """Total expected base points (sum of all components). Used for ranking and tests."""
    return sum(_split_base(player, stats, avg_min, opp_goals_scored_for_cs))


def compute_prediction_components(player, stats, gameweek: int, opponent_strength: dict) -> dict:
    """
    Returns the intermediate factors that make up a player's predicted score:
      fix_mult   — fixture difficulty multiplier (>1 = easy, <1 = hard)
      form_factor — form confidence weight (clamped 0.85–1.15)
      base_pts   — raw xStats expected output before fixture/form scaling

    Used to explain *why* one player scores higher than another in transfer
    suggestions, without re-running the full prediction pipeline.
    """
    season_avg_min = float(stats.minutes) / max(gameweek, 1)
    if stats.minutes_this_gw is not None:
        avg_min = 0.6 * season_avg_min + 0.4 * min(float(stats.minutes_this_gw), 90.0)
    else:
        avg_min = season_avg_min
    app_pts, offensive_pts, cs_pts = _split_base(
        player, stats, avg_min,
        opp_goals_scored_for_cs=opponent_strength.get("opponent_avg_goals_scored"),
    )
    base = app_pts + offensive_pts + cs_pts
    fix_mult = _fixture_multiplier(opponent_strength, player.position)
    form_factor = max(0.85, min((float(stats.form) + 5.0) / 10.0, 1.15))
    return {"fix_mult": fix_mult, "form_factor": form_factor, "base_pts": base}


async def predict_points(
    rows,
    db,
    gameweek: int,
    fixture_from_gameweek: int | None = None,
    num_fixtures: int = 3,
    fixture_count_multipliers: dict[int, float] | None = None,
) -> list:
    """
    Returns list of (player, stats, predicted_pts_per_game) tuples.

    predicted_pts_per_game ≈ expected FPL points for the next fixture,
    adjusted for upcoming fixture difficulty and recent form.

    fixture_from_gameweek: gameweek to use for fixture lookups (defaults to
    gameweek). Pass get_planning_gameweek() result so fixture queries skip
    already-played matches within a partially-complete gameweek.

    num_fixtures: how many upcoming fixtures to average for the difficulty
    signal. Use 1 for single-gameweek decisions (lineup); use 3+ for
    multi-week planning (squad building, transfers).

    fixture_count_multipliers: optional dict[team_id, float] scaling by
    gameweek fixture count. Pass get_gameweek_fixture_multipliers() result
    for single-GW decisions so DGW players score 2× and BGW players score 0.
    """
    from app.services.fixtures import get_opponent_strength_for_fixture

    from_gw = fixture_from_gameweek if fixture_from_gameweek is not None else gameweek

    team_ids = {player.team_id for player, _ in rows}
    opponent_strength_by_team = {
        team_id: await get_opponent_strength_for_fixture(db, team_id, from_gw, num_fixtures=num_fixtures)
        for team_id in team_ids
    }

    result = []
    for player, stats in rows:
        season_avg_min = float(stats.minutes) / max(gameweek, 1)
        if stats.minutes_this_gw is not None:
            # 60% season average + 40% most-recent GW.
            # Catches rotation changes and injury-return ramp-ups faster than
            # season average alone, without letting a single anomalous GW dominate.
            avg_min = 0.6 * season_avg_min + 0.4 * min(float(stats.minutes_this_gw), 90.0)
        else:
            avg_min = season_avg_min
        opponent_strength = opponent_strength_by_team[player.team_id]

        app_pts, offensive_pts, cs_pts = _split_base(
            player, stats, avg_min,
            opp_goals_scored_for_cs=opponent_strength.get("opponent_avg_goals_scored"),
        )
        if app_pts < 1e-9:
            result.append((player, stats, 0.0))
            continue

        fix_mult = _fixture_multiplier(opponent_strength, player.position)

        # Form as a short-term confidence weight, clamped to ±15% swing.
        # FPL form is a 4-GW rolling average — noisy enough that ±25% was
        # giving one-off bonus-point streaks too much power over xStat signals.
        form_factor = max(0.85, min((float(stats.form) + 5.0) / 10.0, 1.15))

        # fix_mult and form_factor only scale offensive components (xG/xA/bonus).
        # CS pts are already fixture-specific via opp_goals_scored_for_cs — scaling
        # them again would double-count the fixture difficulty signal.
        predicted = app_pts + offensive_pts * fix_mult * form_factor + cs_pts

        # Scale by availability: null = assume available (100%), 0 = confirmed out.
        # Doubtful players (e.g. 75%) get proportionally discounted predictions.
        chance = stats.chance_of_playing_next_round
        if chance is not None:
            predicted *= chance / 100.0

        if fixture_count_multipliers is not None:
            predicted *= fixture_count_multipliers.get(player.team_id, 1.0)

        result.append((player, stats, predicted))

    return result

import math

from app.models.player import Position, DEFENSIVE_POSITIONS

DEFCON_THRESHOLD = {
    Position.DEF: 10,
    Position.MID: 12,
    Position.FWD: 12,
}

# Weight rationale:
#   Form dropped to 0.10–0.12 — it's a volatile noise signal over 4 GWs, not a driver.
#   Fixture weight increased — fixture run quality is the most controllable planning input.
#   xG/xA dominate attack positions; xGC dominates defensive positions.
#   xA weight is ~3/5 of xG (assists score 3 pts vs goals 5 pts in FPL).
#   DEF gets a small xA component to value attacking fullbacks (Trent, Trippier).
#   Points/season-average kept as a stability anchor (proven output, position-independent).
WEIGHTS = {
    Position.GKP: {"points": 0.45, "form": 0.10, "fixture": 0.25, "xgc": 0.20},
    Position.DEF: {"points": 0.27, "form": 0.10, "fixture": 0.15, "xgc": 0.25, "defcon": 0.18, "xa": 0.05},
    Position.MID: {"points": 0.20, "form": 0.10, "fixture": 0.20, "xgc": 0.05, "defcon": 0.05, "xg": 0.25, "xa": 0.15},
    Position.FWD: {"points": 0.22, "form": 0.10, "fixture": 0.20, "defcon": 0.02, "xg": 0.38, "xa": 0.08},
}

def normalize(values: list[float]) -> list[float]:
    min_v, max_v = min(values), max(values)
    if max_v == min_v:
        return [0.5 for _ in values]
    return [(v - min_v) / (max_v - min_v) for v in values]


async def score_players(rows, db, gameweek: int = 3):
    from app.services.fixtures import get_team_fixture_difficulty, get_opponent_strength_for_fixture

    points = [float(stats.total_points) for _, stats in rows]
    forms = [float(stats.form) for _, stats in rows]

    team_ids = {player.team_id for player, _ in rows}

    difficulty_by_team = {
        team_id: await get_team_fixture_difficulty(db, team_id, gameweek)
        for team_id in team_ids
    }
    opponent_strength_by_team = {
        team_id: await get_opponent_strength_for_fixture(db, team_id, gameweek)
        for team_id in team_ids
    }

    norm_points = normalize(points)
    norm_form = normalize(forms)

    difficulties = [difficulty_by_team[player.team_id] for player, _ in rows]
    norm_difficulty = normalize(difficulties)
    norm_fixture_ease = [1 - d for d in norm_difficulty]

    atk_ease_team_ids = [
        team_id for team_id in team_ids
        if opponent_strength_by_team[team_id]["opponent_avg_goals_conceded"] is not None
    ]
    atk_ease_by_team = {}
    if atk_ease_team_ids:
        atk_vals = [opponent_strength_by_team[t]["opponent_avg_goals_conceded"] for t in atk_ease_team_ids]
        norm_atk = normalize(atk_vals)
        for team_id, val in zip(atk_ease_team_ids, norm_atk):
            atk_ease_by_team[team_id] = val

    def_ease_team_ids = [
        team_id for team_id in team_ids
        if opponent_strength_by_team[team_id]["opponent_avg_goals_scored"] is not None
    ]
    def_ease_by_team = {}
    if def_ease_team_ids:
        def_vals = [opponent_strength_by_team[t]["opponent_avg_goals_scored"] for t in def_ease_team_ids]
        norm_def = normalize(def_vals)
        for team_id, val in zip(def_ease_team_ids, norm_def):
            def_ease_by_team[team_id] = 1 - val

    xgc_indices = [
        i for i, (player, stats) in enumerate(rows)
        if stats.expected_goals_conceded_per_90 is not None
    ]
    xgc_ease_by_index = {}
    if xgc_indices:
        xgc_vals = [float(rows[i][1].expected_goals_conceded_per_90) for i in xgc_indices]
        norm_xgc = normalize(xgc_vals)
        for pos, i in enumerate(xgc_indices):
            xgc_ease_by_index[i] = 1 - norm_xgc[pos]

    xg_indices = [
        i for i, (player, stats) in enumerate(rows)
        if stats.expected_goals_per_90 is not None
    ]
    xg_norm_by_index = {}
    if xg_indices:
        xg_vals = [float(rows[i][1].expected_goals_per_90) for i in xg_indices]
        norm_xg = normalize(xg_vals)
        for pos, i in enumerate(xg_indices):
            xg_norm_by_index[i] = norm_xg[pos]

    xa_indices = [
        i for i, (player, stats) in enumerate(rows)
        if stats.expected_assists_per_90 is not None
    ]
    xa_norm_by_index = {}
    if xa_indices:
        xa_vals = [float(rows[i][1].expected_assists_per_90) for i in xa_indices]
        norm_xa = normalize(xa_vals)
        for pos, i in enumerate(xa_indices):
            xa_norm_by_index[i] = norm_xa[pos]

    scored = []
    for i, (player, stats) in enumerate(rows):
        weights = WEIGHTS[player.position]
        score = 0.0

        score += weights.get("points", 0) * norm_points[i]
        score += weights.get("form", 0) * norm_form[i]

        if "fixture" in weights:
            if player.position in DEFENSIVE_POSITIONS:
                fixture_ease = def_ease_by_team.get(player.team_id, norm_fixture_ease[i])
            else:
                fixture_ease = atk_ease_by_team.get(player.team_id, norm_fixture_ease[i])
            score += weights["fixture"] * fixture_ease

        if "xgc" in weights:
            score += weights["xgc"] * xgc_ease_by_index.get(i, 0.5)

        if "defcon" in weights:
            threshold = DEFCON_THRESHOLD.get(player.position)
            if threshold and stats.defensive_contribution_per_90 is not None:
                # Soft scaling via log1p: preserves differentiation above the threshold
                # without hard-capping elite defenders at the same value as merely-good ones.
                # Normalised to 1.0 at the threshold, growing slowly beyond it.
                ratio = float(stats.defensive_contribution_per_90) / threshold
                defcon_component = math.log1p(ratio) / math.log1p(1.0)
            else:
                defcon_component = 0.5
            score += weights["defcon"] * defcon_component

        if "xg" in weights:
            score += weights["xg"] * xg_norm_by_index.get(i, 0.5)

        if "xa" in weights:
            score += weights["xa"] * xa_norm_by_index.get(i, 0.5)

        scored.append((player, stats, score))

    return scored

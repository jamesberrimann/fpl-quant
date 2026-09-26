from app.core.db import async_session_factory
from app.services.fixtures import (
    get_team_fixture_difficulty,
    get_opponent_strength_for_fixture,
    get_gameweek_fixture_multipliers,
)
from app.services.scoring import normalize
from app.models.player import Position, DEFENSIVE_POSITIONS

# Captaincy weighting — ceiling is what matters, not season reliability.
# xG dominates because captaincy is a bet on explosive single-GW output.
# Form drops to 10–15%: it's a marginal confidence signal, not a primary driver.
# Fixture weight preserved as meaningful single-GW signal (using num_fixtures=1).
CAPTAIN_WEIGHTS = {
    Position.GKP: {"form": 0.25, "fixture": 0.75},
    Position.DEF: {"form": 0.15, "fixture": 0.45, "xgc": 0.40},
    Position.MID: {"form": 0.15, "fixture": 0.20, "xg": 0.65},
    Position.FWD: {"form": 0.20, "fixture": 0.15, "xg": 0.65},
}

CEILING_RANK = {Position.FWD: 4, Position.MID: 3, Position.DEF: 2, Position.GKP: 1}


async def score_for_captaincy(starting_xi, db, gameweek: int):
    forms = [float(stats.form) for _, stats, _ in starting_xi]
    norm_form = normalize(forms)

    team_ids = {player.team_id for player, _, _ in starting_xi}
    dgw_multipliers = await get_gameweek_fixture_multipliers(db, team_ids, gameweek)

    difficulty_by_team = {
        team_id: await get_team_fixture_difficulty(db, team_id, gameweek, num_fixtures=1)
        for team_id in team_ids
    }
    opponent_strength_by_team = {
        team_id: await get_opponent_strength_for_fixture(db, team_id, gameweek, num_fixtures=1)
        for team_id in team_ids
    }

    difficulties = [difficulty_by_team[player.team_id] for player, _, _ in starting_xi]
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
        i for i, (player, stats, _) in enumerate(starting_xi)
        if stats.expected_goals_conceded_per_90 is not None
    ]
    xgc_ease_by_index = {}
    if xgc_indices:
        xgc_vals = [float(starting_xi[i][1].expected_goals_conceded_per_90) for i in xgc_indices]
        norm_xgc = normalize(xgc_vals)
        for pos, i in enumerate(xgc_indices):
            xgc_ease_by_index[i] = 1 - norm_xgc[pos]

    xg_indices = [
        i for i, (player, stats, _) in enumerate(starting_xi)
        if stats.expected_goals_per_90 is not None
    ]
    xg_norm_by_index = {}
    if xg_indices:
        xg_vals = [float(starting_xi[i][1].expected_goals_per_90) for i in xg_indices]
        norm_xg = normalize(xg_vals)
        for pos, i in enumerate(xg_indices):
            xg_norm_by_index[i] = norm_xg[pos]

    scored = []
    for i, (player, stats, _) in enumerate(starting_xi):
        weights = CAPTAIN_WEIGHTS[player.position]
        captain_score = 0.0
        components: dict[str, float] = {}

        form_c = weights.get("form", 0) * norm_form[i]
        captain_score += form_c
        components["form"] = form_c

        if "fixture" in weights:
            if player.position in DEFENSIVE_POSITIONS:
                fixture_ease = def_ease_by_team.get(player.team_id, norm_fixture_ease[i])
            else:
                fixture_ease = atk_ease_by_team.get(player.team_id, norm_fixture_ease[i])
            fix_c = weights["fixture"] * fixture_ease
            captain_score += fix_c
            components["fixture"] = fix_c
            components["_fixture_ease"] = fixture_ease

        if "xgc" in weights:
            xgc_c = weights["xgc"] * xgc_ease_by_index.get(i, 0.5)
            captain_score += xgc_c
            components["xgc"] = xgc_c

        if "xg" in weights:
            xg_c = weights["xg"] * xg_norm_by_index.get(i, 0.5)
            captain_score += xg_c
            components["xg"] = xg_c

        # DGW/BGW: captaincy value scales directly with number of games played.
        # A player with two fixtures is worth ~2× as captain; BGW players score 0.
        captain_score *= dgw_multipliers.get(player.team_id, 1.0)
        # Components are NOT scaled by DGW so reasons reflect stat quality, not
        # fixture count (the DGW badge already communicates the DGW advantage).

        scored.append((player, stats, captain_score, components))

    return scored


async def pick_captain(starting_xi, gameweek: int):
    async with async_session_factory() as db:
        captain_scored = await score_for_captaincy(starting_xi, db, gameweek)
    return max(captain_scored, key=lambda x: (x[2], CEILING_RANK[x[0].position]))


_DIFFERENTIAL_OWNERSHIP_THRESHOLD = 15.0  # % — below this counts as differential
_DIFFERENTIAL_SCORE_FLOOR = 0.70          # must be ≥ 70% of top pick's ceiling


def get_captain_recommendation(captain_scored):
    ranked = sorted(
        captain_scored,
        key=lambda x: (x[2], CEILING_RANK[x[0].position]),
        reverse=True,
    )

    top = ranked[0]
    result = {
        "top_pick": {"player": top[0], "rating": round(top[2] * 100)},
        "second_pick": {"player": top[0], "rating": round(top[2] * 100)},
        "tie_broken_by_ceiling": False,
        "advantage_pct": None,
    }

    if len(ranked) > 1:
        second = ranked[1]

        top_score_rounded = round(top[2], 6)
        second_score_rounded = round(second[2], 6)

        tie_affected_top_pick = any(
            round(score, 6) == top_score_rounded and player.id != top[0].id
            for player, stats, score, *_ in ranked
        )
        tie_affected_second_pick = any(
            round(score, 6) == second_score_rounded and player.id != second[0].id
            for player, stats, score, *_ in ranked
        )

        result["second_pick"] = {"player": second[0], "rating": round(second[2] * 100)}
        result["tie_broken_by_ceiling"] = tie_affected_top_pick or tie_affected_second_pick

        if second[2] > 0:
            advantage_pct = round((top[2] - second[2]) / second[2] * 100, 1)
        else:
            advantage_pct = None

        result["advantage_pct"] = advantage_pct

    # Find a differential captain option: competitive ceiling (≥70% of top) but
    # low ownership (<15%), distinct from the top pick. This surfaces a rank-chasing
    # alternative without overriding the primary recommendation — the manager decides
    # whether they need a template pick (protecting rank) or a differential (chasing).
    top_stats = top[1]
    top_ownership = (
        float(top_stats.ownership_pct)
        if top_stats is not None and top_stats.ownership_pct is not None
        else None
    )
    differential = None
    # Only search if the top pick itself isn't already differential
    if top_ownership is None or top_ownership >= _DIFFERENTIAL_OWNERSHIP_THRESHOLD:
        score_floor = top[2] * _DIFFERENTIAL_SCORE_FLOOR
        for entry in ranked[1:]:
            entry_stats = entry[1]
            ownership = (
                float(entry_stats.ownership_pct)
                if entry_stats is not None and entry_stats.ownership_pct is not None
                else None
            )
            if (
                ownership is not None
                and ownership < _DIFFERENTIAL_OWNERSHIP_THRESHOLD
                and entry[2] >= score_floor
            ):
                differential = entry
                break

    result["differential_captain"] = differential

    return result


def get_captain_variance(player, stats) -> str:
    """Return 'high', 'medium', or 'low' variance for a captain pick.

    High variance = boom-or-bust (FWD/MID with strong xG — could blank or score a brace).
    Low variance = reliable floor (DEF/GKP where CS is the main return mechanism).
    Use this to distinguish 'protect rank' vs 'chase rank' captaincy choices.
    """
    xg = float(stats.expected_goals_per_90 or 0)
    if player.position in DEFENSIVE_POSITIONS:
        return "low"
    if xg >= 0.4:
        return "high"
    if xg >= 0.2:
        return "medium"
    return "low"


_FACTOR_LABELS: dict[str, str] = {
    "xg": "Strong xG",
    "fixture": "Favourable fixture",
    "form": "Recent form",
    "xgc": "Clean sheet probability",
}
_MIN_FACTOR_CONTRIBUTION = 0.05


def get_captaincy_explanation(player_id: int, captain_scored: list) -> list[str]:
    """Return up to 2 plain-English factors that drove captain selection for player_id.

    Only factors contributing ≥ _MIN_FACTOR_CONTRIBUTION to the score are shown,
    so noise (e.g. a near-zero form contribution) is excluded.
    """
    entry = next((t for t in captain_scored if t[0].id == player_id), None)
    if entry is None or len(entry) < 4:
        return []
    components: dict[str, float] = entry[3]
    return [
        _FACTOR_LABELS[k]
        for k, v in sorted(components.items(), key=lambda x: x[1], reverse=True)
        if v >= _MIN_FACTOR_CONTRIBUTION
        and k in _FACTOR_LABELS
        and (k != "fixture" or components.get("_fixture_ease", 0) > 0.5)
    ][:2]

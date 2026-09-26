from app.models.player import Position

# Ownership thresholds that define squad archetypes.
# These mirror how top managers mentally categorise players.
TEMPLATE_THRESHOLD = 20.0     # ≥20% owned → template pick (everyone has this)
DIFFERENTIAL_THRESHOLD = 10.0 # <10% owned → genuine differential

# Weighted divergence: each player's contribution to the squad's overall
# "template divergence" score. Attackers matter more for rank swings.
_POSITION_WEIGHT = {
    Position.FWD: 1.5,
    Position.MID: 1.2,
    Position.DEF: 0.8,
    Position.GKP: 0.5,
}


def classify_player(ownership_pct: float | None) -> str:
    """Return 'template', 'core', or 'differential' based on ownership %."""
    if ownership_pct is None:
        return "unknown"
    if ownership_pct >= TEMPLATE_THRESHOLD:
        return "template"
    if ownership_pct < DIFFERENTIAL_THRESHOLD:
        return "differential"
    return "core"


def compute_template_divergence(players: list[dict]) -> float:
    """Return a 0–100 score: 0 = pure template squad, 100 = all differentials.

    Each player contributes a position-weighted ownership divergence from 100%.
    A player owned by 5% contributes more divergence than one owned by 40%.
    Score is normalised to [0, 100].
    """
    if not players:
        return 0.0

    total_weight = 0.0
    weighted_divergence = 0.0

    for p in players:
        ownership = p.get("ownership_pct")
        position = p.get("position")
        if ownership is None:
            continue
        weight = _POSITION_WEIGHT.get(position, 1.0)
        # Divergence per player: 1 - ownership/100 (fully owned = 0 divergence)
        divergence = 1.0 - min(ownership / 100.0, 1.0)
        weighted_divergence += divergence * weight
        total_weight += weight

    if total_weight == 0.0:
        return 0.0

    return round((weighted_divergence / total_weight) * 100, 1)


def build_template_comparison(squad_players: list[dict]) -> dict:
    """Given a list of squad player dicts with ownership_pct and position,
    return a template comparison summary.

    Each player dict must have:
        id, web_name, position (Position enum), ownership_pct (float | None),
        team_short_name (str)

    Returns:
        players: list of player entries with classification added
        divergence_score: 0–100 overall squad divergence
        by_position: per-position breakdown (template / core / differential counts)
        differentials: players classified as differential, sorted by ownership asc
        template_picks: players classified as template, sorted by ownership desc
    """
    annotated = []
    for p in squad_players:
        entry = dict(p)
        entry["classification"] = classify_player(p.get("ownership_pct"))
        annotated.append(entry)

    divergence_score = compute_template_divergence(squad_players)

    by_position: dict[str, dict[str, int]] = {}
    for p in annotated:
        pos = p["position"].value if hasattr(p["position"], "value") else str(p["position"])
        if pos not in by_position:
            by_position[pos] = {"template": 0, "core": 0, "differential": 0, "unknown": 0}
        cls = p["classification"]
        by_position[pos][cls] = by_position[pos].get(cls, 0) + 1

    differentials = sorted(
        [p for p in annotated if p["classification"] == "differential"],
        key=lambda p: (p.get("ownership_pct") or 0),
    )
    template_picks = sorted(
        [p for p in annotated if p["classification"] == "template"],
        key=lambda p: (p.get("ownership_pct") or 0),
        reverse=True,
    )

    return {
        "players": annotated,
        "divergence_score": divergence_score,
        "by_position": by_position,
        "differentials": differentials,
        "template_picks": template_picks,
    }

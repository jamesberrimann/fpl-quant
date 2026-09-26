from decimal import Decimal
from datetime import datetime, timezone

from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.services.optimizer import optimize_squad


def make_player(id, team_id, position, web_name):
    return Player(
        id=id, team_id=team_id, first_name=web_name, second_name=web_name,
        web_name=web_name, position=position,
    )


def make_stats(player_id, price, score_seed):
    return PlayerGameweekStats(
        player_id=player_id, gameweek=3, pulled_at=datetime.now(timezone.utc),
        price=Decimal(str(price)), form=Decimal("5.0"), ownership_pct=Decimal("10.0"),
        total_points=int(score_seed * 30), minutes=270,
    )


# Confirmed current (Sept 2026) Man Utd players where verified via search.
# "Reserve" entries are placeholders, not real players -- used only to give
# the optimizer enough candidates per position to make a genuine choice.
ROSTER = [
    (1, 9001, Position.GKP, "Lammens", 5.0),
    (2, 9002, Position.GKP, "Darlow", 4.0),
    (3, 9003, Position.GKP, "Heaton", 4.0),

    (4, 9001, Position.DEF, "Dalot", 5.0),
    (5, 9002, Position.DEF, "Mazraoui", 4.5),
    (6, 9003, Position.DEF, "De Ligt", 5.0),
    (7, 9004, Position.DEF, "Maguire", 4.5),
    (8, 9005, Position.DEF, "Martinez", 5.5),
    (9, 9006, Position.DEF, "Shaw", 4.5),
    (10, 9007, Position.DEF, "Yoro", 4.5),

    (11, 9001, Position.MID, "Mainoo", 5.5),
    (12, 9002, Position.MID, "Tielemans", 5.5),
    (13, 9003, Position.MID, "Mbeumo", 7.5),
    (14, 9004, Position.MID, "B.Fernandes", 8.5),
    (15, 9005, Position.MID, "Rashford", 7.0),
    (16, 9006, Position.MID, "Reserve MID 1", 5.0),
    (17, 9007, Position.MID, "Reserve MID 2", 5.0),

    (18, 9001, Position.FWD, "Cunha", 7.5),
    (19, 9002, Position.FWD, "Reserve FWD 1", 6.0),
    (20, 9003, Position.FWD, "Reserve FWD 2", 6.0),
    (21, 9004, Position.FWD, "Reserve FWD 3", 6.0),
    (22, 9005, Position.FWD, "Reserve FWD 4", 6.0),
]


def build_scored_pool():
    scored = []
    for id, team_id, position, name, price in ROSTER:
        player = make_player(id, team_id, position, name)
        score_seed = (id * 37 % 100) / 100
        stats = make_stats(id, price, score_seed)
        scored.append((player, stats, score_seed))
    return scored


def test_optimal_squad_respects_all_constraints():
    scored = build_scored_pool()
    squad = optimize_squad(scored, budget=100.0)

    assert len(squad) == 15

    position_counts = {}
    for player, stats, score in squad:
        position_counts[player.position] = position_counts.get(player.position, 0) + 1

    assert position_counts[Position.GKP] == 2
    assert position_counts[Position.DEF] == 5
    assert position_counts[Position.MID] == 5
    assert position_counts[Position.FWD] == 3

    total_cost = sum(float(stats.price) for _, stats, _ in squad)
    assert total_cost <= 100.0

    team_counts = {}
    for player, stats, score in squad:
        team_counts[player.team_id] = team_counts.get(player.team_id, 0) + 1
    assert all(count <= 3 for count in team_counts.values())

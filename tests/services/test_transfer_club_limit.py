from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.services.squad_rating import find_best_replacement
from decimal import Decimal
from datetime import datetime, timezone


def make_fake_player_and_stats(id, team_id, price, score_price=5.0):
    player = Player(
        id=id, team_id=team_id, first_name="Fake", second_name="Player",
        web_name=f"Player{id}", position=Position.MID,
    )
    stats = PlayerGameweekStats(
        player_id=id, gameweek=3, pulled_at=datetime.now(timezone.utc),
        price=Decimal(str(price)), form=Decimal("5.0"), ownership_pct=Decimal("10.0"),
        total_points=10, minutes=270,
    )
    return player, stats


def test_replacement_blocked_when_club_already_at_limit():
    best_but_blocked = make_fake_player_and_stats(id=1, team_id=99, price=8.0)
    second_best = make_fake_player_and_stats(id=2, team_id=88, price=8.0)

    scored_players = [
        (best_but_blocked[0], best_but_blocked[1], 0.99),
        (second_best[0], second_best[1], 0.80),
    ]

    team_counts = {99: 3}

    result = find_best_replacement(
        scored_players, Position.MID, exclude_ids=set(), max_price=10.0,
        team_counts=team_counts, max_per_team=3,
    )

    assert result is not None
    assert result[0].id == 2


def test_replacement_allowed_when_club_below_limit():
    candidate = make_fake_player_and_stats(id=1, team_id=99, price=8.0)
    scored_players = [(candidate[0], candidate[1], 0.99)]

    team_counts = {99: 2}

    result = find_best_replacement(
        scored_players, Position.MID, exclude_ids=set(), max_price=10.0,
        team_counts=team_counts, max_per_team=3,
    )

    assert result is not None
    assert result[0].id == 1

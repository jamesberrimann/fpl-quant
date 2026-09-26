from decimal import Decimal
from datetime import datetime, timezone

from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.services.squad_rating import find_best_replacement


def make_entry(id, team_id, price, score):
    player = Player(id=id, team_id=team_id, first_name="F", second_name="L", web_name=f"P{id}", position=Position.MID)
    stats = PlayerGameweekStats(
        player_id=id, gameweek=4, pulled_at=datetime.now(timezone.utc),
        price=Decimal(str(price)), form=Decimal("5.0"), ownership_pct=Decimal("10.0"),
        total_points=10, minutes=270,
    )
    return (player, stats, score)


def test_sequential_transfers_never_exceed_shared_budget():
    my_out_1 = make_entry(1, team_id=9001, price=5.0, score=0.3)
    my_out_2 = make_entry(2, team_id=9002, price=5.0, score=0.3)

    candidate_in_1 = make_entry(3, team_id=9003, price=5.3, score=0.9)
    candidate_in_2 = make_entry(4, team_id=9004, price=5.3, score=0.8)

    pool = [my_out_1, my_out_2, candidate_in_1, candidate_in_2]
    exclude_ids = {1, 2}

    bank = 0.3
    remaining_bank = bank

    for outgoing_player, outgoing_stats, outgoing_score in [my_out_1, my_out_2]:
        max_price = float(outgoing_stats.price) + remaining_bank
        replacement = find_best_replacement(pool, Position.MID, exclude_ids, max_price)

        if replacement is None:
            continue

        new_player, new_stats, new_score = replacement
        price_change = float(new_stats.price) - float(outgoing_stats.price)

        assert price_change <= remaining_bank, (
            f"Transfer accepted a price_change of {price_change} "
            f"exceeding remaining_bank of {remaining_bank}"
        )

        remaining_bank -= price_change
        exclude_ids.add(new_player.id)

        assert remaining_bank >= 0, f"remaining_bank went negative: {remaining_bank}"

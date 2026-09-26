import pytest
from decimal import Decimal
from datetime import datetime, timezone

from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.services.lineup import pick_best_starting_xi, _rescore_gkps_by_fixture


def make_player(id, position, score, team_id=9001):
    player = Player(id=id, team_id=team_id, first_name="F", second_name="L", web_name=f"P{id}", position=position)
    return (player, None, score)


def build_valid_squad():
    squad = []
    squad.append(make_player(1, Position.GKP, 0.9))
    squad.append(make_player(2, Position.GKP, 0.3))

    for i, score in enumerate([0.9, 0.8, 0.7, 0.6, 0.5], start=3):
        squad.append(make_player(i, Position.DEF, score))

    for i, score in enumerate([0.95, 0.85, 0.75, 0.65, 0.55], start=8):
        squad.append(make_player(i, Position.MID, score))

    for i, score in enumerate([0.9, 0.6, 0.3], start=13):
        squad.append(make_player(i, Position.FWD, score))

    return squad


def test_starting_xi_has_exactly_eleven_players():
    squad = build_valid_squad()
    result = pick_best_starting_xi(squad)
    assert len(result["starting_xi"]) == 11


def test_bench_has_exactly_four_players():
    squad = build_valid_squad()
    result = pick_best_starting_xi(squad)
    total_bench = 1 + len(result["bench_outfield"])
    assert total_bench == 4


def test_lowest_scoring_goalkeeper_is_always_benched():
    squad = build_valid_squad()
    result = pick_best_starting_xi(squad)
    starting_ids = {p.id for p, s, sc in result["starting_xi"]}
    assert 2 not in starting_ids
    assert result["bench_gk"][0].id == 2


async def test_rescore_gkps_prefers_easier_fixture(monkeypatch):
    """GKP facing a weaker attack (fewer goals scored) should get a higher score."""
    gkp_easy = Player(id=1, team_id=10, first_name="E", second_name="Z", web_name="Easy", position=Position.GKP)
    gkp_hard = Player(id=2, team_id=20, first_name="H", second_name="R", web_name="Hard", position=Position.GKP)
    gkps = [(gkp_easy, None, 0.3), (gkp_hard, None, 0.9)]  # hard GKP has higher composite score

    async def fake_opponent_strength(db, team_id, gameweek, num_fixtures=1):
        # team 10 faces weak attack (1.0 goals/game), team 20 faces Arsenal-level (2.5 goals/game)
        return {"opponent_avg_goals_scored": 1.0 if team_id == 10 else 2.5,
                "opponent_avg_goals_conceded": None}

    monkeypatch.setattr("app.services.fixtures.get_opponent_strength_for_fixture", fake_opponent_strength)

    result = await _rescore_gkps_by_fixture(gkps, db=None, gameweek=5)

    scores_by_id = {p.id: sc for p, _, sc in result}
    assert scores_by_id[1] > scores_by_id[2], "easier-fixture GKP should outscore harder-fixture GKP"


async def test_rescore_gkps_falls_back_to_composite_when_no_data(monkeypatch):
    gkp = Player(id=1, team_id=10, first_name="A", second_name="B", web_name="GK", position=Position.GKP)
    gkps = [(gkp, None, 0.75)]

    async def fake_opponent_strength(db, team_id, gameweek, num_fixtures=1):
        return {"opponent_avg_goals_scored": None, "opponent_avg_goals_conceded": None}

    monkeypatch.setattr("app.services.fixtures.get_opponent_strength_for_fixture", fake_opponent_strength)

    result = await _rescore_gkps_by_fixture(gkps, db=None, gameweek=5)
    assert result[0][2] == pytest.approx(0.75)


def _make_player_with_stats(id, position, score, total_points, minutes, team_id=9001):
    """Build a (player, stats, score) triple where P/A and predicted score can disagree."""
    player = Player(id=id, team_id=team_id, first_name="F", second_name="L",
                    web_name=f"P{id}", position=position)
    stats = PlayerGameweekStats(
        player_id=id, gameweek=5, pulled_at=datetime.now(timezone.utc),
        price=Decimal("5.0"), form=Decimal("5.0"), ownership_pct=Decimal("10.0"),
        total_points=total_points, minutes=minutes,
    )
    return (player, stats, score)


def test_bench_outfield_ordered_by_predicted_score_not_season_pa():
    """
    Bench ordering must use predicted score, not season P/A.

    id=14: low season P/A (10pts / 1app = 1.0) but high predicted score (0.55)
    id=15: high season P/A (50pts / 1app = 50.0) but low predicted score (0.05)

    Both are benched: their predicted scores (0.55 and 0.05) are low enough
    that any valid formation prefers an extra DEF or MID (all scored 0.9) over
    a second or third FWD. No formation arithmetic needed — the score gap is
    large enough that it holds for any valid 4-X-X or 5-X-X formation.

    Correct order: id=14 first (higher predicted score).
    Old broken order: id=15 first (higher P/A).
    """
    squad = []
    squad.append(make_player(1, Position.GKP, 0.9))
    squad.append(make_player(2, Position.GKP, 0.3))
    for i in range(3, 8):   # 5 DEFs, all score=0.9
        squad.append(make_player(i, Position.DEF, 0.9))
    for i in range(8, 13):  # 5 MIDs, all score=0.9
        squad.append(make_player(i, Position.MID, 0.9))
    squad.append(make_player(13, Position.FWD, 0.9))   # only FWD worth starting
    squad.append(_make_player_with_stats(14, Position.FWD, score=0.55,
                                         total_points=10, minutes=90))
    squad.append(_make_player_with_stats(15, Position.FWD, score=0.05,
                                         total_points=50, minutes=90))

    result = pick_best_starting_xi(squad)
    bench_outfield_ids = [p.id for p, s, sc in result["bench_outfield"]]

    assert 14 in bench_outfield_ids, "FWD id=14 (score=0.55) should be benched"
    assert 15 in bench_outfield_ids, "FWD id=15 (score=0.05) should be benched"

    idx_14 = bench_outfield_ids.index(14)
    idx_15 = bench_outfield_ids.index(15)
    assert idx_14 < idx_15, (
        f"id=14 (score=0.55, low P/A) should appear before id=15 (score=0.05, high P/A). "
        f"Got bench order: {bench_outfield_ids}"
    )


def test_starting_xi_picks_highest_scorers_within_formation_limits():
    squad = build_valid_squad()
    result = pick_best_starting_xi(squad)
    starting_ids = {p.id for p, s, sc in result["starting_xi"]}
    assert 7 not in starting_ids
    assert 12 not in starting_ids
    assert 15 not in starting_ids

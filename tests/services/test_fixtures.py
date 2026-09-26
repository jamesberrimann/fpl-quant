import pytest

from app.core.db import async_session_factory
from app.models.team import Team
from app.models.fixture import Fixture
from app.services.fixtures import get_team_fixture_difficulty


async def test_finished_fixture_excluded_from_difficulty():
    fake_teams = [
        Team(id=9001, name="Fake Team A", short_name="FKA", strength_overall_home=3, strength_overall_away=3,
             strength_attack_home=3, strength_attack_away=3, strength_defence_home=3, strength_defence_away=3),
        Team(id=9002, name="Fake Team B", short_name="FKB", strength_overall_home=3, strength_overall_away=3,
             strength_attack_home=3, strength_attack_away=3, strength_defence_home=3, strength_defence_away=3),
    ]

    fake_fixtures = [
        Fixture(id=9001, gameweek=3, team_h_id=9001, team_a_id=9002, team_h_difficulty=2, team_a_difficulty=3, finished=True),
        Fixture(id=9002, gameweek=4, team_h_id=9001, team_a_id=9002, team_h_difficulty=4, team_a_difficulty=2, finished=False),
        Fixture(id=9003, gameweek=5, team_h_id=9001, team_a_id=9002, team_h_difficulty=3, team_a_difficulty=2, finished=False),
    ]

    async with async_session_factory() as db:
        for t in fake_teams:
            db.add(t)
        await db.commit()

        for f in fake_fixtures:
            db.add(f)
        await db.commit()

        try:
            difficulty = await get_team_fixture_difficulty(db, team_id=9001, from_gameweek=3)
            assert difficulty == 3.5
        finally:
            for f in fake_fixtures:
                await db.delete(f)
            await db.commit()
            for t in fake_teams:
                await db.delete(t)
            await db.commit()


import pytest
from decimal import Decimal
from datetime import datetime, timezone

from app.core.db import async_session_factory
from app.models.team import Team
from app.models.player import Player, Position
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.services.player_pool import get_latest_stats


async def test_get_latest_stats_returns_only_newest_snapshot_per_player():
    team = Team(id=9201, name="Fake FC", short_name="FFC", strength_overall_home=3, strength_overall_away=3,
                strength_attack_home=3, strength_attack_away=3, strength_defence_home=3, strength_defence_away=3)
    player = Player(id=9201, team_id=9201, first_name="F", second_name="L", web_name="Fake", position=Position.MID)

    old_snapshot = PlayerGameweekStats(
        id=920101, player_id=9201, gameweek=4, pulled_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        price=Decimal("5.0"), form=Decimal("3.0"), ownership_pct=Decimal("10.0"),
        total_points=5, minutes=90,
    )
    new_snapshot = PlayerGameweekStats(
        id=920102, player_id=9201, gameweek=4, pulled_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        price=Decimal("5.5"), form=Decimal("6.0"), ownership_pct=Decimal("15.0"),
        total_points=8, minutes=90,
    )

    async with async_session_factory() as db:
        db.add(team)
        db.add(player)
        await db.commit()

        db.add(old_snapshot)
        db.add(new_snapshot)
        await db.commit()

        try:
            rows = await get_latest_stats(db, gameweek=4)
            result = {p.id: s for p, s in rows if p.id == 9201}
            assert result[9201].total_points == 8
            assert result[9201].form == Decimal("6.0")
        finally:
            await db.delete(old_snapshot)
            await db.delete(new_snapshot)
            await db.commit()
            await db.delete(player)
            await db.delete(team)
            await db.commit()


import pytest
from app.services.fixtures import get_team_goals_record, get_opponent_strength_for_fixture


async def test_get_team_goals_record_correctly_attributes_home_and_away_goals():
    team = Team(id=9202, name="Fake United", short_name="FKU", strength_overall_home=3, strength_overall_away=3,
                strength_attack_home=3, strength_attack_away=3, strength_defence_home=3, strength_defence_away=3)
    opponent = Team(id=9203, name="Fake City", short_name="FKC", strength_overall_home=3, strength_overall_away=3,
                     strength_attack_home=3, strength_attack_away=3, strength_defence_home=3, strength_defence_away=3)

    fixture_home = Fixture(id=9205, gameweek=4, team_h_id=9202, team_a_id=9203,
                            team_h_difficulty=3, team_a_difficulty=3, team_h_score=3, team_a_score=1, finished=True)
    fixture_away = Fixture(id=9206, gameweek=5, team_h_id=9203, team_a_id=9202,
                            team_h_difficulty=3, team_a_difficulty=3, team_h_score=2, team_a_score=0, finished=True)

    async with async_session_factory() as db:
        db.add(team)
        db.add(opponent)
        await db.commit()

        db.add(fixture_home)
        db.add(fixture_away)
        await db.commit()

        try:
            record = await get_team_goals_record(db, team_id=9202)
            assert record["avg_goals_scored"] == 1.5
            assert record["avg_goals_conceded"] == 1.5
            assert record["matches_played"] == 2
        finally:
            await db.delete(fixture_home)
            await db.delete(fixture_away)
            await db.commit()
            await db.delete(team)
            await db.delete(opponent)
            await db.commit()


async def test_goals_record_recency_weighting_upweights_recent_defensive_improvement():
    """
    A team that leaks goals early but tightens up recently should show a lower
    weighted average conceded than a flat average would give — confirming the
    last-5-games × 3 recency weighting is working.

    Setup: 8 games total. First 3 games: 2 goals conceded each. Last 5 games: 0 each.
    - Flat avg: (3×2 + 5×0) / 8 = 0.75
    - Recency weighted (3× recent): (3×1×2 + 5×3×0) / (3×1 + 5×3) = 6/18 = 0.333
    The weighted result should be lower, reflecting genuine defensive improvement.
    """
    team = Team(id=9210, name="Improved FC", short_name="IMP",
                strength_overall_home=3, strength_overall_away=3,
                strength_attack_home=3, strength_attack_away=3,
                strength_defence_home=3, strength_defence_away=3)
    opponent = Team(id=9211, name="Foe FC", short_name="FOE",
                     strength_overall_home=3, strength_overall_away=3,
                     strength_attack_home=3, strength_attack_away=3,
                     strength_defence_home=3, strength_defence_away=3)

    # 3 early games: team concedes 2 each
    early_fixtures = [
        Fixture(id=9300+i, gameweek=i+1, team_h_id=9210, team_a_id=9211,
                team_h_difficulty=3, team_a_difficulty=3,
                team_h_score=1, team_a_score=2, finished=True)
        for i in range(3)
    ]
    # 5 recent games: team concedes 0 each (clean sheets)
    recent_fixtures = [
        Fixture(id=9310+i, gameweek=i+4, team_h_id=9210, team_a_id=9211,
                team_h_difficulty=3, team_a_difficulty=3,
                team_h_score=1, team_a_score=0, finished=True)
        for i in range(5)
    ]

    all_fixtures = early_fixtures + recent_fixtures

    async with async_session_factory() as db:
        db.add(team); db.add(opponent); await db.commit()
        for f in all_fixtures: db.add(f)
        await db.commit()

        try:
            record = await get_team_goals_record(db, team_id=9210)
            flat_avg = (3 * 2 + 5 * 0) / 8  # = 0.75

            assert record["matches_played"] == 8
            assert record["avg_goals_conceded"] < flat_avg, (
                f"Recency-weighted avg {record['avg_goals_conceded']:.3f} should be below "
                f"flat average {flat_avg:.3f} — recent clean sheets carry 3× weight"
            )
            # Exact weighted value: (3×1×2 + 5×3×0) / (3×1 + 5×3) = 6/18 = 0.333
            import pytest as _pytest
            assert record["avg_goals_conceded"] == _pytest.approx(6/18, rel=1e-4)
        finally:
            for f in all_fixtures: await db.delete(f)
            await db.commit()
            await db.delete(team); await db.delete(opponent); await db.commit()


async def test_get_opponent_strength_returns_none_when_no_opponent_history():
    team = Team(id=9207, name="Fake Rovers", short_name="FKR", strength_overall_home=3, strength_overall_away=3,
                strength_attack_home=3, strength_attack_away=3, strength_defence_home=3, strength_defence_away=3)
    opponent = Team(id=9208, name="Fake Athletic", short_name="FKA", strength_overall_home=3, strength_overall_away=3,
                     strength_attack_home=3, strength_attack_away=3, strength_defence_home=3, strength_defence_away=3)

    upcoming_fixture = Fixture(id=9209, gameweek=5, team_h_id=9207, team_a_id=9208,
                                team_h_difficulty=3, team_a_difficulty=3, finished=False)

    async with async_session_factory() as db:
        db.add(team)
        db.add(opponent)
        await db.commit()

        db.add(upcoming_fixture)
        await db.commit()

        try:
            result = await get_opponent_strength_for_fixture(db, team_id=9207, from_gameweek=5)
            assert result["opponent_avg_goals_conceded"] is None
            assert result["opponent_avg_goals_scored"] is None
        finally:
            await db.delete(upcoming_fixture)
            await db.commit()
            await db.delete(team)
            await db.delete(opponent)
            await db.commit()

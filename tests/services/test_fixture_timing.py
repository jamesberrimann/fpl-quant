from app.core.db import async_session_factory
from app.models.team import Team
from app.models.fixture import Fixture
from app.models.player import Position
from app.services.fixtures import get_fixture_timing_signal


async def _seed(db, teams, fixtures):
    for t in teams:
        db.add(t)
    await db.commit()
    for f in fixtures:
        db.add(f)
    await db.commit()


async def _cleanup(db, fixtures, teams):
    for f in fixtures:
        await db.delete(f)
    await db.commit()
    for t in teams:
        await db.delete(t)
    await db.commit()


def make_team(id):
    return Team(id=id, name=f"Team {id}", short_name=f"T{id}", strength_overall_home=3, strength_overall_away=3,
                strength_attack_home=3, strength_attack_away=3, strength_defence_home=3, strength_defence_away=3)


async def test_timing_signal_none_with_fewer_than_two_fixtures():
    teams = [make_team(9101), make_team(9102)]
    fixtures = [
        Fixture(id=9101, gameweek=5, team_h_id=9101, team_a_id=9102, team_h_difficulty=4, team_a_difficulty=2, finished=False),
    ]

    async with async_session_factory() as db:
        await _seed(db, teams, fixtures)
        try:
            signal = await get_fixture_timing_signal(db, team_id=9101, position=Position.FWD)
            assert signal is None
        finally:
            await _cleanup(db, fixtures, teams)


async def test_timing_signal_flags_hard_next_fixture_when_away():
    teams = [make_team(9103), make_team(9104)]
    fixtures = [
        Fixture(id=9102, gameweek=5, team_h_id=9104, team_a_id=9103, team_h_difficulty=1, team_a_difficulty=5, finished=False),
        Fixture(id=9103, gameweek=6, team_h_id=9103, team_a_id=9104, team_h_difficulty=2, team_a_difficulty=2, finished=False),
        Fixture(id=9104, gameweek=7, team_h_id=9103, team_a_id=9104, team_h_difficulty=2, team_a_difficulty=2, finished=False),
    ]

    async with async_session_factory() as db:
        await _seed(db, teams, fixtures)
        try:
            signal = await get_fixture_timing_signal(db, team_id=9103, position=Position.FWD)
            assert signal is not None
            assert signal["next_difficulty"] == 5
            assert signal["rest_avg_difficulty"] == 2.0
            assert signal["wait_recommended"] is True
        finally:
            await _cleanup(db, fixtures, teams)


async def test_timing_signal_none_when_gap_below_threshold():
    teams = [make_team(9105), make_team(9106)]
    fixtures = [
        Fixture(id=9105, gameweek=5, team_h_id=9105, team_a_id=9106, team_h_difficulty=3, team_a_difficulty=3, finished=False),
        Fixture(id=9106, gameweek=6, team_h_id=9105, team_a_id=9106, team_h_difficulty=3, team_a_difficulty=3, finished=False),
    ]

    async with async_session_factory() as db:
        await _seed(db, teams, fixtures)
        try:
            signal = await get_fixture_timing_signal(db, team_id=9105, position=Position.FWD)
            assert signal is None
        finally:
            await _cleanup(db, fixtures, teams)


async def test_timing_signal_uses_lower_threshold_for_goals_based_data():
    # opp 9202 concedes 1+1+2=4 goals over 3 games → avg 1.333
    # opp 9203 concedes 2 goals over 1 game → avg 2.0
    # FWD hardness = -avg_goals_conceded: gap = -1.333 - (-2.0) = 0.667
    # Old threshold (1.0): 0.667 < 1.0 → no signal; goals threshold (0.5): 0.667 >= 0.5 → fires
    teams = [make_team(9201), make_team(9202), make_team(9203), make_team(9205)]
    finished = [
        Fixture(id=9211, gameweek=1, team_h_id=9205, team_a_id=9202, team_h_score=1, team_a_score=0, team_h_difficulty=3, team_a_difficulty=3, finished=True),
        Fixture(id=9212, gameweek=2, team_h_id=9205, team_a_id=9202, team_h_score=1, team_a_score=0, team_h_difficulty=3, team_a_difficulty=3, finished=True),
        Fixture(id=9213, gameweek=3, team_h_id=9205, team_a_id=9202, team_h_score=2, team_a_score=0, team_h_difficulty=3, team_a_difficulty=3, finished=True),
        Fixture(id=9214, gameweek=3, team_h_id=9205, team_a_id=9203, team_h_score=2, team_a_score=0, team_h_difficulty=3, team_a_difficulty=3, finished=True),
    ]
    upcoming = [
        Fixture(id=9215, gameweek=20, team_h_id=9201, team_a_id=9202, team_h_difficulty=3, team_a_difficulty=3, finished=False),
        Fixture(id=9216, gameweek=21, team_h_id=9201, team_a_id=9203, team_h_difficulty=3, team_a_difficulty=3, finished=False),
    ]
    all_fixtures = finished + upcoming

    async with async_session_factory() as db:
        await _seed(db, teams, all_fixtures)
        try:
            signal = await get_fixture_timing_signal(db, team_id=9201, position=Position.FWD)
            assert signal is not None, "Expected signal to fire with goals-based 0.5 threshold"
            assert signal["wait_recommended"] is True
            assert abs(signal["next_difficulty"] - (-4 / 3)) < 0.01
        finally:
            await _cleanup(db, all_fixtures, teams)

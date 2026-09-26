from sqlalchemy import select, or_, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fixture import Fixture
from app.models.player import Position, DEFENSIVE_POSITIONS
from app.models.team import Team


async def get_gameweek_fixture_count(db: AsyncSession, team_id: int, gameweek: int) -> int:
    """Returns how many fixtures a team has in a specific gameweek (0=BGW, 1=normal, 2=DGW)."""
    stmt = select(Fixture).where(
        or_(Fixture.team_h_id == team_id, Fixture.team_a_id == team_id),
        Fixture.gameweek == gameweek,
    )
    result = await db.execute(stmt)
    return len(result.scalars().all())


async def get_gameweek_fixture_multipliers(db: AsyncSession, team_ids: set[int], gameweek: int) -> dict[int, float]:
    """Maps team_id → 0.0 (BGW), 1.0 (normal), or 2.0 (DGW) for the given gameweek.

    Used to scale predicted points for single-gameweek decisions: lineup selection,
    captaincy, and immediate transfer value.
    """
    return {
        team_id: float(await get_gameweek_fixture_count(db, team_id, gameweek))
        for team_id in team_ids
    }


async def get_all_gameweek_multipliers_in_range(
    db: AsyncSession, team_ids: set[int], from_gw: int, to_gw: int
) -> dict[int, dict[int, float]]:
    """Maps {gw: {team_id: fixture_count}} for all GWs in [from_gw, to_gw].

    Single DB query equivalent to calling get_gameweek_fixture_multipliers for each GW.
    Unscheduled GWs (no fixtures in DB) return 0.0 for all team_ids.
    """
    info = await get_all_gameweek_fixture_info_in_range(db, team_ids, from_gw, to_gw)
    return {
        gw: {tid: v["count"] for tid, v in teams.items()}
        for gw, teams in info.items()
    }


async def get_all_gameweek_fixture_info_in_range(
    db: AsyncSession, team_ids: set[int], from_gw: int, to_gw: int
) -> dict[int, dict[int, dict]]:
    """Maps {gw: {team_id: {"count": float, "difficulty": float}}} for all GWs in range.

    count: 0.0 (BGW/unscheduled), 1.0 (normal), 2.0 (DGW)
    difficulty: FPL 1–5 rating (avg across fixtures in that GW); 3.0 default for BGW.

    Single DB query — use this in preference to per-GW lookups when scanning the season.
    """
    stmt = select(Fixture).where(
        or_(Fixture.team_h_id.in_(team_ids), Fixture.team_a_id.in_(team_ids)),
        Fixture.gameweek >= from_gw,
        Fixture.gameweek <= to_gw,
    )
    result = await db.execute(stmt)
    fixtures = result.scalars().all()

    info: dict[int, dict[int, dict]] = {
        gw: {tid: {"count": 0.0, "difficulty": 3.0} for tid in team_ids}
        for gw in range(from_gw, to_gw + 1)
    }
    difficulty_sums: dict[int, dict[int, float]] = {
        gw: {tid: 0.0 for tid in team_ids}
        for gw in range(from_gw, to_gw + 1)
    }
    for f in fixtures:
        gw = f.gameweek
        if gw not in info:
            continue
        for tid, diff in ((f.team_h_id, f.team_h_difficulty), (f.team_a_id, f.team_a_difficulty)):
            if tid in info[gw]:
                info[gw][tid]["count"] += 1.0
                difficulty_sums[gw][tid] += diff

    for gw, teams in info.items():
        for tid, v in teams.items():
            if v["count"] > 0:
                v["difficulty"] = difficulty_sums[gw][tid] / v["count"]
    return info


async def get_fixture_counts_in_gameweek_window(
    db: AsyncSession, team_ids: set[int], from_gameweek: int, num_gameweeks: int = 5
) -> dict[int, int]:
    """Total fixtures each team plays across the next `num_gameweeks` gameweeks.

    A DGW team scores 6 games in a 5-GW window (vs 5 for normal, 4 for BGW teams).
    Used to fairly weight squad-building scores so DGW teams aren't under-valued.
    """
    to_gameweek = from_gameweek + num_gameweeks - 1
    stmt = select(Fixture).where(
        or_(Fixture.team_h_id.in_(team_ids), Fixture.team_a_id.in_(team_ids)),
        Fixture.gameweek >= from_gameweek,
        Fixture.gameweek <= to_gameweek,
    )
    result = await db.execute(stmt)
    fixtures = result.scalars().all()

    counts: dict[int, int] = {tid: 0 for tid in team_ids}
    for f in fixtures:
        if f.team_h_id in counts:
            counts[f.team_h_id] += 1
        if f.team_a_id in counts:
            counts[f.team_a_id] += 1
    return counts


async def get_planning_gameweek(db: AsyncSession, current_gameweek: int) -> int:
    """
    Return the gameweek to use for fixture lookups.

    Once any fixture in the current GW has finished, we treat the GW as done
    and look at next week — so Liverpool playing Friday doesn't leave everyone
    else stuck looking at the same gameweek all weekend.
    """
    # FPL sets finished=True only once bonus points are applied, which can lag
    # by hours after the match ends. Check for a non-null score as the reliable
    # "match has been played" signal.
    stmt = select(exists().where(
        Fixture.gameweek == current_gameweek,
        or_(
            Fixture.finished == True,
            Fixture.team_h_score.isnot(None),
        ),
    ))
    result = await db.execute(stmt)
    any_played = result.scalar()
    return current_gameweek + 1 if any_played else current_gameweek

async def get_team_fixture_difficulty(db: AsyncSession, team_id: int, from_gameweek: int, num_fixtures: int = 3) -> float:
    stmt = (
        select(Fixture)
        .where(
            or_(Fixture.team_h_id == team_id, Fixture.team_a_id == team_id),
            Fixture.finished == False,
            Fixture.team_h_score.is_(None),
            Fixture.gameweek >= from_gameweek,
        )
        .order_by(Fixture.gameweek)
        .limit(num_fixtures)
    )
    result = await db.execute(stmt)
    fixtures = result.scalars().all()

    if not fixtures:
        return 3.0

    difficulties = [
        f.team_h_difficulty if f.team_h_id == team_id else f.team_a_difficulty
        for f in fixtures
    ]
    return sum(difficulties) / len(difficulties)


async def get_team_goals_record(db: AsyncSession, team_id: int, home: bool | None = None) -> dict | None:
    """Return recency-weighted goals averages for a team.

    home: True = only home matches, False = only away matches, None = all matches.
    Separating home/away is important because home teams score ~40% more than away,
    so blending distorts opponent strength estimates for upcoming fixture context.

    Recent form matters more than early-season results — a team that tightened
    up defensively in the last 5 games shouldn't be penalised by their GW1–5
    leakiness equally. Weights: last 5 games × 3, earlier games × 1.
    """
    stmt = (
        select(Fixture)
        .where(
            or_(Fixture.team_h_id == team_id, Fixture.team_a_id == team_id),
            or_(Fixture.finished == True, Fixture.team_h_score.isnot(None)),
        )
        .order_by(Fixture.gameweek)
    )
    result = await db.execute(stmt)
    fixtures = result.scalars().all()

    played_fixtures = [
        f for f in fixtures
        if f.team_h_score is not None and f.team_a_score is not None
    ]

    if home is True:
        played_fixtures = [f for f in played_fixtures if f.team_h_id == team_id]
    elif home is False:
        played_fixtures = [f for f in played_fixtures if f.team_a_id == team_id]

    if not played_fixtures:
        return None

    # Last 5 games carry 3× the weight of earlier games.
    _RECENT_WEIGHT = 3
    _RECENT_COUNT = 5
    recent_cutoff = max(0, len(played_fixtures) - _RECENT_COUNT)

    weighted_scored = 0.0
    weighted_conceded = 0.0
    total_weight = 0.0

    for i, f in enumerate(played_fixtures):
        weight = _RECENT_WEIGHT if i >= recent_cutoff else 1.0
        is_home = f.team_h_id == team_id
        weighted_scored += weight * (f.team_h_score if is_home else f.team_a_score)
        weighted_conceded += weight * (f.team_a_score if is_home else f.team_h_score)
        total_weight += weight

    return {
        "avg_goals_scored": weighted_scored / total_weight,
        "avg_goals_conceded": weighted_conceded / total_weight,
        "matches_played": len(played_fixtures),
    }


async def get_opponent_strength_for_fixture(db: AsyncSession, team_id: int, from_gameweek: int, num_fixtures: int = 3) -> dict:
    stmt = (
        select(Fixture)
        .where(
            or_(Fixture.team_h_id == team_id, Fixture.team_a_id == team_id),
            Fixture.finished == False,
            Fixture.team_h_score.is_(None),
            Fixture.gameweek >= from_gameweek,
        )
        .order_by(Fixture.gameweek)
        .limit(num_fixtures)
    )
    result = await db.execute(stmt)
    fixtures = result.scalars().all()

    if not fixtures:
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    opponent_conceded_values = []
    opponent_scored_values = []
    for f in fixtures:
        opponent_id = f.team_a_id if f.team_h_id == team_id else f.team_h_id
        # Query the opponent's record for the venue they'll play in — home teams
        # score ~40% more than away, so blending all results distorts the signal.
        opponent_is_home = (f.team_h_id == opponent_id)
        record = await get_team_goals_record(db, opponent_id, home=opponent_is_home)
        if record is not None:
            opponent_conceded_values.append(record["avg_goals_conceded"])
            opponent_scored_values.append(record["avg_goals_scored"])

    if not opponent_conceded_values:
        return {"opponent_avg_goals_conceded": None, "opponent_avg_goals_scored": None}

    return {
        "opponent_avg_goals_conceded": sum(opponent_conceded_values) / len(opponent_conceded_values),
        "opponent_avg_goals_scored": sum(opponent_scored_values) / len(opponent_scored_values),
    }


async def get_next_fixture_labels(db: AsyncSession, team_ids: set[int], from_gameweek: int) -> dict[int, str]:
    """Returns a fixture label per team for their next gameweek.

    DGW teams get a combined label ("CHE(H)+MCI(A) DGW") showing both fixtures.
    Teams with a blank gameweek show their next non-blank fixture with no DGW suffix.
    """
    stmt = (
        select(Fixture)
        .where(
            or_(Fixture.team_h_id.in_(team_ids), Fixture.team_a_id.in_(team_ids)),
            Fixture.finished == False,
            Fixture.team_h_score.is_(None),
            Fixture.gameweek >= from_gameweek,
        )
        .order_by(Fixture.gameweek)
    )
    result = await db.execute(stmt)
    fixtures = result.scalars().all()

    # For each team: find their next gameweek, then collect ALL fixtures in that GW
    # (handles DGW where two rows share the same gameweek number).
    next_gw_by_team: dict[int, int] = {}
    team_fixtures: dict[int, list[Fixture]] = {}
    for f in fixtures:
        if f.gameweek is None:
            continue
        for tid in (f.team_h_id, f.team_a_id):
            if tid in team_ids:
                if tid not in next_gw_by_team:
                    next_gw_by_team[tid] = f.gameweek
                    team_fixtures[tid] = [f]
                elif f.gameweek == next_gw_by_team[tid]:
                    team_fixtures[tid].append(f)

    opponent_ids: set[int] = set()
    for tid, fs in team_fixtures.items():
        for f in fs:
            opp_id = f.team_a_id if f.team_h_id == tid else f.team_h_id
            opponent_ids.add(opp_id)
    teams_result = await db.execute(select(Team).where(Team.id.in_(opponent_ids)))
    short_names = {t.id: t.short_name for t in teams_result.scalars().all()}

    labels: dict[int, str] = {}
    for tid, fs in team_fixtures.items():
        parts = []
        for f in fs:
            is_home = f.team_h_id == tid
            opp_id = f.team_a_id if is_home else f.team_h_id
            opp = short_names.get(opp_id)
            if opp:
                parts.append(f"{opp}({'H' if is_home else 'A'})")
        if parts:
            label = "+".join(parts)
            if len(parts) > 1:
                label += " DGW"
            labels[tid] = label
    return labels


async def get_next_fixture_is_home(
    db: AsyncSession,
    team_ids: set[int],
    from_gameweek: int,
) -> dict[int, bool | None]:
    """Return {team_id: is_home} for each team's next upcoming unplayed fixture.

    True = home, False = away, absent key = blank gameweek (no fixture found).
    For DGW teams, reflects the first fixture of the double.
    """
    if not team_ids:
        return {}

    stmt = (
        select(Fixture)
        .where(
            or_(Fixture.team_h_id.in_(team_ids), Fixture.team_a_id.in_(team_ids)),
            Fixture.finished == False,
            Fixture.team_h_score.is_(None),
            Fixture.gameweek >= from_gameweek,
        )
        .order_by(Fixture.gameweek)
    )
    result = await db.execute(stmt)
    fixtures = result.scalars().all()

    is_home_by_team: dict[int, bool | None] = {}
    for f in fixtures:
        if f.gameweek is None:
            continue
        for tid in (f.team_h_id, f.team_a_id):
            if tid in team_ids and tid not in is_home_by_team:
                is_home_by_team[tid] = (f.team_h_id == tid)

    return is_home_by_team


async def get_fixture_timing_signal(db: AsyncSession, team_id: int, position: Position, from_gameweek: int = 1, gap_threshold: float = 1.0):
    stmt = (
        select(Fixture)
        .where(
            or_(Fixture.team_h_id == team_id, Fixture.team_a_id == team_id),
            Fixture.finished == False,
            Fixture.team_h_score.is_(None),
            Fixture.gameweek >= from_gameweek,
        )
        .order_by(Fixture.gameweek)
        .limit(3)
    )
    result = await db.execute(stmt)
    fixtures = result.scalars().all()

    if len(fixtures) < 2:
        return None

    def opponent_id_for(f):
        return f.team_a_id if f.team_h_id == team_id else f.team_h_id

    def blended_difficulty_for(f):
        return f.team_h_difficulty if f.team_h_id == team_id else f.team_a_difficulty

    is_defensive = position in DEFENSIVE_POSITIONS

    goals_hardness = []
    all_records_available = True
    for f in fixtures:
        opp_id = opponent_id_for(f)
        opp_is_home = (f.team_h_id == opp_id)
        record = await get_team_goals_record(db, opp_id, home=opp_is_home)
        if record is None:
            all_records_available = False
            break
        goals_hardness.append(record["avg_goals_scored"] if is_defensive else -record["avg_goals_conceded"])

    hardness_values = goals_hardness if all_records_available else [blended_difficulty_for(f) for f in fixtures]

    # Goals-based values span ~0–3 goals/game; the 1–5 difficulty scale spans 4 units.
    # A 1.0 gap threshold calibrated for 1–5 is too coarse on the goals scale — use 0.5
    # when real goals data drives the signal.
    effective_threshold = 0.5 if all_records_available else gap_threshold

    next_hardness = hardness_values[0]
    rest_hardness = hardness_values[1:]
    rest_avg_hardness = sum(rest_hardness) / len(rest_hardness)

    gap = next_hardness - rest_avg_hardness
    if gap >= effective_threshold:
        return {
            "next_difficulty": next_hardness,
            "rest_avg_difficulty": rest_avg_hardness,
            "wait_recommended": True,
        }
    return None

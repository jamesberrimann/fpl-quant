from dataclasses import dataclass, field

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fixture import Fixture
from app.models.team import Team


@dataclass
class FixtureOpponent:
    team_id: int
    short_name: str
    is_home: bool
    fdr: int  # FPL difficulty rating 1–5


@dataclass
class GWFixtureSlot:
    gameweek: int
    opponents: list[FixtureOpponent] = field(default_factory=list)

    @property
    def is_blank(self) -> bool:
        return len(self.opponents) == 0

    @property
    def is_double(self) -> bool:
        return len(self.opponents) >= 2

    @property
    def avg_fdr(self) -> float | None:
        """None for blank gameweeks; average FDR across all fixtures otherwise."""
        if not self.opponents:
            return None
        return sum(o.fdr for o in self.opponents) / len(self.opponents)


async def get_fixture_heatmap(
    db: AsyncSession,
    team_ids: set[int],
    from_gameweek: int,
    num_gameweeks: int = 6,
) -> dict[int, list[GWFixtureSlot]]:
    """Return a per-gameweek fixture plan for each team over num_gameweeks.

    Every gameweek in the range is included even when a team has no fixture
    (blank gameweek) — callers must see blanks explicitly for chip/transfer
    planning. Double gameweek slots carry two opponents.

    Uses FDR (1–5) for difficulty. Goals-based difficulty averages across
    multiple fixtures and suits the prediction model, not a planning heatmap
    where you need per-fixture granularity in a single batch query.
    """
    if not team_ids:
        return {}

    to_gameweek = from_gameweek + num_gameweeks - 1

    # Batch 1: all fixtures in the window involving any of our teams
    stmt = (
        select(Fixture)
        .where(
            or_(Fixture.team_h_id.in_(team_ids), Fixture.team_a_id.in_(team_ids)),
            Fixture.gameweek >= from_gameweek,
            Fixture.gameweek <= to_gameweek,
        )
    )
    result = await db.execute(stmt)
    fixtures = result.scalars().all()

    # Collect all opponent team IDs so we can batch-load their short names
    opponent_ids: set[int] = set()
    for f in fixtures:
        if f.gameweek is None:
            continue
        if f.team_h_id in team_ids:
            opponent_ids.add(f.team_a_id)
        if f.team_a_id in team_ids:
            opponent_ids.add(f.team_h_id)

    # Batch 2: short names for all opponents we'll display
    short_names: dict[int, str] = {}
    if opponent_ids:
        teams_result = await db.execute(
            select(Team).where(Team.id.in_(opponent_ids))
        )
        short_names = {t.id: t.short_name for t in teams_result.scalars().all()}

    # Initialise every slot empty so blank gameweeks appear in output
    grid: dict[int, dict[int, list[Fixture]]] = {
        tid: {gw: [] for gw in range(from_gameweek, to_gameweek + 1)}
        for tid in team_ids
    }
    for f in fixtures:
        if f.gameweek is None:
            continue
        if f.team_h_id in team_ids:
            grid[f.team_h_id][f.gameweek].append(f)
        if f.team_a_id in team_ids:
            grid[f.team_a_id][f.gameweek].append(f)

    heatmap: dict[int, list[GWFixtureSlot]] = {}
    for tid in team_ids:
        slots: list[GWFixtureSlot] = []
        for gw in range(from_gameweek, to_gameweek + 1):
            opponents: list[FixtureOpponent] = []
            for f in grid[tid][gw]:
                is_home = f.team_h_id == tid
                opp_id = f.team_a_id if is_home else f.team_h_id
                fdr = f.team_h_difficulty if is_home else f.team_a_difficulty
                opponents.append(FixtureOpponent(
                    team_id=opp_id,
                    short_name=short_names.get(opp_id, "???"),
                    is_home=is_home,
                    fdr=fdr,
                ))
            slots.append(GWFixtureSlot(gameweek=gw, opponents=opponents))
        heatmap[tid] = slots

    return heatmap

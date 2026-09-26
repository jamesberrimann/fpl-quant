from pydantic import BaseModel


class StartingPlayerOut(BaseModel):
    id: int
    web_name: str
    position: str
    score: float
    team_short_name: str
    next_fixture: str | None = None
    status: str = "a"
    chance_of_playing_next_round: int | None = None


class CaptainOptionOut(BaseModel):
    id: int
    web_name: str
    rating: int
    predicted_pts: float | None = None
    ownership_pct: float | None = None
    top_factors: list[str] | None = None
    next_fixture_is_home: bool | None = None
    variance_level: str | None = None
    is_hot_form: bool | None = None


class AutoSubOut(BaseModel):
    out_id: int
    out_name: str
    in_id: int
    in_name: str


class AutoSubSimulationOut(BaseModel):
    substitutions: list[AutoSubOut]
    unresolved_absences: list[str]   # web_names of absent starters with no eligible sub
    effective_xi_ids: list[int]


class BenchCoverageOut(BaseModel):
    covered_positions: list[str]
    uncovered_positions: list[str]
    warning: str | None = None


class LineupOut(BaseModel):
    starting_xi: list[StartingPlayerOut]
    captain: CaptainOptionOut
    vice_captain: CaptainOptionOut
    captain_advantage_pct: float | None
    tie_broken_by_ceiling: bool
    bench_gk: StartingPlayerOut | None
    bench_outfield: list[StartingPlayerOut]
    differential_captain: CaptainOptionOut | None = None
    bench_coverage: BenchCoverageOut | None = None
    autosub_simulation: AutoSubSimulationOut | None = None

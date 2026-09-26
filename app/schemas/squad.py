from pydantic import BaseModel


class SquadPlayerOut(BaseModel):
    id: int
    web_name: str
    position: str
    team_short_name: str
    price: float
    score: float
    next_fixture: str | None = None
    status: str = "a"
    chance_of_playing_next_round: int | None = None
    percentile: float = 0.0
    flag: str | None = None


class BudgetStepOut(BaseModel):
    budget: float
    squad_score: float
    total_cost: float
    marginal_gain: float | None = None


class BudgetSensitivityOut(BaseModel):
    steps: list[BudgetStepOut]


class SquadOut(BaseModel):
    players: list[SquadPlayerOut]
    total_cost: float
    squad_score: float
    starting_xi: list[SquadPlayerOut]
    bench: list[SquadPlayerOut]
    captain_id: int
    vice_captain_id: int
    captain_predicted_pts: float | None = None
    vc_predicted_pts: float | None = None
    captain_ownership_pct: float | None = None
    vc_ownership_pct: float | None = None
    captain_top_factors: list[str] | None = None
    vc_top_factors: list[str] | None = None
    squad_score_percentile: float | None = None

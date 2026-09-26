from pydantic import BaseModel


class GWCaptainOut(BaseModel):
    gameweek: int
    captain_id: int
    captain_name: str
    captain_pts: int
    captain_bonus: int
    optimal_id: int
    optimal_name: str
    optimal_pts: int
    was_optimal: bool
    regret_pts: int


class CaptainAccuracyOut(BaseModel):
    gameweeks: list[GWCaptainOut]
    hit_rate: float          # fraction of GWs where captain was optimal
    total_regret_pts: int    # total missed bonus pts over the window

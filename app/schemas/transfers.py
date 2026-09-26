from pydantic import BaseModel


class TimingSignalOut(BaseModel):
    next_difficulty: float
    rest_avg_difficulty: float
    wait_recommended: bool


class TransferSuggestionOut(BaseModel):
    out_id: int
    out_web_name: str
    out_team_short_name: str
    in_id: int
    in_web_name: str
    in_team_short_name: str
    position: str
    improvement: float
    price_change: float
    points_cost: int
    timing_signal: TimingSignalOut | None = None
    in_dgw: bool = False
    in_ownership_pct: float | None = None
    is_differential: bool = False
    in_price_last_gw_change: float = 0.0
    out_price_last_gw_change: float = 0.0
    in_rotation_risk: float = 0.0
    in_net_transfers_this_gw: int = 0
    in_hot_form: bool = False
    break_even_weeks: int | None = None
    in_ownership_trend: float | None = None
    in_price_rise_likely: bool = False
    in_price_fall_likely: bool = False
    improvement_drivers: list[str] = []
    is_marginal: bool = False


class TransferSuggestionsOut(BaseModel):
    suggestions: list[TransferSuggestionOut]
    roll_recommendation: bool = False
    roll_reason: str | None = None

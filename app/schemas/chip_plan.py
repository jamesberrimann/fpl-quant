from pydantic import BaseModel


class TripleCaptainWindowOut(BaseModel):
    gameweek: int
    best_player_name: str
    best_player_score: float
    is_dgw: bool
    reason: str


class BenchBoostWindowOut(BaseModel):
    gameweek: int
    dgw_count: int
    reason: str


class FreeHitWindowOut(BaseModel):
    gameweek: int
    blank_count: int
    reason: str


class WildcardWindowOut(BaseModel):
    gameweek: int
    reason: str


class ChipPlanOut(BaseModel):
    triple_captain: TripleCaptainWindowOut | None = None
    bench_boost: BenchBoostWindowOut | None = None
    free_hit: list[FreeHitWindowOut] = []
    wildcard: WildcardWindowOut | None = None

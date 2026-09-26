from pydantic import BaseModel


class GameweekProjectionOut(BaseModel):
    gameweek: int
    predicted_total: float
    dgw_player_count: int = 0
    bgw_player_count: int = 0


class SquadProjectionOut(BaseModel):
    gameweeks: list[GameweekProjectionOut]

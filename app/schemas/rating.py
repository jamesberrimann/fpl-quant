from pydantic import BaseModel


class RatedPlayerOut(BaseModel):
    id: int
    web_name: str
    position: str
    team_short_name: str
    score: float
    percentile: float
    flag: str | None = None
    next_fixture: str | None = None


class SquadRatingOut(BaseModel):
    players: list[RatedPlayerOut]
    squad_score: float

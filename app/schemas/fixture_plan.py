from pydantic import BaseModel


class FixtureOpponentOut(BaseModel):
    team_id: int
    short_name: str
    is_home: bool
    fdr: int


class GWFixtureSlotOut(BaseModel):
    gameweek: int
    opponents: list[FixtureOpponentOut]
    is_blank: bool
    is_double: bool
    avg_fdr: float | None


class PlayerFixturePlanOut(BaseModel):
    player_id: int
    web_name: str
    position: str
    team_id: int
    team_short_name: str
    gameweek_slots: list[GWFixtureSlotOut]


class FixturePlanOut(BaseModel):
    from_gameweek: int
    num_gameweeks: int
    players: list[PlayerFixturePlanOut]

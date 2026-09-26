from pydantic import BaseModel


class TeamScoreOut(BaseModel):
    team_id: int
    team_name: str
    team_short_name: str
    gameweek: int
    is_current_gameweek: bool
    is_home: bool
    team_score: int
    opponent_id: int
    opponent_name: str
    opponent_short_name: str
    opponent_score: int
    fully_confirmed: bool


class SquadScoresOut(BaseModel):
    scores: list[TeamScoreOut]


class PlayerLiveEventOut(BaseModel):
    player_id: int
    web_name: str
    position: str
    team_short_name: str
    gameweek: int
    is_current_gameweek: bool
    events: dict[str, int]


class SquadLiveEventsOut(BaseModel):
    events: list[PlayerLiveEventOut]

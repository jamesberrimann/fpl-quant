from pydantic import BaseModel


class RivalOut(BaseModel):
    manager: str
    rank: int
    pts: int
    gap: int


class MiniLeagueOut(BaseModel):
    league_id: int
    league_name: str
    entry_rank: int
    entry_pts: int
    leader_name: str
    leader_pts: int
    gap_to_leader: int
    rivals: list[RivalOut]


class MiniLeagueContextOut(BaseModel):
    leagues: list[MiniLeagueOut]

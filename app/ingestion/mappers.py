from datetime import datetime
from decimal import Decimal

from app.models.player import Player, Position
from app.models.team import Team
from app.models.player_gameweek_stats import PlayerGameweekStats
from app.models.fixture import Fixture

POSITION_MAP = {
    1: Position.GKP,
    2: Position.DEF,
    3: Position.MID,
    4: Position.FWD,
}


def map_team(raw: dict) -> Team:
    return Team(
        id=raw["id"],
        name=raw["name"],
        short_name=raw["short_name"],
        strength_overall_home=raw["strength_overall_home"],
        strength_overall_away=raw["strength_overall_away"],
        strength_attack_home=raw["strength_attack_home"],
        strength_attack_away=raw["strength_attack_away"],
        strength_defence_home=raw["strength_defence_home"],
        strength_defence_away=raw["strength_defence_away"],
    )


def map_player(raw: dict) -> Player:
    return Player(
        id=raw["id"],
        team_id=raw["team"],
        first_name=raw["first_name"],
        second_name=raw["second_name"],
        web_name=raw["web_name"],
        position=POSITION_MAP[raw["element_type"]],
    )


def map_player_stats(raw: dict, gameweek: int, pulled_at: datetime) -> PlayerGameweekStats:
    xgc_raw = raw.get("expected_goals_conceded_per_90")
    defcon_raw = raw.get("defensive_contribution_per_90")
    xg_raw = raw.get("expected_goals_per_90")
    xa_raw = raw.get("expected_assists_per_90")
    chance_raw = raw.get("chance_of_playing_next_round")
    return PlayerGameweekStats(
        player_id=raw["id"],
        gameweek=gameweek,
        pulled_at=pulled_at,
        price=Decimal(raw["now_cost"]) / 10,
        form=Decimal(raw["form"]),
        ownership_pct=Decimal(raw["selected_by_percent"]),
        expected_goals_conceded_per_90=Decimal(str(xgc_raw)) if xgc_raw is not None else None,
        defensive_contribution_per_90=Decimal(str(defcon_raw)) if defcon_raw is not None else None,
        expected_goals_per_90=Decimal(str(xg_raw)) if xg_raw is not None else None,
        expected_assists_per_90=Decimal(str(xa_raw)) if xa_raw is not None else None,
        status=raw.get("status", "a") or "a",
        chance_of_playing_next_round=int(chance_raw) if chance_raw is not None else None,
        total_points=raw["total_points"],
        minutes=raw["minutes"],
    )


def map_fixture(raw: dict) -> Fixture:
    return Fixture(
        id=raw["id"],
        gameweek=raw["event"],
        team_h_id=raw["team_h"],
        team_a_id=raw["team_a"],
        team_h_difficulty=raw["team_h_difficulty"],
        team_a_difficulty=raw["team_a_difficulty"],
        team_h_score=raw.get("team_h_score"),
        team_a_score=raw.get("team_a_score"),
        finished=raw["finished"],
    )

from pydantic import BaseModel


class TemplatePlayerOut(BaseModel):
    id: int
    web_name: str
    position: str
    team_short_name: str
    ownership_pct: float | None
    classification: str  # "template" | "core" | "differential" | "unknown"


class PositionBreakdownOut(BaseModel):
    template: int = 0
    core: int = 0
    differential: int = 0
    unknown: int = 0


class TemplateComparisonOut(BaseModel):
    players: list[TemplatePlayerOut]
    divergence_score: float
    by_position: dict[str, PositionBreakdownOut]
    differentials: list[TemplatePlayerOut]
    template_picks: list[TemplatePlayerOut]

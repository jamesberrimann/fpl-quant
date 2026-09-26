from sqlalchemy import Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Fixture(Base):
    __tablename__ = "fixtures"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    gameweek: Mapped[int | None] = mapped_column(nullable=True)
    team_h_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    team_a_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    team_h_difficulty: Mapped[int] = mapped_column(nullable=False)
    team_a_difficulty: Mapped[int] = mapped_column(nullable=False)
    team_h_score: Mapped[int | None] = mapped_column(nullable=True)
    team_a_score: Mapped[int | None] = mapped_column(nullable=True)
    finished: Mapped[bool] = mapped_column(Boolean, nullable=False)

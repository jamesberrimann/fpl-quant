import enum
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base
from sqlalchemy import Enum as SQLEnum

class Position(enum.Enum):
    GKP = "GKP"
    DEF = "DEF"
    MID = "MID"
    FWD = "FWD"

DEFENSIVE_POSITIONS = frozenset({Position.GKP, Position.DEF})


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)

    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)

    first_name: Mapped[str] = mapped_column(nullable=False)
    second_name: Mapped[str] = mapped_column(nullable=False)
    web_name: Mapped[str] = mapped_column(nullable=False)

    position: Mapped[Position] = mapped_column(
        SQLEnum(Position, name="player_position"), nullable=False
    )

    team: Mapped["Team"] = relationship(back_populates="players")

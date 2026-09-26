from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)

    name: Mapped[str] = mapped_column(nullable=False)
    short_name: Mapped[str] = mapped_column(nullable=False)

    strength_overall_home: Mapped[int] = mapped_column(nullable=False)
    strength_overall_away: Mapped[int] = mapped_column(nullable=False)
    strength_attack_home: Mapped[int] = mapped_column(nullable=False)
    strength_attack_away: Mapped[int] = mapped_column(nullable=False)
    strength_defence_home: Mapped[int] = mapped_column(nullable=False)
    strength_defence_away: Mapped[int] = mapped_column(nullable=False)

    players: Mapped[list["Player"]] = relationship(back_populates="team")

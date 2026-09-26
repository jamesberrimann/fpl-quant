from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class PlayerGameweekStats(Base):
    __tablename__ = "player_gameweek_stats"

    __table_args__ = (
        Index("ix_player_gameweek_stats_player_id_gameweek", "player_id", "gameweek"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    gameweek: Mapped[int] = mapped_column(nullable=False)

    pulled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    price: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    form: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    ownership_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    expected_goals_conceded_per_90: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    defensive_contribution_per_90: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    expected_goals_per_90: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    expected_assists_per_90: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    # Per-GW deltas: difference between this snapshot and the previous GW snapshot.
    # Null for GW1, new signings mid-season, or when prev snapshot is missing.
    xg_this_gw_per_90: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    xa_this_gw_per_90: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    xgc_this_gw_per_90: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    # Actual minutes played this specific gameweek (0 = unused sub / absent).
    # Null only when the previous snapshot is unavailable (GW1 / new signing).
    minutes_this_gw: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(1), nullable=False, server_default="a", default="a")
    chance_of_playing_next_round: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    total_points: Mapped[int] = mapped_column(nullable=False)
    minutes: Mapped[int] = mapped_column(nullable=False)

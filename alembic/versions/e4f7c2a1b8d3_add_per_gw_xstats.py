"""add per-GW xstats columns

Revision ID: e4f7c2a1b8d3
Revises: b3e7f1a9d254
Create Date: 2026-09-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4f7c2a1b8d3'
down_revision: Union[str, Sequence[str], None] = 'b3e7f1a9d254'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('player_gameweek_stats', sa.Column('xg_this_gw_per_90', sa.Numeric(6, 2), nullable=True))
    op.add_column('player_gameweek_stats', sa.Column('xa_this_gw_per_90', sa.Numeric(6, 2), nullable=True))
    op.add_column('player_gameweek_stats', sa.Column('xgc_this_gw_per_90', sa.Numeric(6, 2), nullable=True))


def downgrade() -> None:
    op.drop_column('player_gameweek_stats', 'xgc_this_gw_per_90')
    op.drop_column('player_gameweek_stats', 'xa_this_gw_per_90')
    op.drop_column('player_gameweek_stats', 'xg_this_gw_per_90')

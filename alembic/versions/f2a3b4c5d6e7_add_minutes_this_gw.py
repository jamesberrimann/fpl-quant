"""add minutes_this_gw column

Revision ID: f2a3b4c5d6e7
Revises: e4f7c2a1b8d3
Create Date: 2026-09-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'e4f7c2a1b8d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('player_gameweek_stats', sa.Column('minutes_this_gw', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('player_gameweek_stats', 'minutes_this_gw')

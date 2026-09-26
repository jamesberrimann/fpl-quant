"""add player availability fields

Revision ID: b3e7f1a9d254
Revises: a4f8e2c91d37
Create Date: 2026-09-14 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3e7f1a9d254'
down_revision: Union[str, Sequence[str], None] = 'a4f8e2c91d37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'player_gameweek_stats',
        sa.Column('status', sa.String(1), nullable=False, server_default='a'),
    )
    op.add_column(
        'player_gameweek_stats',
        sa.Column('chance_of_playing_next_round', sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_column('player_gameweek_stats', 'chance_of_playing_next_round')
    op.drop_column('player_gameweek_stats', 'status')

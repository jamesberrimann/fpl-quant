"""add expected_assists_per_90

Revision ID: a4f8e2c91d37
Revises: f1f03911618e
Create Date: 2026-09-13 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a4f8e2c91d37'
down_revision: Union[str, Sequence[str], None] = 'f1f03911618e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'player_gameweek_stats',
        sa.Column('expected_assists_per_90', sa.Numeric(precision=6, scale=2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('player_gameweek_stats', 'expected_assists_per_90')

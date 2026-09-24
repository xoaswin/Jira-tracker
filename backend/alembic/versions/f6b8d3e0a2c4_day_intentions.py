"""day_intentions table

Revision ID: f6b8d3e0a2c4
Revises: e5a7c2d9f1b3
Create Date: 2026-09-24 10:30:00.000000

Adds the start-of-day plan store: one row per local date holding the user's
intended focus (free-text note + a list of Jira keys). Independent of sessions
so the plan persists even when no timer is running; the desktop check-in nudges
read it back.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6b8d3e0a2c4'
down_revision: Union[str, Sequence[str], None] = 'e5a7c2d9f1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'day_intentions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('plan_date', sa.String(), nullable=False),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('ticket_keys', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_day_intentions_plan_date', 'day_intentions', ['plan_date'], unique=True
    )


def downgrade() -> None:
    op.drop_index('ix_day_intentions_plan_date', table_name='day_intentions')
    op.drop_table('day_intentions')

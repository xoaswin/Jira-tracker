"""activity_segments table

Revision ID: d0f2b4c6e8a1
Revises: c9e1a3b5d7f0
Create Date: 2026-09-29 10:30:00.000000

Foreground-window activity recorded by the desktop app (local only): feeds
zero-click tracking, the day timeline and the focus radar.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd0f2b4c6e8a1'
down_revision: str | Sequence[str] | None = 'c9e1a3b5d7f0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'activity_segments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=False),
        sa.Column('app', sa.String(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('issue_key', sa.String(), nullable=True),
        sa.Column('key_source', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_activity_segments_started_at'), 'activity_segments', ['started_at'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_activity_segments_started_at'), table_name='activity_segments')
    op.drop_table('activity_segments')

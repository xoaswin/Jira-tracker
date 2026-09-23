"""settings work window + accountability

Revision ID: d4f6b1a2c8e9
Revises: c3e5a9b8d1f2
Create Date: 2026-09-21 10:00:00.000000

Adds the work-window and accountability settings that drive the daily-
completeness nudge and the recurring "what are you working on?" check-in.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f6b1a2c8e9'
down_revision: Union[str, Sequence[str], None] = 'c3e5a9b8d1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: work window + daily target + check-in interval."""
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('work_start_time', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('work_end_time', sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column('daily_target_hours', sa.Float(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column(
                'checkin_interval_minutes', sa.Integer(), nullable=False, server_default='0'
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('checkin_interval_minutes')
        batch_op.drop_column('daily_target_hours')
        batch_op.drop_column('work_end_time')
        batch_op.drop_column('work_start_time')

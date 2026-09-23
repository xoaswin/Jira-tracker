"""settings auto_actual_dates

Revision ID: e5a7c2d9f1b3
Revises: d4f6b1a2c8e9
Create Date: 2026-09-21 15:00:00.000000

Adds the opt-in that auto-stamps a ticket's actual start/end date fields from
the work session's dates on finish, so the user never hand-edits them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a7c2d9f1b3'
down_revision: Union[str, Sequence[str], None] = 'd4f6b1a2c8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'auto_actual_dates', sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('auto_actual_dates')

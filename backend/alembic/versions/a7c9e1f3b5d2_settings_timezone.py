"""settings timezone

Revision ID: a7c9e1f3b5d2
Revises: f6b8d3e0a2c4
Create Date: 2026-09-28 14:00:00.000000

Adds the user's working timezone (IANA name). Day buckets, "today", the work
window and check-ins follow it instead of the machine clock. Defaults to IST.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c9e1f3b5d2'
down_revision: Union[str, Sequence[str], None] = 'f6b8d3e0a2c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('timezone', sa.String(), nullable=False, server_default='Asia/Kolkata')
        )


def downgrade() -> None:
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('timezone')

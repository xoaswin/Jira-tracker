"""issue assignee display name

Revision ID: c3e5a9b8d1f2
Revises: b2d4f8a1c6e7
Create Date: 2026-09-18 09:00:00.000000

Stores the assignee's human-readable display name alongside the opaque account
id, so the "what are you working on" search can show WHO owns each ticket. The
account id stays for the "is this mine?" comparison against the connected user.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e5a9b8d1f2'
down_revision: Union[str, Sequence[str], None] = 'b2d4f8a1c6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add issues.assignee_name."""
    with op.batch_alter_table('issues', schema=None) as batch_op:
        batch_op.add_column(sa.Column('assignee_name', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('issues', schema=None) as batch_op:
        batch_op.drop_column('assignee_name')

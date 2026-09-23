"""phase5 settings issue_scope

Revision ID: b2d4f8a1c6e7
Revises: a1c2e9f7b3d4
Create Date: 2026-09-11 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2d4f8a1c6e7'
down_revision: Union[str, Sequence[str], None] = 'a1c2e9f7b3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: which issues to cache/search per board."""
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'issue_scope',
                sa.String(),
                nullable=False,
                server_default='open_on_board',
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('issue_scope')

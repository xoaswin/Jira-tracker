"""settings git_repo_paths + auto_track

Revision ID: c9e1a3b5d7f0
Revises: b8d0f2a4c6e1
Create Date: 2026-09-29 10:00:00.000000

Code folders editable in the app (the packaged desktop build has no .env) and
the zero-click tracking switch.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9e1a3b5d7f0'
down_revision: str | Sequence[str] | None = 'b8d0f2a4c6e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('git_repo_paths', sa.JSON(), nullable=False, server_default='[]')
        )
        batch_op.add_column(
            sa.Column('auto_track', sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('auto_track')
        batch_op.drop_column('git_repo_paths')

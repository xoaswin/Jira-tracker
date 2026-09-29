"""mobile_devices table

Revision ID: b8d0f2a4c6e1
Revises: a7c9e1f3b5d2
Create Date: 2026-09-28 20:00:00.000000

Paired phones for the mobile companion. Only a SHA-256 of each device token is
stored; the token itself only ever exists in the pairing QR and on the phone.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d0f2a4c6e1'
down_revision: str | Sequence[str] | None = 'a7c9e1f3b5d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'mobile_devices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('token_hash', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        sa.Column('user_agent', sa.String(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_mobile_devices_token_hash'), 'mobile_devices', ['token_hash'], unique=True
    )

def downgrade() -> None:
    op.drop_index(op.f('ix_mobile_devices_token_hash'), table_name='mobile_devices')
    op.drop_table('mobile_devices')

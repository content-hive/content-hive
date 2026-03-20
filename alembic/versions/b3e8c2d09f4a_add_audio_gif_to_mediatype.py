"""Add AUDIO and GIF to mediatype enum

Revision ID: b3e8c2d09f4a
Revises: a2517425d93c
Create Date: 2026-03-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e8c2d09f4a'
down_revision: Union[str, Sequence[str], None] = 'a2517425d93c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_ENUM = ('IMAGE', 'VIDEO', 'LIVEPHOTO')
_NEW_ENUM = ('IMAGE', 'VIDEO', 'LIVEPHOTO', 'AUDIO', 'GIF')


def upgrade() -> None:
    """Extend mediatype enum with AUDIO and GIF values."""
    with op.batch_alter_table('media', schema=None) as batch_op:
        batch_op.alter_column(
            'type',
            existing_type=sa.Enum(*_OLD_ENUM, name='mediatype'),
            type_=sa.Enum(*_NEW_ENUM, name='mediatype'),
            existing_nullable=True,
        )


def downgrade() -> None:
    """Revert mediatype enum to IMAGE, VIDEO, LIVEPHOTO only."""
    with op.batch_alter_table('media', schema=None) as batch_op:
        batch_op.alter_column(
            'type',
            existing_type=sa.Enum(*_NEW_ENUM, name='mediatype'),
            type_=sa.Enum(*_OLD_ENUM, name='mediatype'),
            existing_nullable=True,
        )

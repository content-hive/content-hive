"""Add url_fallbacks and cover_fallbacks to media

Revision ID: c1f8a3b2e947
Revises: 5d2da04c7dfd
Create Date: 2026-04-14 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1f8a3b2e947"
down_revision: str | Sequence[str] | None = "5d2da04c7dfd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add url_fallbacks and cover_fallbacks JSON columns to media table."""
    with op.batch_alter_table("media", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("url_fallbacks", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("cover_fallbacks", sa.JSON(), nullable=False, server_default="[]")
        )


def downgrade() -> None:
    """Remove url_fallbacks and cover_fallbacks columns from media table."""
    with op.batch_alter_table("media", schema=None) as batch_op:
        batch_op.drop_column("cover_fallbacks")
        batch_op.drop_column("url_fallbacks")

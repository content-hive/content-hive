"""Add avatar_path and banner_path columns to authors table.

Revision ID: d4c7e1a92f30
Revises: c1f8a3b2e947
Create Date: 2026-06-22 10:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4c7e1a92f30"
down_revision: str | Sequence[str] | None = "c1f8a3b2e947"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add avatar_path and banner_path columns to authors table."""
    with op.batch_alter_table("authors", schema=None) as batch_op:
        batch_op.add_column(sa.Column("avatar_path", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("banner_path", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove avatar_path and banner_path columns from authors table."""
    with op.batch_alter_table("authors", schema=None) as batch_op:
        batch_op.drop_column("banner_path")
        batch_op.drop_column("avatar_path")

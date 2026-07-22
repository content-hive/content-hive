"""Add tags JSON column on user_authors for per-user author tags.

Revision ID: d7e2a4b91c30
Revises: c5d9e1f82a14
Create Date: 2026-07-22 16:58:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e2a4b91c30"
down_revision: str | Sequence[str] | None = "c5d9e1f82a14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add tags column to user_authors."""
    with op.batch_alter_table("user_authors", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade() -> None:
    """Remove tags column from user_authors."""
    with op.batch_alter_table("user_authors", schema=None) as batch_op:
        batch_op.drop_column("tags")

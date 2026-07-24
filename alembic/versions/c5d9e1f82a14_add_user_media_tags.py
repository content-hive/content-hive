"""Add user_media table for per-user media tags.

Revision ID: c5d9e1f82a14
Revises: a8f4c2e91b07
Create Date: 2026-07-22 16:48:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from contenthive.database.orm_models import AwareDatetime

# revision identifiers, used by Alembic.
revision: str = "c5d9e1f82a14"
down_revision: str | Sequence[str] | None = "a8f4c2e91b07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create user_media table."""
    op.create_table(
        "user_media",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", AwareDatetime(), nullable=False),
        sa.Column("updated_at", AwareDatetime(), nullable=False),
        sa.Column("deleted_at", AwareDatetime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "media_id"),
    )
    with op.batch_alter_table("user_media", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_media_updated_at"), ["updated_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_user_media_deleted_at"), ["deleted_at"], unique=False)


def downgrade() -> None:
    """Drop user_media table."""
    with op.batch_alter_table("user_media", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_media_deleted_at"))
        batch_op.drop_index(batch_op.f("ix_user_media_updated_at"))

    op.drop_table("user_media")

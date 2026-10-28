"""Add tags table and tags JSON column on user_parse_results.

Revision ID: a8f4c2e91b07
Revises: f3a9c1d2e5b7
Create Date: 2026-07-22 16:22:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from contenthive.database.orm_models import AwareDatetime

# revision identifiers, used by Alembic.
revision: str = "a8f4c2e91b07"
down_revision: str | Sequence[str] | None = "f3a9c1d2e5b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create tags table and add tags column to user_parse_results."""
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", AwareDatetime(), nullable=False),
        sa.Column("updated_at", AwareDatetime(), nullable=False),
        sa.Column("deleted_at", AwareDatetime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_user_tag_name"),
    )
    with op.batch_alter_table("tags", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_tags_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_tags_updated_at"), ["updated_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_tags_deleted_at"), ["deleted_at"], unique=False)

    with op.batch_alter_table("user_parse_results", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade() -> None:
    """Drop tags column and tags table."""
    with op.batch_alter_table("user_parse_results", schema=None) as batch_op:
        batch_op.drop_column("tags")

    with op.batch_alter_table("tags", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tags_deleted_at"))
        batch_op.drop_index(batch_op.f("ix_tags_updated_at"))
        batch_op.drop_index(batch_op.f("ix_tags_user_id"))

    op.drop_table("tags")

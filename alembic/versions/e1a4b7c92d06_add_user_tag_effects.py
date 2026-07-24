"""Add user_tag_effects table for per-user tag display rules.

Revision ID: e1a4b7c92d06
Revises: d7e2a4b91c30
Create Date: 2026-07-24 15:35:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from contenthive.database.orm_models import AwareDatetime

# revision identifiers, used by Alembic.
revision: str = "e1a4b7c92d06"
down_revision: str | Sequence[str] | None = "d7e2a4b91c30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create user_tag_effects table."""
    op.create_table(
        "user_tag_effects",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("effect", sa.Enum("blur", "hide", name="tageffect"), nullable=False),
        sa.Column("created_at", AwareDatetime(), nullable=False),
        sa.Column("updated_at", AwareDatetime(), nullable=False),
        sa.Column("deleted_at", AwareDatetime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "tag_id", "effect"),
    )
    with op.batch_alter_table("user_tag_effects", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_tag_effects_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_user_tag_effects_updated_at"), ["updated_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_user_tag_effects_deleted_at"), ["deleted_at"], unique=False)


def downgrade() -> None:
    """Drop user_tag_effects table."""
    with op.batch_alter_table("user_tag_effects", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_tag_effects_deleted_at"))
        batch_op.drop_index(batch_op.f("ix_user_tag_effects_updated_at"))
        batch_op.drop_index(batch_op.f("ix_user_tag_effects_user_id"))

    op.drop_table("user_tag_effects")

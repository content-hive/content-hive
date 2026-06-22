"""Add AUTHOR_PROFILE_DOWNLOAD to tasktype enum

Revision ID: e7f2b1c94a08
Revises: d4c7e1a92f30
Create Date: 2026-06-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7f2b1c94a08"
down_revision: str | Sequence[str] | None = "d4c7e1a92f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_ENUM = ("PARSE_CONTENT", "MEDIA_DOWNLOAD", "CONTENT_ANALYSIS")
_NEW_ENUM = ("PARSE_CONTENT", "MEDIA_DOWNLOAD", "CONTENT_ANALYSIS", "AUTHOR_PROFILE_DOWNLOAD")


def upgrade() -> None:
    """Extend tasktype enum with AUTHOR_PROFILE_DOWNLOAD on main_tasks and sub_tasks."""
    with op.batch_alter_table("main_tasks", schema=None) as batch_op:
        batch_op.alter_column(
            "type",
            existing_type=sa.Enum(*_OLD_ENUM, name="tasktype"),
            type_=sa.Enum(*_NEW_ENUM, name="tasktype"),
            existing_nullable=False,
        )
    with op.batch_alter_table("sub_tasks", schema=None) as batch_op:
        batch_op.alter_column(
            "type",
            existing_type=sa.Enum(*_OLD_ENUM, name="tasktype"),
            type_=sa.Enum(*_NEW_ENUM, name="tasktype"),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Revert tasktype enum to values available before AUTHOR_PROFILE_DOWNLOAD."""
    with op.batch_alter_table("sub_tasks", schema=None) as batch_op:
        batch_op.alter_column(
            "type",
            existing_type=sa.Enum(*_NEW_ENUM, name="tasktype"),
            type_=sa.Enum(*_OLD_ENUM, name="tasktype"),
            existing_nullable=False,
        )
    with op.batch_alter_table("main_tasks", schema=None) as batch_op:
        batch_op.alter_column(
            "type",
            existing_type=sa.Enum(*_NEW_ENUM, name="tasktype"),
            type_=sa.Enum(*_OLD_ENUM, name="tasktype"),
            existing_nullable=False,
        )

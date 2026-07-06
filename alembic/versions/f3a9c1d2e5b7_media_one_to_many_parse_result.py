"""Media one-to-many with parse result

Convert ParseResult <-> Media from many-to-many (parse_result_media join table
plus a global unique media.url) to a one-to-many relationship where each media
row is owned by a single parse result.

Revision ID: f3a9c1d2e5b7
Revises: e7f2b1c94a08
Create Date: 2026-07-06 17:40:00.000000

"""

from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a9c1d2e5b7"
down_revision: str | Sequence[str] | None = "e7f2b1c94a08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Naming convention so SQLite batch mode can drop the original unnamed
# UNIQUE(url) constraint by a deterministic name.
_NAMING_CONVENTION = {"uq": "uq_%(table_name)s_%(column_0_name)s"}

# Media columns copied verbatim when duplicating a shared media row.
_COPYABLE_COLUMNS = (
    "url",
    "type",
    "title",
    "duration",
    "width",
    "height",
    "cover",
    "url_fallbacks",
    "cover_fallbacks",
    "media_path",
    "cover_path",
    "status",
    "created_at",
    "updated_at",
    "deleted_at",
)


def upgrade() -> None:
    """Attach media rows to a single parse result and drop the join table."""
    conn = op.get_bind()

    # 1. Add the new columns as nullable and drop the global UNIQUE(url) so that
    #    shared media rows can be duplicated during backfill without collisions.
    with op.batch_alter_table("media", schema=None, naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.add_column(sa.Column("parse_result_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("order", sa.Integer(), nullable=False, server_default="0"))
        batch_op.drop_constraint("uq_media_url", type_="unique")

    # 2. Backfill from parse_result_media.
    #    A media row shared by multiple parse results is duplicated so that each
    #    parse result owns its own copy (no data loss).
    assoc_rows = conn.execute(sa.text('SELECT parse_result_id, media_id, "order" FROM parse_result_media')).fetchall()

    assocs_by_media: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for parse_result_id, media_id, order in assoc_rows:
        assocs_by_media[media_id].append((parse_result_id, order))

    copy_cols = ", ".join(f'"{c}"' if c == "order" else c for c in _COPYABLE_COLUMNS)
    for media_id, assocs in assocs_by_media.items():
        first_pr, first_order = assocs[0]
        conn.execute(
            sa.text('UPDATE media SET parse_result_id = :pr, "order" = :o WHERE id = :mid'),
            {"pr": first_pr, "o": first_order, "mid": media_id},
        )
        for parse_result_id, order in assocs[1:]:
            conn.execute(
                sa.text(
                    f'INSERT INTO media (parse_result_id, "order", {copy_cols}) '
                    f"SELECT :pr, :o, {copy_cols} FROM media WHERE id = :mid"
                ),
                {"pr": parse_result_id, "o": order, "mid": media_id},
            )

    # 3. Remove any media rows that were never associated with a parse result.
    conn.execute(sa.text("DELETE FROM media WHERE parse_result_id IS NULL"))

    # 4. Finalize constraints: NOT NULL, FK, composite unique, index.
    with op.batch_alter_table("media", schema=None) as batch_op:
        batch_op.alter_column(
            "order",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=None,
        )
        batch_op.alter_column("parse_result_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_unique_constraint("uq_parse_result_url", ["parse_result_id", "url"])
        batch_op.create_foreign_key(
            "fk_media_parse_result_id",
            "parse_results",
            ["parse_result_id"],
            ["id"],
        )

    # 5. Drop the now-unused join table.
    op.drop_table("parse_result_media")


def downgrade() -> None:
    """Restore the many-to-many join table and global unique media.url."""
    conn = op.get_bind()

    # 1. Recreate the join table.
    op.create_table(
        "parse_result_media",
        sa.Column("parse_result_id", sa.Integer(), nullable=False),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parse_result_id"], ["parse_results.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("parse_result_id", "media_id"),
    )

    # 2. Populate associations from the owned media rows.
    conn.execute(
        sa.text(
            'INSERT INTO parse_result_media (parse_result_id, media_id, "order") '
            'SELECT parse_result_id, id, "order" FROM media'
        )
    )

    # 3. Collapse duplicate-url media rows so global UNIQUE(url) can be restored.
    #    Keep the lowest id per url, repoint associations, delete the duplicates.
    dup_rows = conn.execute(sa.text("SELECT url, MIN(id) FROM media GROUP BY url")).fetchall()
    for url, keep_id in dup_rows:
        conn.execute(
            sa.text(
                "UPDATE parse_result_media SET media_id = :keep "
                "WHERE media_id IN (SELECT id FROM media WHERE url = :url AND id != :keep)"
            ),
            {"keep": keep_id, "url": url},
        )
        conn.execute(
            sa.text("DELETE FROM media WHERE url = :url AND id != :keep"),
            {"url": url, "keep": keep_id},
        )

    # 4. Drop the one-to-many columns/constraints and restore the global url unique.
    #    Dropping parse_result_id also removes its FK during table rebuild.
    with op.batch_alter_table("media", schema=None, naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("uq_parse_result_url", type_="unique")
        batch_op.create_unique_constraint("uq_media_url", ["url"])
        batch_op.drop_column("order")
        batch_op.drop_column("parse_result_id")

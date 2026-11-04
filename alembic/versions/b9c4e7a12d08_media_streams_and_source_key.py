"""Replace media URL columns with source_key and streams JSON.

Revision ID: b9c4e7a12d08
Revises: f8b2c4d61e09
Create Date: 2026-11-04 00:00:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b9c4e7a12d08"
down_revision: str | Sequence[str] | None = "f8b2c4d61e09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _as_list(value: object) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
    return []


def _stream(role: str, url: str, fallbacks: list[str]) -> dict:
    return {"role": role, "urls": [url, *fallbacks] if url else fallbacks}


def _normalize_media_type(media_type: object) -> str | None:
    """SQLAlchemy Enum persists names (IMAGE); comparisons use values (image)."""
    if media_type is None:
        return None
    text = str(media_type).strip().lower()
    return text or None


def _migrate_streams(
    media_type: str | None,
    url: str,
    cover: str | None,
    url_fallbacks: list[str],
    cover_fallbacks: list[str],
) -> list[dict]:
    media_type = _normalize_media_type(media_type)
    cover_stream_role = "image" if media_type == "livephoto" else "cover"
    if media_type in ("image", "gif"):
        return [_stream("image", url, url_fallbacks)]
    if media_type == "audio":
        streams = [_stream("audio", url, url_fallbacks)]
    elif media_type == "livephoto":
        streams = [_stream("video", url, url_fallbacks)]
    elif media_type == "link":
        streams = [_stream("link", url, url_fallbacks)]
    else:
        streams = [_stream("video", url, url_fallbacks)]
    if cover:
        streams.append(_stream(cover_stream_role, cover, cover_fallbacks))
    return streams


def upgrade() -> None:
    """Move remote URLs into streams JSON and key rows by source_key."""
    with op.batch_alter_table("media", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_key", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("streams", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("extra", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("media_duration", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("media_width", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("media_height", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("cover_width", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("cover_height", sa.Integer(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, url, type, cover, url_fallbacks, cover_fallbacks, duration, width, height FROM media")
    ).fetchall()
    for row in rows:
        media_id, url, media_type, cover, url_fallbacks, cover_fallbacks, duration, width, height = row
        streams = _migrate_streams(
            media_type,
            url,
            cover,
            _as_list(url_fallbacks),
            _as_list(cover_fallbacks),
        )
        conn.execute(
            sa.text(
                "UPDATE media SET source_key = :source_key, streams = :streams, extra = :extra, "
                "media_duration = :media_duration, media_width = :media_width, media_height = :media_height, "
                "cover_width = :cover_width, cover_height = :cover_height WHERE id = :id"
            ),
            {
                "id": media_id,
                "source_key": url,
                "streams": json.dumps(streams),
                "extra": json.dumps({}),
                "media_duration": duration,
                "media_width": width,
                "media_height": height,
                "cover_width": width,
                "cover_height": height,
            },
        )

    with op.batch_alter_table("media", schema=None) as batch_op:
        batch_op.alter_column("source_key", existing_type=sa.String(), nullable=False)
        batch_op.alter_column("streams", existing_type=sa.JSON(), nullable=False, server_default="[]")
        batch_op.alter_column("extra", existing_type=sa.JSON(), nullable=False, server_default="{}")
        batch_op.drop_constraint("uq_parse_result_url", type_="unique")
        batch_op.create_unique_constraint("uq_parse_result_source_key", ["parse_result_id", "source_key"])
        batch_op.drop_column("url")
        batch_op.drop_column("url_fallbacks")
        batch_op.drop_column("cover")
        batch_op.drop_column("cover_fallbacks")
        batch_op.drop_column("duration")
        batch_op.drop_column("width")
        batch_op.drop_column("height")


def downgrade() -> None:
    """Restore url/cover columns from the first stream and optional cover/still."""
    with op.batch_alter_table("media", schema=None) as batch_op:
        batch_op.add_column(sa.Column("url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("url_fallbacks", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("cover", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("cover_fallbacks", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("duration", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("width", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("height", sa.Integer(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, type, streams, media_duration, media_width, media_height FROM media")
    ).fetchall()
    for row in rows:
        media_id, media_type, streams_raw, duration, width, height = row
        streams = streams_raw
        if isinstance(streams_raw, str):
            try:
                streams = json.loads(streams_raw)
            except json.JSONDecodeError:
                streams = []
        if not isinstance(streams, list):
            streams = []
        primary = next((item for item in streams if isinstance(item, dict) and item.get("role") != "cover"), None)
        cover_role = "image" if media_type == "livephoto" else "cover"
        cover_item = next(
            (item for item in streams if isinstance(item, dict) and item.get("role") == cover_role),
            None,
        )
        primary_urls = _as_list((primary or {}).get("urls"))
        cover_urls = _as_list((cover_item or {}).get("urls"))
        conn.execute(
            sa.text(
                "UPDATE media SET url = :url, url_fallbacks = :url_fallbacks, cover = :cover, "
                "cover_fallbacks = :cover_fallbacks, duration = :duration, width = :width, height = :height "
                "WHERE id = :id"
            ),
            {
                "id": media_id,
                "url": primary_urls[0] if primary_urls else "",
                "url_fallbacks": json.dumps(primary_urls[1:]),
                "cover": cover_urls[0] if cover_urls else None,
                "cover_fallbacks": json.dumps(cover_urls[1:]),
                "duration": duration,
                "width": width,
                "height": height,
            },
        )

    with op.batch_alter_table("media", schema=None) as batch_op:
        batch_op.alter_column("url", existing_type=sa.String(), nullable=False)
        batch_op.alter_column("url_fallbacks", existing_type=sa.JSON(), nullable=False, server_default="[]")
        batch_op.alter_column("cover_fallbacks", existing_type=sa.JSON(), nullable=False, server_default="[]")
        batch_op.drop_constraint("uq_parse_result_source_key", type_="unique")
        batch_op.create_unique_constraint("uq_parse_result_url", ["parse_result_id", "url"])
        batch_op.drop_column("source_key")
        batch_op.drop_column("streams")
        batch_op.drop_column("extra")
        batch_op.drop_column("media_duration")
        batch_op.drop_column("media_width")
        batch_op.drop_column("media_height")
        batch_op.drop_column("cover_width")
        batch_op.drop_column("cover_height")

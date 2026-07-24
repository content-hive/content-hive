"""Models for per-user tag vocabulary and assignments."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from contenthive.database.orm_models import Tag
from contenthive.models.api import APIBaseModel


@dataclass
class TagEntity:
    """Tag database entity (per-user vocabulary)"""

    id: int | None = None
    user_id: int = 0
    name: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None

    @classmethod
    def from_orm(cls, orm: Tag) -> "TagEntity":
        """Convert ORM Tag object to entity"""
        return cls(
            id=orm.id,
            user_id=orm.user_id,
            name=orm.name,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            deleted_at=orm.deleted_at,
        )


class TagInfo(APIBaseModel):
    """Tag information returned by the API"""

    id: int = Field(..., description="Tag ID")
    name: str = Field(..., description="Tag name")
    created_at: datetime = Field(..., description="Database creation timestamp")
    updated_at: datetime = Field(..., description="Database update timestamp")
    deleted_at: datetime | None = Field(None, description="Deletion timestamp (null if not deleted)")

    @classmethod
    def from_entity(cls, entity: TagEntity) -> "TagInfo":
        """Create TagInfo from TagEntity"""
        return cls(
            id=entity.id if entity.id else 0,
            name=entity.name,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            deleted_at=entity.deleted_at,
        )


class SyncTagInfo(TagInfo):
    """Tag vocabulary row for incremental sync (includes soft-deleted rows)."""


class CreateTagRequest(APIBaseModel):
    """Create a tag in the user's vocabulary (does not attach to content)"""

    name: str = Field(..., min_length=1, description="Tag name")


class UpdateTagRequest(APIBaseModel):
    """Rename a tag"""

    name: str = Field(..., min_length=1, description="New tag name")


class TagAssignmentRequest(APIBaseModel):
    """Assign tags to content, media, or author (upsert by name for replace/add)"""

    target: Literal["content", "media", "author"] = Field(
        ...,
        description="Assignment target type",
    )
    id: int = Field(..., description="Target ID (parse_result_id, media_id, or author_id)")
    names: list[str] = Field(default_factory=list, description="Tag names (upserted for replace/add)")
    tag_ids: list[int] = Field(default_factory=list, description="Tag IDs to remove (remove mode)")

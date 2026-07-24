"""Models for per-user tag vocabulary and assignments."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from contenthive.database.orm_models import Tag, UserTagEffect
from contenthive.models.api import APIBaseModel
from contenthive.models.enumerates import TagEffect


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


@dataclass
class TagEffectEntity:
    """Per-user tag display effect entity"""

    user_id: int = 0
    tag_id: int = 0
    effect: TagEffect = TagEffect.BLUR
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_orm(cls, orm: UserTagEffect) -> "TagEffectEntity":
        """Convert ORM UserTagEffect to entity"""
        return cls(
            user_id=orm.user_id,
            tag_id=orm.tag_id,
            effect=orm.effect,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
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


class TagEffectInfo(APIBaseModel):
    """One display effect assigned to a tag (a tag may have multiple rows)."""

    tag_id: int = Field(..., description="Tag ID")
    effect: TagEffect = Field(..., description="Display effect (blur or hide)")
    created_at: datetime = Field(..., description="Database creation timestamp")
    updated_at: datetime = Field(..., description="Database update timestamp")

    @classmethod
    def from_entity(cls, entity: TagEffectEntity) -> "TagEffectInfo":
        """Create TagEffectInfo from TagEffectEntity"""
        return cls(
            tag_id=entity.tag_id,
            effect=entity.effect,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )


class CreateTagRequest(APIBaseModel):
    """Create a tag in the user's vocabulary (does not attach to content)"""

    name: str = Field(..., min_length=1, description="Tag name")


class UpdateTagRequest(APIBaseModel):
    """Rename a tag"""

    name: str = Field(..., min_length=1, description="New tag name")


class UpsertTagEffectRequest(APIBaseModel):
    """Add a display effect to a tag (does not remove other effects on the same tag)"""

    effect: TagEffect = Field(..., description="Display effect to add (blur or hide)")


class TagEffectItem(APIBaseModel):
    """One tag-effect pair for bulk replace"""

    tag_id: int = Field(..., description="Tag ID")
    effect: TagEffect = Field(..., description="Display effect (blur or hide)")


class ReplaceTagEffectsRequest(APIBaseModel):
    """Replace all tag effects for the current user"""

    items: list[TagEffectItem] = Field(
        default_factory=list,
        description="Full effect list after replace (same tag_id may appear with multiple effects)",
    )


class TagAssignmentRequest(APIBaseModel):
    """Assign tags to content, media, or author (upsert by name for replace/add)"""

    target: Literal["content", "media", "author"] = Field(
        ...,
        description="Assignment target type",
    )
    id: int = Field(..., description="Target ID (parse_result_id, media_id, or author_id)")
    names: list[str] = Field(default_factory=list, description="Tag names (upserted for replace/add)")
    tag_ids: list[int] = Field(default_factory=list, description="Tag IDs to remove (remove mode)")

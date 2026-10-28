"""
Models for content-related operations.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field, HttpUrl

from contenthive.database.orm_models import Author, Media, ParseResult, Platform
from contenthive.models.api import APIBaseModel
from contenthive.models.enumerates import MediaStatus, MediaType, ParserResultStatus
from contenthive.models.tag import TagEntity, TagInfo
from contenthive.utils.sidecar import SIDECAR_SCHEMA_VERSION

# Database Models


@dataclass
class PlatformEntity:
    """Platform database entity"""

    id: int | None = None
    code: str = ""
    name: str = ""
    url: str = ""
    icon_url: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None

    @classmethod
    def from_orm(cls, orm: Platform) -> "PlatformEntity":
        """Convert ORM Platform object to entity"""
        return PlatformEntity(
            id=orm.id,
            code=orm.code,
            name=orm.name,
            url=orm.url,
            icon_url=orm.icon_url,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            deleted_at=orm.deleted_at,
        )


@dataclass
class AuthorEntity:
    """Author database entity"""

    id: int | None = None
    platform_id: int = 0
    uid: str = ""
    name: str | None = None
    username: str = ""
    avatar: str | None = None
    avatar_path: str | None = None
    url: str | None = None
    banner: str | None = None
    banner_path: str | None = None
    description: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None

    platform: PlatformEntity = field(default_factory=PlatformEntity)
    # Per-user tags resolved for the requesting user (not stored on authors)
    tags: list[TagEntity] = field(default_factory=list)
    # Sync path: raw tag IDs without resolving vocabulary rows
    tag_ids: list[int] = field(default_factory=list)

    @classmethod
    def from_orm(cls, orm: Author, tags: list[TagEntity] | None = None) -> "AuthorEntity":
        """Convert ORM Author object to entity"""

        if orm.platform is None:
            # Author's platform information is missing, cannot convert to AuthorEntity
            raise ValueError(f"Author ORM object (id={orm.id}) has no associated platform")

        return cls(
            id=orm.id,
            platform_id=orm.platform_id,
            uid=orm.uid,
            name=orm.name,
            username=orm.username,
            avatar=orm.avatar,
            avatar_path=orm.avatar_path,
            url=orm.url,
            banner=orm.banner,
            banner_path=orm.banner_path,
            description=orm.description,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            deleted_at=orm.deleted_at,
            platform=PlatformEntity.from_orm(orm.platform),
            tags=tags or [],
        )


@dataclass
class MediaEntity:
    """Media database entity"""

    id: int | None = None
    status: MediaStatus = MediaStatus.PENDING
    url: str = ""
    type: MediaType | None = None
    title: str | None = None
    cover: str | None = None
    url_fallbacks: list[str] = field(default_factory=list)
    cover_fallbacks: list[str] = field(default_factory=list)
    duration: int | None = None
    width: int | None = None
    height: int | None = None
    media_path: str | None = None
    cover_path: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None
    # Per-user tags resolved for the requesting user (not stored on media)
    tags: list[TagEntity] = field(default_factory=list)
    # Sync path: raw tag IDs without resolving vocabulary rows
    tag_ids: list[int] = field(default_factory=list)

    @classmethod
    def from_orm(cls, orm: Media, tags: list[TagEntity] | None = None) -> "MediaEntity":
        """Convert ORM Media object to entity"""
        return cls(
            id=orm.id,
            status=orm.status,
            url=orm.url,
            type=orm.type,
            title=orm.title,
            cover=orm.cover,
            url_fallbacks=orm.url_fallbacks or [],
            cover_fallbacks=orm.cover_fallbacks or [],
            duration=orm.duration,
            width=orm.width,
            height=orm.height,
            media_path=orm.media_path,
            cover_path=orm.cover_path,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            deleted_at=orm.deleted_at,
            tags=tags or [],
        )


@dataclass
class ParseResultEntity:
    """Parse result database entity"""

    id: int | None = None
    pid: str = ""
    url: str = ""
    title: str | None = None
    content: str | None = None
    author_id: int = 0
    platform_id: int = 0
    post_time: int | None = None
    parser: str = ""
    state: ParserResultStatus = ParserResultStatus.SUCCESS
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None

    # Related entities (for joins) - must not be None
    author: AuthorEntity = field(default_factory=AuthorEntity)
    platform: PlatformEntity = field(default_factory=PlatformEntity)
    media: list[MediaEntity] = field(default_factory=list)
    # Per-user tags resolved for the requesting user (not stored on parse_results)
    tags: list[TagEntity] = field(default_factory=list)
    # Sync path: raw tag IDs without resolving vocabulary rows
    tag_ids: list[int] = field(default_factory=list)

    @classmethod
    def from_orm(cls, orm: ParseResult, tags: list[TagEntity] | None = None) -> "ParseResultEntity":
        """Convert ORM ParseResult object to entity"""

        if orm.author is None:
            raise ValueError(f"ParseResult ORM object (id={orm.id}) has no associated author")

        if orm.platform is None:
            raise ValueError(f"ParseResult ORM object (id={orm.id}) has no associated platform")

        return cls(
            id=orm.id,
            pid=orm.pid,
            url=orm.url,
            title=orm.title,
            content=orm.content,
            author_id=orm.author_id,
            platform_id=orm.platform_id,
            post_time=orm.post_time,
            parser=orm.parser,
            state=orm.state,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            deleted_at=orm.deleted_at,
            author=AuthorEntity.from_orm(orm.author),
            platform=PlatformEntity.from_orm(orm.platform),
            media=[MediaEntity.from_orm(m) for m in orm.media] if orm.media else [],
            tags=tags or [],
        )


# Service Models


class SidecarPlatformInfo(APIBaseModel):
    """Platform block embedded in metadata sidecar files."""

    code: str = Field(..., description="Platform code")
    name: str = Field(..., description="Platform name")
    url: str = Field(..., description="Platform URL")
    icon_url: str | None = Field(None, description="Platform icon URL")

    @classmethod
    def from_entity(cls, entity: PlatformEntity) -> "SidecarPlatformInfo":
        """Create SidecarPlatformInfo from PlatformEntity."""
        return cls(
            code=entity.code,
            name=entity.name,
            url=entity.url,
            icon_url=entity.icon_url,
        )


class SidecarAuthorInfo(APIBaseModel):
    """Author block embedded in content metadata sidecar files."""

    uid: str = Field(..., description="Author uid on the platform")
    name: str | None = Field(None, description="Author display name")
    username: str = Field(..., description="Author username")
    avatar: str | None = Field(None, description="Remote avatar URL")
    url: str | None = Field(None, description="Author profile URL")
    banner: str | None = Field(None, description="Remote banner URL")
    description: str | None = Field(None, description="Author description")

    @classmethod
    def from_entity(cls, entity: AuthorEntity) -> "SidecarAuthorInfo":
        """Create SidecarAuthorInfo from AuthorEntity."""
        return cls(
            uid=entity.uid,
            name=entity.name,
            username=entity.username,
            avatar=entity.avatar,
            url=entity.url,
            banner=entity.banner,
            description=entity.description,
        )


class SidecarMediaInfo(APIBaseModel):
    """Media item block embedded in content metadata sidecar files."""

    order: int = Field(..., description="Display order within the content")
    id: int = Field(..., description="Media database ID")
    status: MediaStatus = Field(..., description="Download status")
    url: str = Field(..., description="Original media URL")
    type: MediaType | None = Field(None, description="Media type")
    title: str | None = Field(None, description="Media title")
    cover: str | None = Field(None, description="Original cover URL")
    url_fallbacks: list[str] = Field(default_factory=list, description="Fallback media URLs")
    cover_fallbacks: list[str] = Field(default_factory=list, description="Fallback cover URLs")
    duration: int | None = Field(None, description="Video duration in seconds")
    width: int | None = Field(None, description="Media width in pixels")
    height: int | None = Field(None, description="Media height in pixels")
    media_path: str | None = Field(None, description="Local media file path")
    cover_path: str | None = Field(None, description="Local cover file path")

    @classmethod
    def from_entity(cls, entity: MediaEntity, order: int) -> "SidecarMediaInfo":
        """Create SidecarMediaInfo from MediaEntity."""
        return cls(
            order=order,
            id=entity.id if entity.id else 0,
            status=entity.status,
            url=entity.url,
            type=entity.type,
            title=entity.title,
            cover=entity.cover,
            url_fallbacks=entity.url_fallbacks,
            cover_fallbacks=entity.cover_fallbacks,
            duration=entity.duration,
            width=entity.width,
            height=entity.height,
            media_path=entity.media_path,
            cover_path=entity.cover_path,
        )


class ContentSidecar(APIBaseModel):
    """On-disk metadata for a single parsed content item."""

    schema_version: int = Field(default=SIDECAR_SCHEMA_VERSION, description="Sidecar schema version")
    updated_at: datetime = Field(..., description="Last sync timestamp")
    id: int = Field(..., description="Parse result database ID")
    pid: str = Field(..., description="Platform content ID")
    url: str = Field(..., description="Source content URL")
    title: str | None = Field(None, description="Content title")
    content: str | None = Field(None, description="Content text")
    post_time: int | None = Field(None, description="Post timestamp in seconds since epoch")
    parser: str = Field(..., description="Parser plugin domain")
    state: ParserResultStatus = Field(..., description="Parsing state")
    platform: SidecarPlatformInfo = Field(..., description="Platform information")
    author: SidecarAuthorInfo = Field(..., description="Author information")
    media: list[SidecarMediaInfo] = Field(default_factory=list, description="Media items")

    @classmethod
    def from_entity(cls, entity: ParseResultEntity) -> "ContentSidecar":
        """Create ContentSidecar from ParseResultEntity."""
        return cls(
            updated_at=datetime.now(UTC),
            id=entity.id if entity.id else 0,
            pid=entity.pid,
            url=entity.url,
            title=entity.title,
            content=entity.content,
            post_time=entity.post_time,
            parser=entity.parser,
            state=entity.state,
            platform=SidecarPlatformInfo.from_entity(entity.platform),
            author=SidecarAuthorInfo.from_entity(entity.author),
            media=[SidecarMediaInfo.from_entity(media, order) for order, media in enumerate(entity.media)],
        )


class AuthorSidecar(SidecarAuthorInfo):
    """On-disk metadata for an author directory."""

    schema_version: int = Field(default=SIDECAR_SCHEMA_VERSION, description="Sidecar schema version")
    updated_at: datetime = Field(..., description="Last sync timestamp")
    id: int = Field(..., description="Author database ID")
    avatar_path: str | None = Field(None, description="Local avatar path served under /media")
    banner_path: str | None = Field(None, description="Local banner path served under /media")
    platform: SidecarPlatformInfo = Field(..., description="Platform information")

    @classmethod
    def from_entity(cls, entity: AuthorEntity) -> "AuthorSidecar":
        """Create AuthorSidecar from AuthorEntity."""
        return cls(
            **SidecarAuthorInfo.from_entity(entity).model_dump(),
            updated_at=datetime.now(UTC),
            id=entity.id if entity.id else 0,
            avatar_path=entity.avatar_path,
            banner_path=entity.banner_path,
            platform=SidecarPlatformInfo.from_entity(entity.platform),
        )


class DownloadedMediaInfo(BaseModel):
    """Information about downloaded media file"""

    status: MediaStatus = Field(..., description="Download status: pending, downloading, completed, failed")
    url: str = Field(..., description="Original media URL")
    type: MediaType | None = Field(None, description="Media type")
    title: str | None = Field(None, description="Media title")
    cover: str | None = Field(None, description="Original video cover URL")
    url_fallbacks: list[str] = Field(default_factory=list, description="Fallback media URLs")
    cover_fallbacks: list[str] = Field(default_factory=list, description="Fallback cover URLs")
    duration: int | None = Field(None, description="Video duration in seconds")
    width: int | None = Field(None, description="Media width in pixels")
    height: int | None = Field(None, description="Media height in pixels")
    media_path: str | None = Field(None, description="Local media file path")
    cover_path: str | None = Field(None, description="Local cover file path")


# API Response Models


class PaginationInfo(APIBaseModel):
    """Pagination metadata"""

    page: int = Field(..., description="Current page number", ge=1)
    page_size: int = Field(..., description="Items per page", ge=1)
    total: int = Field(..., description="Total number of items", ge=0)
    total_pages: int = Field(..., description="Total number of pages", ge=0)


class PaginatedResponse[T](APIBaseModel):
    """Paginated response model"""

    items: list[T] = Field(..., description="List of items")
    pagination: PaginationInfo = Field(..., description="Pagination information")


class SyncResponse[T](APIBaseModel):
    """Sync response model with server timestamp"""

    items: list[T] = Field(..., description="List of items")
    pagination: PaginationInfo = Field(..., description="Pagination information")
    sync_timestamp: datetime = Field(
        ...,
        description="Server timestamp for this sync operation (use this for next sync)",
    )


class MediaInfo(APIBaseModel):
    """Stored media item model (with local paths)"""

    id: int = Field(..., description="Media ID")
    status: MediaStatus = Field(..., description="Download status: pending, downloading, completed, failed")
    url: HttpUrl = Field(..., description="Original media URL")
    type: MediaType | None = Field(None, description="Media type")
    title: str | None = Field(None, description="Media title")
    duration: int | None = Field(None, description="Video duration in seconds")
    width: int | None = Field(None, description="Media width in pixels")
    height: int | None = Field(None, description="Media height in pixels")
    cover: HttpUrl | None = Field(None, description="Original video cover URL")
    url_fallbacks: list[HttpUrl] = Field(default_factory=list, description="Fallback media URLs")
    cover_fallbacks: list[HttpUrl] = Field(default_factory=list, description="Fallback cover URLs")
    media_path: str | None = Field(None, description="Local media file path")
    cover_path: str | None = Field(None, description="Local cover file path")
    tags: list[TagInfo] = Field(default_factory=list, description="Per-user tags on this media item")
    created_at: datetime = Field(..., description="Database creation timestamp")
    updated_at: datetime = Field(..., description="Database update timestamp")
    deleted_at: datetime | None = Field(None, description="Deletion timestamp (null if not deleted)")

    @classmethod
    def from_entity(cls, entity: MediaEntity) -> "MediaInfo":
        """Create MediaInfo from MediaEntity"""
        return cls(
            id=entity.id if entity.id else 0,
            status=entity.status,
            url=entity.url,  # type: ignore
            type=entity.type,
            title=entity.title,
            duration=entity.duration,
            width=entity.width,
            height=entity.height,
            cover=entity.cover,  # type: ignore
            url_fallbacks=entity.url_fallbacks,  # type: ignore
            cover_fallbacks=entity.cover_fallbacks,  # type: ignore
            media_path=entity.media_path,
            cover_path=entity.cover_path,
            tags=[TagInfo.from_entity(tag) for tag in entity.tags],
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            deleted_at=entity.deleted_at,
        )


class PlatformInfo(APIBaseModel):
    """Platform information model (with database ID)"""

    id: int = Field(..., description="Platform ID")
    name: str = Field(..., description="Platform name")
    code: str = Field(..., description="Platform code")
    url: HttpUrl = Field(..., description="Platform URL")
    icon_url: HttpUrl | None = Field(None, description="Platform icon URL")
    created_at: datetime = Field(..., description="Database creation timestamp")
    updated_at: datetime = Field(..., description="Database update timestamp")
    deleted_at: datetime | None = Field(None, description="Deletion timestamp (null if not deleted)")

    @classmethod
    def from_entity(cls, entity: PlatformEntity) -> "PlatformInfo":
        """Create PlatformInfo from PlatformEntity"""
        return cls(
            id=entity.id if entity.id else 0,
            name=entity.name,
            code=entity.code,
            url=entity.url,  # type: ignore
            icon_url=entity.icon_url,  # type: ignore
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            deleted_at=entity.deleted_at,
        )


class AuthorInfo(APIBaseModel):
    """Author information model (with database ID)"""

    id: int = Field(..., description="Author ID")
    uid: str = Field(..., description="User ID")
    name: str | None = Field(None, description="Author name")
    username: str = Field(..., description="Username")
    avatar: HttpUrl | None = Field(None, description="Avatar URL")
    avatar_path: str | None = Field(None, description="Local avatar path served under /media")
    url: HttpUrl | None = Field(None, description="Author profile URL")
    banner: HttpUrl | None = Field(None, description="Author banner URL")
    banner_path: str | None = Field(None, description="Local banner path served under /media")
    description: str | None = Field(None, description="Author description")
    platform: PlatformInfo = Field(..., description="Platform information")
    tags: list[TagInfo] = Field(default_factory=list, description="Per-user tags on this author")
    created_at: datetime = Field(..., description="Database creation timestamp")
    updated_at: datetime = Field(..., description="Database update timestamp")
    deleted_at: datetime | None = Field(None, description="Deletion timestamp (null if not deleted)")

    @classmethod
    def from_entity(cls, entity: AuthorEntity) -> "AuthorInfo":
        """Create AuthorInfo from AuthorEntity"""
        return cls(
            id=entity.id if entity.id else 0,
            uid=entity.uid,
            name=entity.name,
            username=entity.username,
            avatar=entity.avatar,  # type: ignore
            avatar_path=entity.avatar_path,
            url=entity.url,  # type: ignore
            banner=entity.banner,  # type: ignore
            banner_path=entity.banner_path,
            description=entity.description,
            platform=PlatformInfo.from_entity(entity.platform),
            tags=[TagInfo.from_entity(tag) for tag in entity.tags],
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            deleted_at=entity.deleted_at,
        )


class URLParserResult(APIBaseModel):
    """API response model for stored content (with downloaded media)"""

    id: int = Field(..., description="Parser result ID")
    pid: str = Field(..., description="Content ID")
    url: HttpUrl = Field(..., description="The URL that was fetched")
    title: str | None = Field(None, description="Content title")
    content: str | None = Field(None, description="Content text")
    media: list[MediaInfo] = Field(default_factory=list, description="List of stored media items")
    author: AuthorInfo = Field(..., description="Author information")
    platform: PlatformInfo = Field(..., description="Platform information")
    post_time: int | None = Field(None, description="Post timestamp in seconds since epoch")
    parser: str = Field(..., description="Parser type used")
    state: ParserResultStatus = Field(..., description="Parsing state")
    tags: list[TagInfo] = Field(default_factory=list, description="Per-user tags on this content")
    created_at: datetime = Field(..., description="Database creation timestamp")
    updated_at: datetime = Field(..., description="Database update timestamp")
    deleted_at: datetime | None = Field(None, description="Deletion timestamp (null if not deleted)")

    @classmethod
    def from_entity(cls, entity: ParseResultEntity) -> "URLParserResult":
        """Create URLParserResult from ParseResultEntity"""
        return cls(
            id=entity.id if entity.id else 0,
            pid=entity.pid,
            url=entity.url,  # type: ignore
            title=entity.title,
            content=entity.content,
            media=[MediaInfo.from_entity(media) for media in entity.media],
            author=AuthorInfo.from_entity(entity.author),
            platform=PlatformInfo.from_entity(entity.platform),
            post_time=entity.post_time,
            parser=entity.parser,
            state=entity.state,
            tags=[TagInfo.from_entity(tag) for tag in entity.tags],
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            deleted_at=entity.deleted_at,
        )


class SyncMediaInfo(APIBaseModel):
    """Media item in content sync responses (tag IDs only)."""

    id: int = Field(..., description="Media ID")
    status: MediaStatus = Field(..., description="Download status: pending, downloading, completed, failed")
    url: HttpUrl = Field(..., description="Original media URL")
    type: MediaType | None = Field(None, description="Media type")
    title: str | None = Field(None, description="Media title")
    duration: int | None = Field(None, description="Video duration in seconds")
    width: int | None = Field(None, description="Media width in pixels")
    height: int | None = Field(None, description="Media height in pixels")
    cover: HttpUrl | None = Field(None, description="Original video cover URL")
    url_fallbacks: list[HttpUrl] = Field(default_factory=list, description="Fallback media URLs")
    cover_fallbacks: list[HttpUrl] = Field(default_factory=list, description="Fallback cover URLs")
    media_path: str | None = Field(None, description="Local media file path")
    cover_path: str | None = Field(None, description="Local cover file path")
    tag_ids: list[int] = Field(default_factory=list, description="Per-user tag IDs on this media item")
    created_at: datetime = Field(..., description="Database creation timestamp")
    updated_at: datetime = Field(..., description="Database update timestamp")
    deleted_at: datetime | None = Field(None, description="Deletion timestamp (null if not deleted)")

    @classmethod
    def from_entity(cls, entity: MediaEntity) -> "SyncMediaInfo":
        """Create SyncMediaInfo from MediaEntity"""
        return cls(
            id=entity.id if entity.id else 0,
            status=entity.status,
            url=entity.url,  # type: ignore
            type=entity.type,
            title=entity.title,
            duration=entity.duration,
            width=entity.width,
            height=entity.height,
            cover=entity.cover,  # type: ignore
            url_fallbacks=entity.url_fallbacks,  # type: ignore
            cover_fallbacks=entity.cover_fallbacks,  # type: ignore
            media_path=entity.media_path,
            cover_path=entity.cover_path,
            tag_ids=entity.tag_ids,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            deleted_at=entity.deleted_at,
        )


class SyncAuthorInfo(APIBaseModel):
    """Author information in content sync responses (tag IDs only)."""

    id: int = Field(..., description="Author ID")
    uid: str = Field(..., description="User ID")
    name: str | None = Field(None, description="Author name")
    username: str = Field(..., description="Username")
    avatar: HttpUrl | None = Field(None, description="Avatar URL")
    avatar_path: str | None = Field(None, description="Local avatar path served under /media")
    url: HttpUrl | None = Field(None, description="Author profile URL")
    banner: HttpUrl | None = Field(None, description="Author banner URL")
    banner_path: str | None = Field(None, description="Local banner path served under /media")
    description: str | None = Field(None, description="Author description")
    platform: PlatformInfo = Field(..., description="Platform information")
    tag_ids: list[int] = Field(default_factory=list, description="Per-user tag IDs on this author")
    created_at: datetime = Field(..., description="Database creation timestamp")
    updated_at: datetime = Field(..., description="Database update timestamp")
    deleted_at: datetime | None = Field(None, description="Deletion timestamp (null if not deleted)")

    @classmethod
    def from_entity(cls, entity: AuthorEntity) -> "SyncAuthorInfo":
        """Create SyncAuthorInfo from AuthorEntity"""
        return cls(
            id=entity.id if entity.id else 0,
            uid=entity.uid,
            name=entity.name,
            username=entity.username,
            avatar=entity.avatar,  # type: ignore
            avatar_path=entity.avatar_path,
            url=entity.url,  # type: ignore
            banner=entity.banner,  # type: ignore
            banner_path=entity.banner_path,
            description=entity.description,
            platform=PlatformInfo.from_entity(entity.platform),
            tag_ids=entity.tag_ids,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            deleted_at=entity.deleted_at,
        )


class SyncURLParserResult(APIBaseModel):
    """Content sync response item (tag IDs only)."""

    id: int = Field(..., description="Parser result ID")
    pid: str = Field(..., description="Content ID")
    url: HttpUrl = Field(..., description="The URL that was fetched")
    title: str | None = Field(None, description="Content title")
    content: str | None = Field(None, description="Content text")
    media: list[SyncMediaInfo] = Field(default_factory=list, description="List of stored media items")
    author: SyncAuthorInfo = Field(..., description="Author information")
    platform: PlatformInfo = Field(..., description="Platform information")
    post_time: int | None = Field(None, description="Post timestamp in seconds since epoch")
    parser: str = Field(..., description="Parser type used")
    state: ParserResultStatus = Field(..., description="Parsing state")
    tag_ids: list[int] = Field(default_factory=list, description="Per-user tag IDs on this content")
    created_at: datetime = Field(..., description="Database creation timestamp")
    updated_at: datetime = Field(..., description="Database update timestamp")
    deleted_at: datetime | None = Field(None, description="Deletion timestamp (null if not deleted)")

    @classmethod
    def from_entity(cls, entity: ParseResultEntity) -> "SyncURLParserResult":
        """Create SyncURLParserResult from ParseResultEntity"""
        return cls(
            id=entity.id if entity.id else 0,
            pid=entity.pid,
            url=entity.url,  # type: ignore
            title=entity.title,
            content=entity.content,
            media=[SyncMediaInfo.from_entity(media) for media in entity.media],
            author=SyncAuthorInfo.from_entity(entity.author),
            platform=PlatformInfo.from_entity(entity.platform),
            post_time=entity.post_time,
            parser=entity.parser,
            state=entity.state,
            tag_ids=entity.tag_ids,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            deleted_at=entity.deleted_at,
        )

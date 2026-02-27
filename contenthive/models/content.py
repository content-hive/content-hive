"""
Models for content-related operations.
"""

from datetime import datetime, timezone
from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, Literal, Generic, TypeVar
from dataclasses import dataclass, field

from contenthive.models.api import APIBaseModel

T = TypeVar('T')

# Database Models

@dataclass
class PlatformEntity:
    """Platform database entity"""
    id: Optional[int] = None
    code: str = ""
    name: str = ""
    url: str = ""
    icon_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class AuthorEntity:
    """Author database entity"""
    id: Optional[int] = None
    platform_id: int = 0
    uid: str = ""
    name: Optional[str] = None
    username: str = ""
    avatar: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    platform: PlatformEntity = field(default_factory=PlatformEntity)


@dataclass
class MediaEntity:
    """Media database entity"""
    id: Optional[int] = None
    status: str = "pending"  # pending, downloading, completed, failed
    url: str = ""
    type: str = ""  # 'image' or 'video'
    title: Optional[str] = None
    cover: Optional[str] = None
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    media_path: Optional[str] = None
    cover_path: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class ParseResultEntity:
    """Parse result database entity"""
    id: Optional[int] = None
    pid: str = ""
    url: str = ""
    content: str = ""
    author_id: int = 0
    platform_id: int = 0
    post_time: Optional[int] = None
    parser: str = ""
    state: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    
    # Related entities (for joins) - must not be None
    author: AuthorEntity = field(default_factory=AuthorEntity)
    platform: PlatformEntity = field(default_factory=PlatformEntity)
    media: list[MediaEntity] = field(default_factory=list)

# Service Models

class DownloadedMediaInfo(BaseModel):
    """Information about downloaded media file"""
    status: str = Field(..., description="Download status: pending, downloading, completed, failed")
    url: HttpUrl = Field(..., description="Original media URL")
    type: Optional[Literal["image", "video"]] = Field(None, description="Media type")
    title: Optional[str] = Field(None, description="Media title")
    cover: Optional[HttpUrl] = Field(None, description="Original video cover URL")
    duration: Optional[int] = Field(None, description="Video duration in seconds")
    width: Optional[int] = Field(None, description="Media width in pixels")
    height: Optional[int] = Field(None, description="Media height in pixels")
    media_path: Optional[str] = Field(None, description="Local media file path")
    cover_path: Optional[str] = Field(None, description="Local cover file path")

# API Response Models

class PaginationInfo(APIBaseModel):
    """Pagination metadata"""
    
    page: int = Field(..., description="Current page number", ge=1)
    page_size: int = Field(..., description="Items per page", ge=1)
    total: int = Field(..., description="Total number of items", ge=0)
    total_pages: int = Field(..., description="Total number of pages", ge=0)


class PaginatedResponse(APIBaseModel, Generic[T]):
    """Paginated response model"""
    
    items: list[T] = Field(..., description="List of items")
    pagination: PaginationInfo = Field(..., description="Pagination information")


class SyncResponse(APIBaseModel, Generic[T]):
    """Sync response model with server timestamp"""
    
    items: list[T] = Field(..., description="List of items")
    pagination: PaginationInfo = Field(..., description="Pagination information")
    sync_timestamp: datetime = Field(..., description="Server timestamp for this sync operation (use this for next sync)")


class MediaInfo(APIBaseModel):
    """Stored media item model (with local paths)"""
    id: int = Field(..., description="Media ID")
    status: str = Field(..., description="Download status: pending, downloading, completed, failed")
    url: HttpUrl = Field(..., description="Original media URL")
    type: Optional[Literal["image", "video"]] = Field(None, description="Media type")
    title: Optional[str] = Field(None, description="Media title")
    duration: Optional[int] = Field(None, description="Video duration in seconds")
    width: Optional[int] = Field(None, description="Media width in pixels")
    height: Optional[int] = Field(None, description="Media height in pixels")
    cover: Optional[HttpUrl] = Field(None, description="Original video cover URL")
    media_path: Optional[str] = Field(None, description="Local media file path")
    cover_path: Optional[str] = Field(None, description="Local cover file path")

    @classmethod
    def from_entity(cls, entity: MediaEntity) -> "MediaInfo":
        """Create MediaInfo from MediaEntity"""
        return cls(
            id=entity.id if entity.id else 0,
            status=entity.status,
            url=entity.url, # type: ignore
            type=entity.type,  # type: ignore
            title=entity.title,
            duration=entity.duration,
            width=entity.width,
            height=entity.height,
            cover=entity.cover, # type: ignore
            media_path=entity.media_path,
            cover_path=entity.cover_path
        )


class PlatformInfo(APIBaseModel):
    """Platform information model (with database ID)"""
    id: int = Field(..., description="Platform ID")
    name: str = Field(..., description="Platform name")
    code: str = Field(..., description="Platform code")
    url: HttpUrl = Field(..., description="Platform URL")
    icon_url: Optional[HttpUrl] = Field(None, description="Platform icon URL")

    @classmethod
    def from_entity(cls, entity: PlatformEntity) -> "PlatformInfo":
        """Create PlatformInfo from PlatformEntity"""
        return cls(
            id=entity.id if entity.id else 0,
            name=entity.name,
            code=entity.code,
            url=entity.url, # type: ignore
            icon_url=entity.icon_url, # type: ignore
        )

class AuthorInfo(APIBaseModel):
    """Author information model (with database ID)"""
    id: int = Field(..., description="Author ID")
    uid: str = Field(..., description="User ID")
    name: Optional[str] = Field(None, description="Author name")
    username: str = Field(..., description="Username")
    avatar: Optional[HttpUrl] = Field(None, description="Avatar URL")
    url: Optional[HttpUrl] = Field(None, description="Author profile URL")
    platform: PlatformInfo = Field(..., description="Platform information")

    @classmethod
    def from_entity(cls, entity: AuthorEntity) -> "AuthorInfo":
        """Create AuthorInfo from AuthorEntity"""
        return cls(
            id=entity.id if entity.id else 0,
            uid=entity.uid,
            name=entity.name ,
            username=entity.username,
            avatar=entity.avatar, # type: ignore
            url=entity.url, # type: ignore
            platform=PlatformInfo.from_entity(entity.platform)
        )

class URLParserResult(APIBaseModel):
    """API response model for stored content (with downloaded media)"""
    id: int = Field(..., description="Parser result ID")
    pid: str = Field(..., description="Content ID")
    url: HttpUrl = Field(..., description="The URL that was fetched")
    content: str = Field(..., description="Content text")
    media: list[MediaInfo] = Field(default_factory=list, description="List of stored media items")
    author: AuthorInfo = Field(..., description="Author information")
    platform: PlatformInfo = Field(..., description="Platform information")
    post_time: Optional[int] = Field(None, description="Post timestamp in seconds since epoch")
    parser: str = Field(..., description="Parser type used")
    state: Literal["success", "error"] = Field(..., description="Parsing state")
    created_at: datetime = Field(..., description="Database creation timestamp")
    updated_at: datetime = Field(..., description="Database update timestamp")
    deleted_at: Optional[datetime] = Field(None, description="Deletion timestamp (null if not deleted)")

    @classmethod
    def from_entity(cls, entity: ParseResultEntity) -> "URLParserResult":
        """Create URLParserResult from ParseResultEntity"""
        return cls(
            id=entity.id if entity.id else 0,
            pid=entity.pid,
            url=entity.url,  # type: ignore
            content=entity.content,
            media=[MediaInfo.from_entity(media) for media in entity.media],
            author=AuthorInfo.from_entity(entity.author),
            platform=PlatformInfo.from_entity(entity.platform),
            post_time=entity.post_time,
            parser=entity.parser,
            state=entity.state,  # type: ignore
            created_at=(entity.created_at) if entity.created_at else datetime.now(timezone.utc),
            updated_at=(entity.updated_at) if entity.updated_at else datetime.now(timezone.utc),
            deleted_at=entity.deleted_at,
        )
    

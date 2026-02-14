"""
Models for content-related operations.
"""

from datetime import datetime
from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, Literal, Generic, TypeVar
from dataclasses import dataclass, field

from contenthive.models.parser import (
    ParserMediaInfo,
    ParserAuthorInfo,
    ParserPlatformInfo,
    ParserResult,
)

T = TypeVar('T')

# Database Models

@dataclass
class PlatformEntity:
    """Platform database entity"""
    id: Optional[int] = None
    code: str = ""
    name: str = ""
    url: str = ""
    icon_url: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class AuthorEntity:
    """Author database entity"""
    id: Optional[int] = None
    platform_id: int = 0
    uid: str = ""
    name: str = ""
    username: str = ""
    avatar: str = ""
    url: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    platform: PlatformEntity = field(default_factory=PlatformEntity)


@dataclass
class MediaEntity:
    """Media database entity"""
    id: Optional[int] = None
    url: str = ""
    type: str = ""  # 'image' or 'video'
    title: Optional[str] = None
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    cover: Optional[str] = None
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
    user_id: Optional[int] = None
    post_time: int = 0
    parser: str = ""
    state: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Related entities (for joins) - must not be None
    author: AuthorEntity = field(default_factory=AuthorEntity)
    platform: PlatformEntity = field(default_factory=PlatformEntity)
    media: list[MediaEntity] = field(default_factory=list)

# API Response Models

class PaginationInfo(BaseModel):
    """Pagination metadata"""
    
    page: int = Field(..., description="Current page number", ge=1)
    page_size: int = Field(..., description="Items per page", ge=1)
    total: int = Field(..., description="Total number of items", ge=0)
    total_pages: int = Field(..., description="Total number of pages", ge=0)


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response model"""
    
    items: list[T] = Field(..., description="List of items")
    pagination: PaginationInfo = Field(..., description="Pagination information")


class MediaInfo(BaseModel):
    """Stored media item model (with local paths)"""
    id: int = Field(..., description="Media ID")
    url: HttpUrl = Field(..., description="Original media URL")
    type: Optional[Literal["image", "video"]] = Field(None, description="Media type")
    title: Optional[str] = Field(None, description="Media title")
    duration: Optional[int] = Field(None, description="Video duration in seconds")
    width: Optional[int] = Field(None, description="Media width in pixels")
    height: Optional[int] = Field(None, description="Media height in pixels")
    cover: Optional[HttpUrl] = Field(None, description="Original video cover URL")
    media_path: Optional[str] = Field(None, description="Local media file path")
    cover_path: Optional[str] = Field(None, description="Local cover file path")


class PlatformInfo(BaseModel):
    """Platform information model (with database ID)"""
    id: int = Field(..., description="Platform ID")
    name: str = Field(..., description="Platform name")
    code: str = Field(..., description="Platform code")
    url: HttpUrl = Field(..., description="Platform URL")
    icon_url: HttpUrl = Field(..., description="Platform icon URL")


class AuthorInfo(BaseModel):
    """Author information model (with database ID)"""
    id: int = Field(..., description="Author ID")
    uid: str = Field(..., description="User ID")
    name: str = Field(..., description="Author name")
    username: str = Field(..., description="Username")
    avatar: HttpUrl = Field(..., description="Avatar URL")
    url: HttpUrl = Field(..., description="Author profile URL")
    platform: PlatformInfo = Field(..., description="Platform information")


class URLParserResult(BaseModel):
    """API response model for stored content (with downloaded media)"""
    id: int = Field(..., description="Parser result ID")
    pid: str = Field(..., description="Content ID")
    url: HttpUrl = Field(..., description="The URL that was fetched")
    content: str = Field(..., description="Content text")
    media: list[MediaInfo] = Field(default_factory=list, description="List of stored media items")
    author: AuthorInfo = Field(..., description="Author information")
    platform: PlatformInfo = Field(..., description="Platform information")
    post_time: int = Field(..., description="Post timestamp in seconds since epoch")
    parser: str = Field(..., description="Parser type used")
    state: Literal["success", "error"] = Field(..., description="Parsing state")
    created_at: datetime = Field(..., description="Database creation timestamp")
    updated_at: datetime = Field(..., description="Database update timestamp")

# Mapper
# Mapper for parser result to entity conversions

class ParserMapper:
    """Mapper for parser result to entity conversions"""

    @staticmethod
    def parser_result_to_entity(
        parser_result: ParserResult,
        platform_entity: PlatformEntity,
        author_entity: AuthorEntity,
        user_id: Optional[int] = None,
    ) -> ParseResultEntity:
        """Convert ParserResult to ParseResultEntity (for initial save)"""
        return ParseResultEntity(
            pid=parser_result.pid,
            url=str(parser_result.url),
            content=parser_result.content,
            post_time=parser_result.post_time,
            parser=parser_result.parser,
            state=parser_result.state,
            user_id=user_id,
            platform_id=platform_entity.id if platform_entity.id else 0,
            author_id=author_entity.id if author_entity.id else 0,
            author=author_entity,
            platform=platform_entity,
            media=[
                ParserMapper.media_info_to_entity(media)
                for media in parser_result.media
            ],
        )

    @staticmethod
    def media_info_to_entity(media: ParserMediaInfo) -> MediaEntity:
        """Convert MediaInfo (with local paths) to MediaEntity (for storage)"""
        return MediaEntity(
            url=str(media.url),
            type=str(media.type) if media.type else "",
            title=media.title,
            duration=None,
            width=None,
            height=None,
            cover=str(media.cover) if media.cover else None,
            media_path=None,
            cover_path=None,
        )


    @staticmethod
    def parser_author_to_entity(
        author: ParserAuthorInfo, platform_id: int
    ) -> AuthorEntity:
        """Convert ParserAuthorInfo to AuthorEntity"""
        return AuthorEntity(
            platform_id=platform_id,
            uid=author.uid,
            name=author.name,
            username=author.username,
            avatar=str(author.avatar) if author.avatar else "",
            url=str(author.url),
        )

    @staticmethod
    def parser_platform_to_entity(platform: ParserPlatformInfo) -> PlatformEntity:
        """Convert ParserPlatformInfo to PlatformEntity"""
        return PlatformEntity(
            code=platform.code,
            name=platform.name,
            url=str(platform.url),
            icon_url=str(platform.icon_url) if platform.icon_url else "",
        )

# Mapper for entity to content model conversions

class ContentMapper:
    """Mapper for entity to content model conversions"""

    @staticmethod
    def entity_to_url_parser_result(entity: ParseResultEntity) -> URLParserResult:
        """Convert ParseResultEntity to URLParserResult (for API response)"""
        return URLParserResult(
            id=entity.id if entity.id else 0,
            pid=entity.pid,
            url=entity.url,  # type: ignore
            content=entity.content,
            author=ContentMapper.author_entity_to_info(entity.author),
            platform=ContentMapper.platform_entity_to_info(entity.platform),
            media=[
                ContentMapper.media_entity_to_info(media)
                for media in entity.media
            ],
            post_time=entity.post_time,
            parser=entity.parser,
            state=entity.state,  # type: ignore
            created_at=(entity.created_at) if entity.created_at else datetime.now(),
            updated_at=(entity.updated_at) if entity.updated_at else datetime.now(),
        )

    @staticmethod
    def media_entity_to_info(media: MediaEntity) -> MediaInfo:
        """Convert MediaEntity to MediaInfo (with local paths)"""
        return MediaInfo(
            id=media.id if media.id else 0,
            url=media.url, # type: ignore
            type=media.type,  # type: ignore
            title=media.title,
            duration=media.duration,
            width=media.width,
            height=media.height,
            cover=media.cover, # type: ignore
            media_path=media.media_path,
            cover_path=media.cover_path
        )

    @staticmethod
    def author_entity_to_info(author: AuthorEntity) -> AuthorInfo:
        """Convert AuthorEntity to AuthorInfo"""
        return AuthorInfo(
            id=author.id if author.id else 0,
            uid=author.uid,
            name=author.name,
            username=author.username,
            avatar=author.avatar, # type: ignore
            url=author.url, # type: ignore
            platform=ContentMapper.platform_entity_to_info(author.platform),
        )

    @staticmethod
    def platform_entity_to_info(platform: PlatformEntity) -> PlatformInfo:
        """Convert PlatformEntity to PlatformInfo"""
        return PlatformInfo(
            id=platform.id if platform.id else 0,
            code=platform.code,
            name=platform.name,
            url=platform.url, # type: ignore
            icon_url=platform.icon_url, # type: ignore
        )
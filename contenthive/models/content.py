"""
Models for content-related operations.
"""

from datetime import datetime
from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, Any, Literal, Generic, TypeVar

from contenthive.models.media import MediaItem

T = TypeVar('T')


class ErrorDetail(BaseModel):
    """Error detail model"""
    
    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    details: Optional[dict[str, Any]] = Field(None, description="Detailed error information")


class APIResponse(BaseModel):
    """API response model"""
    
    status: Literal["success", "error"] = Field(..., description="Response status")
    data: Optional[Any] = Field(default=None, description="Response data")
    error: Optional[ErrorDetail] = Field(default=None, description="Error information")
    timestamp: datetime = Field(default_factory=datetime.now, description="Response timestamp")


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


class MediaInfo(MediaItem):
    """Stored media item model (with local paths)"""
    id: int = Field(..., description="Media ID")
    url: HttpUrl = Field(..., description="Original media URL")
    type: Optional[Literal["image", "video"]] = Field(None, description="Media type")
    title: Optional[str] = Field(None, description="Media title")
    duration: Optional[int] = Field(None, description="Video duration in seconds")
    width: Optional[str] = Field(None, description="Media width in pixels")
    height: Optional[str] = Field(None, description="Media height in pixels")
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
    created_time: int = Field(..., description="Creation timestamp in milliseconds")
    parser: str = Field(..., description="Parser type used")
    state: Literal["success", "error"] = Field(..., description="Parsing state")
    created_at: datetime = Field(..., description="Database creation timestamp")
    updated_at: datetime = Field(..., description="Database update timestamp")

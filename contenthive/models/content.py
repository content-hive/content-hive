"""
Models for content-related operations.
"""

from datetime import datetime
from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, Any, Dict, Literal

class ErrorDetail(BaseModel):
    """Error detail model"""
    
    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Detailed error information")


class APIResponse(BaseModel):
    """API response model"""
    
    status: Literal["success", "error"] = Field(..., description="Response status")
    data: Optional[Any] = Field(default=None, description="Response data")
    error: Optional[ErrorDetail] = Field(default=None, description="Error information")
    timestamp: datetime = Field(default_factory=datetime.now, description="Response timestamp")


class ImageItem(BaseModel):
    """Image item model"""
    url: HttpUrl = Field(..., description="Image URL")

class VideoItem(BaseModel):
    """Video item model"""
    url: HttpUrl = Field(..., description="Video URL")

class AuthorInfo(BaseModel):
    """Author information model"""
    id: Optional[int] = Field(None, description="Author ID")
    uid: str = Field(..., description="User ID")
    name: str = Field(..., description="Author name")
    userName: str = Field(..., description="Username")
    avatar: HttpUrl = Field(..., description="Avatar URL")
    url: HttpUrl = Field(..., description="Author profile URL")


class PlatformInfo(BaseModel):
    """Platform information model"""
    id: Optional[int] = Field(None, description="Platform ID")
    name: str = Field(..., description="Platform name")
    code: str = Field(..., description="Platform code")
    url: HttpUrl = Field(..., description="Platform URL")
    iconUrl: HttpUrl = Field(..., description="Platform icon URL")


class URLParserResult(BaseModel):
    """Response model for fetched URL content"""
    id: Optional[int] = Field(None, description="Parser result ID")
    pid: str = Field(..., description="Content ID")
    url: HttpUrl = Field(..., description="The URL that was fetched")
    content: str = Field(..., description="Content text")
    images: list[ImageItem] = Field(default_factory=list, description="List of images")
    videos: list[VideoItem] = Field(default_factory=list, description="List of videos")
    author: AuthorInfo = Field(..., description="Author information")
    createdTime: int = Field(..., description="Creation timestamp in milliseconds")
    parser: str = Field(..., description="Parser type used")
    state: Literal["success", "error"] = Field(..., description="Parsing state")
    platform: PlatformInfo = Field(..., description="Platform information")


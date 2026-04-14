"""
Models for parser operations.
"""

from pydantic import BaseModel, HttpUrl, Field
from typing import Optional

from contenthive.models.enumerates import MediaType, ParserResultStatus


class ParserMediaInfo(BaseModel):
    """Media information from parser (no database ID)"""
    url: HttpUrl = Field(..., description="Media URL")
    type: Optional[MediaType] = Field(None, description="Media type")
    title: Optional[str] = Field(None, description="Media title")
    cover: Optional[HttpUrl] = Field(None, description="Video cover URL")
    duration: Optional[int] = Field(None, description="Video duration in seconds")
    width: Optional[int] = Field(None, description="Media width in pixels")
    height: Optional[int] = Field(None, description="Media height in pixels")
    url_fallbacks: Optional[list[HttpUrl]] = Field(default=None, description="Fallback media URLs")
    cover_fallbacks: Optional[list[HttpUrl]] = Field(default=None, description="Fallback cover URLs")


class ParserPlatformInfo(BaseModel):
    """Platform information from parser (no database ID)"""
    code: str = Field(..., description="Platform code")
    name: str = Field(..., description="Platform name")
    url: HttpUrl = Field(..., description="Platform URL")
    icon_url: Optional[HttpUrl] = Field(None, description="Platform icon URL")


class ParserAuthorInfo(BaseModel):
    """Author information from parser (no database ID)"""
    uid: str = Field(..., description="User ID on platform")
    name: Optional[str] = Field(None, description="Author name")
    username: str = Field(..., description="Username")
    avatar: Optional[HttpUrl] = Field(None, description="Avatar URL")
    url: Optional[HttpUrl] = Field(None, description="Author profile URL")
    banner: Optional[HttpUrl] = Field(None, description="Author banner URL")
    description: Optional[str] = Field(None, description="Author description")

class ParserResult(BaseModel):
    """Raw parser result (before saving to database)"""
    pid: str = Field(..., description="Content ID")
    url: HttpUrl = Field(..., description="The URL that was parsed")
    title: Optional[str] = Field(None, description="Content title")
    content: Optional[str] = Field(None, description="Content text")
    media: list[ParserMediaInfo] = Field(default_factory=list, description="List of media items")
    author: ParserAuthorInfo = Field(..., description="Author information")
    platform: ParserPlatformInfo = Field(..., description="Platform information")
    post_time: Optional[int] = Field(None, description="Post timestamp in seconds since epoch")
    parser: str = Field(..., description="Parser type used")
    state: ParserResultStatus = Field(..., description="Parsing state")
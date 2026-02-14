"""
Models for parser operations.
"""

from pydantic import HttpUrl, Field
from typing import Optional, Literal

from contenthive.models.api import BaseEntity


class ParserMediaInfo(BaseEntity):
    """Media information from parser (no database ID)"""
    url: HttpUrl = Field(..., description="Media URL")
    type: Optional[Literal["image", "video"]] = Field(None, description="Media type")
    title: Optional[str] = Field(None, description="Media title")
    cover: Optional[HttpUrl] = Field(None, description="Video cover URL")


class ParserPlatformInfo(BaseEntity):
    """Platform information from parser (no database ID)"""
    code: str = Field(..., description="Platform code")
    name: str = Field(..., description="Platform name")
    url: HttpUrl = Field(..., description="Platform URL")
    icon_url: Optional[HttpUrl] = Field(None, description="Platform icon URL")


class ParserAuthorInfo(BaseEntity):
    """Author information from parser (no database ID)"""
    uid: str = Field(..., description="User ID on platform")
    name: Optional[str] = Field(None, description="Author name")
    username: str = Field(..., description="Username")
    avatar: Optional[HttpUrl] = Field(None, description="Avatar URL")
    url: Optional[HttpUrl] = Field(None, description="Author profile URL")


class ParserResult(BaseEntity):
    """Raw parser result (before saving to database)"""
    pid: str = Field(..., description="Content ID")
    url: HttpUrl = Field(..., description="The URL that was parsed")
    content: str = Field(..., description="Content text")
    media: list[ParserMediaInfo] = Field(default_factory=list, description="List of media items")
    author: ParserAuthorInfo = Field(..., description="Author information")
    platform: ParserPlatformInfo = Field(..., description="Platform information")
    post_time: Optional[int] = Field(None, description="Post timestamp in seconds since epoch")
    parser: str = Field(..., description="Parser type used")
    state: Literal["success", "error"] = Field(..., description="Parsing state")
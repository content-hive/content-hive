"""
Models for parser operations.
"""

from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, Literal


class ParserMediaInfo(BaseModel):
    """Media information from parser (no database ID)"""
    url: HttpUrl = Field(..., description="Media URL")
    type: Optional[Literal["image", "video"]] = Field(None, description="Media type")
    title: Optional[str] = Field(None, description="Media title")
    cover: Optional[HttpUrl] = Field(None, description="Video cover URL")


class ParserAuthorInfo(BaseModel):
    """Author information from parser (no database ID)"""
    uid: str = Field(..., description="User ID on platform")
    name: str = Field(..., description="Author name")
    username: str = Field(..., description="Username")
    avatar: HttpUrl = Field(..., description="Avatar URL")
    url: HttpUrl = Field(..., description="Author profile URL")


class ParserPlatformInfo(BaseModel):
    """Platform information from parser (no database ID)"""
    code: str = Field(..., description="Platform code")
    name: str = Field(..., description="Platform name")
    url: HttpUrl = Field(..., description="Platform URL")
    icon_url: HttpUrl = Field(..., description="Platform icon URL")


class ParserResult(BaseModel):
    """Raw parser result (before saving to database)"""
    pid: str = Field(..., description="Content ID")
    url: HttpUrl = Field(..., description="The URL that was parsed")
    content: str = Field(..., description="Content text")
    media: list[ParserMediaInfo] = Field(default_factory=list, description="List of media items")
    author: ParserAuthorInfo = Field(..., description="Author information")
    platform: ParserPlatformInfo = Field(..., description="Platform information")
    created_time: int = Field(..., description="Creation timestamp in milliseconds")
    parser: str = Field(..., description="Parser type used")
    state: Literal["success", "error"] = Field(..., description="Parsing state")
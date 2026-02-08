"""
Media models for ContentHive
"""

from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, Literal


class MediaItem(BaseModel):
    """Media item model (parsed from URL)"""
    url: HttpUrl = Field(..., description="Media URL")
    type: Optional[Literal["image", "video"]] = Field(None, description="Media type")
    title: Optional[str] = Field(None, description="Media title")
    duration: Optional[int] = Field(None, description="Video duration in seconds")
    width: Optional[str] = Field(None, description="Media width in pixels")
    height: Optional[str] = Field(None, description="Media height in pixels")
    cover: Optional[HttpUrl] = Field(None, description="Video cover URL")
    media_path: Optional[str] = Field(None, description="Local media file path")
    cover_path: Optional[str] = Field(None, description="Local cover file path")

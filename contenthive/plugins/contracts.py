"""
Plugin contract types. This is the stable interface between Content Hive
and its plugins. Plugins must only import from contenthive.plugins.*.
"""
from typing import Optional
from pydantic import BaseModel

# Re-export enums from enumerates so plugins only need to import from here
from contenthive.models.enumerates import MediaType, ParserResultStatus


class ParserMediaInfo(BaseModel):
    """Media information exchanged between plugins and the core."""
    url: str
    type: Optional[MediaType] = None
    title: Optional[str] = None
    cover: Optional[str] = None
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    url_fallbacks: Optional[list[str]] = None
    cover_fallbacks: Optional[list[str]] = None


class ParserPlatformInfo(BaseModel):
    """Platform information exchanged between plugins and the core."""
    code: str
    name: str
    url: str
    icon_url: Optional[str] = None


class ParserAuthorInfo(BaseModel):
    """Author information exchanged between plugins and the core."""
    uid: str
    name: Optional[str] = None
    username: str
    avatar: Optional[str] = None
    url: Optional[str] = None
    banner: Optional[str] = None
    description: Optional[str] = None


class ParserResult(BaseModel):
    """Full parse result returned by a plugin's parse service."""
    pid: str
    url: str
    title: Optional[str] = None
    content: Optional[str] = None
    media: list[ParserMediaInfo] = []
    author: ParserAuthorInfo
    platform: ParserPlatformInfo
    post_time: Optional[int] = None
    parser: str
    state: ParserResultStatus

"""
Database entity models
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

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


@dataclass
class MediaEntity:
    """Media database entity"""
    id: Optional[int] = None
    url: str = ""
    type: str = ""  # 'image' or 'video'
    title: Optional[str] = None
    duration: Optional[int] = None
    width: Optional[str] = None
    height: Optional[str] = None
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
    created_time: int = 0
    parser: str = ""
    state: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Related entities (for joins) - must not be None
    author: AuthorEntity = field(default_factory=lambda: AuthorEntity())
    platform: PlatformEntity = field(default_factory=lambda: PlatformEntity())
    media: list[MediaEntity] = field(default_factory=list)
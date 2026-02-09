"""
Mappers for converting between entities and models
"""
from typing import Optional
from datetime import datetime
from pydantic import HttpUrl

from contenthive.models.content import (
    AuthorInfo,
    PlatformInfo,
    MediaInfo,
    URLParserResult,
)
from contenthive.models.parser import (
    ParserMediaInfo,
    ParserAuthorInfo,
    ParserPlatformInfo,
    ParserResult,
)
from contenthive.models.entities import (
    AuthorEntity,
    MediaEntity,
    ParseResultEntity,
    PlatformEntity,
)
from contenthive.models.media import MediaItem


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
            created_time=parser_result.created_time,
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
    def media_item_to_entity(media: MediaItem) -> MediaEntity:
        """Convert MediaItem (from parser) to MediaEntity (for storage)"""
        return MediaEntity(
            url=str(media.url),
            type=str(media.type) if media.type else "",
            title=media.title,
            duration=media.duration,
            width=media.width,
            height=media.height,
            cover=str(media.cover) if media.cover else None,
            # media_path and cover_path will be set after download
            media_path=media.media_path,
            cover_path=media.cover_path,
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


class ContentMapper:
    """Mapper for entity to content model conversions"""

    @staticmethod
    def entity_to_url_parser_result(entity: ParseResultEntity) -> URLParserResult:
        """Convert ParseResultEntity to URLParserResult (for API response)"""
        return URLParserResult(
            id=entity.id if entity.id else 0,
            pid=entity.pid,
            url=HttpUrl(entity.url),
            content=entity.content,
            author=ContentMapper.author_entity_to_info(entity.author),
            platform=ContentMapper.platform_entity_to_info(entity.platform),
            media=[
                ContentMapper.media_entity_to_info(media)
                for media in entity.media
            ],
            created_time=entity.created_time,
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
            url=HttpUrl(media.url),
            type=media.type,  # type: ignore
            title=media.title,
            duration=media.duration,
            width=media.width,
            height=media.height,
            cover=HttpUrl(media.cover) if media.cover else None,
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
            avatar=HttpUrl(author.avatar),
            url=HttpUrl(author.url),
            platform=ContentMapper.platform_entity_to_info(author.platform),
        )

    @staticmethod
    def platform_entity_to_info(platform: PlatformEntity) -> PlatformInfo:
        """Convert PlatformEntity to PlatformInfo"""
        return PlatformInfo(
            id=platform.id if platform.id else 0,
            code=platform.code,
            name=platform.name,
            url=HttpUrl(platform.url),
            icon_url=HttpUrl(platform.icon_url),
        )
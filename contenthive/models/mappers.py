"""
Mappers for converting between entities and models
"""
from typing import Optional

from pydantic import HttpUrl

from contenthive.models.content import (
    AuthorInfo,
    ImageItem,
    PlatformInfo,
    URLParserResult,
    VideoItem,
)
from contenthive.models.entities import (
    AuthorEntity,
    MediaEntity,
    ParseResultEntity,
    PlatformEntity,
)


class ContentMapper:
    """Mapper for content-related conversions"""

    @staticmethod
    def entity_to_model(entity: ParseResultEntity) -> URLParserResult:
        """Convert ParseResultEntity to URLParserResult"""
        return URLParserResult(
            id=entity.id,
            pid=entity.pid,
            url=HttpUrl(entity.url),
            content=entity.content,
            author=AuthorInfo(
                id=entity.author.id,
                uid=entity.author.uid,
                name=entity.author.name,
                userName=entity.author.username,
                avatar=HttpUrl(entity.author.avatar),
                url=HttpUrl(entity.author.url),
            ),
            platform=PlatformInfo(
                id=entity.platform.id,
                code=entity.platform.code,
                name=entity.platform.name,
                url=HttpUrl(entity.platform.url),
                iconUrl=HttpUrl(entity.platform.icon_url),
            ),
            images=[ImageItem(url=HttpUrl(img.url)) for img in entity.images],
            videos=[VideoItem(url=HttpUrl(vid.url)) for vid in entity.videos],
            createdTime=entity.created_time,
            parser=entity.parser,
            state=entity.state,  # type: ignore
        )

    @staticmethod
    def model_to_entity(
        model: URLParserResult, user_id: Optional[int] = None
    ) -> ParseResultEntity:
        """Convert URLParserResult to ParseResultEntity"""
        return ParseResultEntity(
            id=model.id,
            pid=model.pid,
            url=str(model.url),
            content=model.content,
            created_time=model.createdTime,
            parser=model.parser,
            state=model.state,
            user_id=user_id,
            author=AuthorEntity(
                id=model.author.id,
                uid=model.author.uid,
                name=model.author.name,
                username=model.author.userName,
                avatar=str(model.author.avatar),
                url=str(model.author.url),
            ),
            platform=PlatformEntity(
                id=model.platform.id,
                code=model.platform.code,
                name=model.platform.name,
                url=str(model.platform.url),
                icon_url=str(model.platform.iconUrl),
            ),
            images=[MediaEntity(url=str(img.url), type="image") for img in model.images],
            videos=[MediaEntity(url=str(vid.url), type="video") for vid in model.videos],
        )
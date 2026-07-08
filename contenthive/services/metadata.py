"""
Metadata sidecar service for persisting database content to disk.
"""

from pathlib import Path

from pydantic import BaseModel

from contenthive.database.content_dao import ContentDAO
from contenthive.logger import logger
from contenthive.models.content import (
    AuthorSidecar,
    ContentSidecar,
)
from contenthive.services.media import MediaService, media_service
from contenthive.utils.content import resolve_content_id
from contenthive.utils.sidecar import METADATA_FILENAME


class MetadataService:
    """
    Service for writing and updating metadata.json sidecar files on disk.
    """

    def __init__(self, media: MediaService = media_service):
        """
        Initialize the MetadataService.

        Args:
            media: MediaService used for directory path resolution.
        """
        self._media = media

    def sync_content_sidecar(self, parse_result_id: int, user_id: int) -> None:
        """
        Write or update the content-level metadata sidecar from the database.

        Args:
            parse_result_id: Parse result database ID
            user_id: User ID for access control when loading the entity
        """
        try:
            with ContentDAO() as dao:
                entity = dao.get_parse_result(parse_result_id, user_id)

            content_id = resolve_content_id(entity.pid, entity.url)
            content_dir = self._media.get_content_directory(
                entity.platform.code,
                entity.author.uid,
                content_id,
            )
            sidecar = ContentSidecar.from_entity(entity)
            self._write_json(content_dir / METADATA_FILENAME, sidecar)
            logger.debug(
                f"Synced content sidecar for parse_result_id={parse_result_id} -> {content_dir / METADATA_FILENAME}"
            )
        except Exception:
            logger.exception(f"Failed to sync content sidecar for parse_result_id={parse_result_id}")

    def sync_author_sidecar(self, platform_code: str, author_uid: str) -> None:
        """
        Write or update the author-level metadata sidecar from the database.

        Args:
            platform_code: Platform code
            author_uid: Author uid on the platform
        """
        try:
            with ContentDAO() as dao:
                entity = dao.get_author_profile_state(platform_code, author_uid)

            if entity is None:
                logger.warning(f"Author not found for sidecar sync: platform={platform_code}, author_uid={author_uid}")
                return

            author_dir = self._media.get_author_directory(platform_code, author_uid)
            sidecar = AuthorSidecar.from_entity(entity)
            self._write_json(author_dir / METADATA_FILENAME, sidecar)
            logger.debug(f"Synced author sidecar for {platform_code}/{author_uid} -> {author_dir / METADATA_FILENAME}")
        except Exception:
            logger.exception(f"Failed to sync author sidecar for platform={platform_code}, author_uid={author_uid}")

    def _write_json(self, path: Path, model: BaseModel) -> None:
        """
        Serialize a Pydantic model to a JSON file, creating parent directories.

        Args:
            path: Destination file path
            model: Pydantic model to serialize
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            model.model_dump_json(indent=2),
            encoding="utf-8",
        )


metadata_service = MetadataService()

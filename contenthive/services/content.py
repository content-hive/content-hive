"""
Parser service for fetching and parsing URL content.
"""

from datetime import UTC, datetime

from pydantic import HttpUrl

from contenthive.database.content_dao import ContentDAO
from contenthive.logger import logger
from contenthive.models.content import (
    AuthorInfo,
    PaginatedResponse,
    PaginationInfo,
    PlatformInfo,
    SyncResponse,
    URLParserResult,
)
from contenthive.plugins.contracts import ParserResult
from contenthive.plugins.manager import get_plugin_manager
from contenthive.services.media import media_service


class ContentService:
    """
    Parser service for fetching and parsing URL content.
    """

    def __init__(self):
        """
        Initialize the ParserService.
        """
        pass

    async def _find_parser_for_url(
        self, url: str, preferred_domain: str | None = None
    ) -> str | None:
        """
        Find parser entity for URL.
        """
        manager = get_plugin_manager()
        if not manager:
            raise Exception("Plugin manager not initialized")

        parser_domains = [
            domain
            for domain in manager.services
            if "can_parse" in manager.services.get(domain, {})
        ]

        # Try preferred parser first
        if preferred_domain and preferred_domain in parser_domains:
            try:
                if await manager.call_service(
                    preferred_domain, "can_parse", {"url": url}
                ):
                    return preferred_domain
            except Exception:
                logger.exception(f"Error checking preferred parser {preferred_domain}")

        # Try all parsers
        for domain in parser_domains:
            if preferred_domain and domain == preferred_domain:
                continue

            try:
                if await manager.call_service(domain, "can_parse", {"url": url}):
                    return domain
            except Exception:
                logger.exception(f"Error checking parser {domain}")

        return None

    async def parser_content(
        self, url: HttpUrl, plugin_id: str | None = None
    ) -> ParserResult | None:
        """
        Fetch and parse content from the given URL using the appropriate parser plugin.

        Args:
            url: The URL to fetch and parse content from.
            plugin_id: Optional preferred parser plugin domain to use for parsing.

        Returns:
            ParserResult containing the parsed content and metadata, or None if parsing failed.
        """
        try:
            logger.info(f"Fetching content from URL: {url}")

            manager = get_plugin_manager()
            if not manager:
                raise Exception("Plugin manager not initialized")

            # Find parser for URL
            domain = await self._find_parser_for_url(
                str(url), preferred_domain=plugin_id
            )

            if not domain:
                raise Exception(f"No parser found for URL: {url}")

            logger.debug(f"Using parser plugin: {domain} for URL: {url}")

            # Parse content
            result = await manager.call_service(domain, "parse", {"url": str(url)})

            if not result:
                raise Exception(f"Parser returned empty result for URL: {url}")

            return result
        except Exception as e:
            logger.exception(f"Error fetching content from URL {url}")
            raise ValueError(f"Failed to parse URL content: {e}") from e

    async def list_contents(
        self,
        user_id: int,
        platform_id: int | None = None,
        author_id: int | None = None,
        page: int = 1,
        page_size: int = 10,
        sort_by: str = "created_at",
        order: str = "desc",
    ) -> PaginatedResponse[URLParserResult]:
        """
        Fetch contents from the database with pagination and sorting.

        Args:
            user_id: User ID to filter contents
            platform_id: Filter by platform ID
            author_id: Filter by author ID
            page: Page number (starting from 1)
            page_size: Number of items per page
            sort_by: Field to sort by
            order: Sort order (asc/desc)

        Returns:
            PaginatedResponse containing list of URLParserResult and pagination info
        """
        try:
            offset = (page - 1) * page_size
            with ContentDAO() as dao:
                results, total = dao.list_parse_results(
                    user_id=user_id,
                    platform_id=platform_id,
                    author_id=author_id,
                    limit=page_size,
                    offset=offset,
                    sort_by=sort_by,
                    order=order,
                )

            items = [URLParserResult.from_entity(result) for result in results]
            total_pages = (total + page_size - 1) // page_size  # Ceiling division

            return PaginatedResponse(
                items=items,
                pagination=PaginationInfo(
                    page=page, page_size=page_size, total=total, total_pages=total_pages
                ),
            )
        except Exception:
            logger.exception("Error fetching contents from the database")
            raise

    async def list_platforms(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 10,
        sort_by: str = "id",
        order: str = "asc",
    ) -> PaginatedResponse[PlatformInfo]:
        """
        Fetch platforms from the database with pagination and sorting.

        Args:
            user_id: User ID to filter platforms
            page: Page number (starting from 1)
            page_size: Number of items per page
            sort_by: Field to sort by
            order: Sort order (asc/desc)

        Returns:
            PaginatedResponse containing list of PlatformInfo and pagination info
        """
        try:
            offset = (page - 1) * page_size
            with ContentDAO() as dao:
                platforms, total = dao.list_platforms(
                    user_id=user_id,
                    limit=page_size,
                    offset=offset,
                    sort_by=sort_by,
                    order=order,
                )

            items = [PlatformInfo.from_entity(platform) for platform in platforms]
            total_pages = (total + page_size - 1) // page_size

            return PaginatedResponse(
                items=items,
                pagination=PaginationInfo(
                    page=page, page_size=page_size, total=total, total_pages=total_pages
                ),
            )
        except Exception:
            logger.exception("Error fetching platforms from the database")
            raise

    async def list_authors(
        self,
        user_id: int,
        platform_id: int | None = None,
        page: int = 1,
        page_size: int = 10,
        sort_by: str = "id",
        order: str = "asc",
    ) -> PaginatedResponse[AuthorInfo]:
        """
        Fetch authors from the database with pagination and sorting.

        Args:
            user_id: User ID to filter authors
            platform_id: Filter by platform ID
            page: Page number (starting from 1)
            page_size: Number of items per page
            sort_by: Field to sort by
            order: Sort order (asc/desc)

        Returns:
            PaginatedResponse containing list of AuthorInfo and pagination info
        """
        try:
            offset = (page - 1) * page_size
            with ContentDAO() as dao:
                authors, total = dao.list_authors(
                    user_id=user_id,
                    platform_id=platform_id,
                    limit=page_size,
                    offset=offset,
                    sort_by=sort_by,
                    order=order,
                )

            items = [AuthorInfo.from_entity(author) for author in authors]
            total_pages = (total + page_size - 1) // page_size

            return PaginatedResponse(
                items=items,
                pagination=PaginationInfo(
                    page=page, page_size=page_size, total=total, total_pages=total_pages
                ),
            )
        except Exception:
            logger.exception("Error fetching authors from the database")
            raise

    async def delete_platform(self, user_id: int, platform_id: int) -> bool:
        """
        Delete platform and all related data (authors, parse results, media files).

        Args:
            user_id: User ID performing the deletion
            platform_id: Platform ID to delete

        Returns:
            True if deletion was successful
        """
        try:
            with ContentDAO() as dao:
                success, file_paths = dao.delete_platform(
                    user_id, platform_id, commit=True
                )

            if success and file_paths:
                deleted, failed = media_service.delete_media_files(file_paths)
                logger.info(
                    f"Deleted platform {platform_id}: {len(file_paths)} files ({deleted} deleted, {failed} failed)"
                )

            return success
        except Exception:
            logger.exception(f"Error deleting platform {platform_id}")
            raise

    async def delete_author(self, user_id: int, author_id: int) -> bool:
        """
        Delete author and all related data (parse results, media files).

        Args:
            user_id: User ID performing the deletion
            author_id: Author ID to delete

        Returns:
            True if deletion was successful
        """
        try:
            with ContentDAO() as dao:
                success, file_paths = dao.delete_author(user_id, author_id, commit=True)

            if success and file_paths:
                deleted, failed = media_service.delete_media_files(file_paths)
                logger.info(
                    f"Deleted author {author_id}: {len(file_paths)} files ({deleted} deleted, {failed} failed)"
                )

            return success
        except Exception:
            logger.exception(f"Error deleting author {author_id}")
            raise

    async def delete_parse_result(self, user_id: int, parse_result_id: int) -> bool:
        """
        Delete parse result and associated media files.

        Args:
            user_id: User ID performing the deletion
            parse_result_id: Parse result ID to delete

        Returns:
            True if deletion was successful
        """
        try:
            with ContentDAO() as dao:
                success, file_paths = dao.delete_parse_result(
                    user_id, parse_result_id, commit=True
                )

            if success and file_paths:
                deleted, failed = media_service.delete_media_files(file_paths)
                logger.info(
                    f"Deleted parse result {parse_result_id}: {len(file_paths)} files"
                    f" ({deleted} deleted, {failed} failed)"
                )

            return success
        except Exception:
            logger.exception(f"Error deleting parse result {parse_result_id}")
            raise

    async def increment_sync(
        self,
        user_id: int,
        last_sync_time: datetime | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> SyncResponse[URLParserResult]:
        """
        Incrementally sync content for the user based on last sync time.

        Args:
            user_id: User ID to sync content for
            last_sync_time: Optional datetime of the last sync time. If not provided, will return all content.
            page: Page number (starting from 1)
            page_size: Number of items per page

        Returns:
            SyncResponse with items, pagination info, and server sync_timestamp
        """
        try:
            # Capture server timestamp BEFORE query to ensure no data is missed
            sync_timestamp = datetime.now(UTC)

            offset = (page - 1) * page_size
            with ContentDAO() as dao:
                results, total = dao.sync_parse_results(
                    user_id=user_id,
                    last_sync_time=last_sync_time,
                    limit=page_size,
                    offset=offset,
                )

            items = [URLParserResult.from_entity(result) for result in results]
            total_pages = (total + page_size - 1) // page_size

            return SyncResponse(
                items=items,
                pagination=PaginationInfo(
                    page=page, page_size=page_size, total=total, total_pages=total_pages
                ),
                sync_timestamp=sync_timestamp,
            )
        except Exception:
            logger.exception(f"Error syncing content for user {user_id}")
            raise


content_service = ContentService()

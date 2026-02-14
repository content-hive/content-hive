"""
Parser service for fetching and parsing URL content.
"""

from typing import Optional
from pydantic import HttpUrl
from contenthive.logger import logger
from contenthive.models.content import (
    URLParserResult, 
    PlatformInfo, 
    AuthorInfo, 
    PaginatedResponse, 
    PaginationInfo
)
from contenthive.database.contentDAO import ParserDAO
from contenthive.plugins.manager import get_plugin_manager
from contenthive.services.media import mediaService

class ParserService:
    """
    Parser service for fetching and parsing URL content.
    """
    def __init__(self):
        """
        Initialize the ParserService.
        """
        pass

    async def _find_parser_for_url(self, url: str, preferred_domain: Optional[str] = None) -> Optional[str]:
        """
        Find parser entity for URL.
        """
        manager = get_plugin_manager()
        if not manager:
            raise Exception("Plugin manager not initialized")
        
        parser_domains = [
            domain for domain in manager.services.keys()
            if "can_parse" in manager.services.get(domain, {})
        ]

        # Try preferred parser first
        if preferred_domain and preferred_domain in parser_domains:
            try:
                if await manager.call_service(preferred_domain, "can_parse", {"url": url}):
                    return preferred_domain
            except Exception as e:
                logger.error(f"Error checking preferred parser {preferred_domain}: {e}")
        
        # Try all parsers
        for domain in parser_domains:
            if preferred_domain and domain == preferred_domain:
                continue
            
            try:
                if await manager.call_service(domain, "can_parse", {"url": url}):
                    return domain
            except Exception as e:
                logger.error(f"Error checking {domain}: {e}")
        
        return None
    
    async def parser_content(
        self, 
        user_id: int,
        url: HttpUrl, 
        plugin_id: Optional[str] = None,
        download_media: bool = True
    ) -> Optional[URLParserResult]:
        """
        Fetch and parse content from the given URL.
        
        Args:
            url: URL to parse
            plugin_id: Optional specific plugin to use
            download_media: Whether to download media files locally
        """
        try:
            logger.info(f"Fetching content from URL: {url}")

            manager = get_plugin_manager()
            if not manager:
                raise Exception("Plugin manager not initialized")
            
            # Find parser for URL
            domain = await self._find_parser_for_url(str(url), preferred_domain=plugin_id)
            
            if not domain:
                raise Exception(f"No parser found for URL: {url}")
            
            logger.info(f"Using parser plugin: {domain} for URL: {url}")
            
            # Parse content
            result = await manager.call_service(domain, "parse", {"url": str(url)})
            
            if not result:
                raise Exception(f"Parser returned empty result for URL: {url}")
            
            logger.info(f"Successfully parsed content from URL: {url} using plugin: {domain}")
            
            # Save parse result to database
            with ParserDAO() as dao:
                parse_result_id = dao.save_parse_result(result, user_id=user_id)

            # Download media files if requested
            if download_media and result.media:
                downloaded_media = await mediaService.download_media_for_result(result)
                with ParserDAO() as dao:
                    dao.save_downloaded_medias(downloaded_media, commit=True)
            
            # Return the saved parse result (with or without media)
            with ParserDAO() as dao:
                entity = dao.get_parse_result(parse_result_id)
                return URLParserResult.from_entity(entity)
                
        except Exception as e:
            logger.error(f"Error fetching content from URL {url}: {e}")
            raise

    async def list_contents(
            self,
            user_id: int,
            platform_id: Optional[int] = None,
            author_id: Optional[int] = None,
            page: int = 1, page_size: int = 10,
            sort_by: str = "created_at", order: str = "desc"
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
            with ParserDAO() as dao:
                results, total = dao.list_parse_results(
                    user_id=user_id,
                    platform_id=platform_id, 
                    author_id=author_id,
                    limit=page_size,
                    offset=offset,
                    sort_by=sort_by,
                    order=order
                )
            
            items = [URLParserResult.from_entity(result) for result in results]
            total_pages = (total + page_size - 1) // page_size  # Ceiling division
            
            return PaginatedResponse(
                items=items,
                pagination=PaginationInfo(
                    page=page,
                    page_size=page_size,
                    total=total,
                    total_pages=total_pages
                )
            )
        except Exception as e:
            logger.error(f"Error fetching contents from the database: {e}")
            raise
    
    async def list_platforms(
            self,
            user_id: int,
            page: int = 1, page_size: int = 10,
            sort_by: str = "id", order: str = "asc"
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
            with ParserDAO() as dao:
                platforms, total = dao.list_platforms(
                    user_id=user_id,
                    limit=page_size,
                    offset=offset,
                    sort_by=sort_by,
                    order=order
                )
            
            items = [PlatformInfo.from_entity(platform) for platform in platforms]
            total_pages = (total + page_size - 1) // page_size
            
            return PaginatedResponse(
                items=items,
                pagination=PaginationInfo(
                    page=page,
                    page_size=page_size,
                    total=total,
                    total_pages=total_pages
                )
            )
        except Exception as e:
            logger.error(f"Error fetching platforms from the database: {e}")
            raise

    async def list_authors(
            self,
            user_id: int,
            platform_id: Optional[int] = None,
            page: int = 1, page_size: int = 10,
            sort_by: str = "id", order: str = "asc"
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
            with ParserDAO() as dao:
                authors, total = dao.list_authors(
                    user_id=user_id,
                    platform_id=platform_id,
                    limit=page_size,
                    offset=offset,
                    sort_by=sort_by,
                    order=order
                )
            
            items = [AuthorInfo.from_entity(author) for author in authors]
            total_pages = (total + page_size - 1) // page_size
            
            return PaginatedResponse(
                items=items,
                pagination=PaginationInfo(
                    page=page,
                    page_size=page_size,
                    total=total,
                    total_pages=total_pages
                )
            )
        except Exception as e:
            logger.error(f"Error fetching authors from the database: {e}")
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
            logger.info(f"Deleting platform {platform_id}")
            
            with ParserDAO() as dao:
                success, file_paths = dao.delete_platform(user_id, platform_id, commit=True)
            
            if success and file_paths:
                deleted, failed = mediaService.delete_media_files(file_paths)
                logger.info(f"Deleted platform {platform_id}: {len(file_paths)} files ({deleted} deleted, {failed} failed)")
            
            return success
        except Exception as e:
            logger.error(f"Error deleting platform {platform_id}: {e}")
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
            logger.info(f"Deleting author {author_id}")
            
            with ParserDAO() as dao:
                success, file_paths = dao.delete_author(user_id, author_id, commit=True)
            
            if success and file_paths:
                deleted, failed = mediaService.delete_media_files(file_paths)
                logger.info(f"Deleted author {author_id}: {len(file_paths)} files ({deleted} deleted, {failed} failed)")
            
            return success
        except Exception as e:
            logger.error(f"Error deleting author {author_id}: {e}")
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
            logger.info(f"Deleting parse result {parse_result_id}")
            
            with ParserDAO() as dao:
                success, file_paths = dao.delete_parse_result(user_id, parse_result_id, commit=True)
            
            if success and file_paths:
                deleted, failed = mediaService.delete_media_files(file_paths)
                logger.info(f"Deleted parse result {parse_result_id}: {len(file_paths)} files ({deleted} deleted, {failed} failed)")
            
            return success
        except Exception as e:
            logger.error(f"Error deleting parse result {parse_result_id}: {e}")
            raise

parserService = ParserService()


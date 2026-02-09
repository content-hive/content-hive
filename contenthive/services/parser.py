"""
Parser service for fetching and parsing URL content.
"""

from typing import Optional
from pydantic import HttpUrl
from contenthive.logger import logger
from contenthive.models.content import URLParserResult, PlatformInfo, AuthorInfo
from contenthive.database.parserDAO import parserDAO
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

    async def parser_content(
        self, 
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
            if manager:
                plugin_id, parser = await manager.async_find_parser_for_url(str(url), preferred_domain=plugin_id)
                if parser:
                    logger.info(f"Using parser plugin: {plugin_id} for URL: {url}")
                    result = await parser.parse(str(url))
                    if result:
                        logger.info(f"Successfully parsed content from URL: {url} using plugin: {plugin_id}")
                        
                        with parserDAO as dao:
                            parse_result_id = dao.save_parse_result(result)

                        # Download media files if requested
                        if download_media and result.media:
                            media_entities = await mediaService.download_media_for_result(result)
                            with parserDAO as dao:
                                dao.save_medias(media_entities, commit=True)
                        
                        # Return the saved parse result (with or without media)
                        with parserDAO as dao:
                            return dao.get_parse_result(parse_result_id)
        except Exception as e:
            logger.error(f"Error fetching content from URL {url}: {e}")
            raise

    async def list_contents(self, platform_id: Optional[int] = None, author_id: Optional[int] = None) -> list[URLParserResult]:
        """
        Fetch contents from the database.
        """
        try:
            with parserDAO as dao:
                results = dao.list_parse_results(platform_id=platform_id, author_id=author_id)
            return results
        except Exception as e:
            logger.error(f"Error fetching contents from the database: {e}")
            raise
    
    async def list_platforms(self) -> list[PlatformInfo]:
        """
        Fetch platforms from the database.
        """
        try:
            with parserDAO as dao:
                platforms = dao.list_platforms()
                return platforms
        except Exception as e:
            logger.error(f"Error fetching platforms from the database: {e}")
            raise

    async def list_authors(self, platform_id: Optional[int] = None) -> list[AuthorInfo]:
        """
        Fetch authors from the database.
        """
        try:
            with parserDAO as dao:
                authors = dao.list_authors(platform_id=platform_id)
                return authors
        except Exception as e:
            logger.error(f"Error fetching authors from the database: {e}")
            raise

parserService = ParserService()


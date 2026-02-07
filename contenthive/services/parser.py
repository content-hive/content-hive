"""
Parser service for fetching and parsing URL content.
"""

from typing import Optional
from pydantic import HttpUrl
from contenthive.logger import logger
from contenthive.main import get_plugin_manager
from contenthive.models.content import URLParserResult, PlatformInfo, AuthorInfo
from contenthive.database.ParserDAO import parserDAO

class ParserService:
    """
    Parser service for fetching and parsing URL content.
    """
    def __init__(self):
        """
        Initialize the ParserService.

        Args:
            context: ServiceContext object providing access to app, data_dir, db, and logger.
        """
        pass

    async def parser_content(self, url: HttpUrl, plugin_id: Optional[str] = None) -> Optional[URLParserResult]:
        """
        Fetch and parse content from the given URL.
        """
        try:
            logger.info(f"Fetching content from URL: {url}")

            manager = get_plugin_manager()
            if manager:
                plugin_id, parser = manager.find_parser_for_url(str(url), plugin_id=plugin_id)
                if parser:
                    logger.info(f"Using parser plugin: {plugin_id} for URL: {url}")
                    result = parser.parse(str(url))
                    if result:
                        logger.info(f"Successfully parsed content from URL: {url} using plugin: {plugin_id}")
                        return parserDAO.save_parse_result(result)
        except Exception as e:
            logger.error(f"Error fetching content from URL {url}: {e}")
            raise
        

    async def list_contents(self, platform_id: Optional[int] = None, author_id: Optional[int] = None) -> list[URLParserResult]:
        """
        Fetch contents from the database.
        """
        try:
            results = parserDAO.list_parse_results(platform_id=platform_id, author_id=author_id)
            return results
        except Exception as e:
            logger.error(f"Error fetching contents from the database: {e}")
            raise
    
    async def list_platforms(self) -> list[PlatformInfo]:
        """
        Fetch platforms from the database.
        """
        try:
            platforms = parserDAO.list_platforms()
            return platforms
        except Exception as e:
            logger.error(f"Error fetching platforms from the database: {e}")
            raise

    async def list_authors(self, platform_id: Optional[int] = None) -> list[AuthorInfo]:
        """
        Fetch authors from the database.
        """
        try:
            authors = parserDAO.list_authors(platform_id=platform_id)
            return authors
        except Exception as e:
            logger.error(f"Error fetching authors from the database: {e}")
            raise

parserService = ParserService()
    
    
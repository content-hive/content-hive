"""
Media service for downloading and managing media files.
"""

import asyncio
import mimetypes
import os
from typing import Optional
import aiohttp
import hashlib
from pathlib import Path

from pydantic import HttpUrl
from contenthive.logger import logger
from contenthive.models.enumerates import MediaStatus, MediaType
from contenthive.models.parser import ParserResult
from contenthive.models.content import DownloadedMediaInfo
from contenthive.config import settings
from urllib.parse import quote

class MediaService:
    """
    Service for handling media file downloads and management.
    """
    def __init__(self, media_dir: Path = settings.media_dir):
        """
        Initialize the MediaService.

        Args:
            media_dir: Base directory for storing media files.
        """
        self.media_dir = media_dir

    def get_relative_media_path(self, local_path: Path) -> str:
        """
        Convert local file path to web-accessible relative path.
        
        Args:
            local_path: Local file system path
            
        Returns:
            Relative path starting with /media/
        """
        try:
            relative_path = local_path.relative_to(self.media_dir)
            # URL encode the path components
            parts = [quote(part) for part in relative_path.parts]
            return "/media/" + "/".join(parts)
        except Exception as e:
            logger.error(f"Failed to generate relative media path: {e}")
            return ""


    async def download_single_media(
        self,
        platform: str,
        author: str,
        content_id: str,
        media_url: HttpUrl,
        media_type: MediaType,
        media_cover: Optional[HttpUrl] = None,
        media_description: Optional[str] = None,
        media_index: int = 0
    ) -> Optional[DownloadedMediaInfo]:
        """
        Download a single media file and its optional cover image, then return the local paths.
        Args:
            platform: Platform code (e.g., "twitter")
            author: Author username
            content_id: Content ID
            media_url: URL of the media to download
            media_type: Type of the media (e.g., image, video)
            media_cover: Optional URL of the cover image
            media_description: Optional description of the media
            media_index: Index of the media in the list
        Returns:
            DownloadedMediaInfo object or None if download failed
        """
        try:
            # Sanitize directory names
            platform = self._sanitize_filename(platform)
            author = self._sanitize_filename(author)
        
            media_dir = self.media_dir / platform / author / content_id
            media_dir.mkdir(parents=True, exist_ok=True)

            headers = {
                "User-Agent": settings.download_user_agent
            }
            async with aiohttp.ClientSession(trust_env=True, headers=headers) as session:
                local_path = await self._download_file(
                    session,
                    str(media_url),
                    media_dir,
                    media_index,
                    file_type="media"
                )
                cover_path = None
                if media_cover:
                    cover_path = await self._download_file(
                        session, 
                        str(media_cover), 
                        media_dir, 
                        media_index,
                        file_type="cover"
                    )

                downloaded_media = DownloadedMediaInfo(
                    status=MediaStatus.COMPLETED,
                    url=media_url,
                    type=media_type,
                    title=media_description,
                    cover=media_cover,
                    duration=0,
                    width=0,
                    height=0,
                    media_path=self.get_relative_media_path(local_path),
                    cover_path=self.get_relative_media_path(cover_path) if cover_path else None
                )

                return downloaded_media
        except Exception as e:
            logger.error(f"Failed to create media directory: {e}")
            return None

    async def _download_file(
        self, 
        session: aiohttp.ClientSession, 
        url: str, 
        save_dir: Path, 
        index: int,
        file_type: str = "media"
    ) -> Path:
        """
        Download a single file with retry logic.
        
        Args:
            session: aiohttp session
            url: URL of the file to download
            save_dir: Directory to save the file to
            index: File index used in the filename
            file_type: File type used in the filename, e.g. "media" or "cover"
            
        Returns:
            Path to the saved file
        """
        last_error: Exception = Exception("Unknown error")
        for attempt in range(settings.download_max_retries + 1):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    response.raise_for_status()

                    # Get file extension from URL or content-type
                    content_type = response.headers.get('content-type', '')
                    ext = self._get_file_extension(url, content_type)

                    filename = f"{index:03d}_{file_type}{ext}"
                    filepath = save_dir / filename

                    # Save file
                    with open(filepath, 'wb') as f:
                        f.write(await response.read())

                    return filepath
            except Exception as e:
                last_error = e
                if attempt < settings.download_max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        f"Download attempt {attempt + 1}/{settings.download_max_retries + 1} "
                        f"failed for {url}, retrying in {wait}s: {e}"
                    )
                    await asyncio.sleep(wait)

        raise last_error

    def _get_media_directory(self, result: ParserResult) -> Path:
        """
        Get the directory path for storing media files.
        
        Args:
            result: Parser result
            
        Returns:
            Path to media directory
        """
        platform = result.platform.code if result.platform else "unknown"
        author = result.author.username if result.author else "unknown"

        # Sanitize directory names
        platform = self._sanitize_filename(platform)
        author = self._sanitize_filename(author)
        
        # Use content ID or hash of URL as unique identifier
        content_id = str(result.pid) if result.pid else hashlib.md5(str(result.url).encode()).hexdigest()[:16]
        
        return self.media_dir / platform / author / content_id


    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """
        Sanitize filename by removing invalid characters.
        
        Args:
            name: Original filename
            
        Returns:
            Sanitized filename
        """
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        return name.strip()[:100]  # Limit length

    @staticmethod
    def _get_file_extension(url: str, content_type: str) -> str:
        """
        Get file extension from URL or content-type.
        
        Args:
            url: File URL
            content_type: HTTP content-type header
            
        Returns:
            File extension with leading dot
        """
        # Try to get extension from URL
        url_ext = os.path.splitext(url.split('?')[0])[1]
        if url_ext and len(url_ext) <= 5:
            return url_ext
        
        # Fallback to content-type
        ext = mimetypes.guess_extension(content_type.split(';')[0].strip())
        if ext:
            return ext
        return ''

    def delete_media_files(self, file_paths: list[str]) -> tuple[int, int]:
        """
        Delete media files from disk given their relative paths.
        
        Args:
            file_paths: List of media file paths (relative paths starting with /media/)
            
        Returns:
            Tuple of (deleted_count, failed_count)
        """
        if not file_paths:
            return 0, 0
        
        deleted_count = 0
        failed_count = 0
        
        media_root = self.media_dir.resolve()

        for media_path in file_paths:
            try:
                # Convert relative path to absolute path
                if media_path.startswith('/media/'):
                    abs_path = self.media_dir / media_path[7:]  # Remove '/media/'
                    resolved_path = abs_path.resolve()
                    
                    # Check if path is within media directory
                    if resolved_path == media_root or media_root not in resolved_path.parents:
                        failed_count += 1
                        logger.warning(f"Attempted to delete file outside media directory: {resolved_path}")
                        continue

                    if resolved_path.exists():
                        resolved_path.unlink()
                        deleted_count += 1
                        logger.debug(f"Deleted media file: {resolved_path}")
                    else:
                        logger.debug(f"File does not exist: {resolved_path}")
            except Exception as e:
                failed_count += 1
                logger.warning(f"Failed to delete media file {media_path}: {e}")
        
        if deleted_count > 0 or failed_count > 0:
            logger.info(f"Media file cleanup: {deleted_count} deleted, {failed_count} failed")
        
        return deleted_count, failed_count

media_service = MediaService()
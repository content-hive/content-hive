"""
Media service for downloading and managing media files.
"""

import os
import aiohttp
import hashlib
import shutil
from pathlib import Path
from contenthive.logger import logger
from contenthive.models.enumerates import MediaStatus
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

    async def download_media_for_result(self, result: ParserResult) -> list[DownloadedMediaInfo]:
        """
        Download all media files for a parser result.
        
        Args:
            result: Parser result containing media URLs
            
        Returns:
            List of DownloadedMediaInfo with updated local paths
        """
        if not (result.media):
            return []
        
        media_dir = self._get_media_directory(result)
        media_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Downloading {len(result.media)} media files to {media_dir}")
        
        local_media_items = []
        async with aiohttp.ClientSession(trust_env=True) as session:
            for i, media in enumerate(result.media):
                try:
                    local_path = await self._download_single_media(
                        session, 
                        str(media.url), 
                        media_dir, 
                        index=i
                    )
                    
                    cover_path = None
                    if media.cover:
                        # Download cover image if available
                        cover_path = await self._download_single_media(
                            session,
                            str(media.cover),
                            media_dir,
                            index=i
                        )

                    downloaded_media = DownloadedMediaInfo(
                        status=MediaStatus.COMPLETED,
                        url=media.url,
                        type=media.type,
                        title=media.title,
                        cover=media.cover,
                        duration=0,
                        width=0,
                        height=0,
                        media_path=self.get_relative_media_path(local_path),
                        cover_path=self.get_relative_media_path(cover_path) if cover_path else None
                    )

                    local_media_items.append(downloaded_media)
                    logger.info(f"Downloaded media {i+1}/{len(result.media)}: {downloaded_media.media_path}")
                except Exception as e:
                    failed_media = DownloadedMediaInfo(
                        status=MediaStatus.FAILED,
                        url=media.url,
                        type=media.type,
                        title=media.title,
                        cover=media.cover,
                        duration=0,
                        width=0,
                        height=0,                        
                        media_path=None,
                        cover_path=None
                    )
                    local_media_items.append(failed_media)
                    logger.error(f"Failed to download media {media.url}: {e}")
                    continue
        
        return local_media_items

    async def _download_single_media(
        self, 
        session: aiohttp.ClientSession, 
        url: str, 
        save_dir: Path, 
        index: int
    ) -> Path:
        """
        Download a single media file.
        
        Args:
            session: aiohttp session
            url: Media URL to download
            save_dir: Directory to save the file
            index: Index of the media in the list
            
        Returns:
            Path to the saved file
        """
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response:
            response.raise_for_status()
            
            # Get file extension from URL or content-type
            content_type = response.headers.get('content-type', '')
            ext = self._get_file_extension(url, content_type)
            
            # Generate filename using hash to avoid conflicts
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            filename = f"media_{index:03d}_{url_hash}{ext}"
            filepath = save_dir / filename
            
            # Save file
            with open(filepath, 'wb') as f:
                f.write(await response.read())
            
            return filepath

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

    def delete_media_for_result(self, result: ParserResult) -> bool:
        """
        Delete all media files for a parser result.
        
        Args:
            result: Parser result
            
        Returns:
            True if successful, False otherwise
        """
        try:
            media_dir = self._get_media_directory(result)
            if media_dir.exists():
                shutil.rmtree(media_dir)
                logger.info(f"Deleted media directory: {media_dir}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete media directory: {e}")
            return False

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
        type_map = {
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/webp': '.webp',
            'video/mp4': '.mp4',
            'video/webm': '.webm',
            'video/quicktime': '.mov',
        }
        return type_map.get(content_type.split(';')[0].strip(), '')

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
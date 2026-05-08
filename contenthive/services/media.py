"""
Media service for downloading and managing media files.
"""

import asyncio
import hashlib
import mimetypes
import os
import shutil
from pathlib import Path
from urllib.parse import quote

import aiofiles
import aiohttp
import magic

from contenthive.config import settings
from contenthive.logger import logger
from contenthive.models.content import DownloadedMediaInfo
from contenthive.models.enumerates import MediaStatus
from contenthive.plugins.contracts import ParserMediaInfo
from contenthive.plugins.manager import get_plugin_manager


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

    def _get_relative_media_path(self, local_path: Path) -> str:
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
        except Exception:
            logger.exception("Failed to generate relative media path")
            return ""

    async def download_media(
        self,
        platform: str,
        author: str,
        content_id: str,
        media: ParserMediaInfo,
        media_index: int = 0,
        plugin_domain: str | None = None,
    ) -> DownloadedMediaInfo | None:
        """
        Download a single media file, using a plugin download service when available
        and falling back to the built-in HTTP downloader otherwise.

        Args:
            platform: Platform code
            author: Author username or uid
            content_id: Content ID
            media: Media information from parser
            media_index: Index of the media item (used in filename)
            plugin_domain: Plugin domain to use for download (from ParserResult.parser).
                           If the plugin has registered a "download" service it will be used;
                           otherwise falls back to the built-in downloader.

        Returns:
            DownloadedMediaInfo on success, or None if the download fails (whether via
            plugin or the built-in downloader)
        """
        save_dir = self._prepare_media_directory(platform, author, content_id)
        manager = get_plugin_manager()

        try:
            if (
                plugin_domain
                and manager
                and manager.has_service(plugin_domain, "download")
            ):
                logger.debug(f"Using plugin '{plugin_domain}' download service")
                plugin_result = await manager.call_service(
                    plugin_domain,
                    "download",
                    {
                        "media": media.model_dump(mode="json"),
                    },
                )
                media_path, cover_path = self._move_plugin_download_result(
                    save_dir=save_dir,
                    plugin_result=plugin_result,
                    media_index=media_index,
                    media_url=media.url,
                    media_cover=media.cover,
                )
            else:
                logger.debug("Using built-in downloader")
                media_urls = [media.url] + list(media.url_fallbacks or [])
                cover_urls = ([media.cover] if media.cover else []) + list(
                    media.cover_fallbacks or []
                )
                media_path, cover_path = await self._download_single_media(
                    save_dir=save_dir,
                    media_urls=media_urls,
                    media_index=media_index,
                    cover_urls=cover_urls,
                )
        except Exception:
            logger.exception(
                f"Failed to download media for content {content_id}: {media.url}"
            )
            return None

        return DownloadedMediaInfo(
            status=MediaStatus.COMPLETED,
            url=media.url,
            type=media.type,
            title=media.title,
            cover=media.cover,
            url_fallbacks=media.url_fallbacks or [],
            cover_fallbacks=media.cover_fallbacks or [],
            duration=media.duration,
            width=media.width,
            height=media.height,
            media_path=self._get_relative_media_path(media_path),
            cover_path=self._get_relative_media_path(cover_path)
            if cover_path
            else None,
        )

    def _prepare_media_directory(
        self, platform: str, author: str, content_id: str
    ) -> Path:
        """
        Build and create the media save directory, return the Path.

        Args:
            platform: Platform code
            author: Author username or uid
            content_id: Content ID

        Returns:
            Path to the created directory
        """
        platform = self._sanitize_filename(platform)
        author = self._sanitize_filename(author)
        content_id = self._sanitize_filename(content_id)
        save_dir = self.media_dir / platform / author / content_id
        save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir

    def _move_plugin_download_result(
        self,
        save_dir: Path,
        plugin_result: dict,
        media_index: int,
        media_url: str,
        media_cover: str | None,
    ) -> tuple[Path, Path | None]:
        """
        Validate plugin-returned temporary file paths and move them into save_dir.

        Args:
            save_dir: Destination directory
            plugin_result: Dict with keys "media_path" (Path) and optional "cover_path" (Path)
            media_index: Media index used in the filename
            media_url: Original media URL, used to compute filename hash
            media_cover: Original cover URL, used to compute filename hash

        Returns:
            Tuple of (media_path, cover_path)
        """
        temp_media = self._validate_plugin_temp_path(plugin_result["media_path"])
        temp_cover = self._validate_plugin_temp_path(plugin_result.get("cover_path"))

        if temp_media is None:
            raise RuntimeError("Plugin result missing required 'media_path'")
        media_path = self._move_to_save_dir(
            temp_media, save_dir, media_index, "media", media_url
        )
        cover_path = (
            self._move_to_save_dir(
                temp_cover, save_dir, media_index, "cover", media_cover
            )
            if temp_cover and media_cover
            else None
        )
        return media_path, cover_path

    async def _download_single_media(
        self,
        save_dir: Path,
        media_urls: list[str],
        media_index: int,
        cover_urls: list[str],
    ) -> tuple[Path, Path | None]:
        """
        Download media and optional cover concurrently into save_dir.
        Each accepts a list of URLs; fallback order is handled inside _download_file.

        Returns:
            Tuple of (media_path, cover_path)
        """
        headers = {"User-Agent": settings.download_user_agent}
        async with aiohttp.ClientSession(trust_env=True, headers=headers) as session:
            tasks = [
                self._download_file(session, media_urls, save_dir, media_index, "media")
            ]
            if cover_urls:
                tasks.append(
                    self._download_file(
                        session, cover_urls, save_dir, media_index, "cover"
                    )
                )
            results = await asyncio.gather(*tasks, return_exceptions=True)

        media_result = results[0]
        if isinstance(media_result, BaseException):
            raise media_result

        cover_result = results[1] if cover_urls else None
        if isinstance(cover_result, BaseException):
            logger.warning(f"Cover download failed, skipping: {cover_result}")
            cover_result = None

        return media_result, cover_result

    async def _download_file(
        self,
        session: aiohttp.ClientSession,
        urls: list[str],
        save_dir: Path,
        index: int,
        file_type: str = "media",
    ) -> Path:
        """
        Download a file with fallback URL support and per-URL retry logic.

        Tries each URL in order. For each URL, retries on transient errors up to
        download_max_retries times. Moves to the next fallback URL on 4xx or when
        all retries are exhausted. Raises the last error if all URLs fail.

        Args:
            session: aiohttp session
            urls: Ordered list of URLs to try (primary first, then fallbacks)
            save_dir: Directory to save the file to
            index: File index used in the filename
            file_type: File type used in the filename, e.g. "media" or "cover"

        Returns:
            Path to the saved file
        """
        last_error: Exception = Exception("No URLs provided")

        for url_attempt, url in enumerate(urls):
            url_last_error: Exception = Exception("Unknown error")
            for retry in range(settings.download_max_retries + 1):
                try:
                    async with session.get(
                        url, timeout=aiohttp.ClientTimeout(total=60)
                    ) as response:
                        response.raise_for_status()

                        # Read first chunk to detect MIME type from magic bytes
                        first_chunk = await response.content.read(4096)
                        if not first_chunk:
                            raise aiohttp.ClientError("Empty response body")

                        content_type = response.headers.get("content-type", "")
                        ext = self._detect_extension(first_chunk, url, content_type)

                        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                        filename = f"{index:03d}_{file_type}_{url_hash}{ext}"
                        filepath = save_dir / filename

                        # Write first chunk then stream the rest to disk
                        async with aiofiles.open(filepath, "wb") as f:
                            await f.write(first_chunk)
                            async for chunk in response.content.iter_chunked(65536):
                                await f.write(chunk)

                        logger.debug(f"Downloaded {file_type} from {url} -> {filepath}")
                        return filepath
                except aiohttp.ClientResponseError as e:
                    url_last_error = e
                    if 400 <= e.status < 500:
                        break  # 4xx: no point retrying this URL; try next fallback
                except (TimeoutError, aiohttp.ClientError) as e:
                    # Transient network / timeout errors are safe to retry
                    url_last_error = e
                # All other exceptions (OSError, CancelledError, etc.) propagate immediately

                if retry < settings.download_max_retries:
                    wait = 2**retry
                    logger.warning(
                        f"Download attempt {retry + 1}/{settings.download_max_retries + 1} "
                        f"failed for {url}, retrying in {wait}s: {url_last_error}"
                    )
                    await asyncio.sleep(wait)

            # This URL exhausted all retries (or got 4xx); try next fallback
            last_error = url_last_error
            if url_attempt < len(urls) - 1:
                logger.warning(
                    f"{file_type} URL {url_attempt + 1}/{len(urls)} failed ({url}), "
                    f"trying fallback: {urls[url_attempt + 1]}"
                )

        raise last_error

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
            name = name.replace(char, "_")
        return name.strip()[:100]  # Limit length

    # Normalise extensions that mimetypes.guess_extension returns inconsistently
    # across platforms (e.g. .jpe / .jpeg → .jpg on some systems).
    _EXT_NORMALISE: dict[str, str] = {
        ".jpe": ".jpg",
        ".jpeg": ".jpg",
    }

    @classmethod
    def _detect_extension(cls, data: bytes, url: str, content_type: str) -> str:
        """
        Determine the file extension using magic bytes first, then URL, then
        Content-Type header as successive fallbacks.

        Args:
            data: First bytes of the downloaded file (used for magic detection).
            url: Source URL of the file.
            content_type: HTTP Content-Type header value.

        Returns:
            File extension with leading dot, or empty string if undetermined.
        """
        # 1. Magic-byte detection — most reliable
        try:
            mime = magic.from_buffer(data, mime=True)
            if mime:
                ext = mimetypes.guess_extension(mime)
                if ext:
                    return cls._EXT_NORMALISE.get(ext, ext)
        except Exception:
            pass

        # 2. Extension embedded in the URL path
        url_ext = os.path.splitext(url.split("?")[0])[1]
        if url_ext and len(url_ext) <= 5:
            return url_ext

        # 3. Content-Type header
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext:
            return cls._EXT_NORMALISE.get(ext, ext)

        return ""

    def _validate_plugin_temp_path(self, path: str | None) -> Path | None:
        """
        Validate that a plugin-returned path points to an existing regular file
        (not a symlink or directory).

        Args:
            path: Path-like or None returned by the plugin

        Returns:
            Resolved Path, or None if path is None

        Raises:
            RuntimeError: If the path does not exist, is a symlink, or is not a regular file
        """
        if path is None:
            return None
        original = Path(path)
        # Check the original path before resolve() follows any symlinks.
        if original.is_symlink():
            raise RuntimeError(
                f"Plugin returned a symlink, which is not allowed: {original}"
            )
        try:
            resolved = original.resolve(strict=True)
        except OSError:
            raise RuntimeError(f"Plugin returned non-existent path: {original}")
        if not resolved.is_file():
            raise RuntimeError(
                f"Plugin returned invalid path (not a regular file): {resolved}"
            )
        return resolved

    def _move_to_save_dir(
        self, temp_path: Path, save_dir: Path, index: int, file_type: str, url: str
    ) -> Path:
        """
        Move a plugin's temporary file into save_dir, detecting its extension via
        magic bytes and naming it with the same convention as _download_file():
        {index:03d}_{file_type}_{url_hash}{ext}.

        Args:
            temp_path: Validated temporary file path
            save_dir: Destination directory
            index: Media index used in filename
            file_type: "media" or "cover"
            url: Original URL, used to compute filename hash

        Returns:
            Final path of the moved file
        """
        with temp_path.open("rb") as f:
            first_chunk = f.read(4096)
        ext = self._detect_extension(first_chunk, url, "")
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        filename = f"{index:03d}_{file_type}_{url_hash}{ext}"
        final_path = save_dir / filename
        shutil.move(str(temp_path), final_path)
        logger.debug(f"Moved plugin file {temp_path} -> {final_path}")
        return final_path

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
                if media_path.startswith("/media/"):
                    abs_path = self.media_dir / media_path[7:]  # Remove '/media/'
                    resolved_path = abs_path.resolve()

                    # Check if path is within media directory
                    if (
                        resolved_path == media_root
                        or media_root not in resolved_path.parents
                    ):
                        failed_count += 1
                        logger.warning(
                            f"Attempted to delete file outside media directory: {resolved_path}"
                        )
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
            logger.info(
                f"Media file cleanup: {deleted_count} deleted, {failed_count} failed"
            )

        return deleted_count, failed_count


media_service = MediaService()

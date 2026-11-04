"""
Media service for downloading and managing media files.
"""

import asyncio
import hashlib
import mimetypes
import os
import shutil
import tempfile
from pathlib import Path
from typing import ClassVar
from urllib.parse import quote, unquote

import aiofiles
import aiohttp
import magic

from contenthive.config import settings
from contenthive.logger import logger
from contenthive.models.content import DownloadedMediaInfo
from contenthive.models.download import DownloadRetryInfo
from contenthive.models.enumerates import AuthorProfileAsset, DownloadRetryPhase, MediaStatus
from contenthive.plugins.contracts import ParserMediaInfo
from contenthive.plugins.manager import get_plugin_manager
from contenthive.services.assemble import assemble_streams
from contenthive.settings.store import get_settings
from contenthive.utils.live_download import (
    BoundPercentProgress,
    ByteProgressCallback,
    DownloadStateCallback,
    ProgressCallback,
    bind_percent_progress,
    invoke_byte_progress,
    invoke_download_state,
    invoke_progress,
)
from contenthive.utils.path_safety import is_path_within_base, sanitize_path_component


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

    def get_content_directory(self, platform: str, author_uid: str, content_id: str) -> Path:
        """
        Build the content save directory path without creating it.

        Args:
            platform: Platform code
            author_uid: Author uid
            content_id: Content directory name (already resolved or raw; will be sanitized)

        Returns:
            Path to the content directory
        """
        platform = sanitize_path_component(platform)
        author_uid = sanitize_path_component(author_uid)
        content_id = sanitize_path_component(content_id)
        return self.media_dir / platform / author_uid / content_id

    def get_author_directory(self, platform: str, author_uid: str) -> Path:
        """
        Build the author directory path without creating it.

        Args:
            platform: Platform code
            author_uid: Author uid

        Returns:
            Path to the author directory
        """
        platform = sanitize_path_component(platform)
        author_uid = sanitize_path_component(author_uid)
        return self.media_dir / platform / author_uid

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
        on_progress: ProgressCallback | None = None,
        on_download_state: DownloadStateCallback | None = None,
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
            on_progress: Optional 0-100 percent callback for the main media file
                (cover is downloaded in parallel but not included).
            on_download_state: Optional live retry/phase callback (built-in downloader only).

        Returns:
            DownloadedMediaInfo on success, or None if the download fails (whether via
            plugin or the built-in downloader)
        """
        save_dir = self._prepare_media_directory(platform, author, content_id)
        manager = get_plugin_manager()
        temps: dict[str, Path] = {}
        assembled_files: list[Path] = []

        try:
            if plugin_domain and manager and manager.has_service(plugin_domain, "download"):
                logger.debug(f"Using plugin '{plugin_domain}' download service")
                plugin_result = await manager.call_service(
                    plugin_domain,
                    "download",
                    {
                        "media": media.model_dump(mode="json"),
                        "on_progress": on_progress,
                    },
                )
                temps = self._temps_from_plugin_result(plugin_result)
            else:
                logger.debug("Using built-in downloader")
                temps = await self._download_streams_builtin(
                    media,
                    on_progress=on_progress,
                    on_download_state=on_download_state,
                )
            assembled = await assemble_streams(media, temps)
            temps = {}
            assembled_files = [path for path in (assembled.media_path, assembled.cover_path) if path is not None]
            media_path = (
                self._move_to_save_dir(assembled.media_path, save_dir, media_index, "media", media.hash_url())
                if assembled.media_path is not None
                else None
            )
            cover_stream = media.cover_file_stream()
            cover_path = (
                self._move_to_save_dir(assembled.cover_path, save_dir, media_index, "cover", cover_stream.urls[0])
                if assembled.cover_path is not None and cover_stream is not None
                else None
            )
        except Exception:
            for path in temps.values():
                path.unlink(missing_ok=True)
            for path in assembled_files:
                path.unlink(missing_ok=True)
            logger.exception(f"Failed to download media for content {content_id}: {media.source_key}")
            return None

        return DownloadedMediaInfo(
            status=MediaStatus.COMPLETED,
            source_key=media.source_key,
            type=media.type,
            title=media.title,
            streams=list(media.streams),
            extra=dict(media.extra or {}),
            media_path=self._get_relative_media_path(media_path) if media_path else None,
            media_duration=assembled.media_duration,
            media_width=assembled.media_width,
            media_height=assembled.media_height,
            cover_path=self._get_relative_media_path(cover_path) if cover_path else None,
            cover_width=assembled.cover_width,
            cover_height=assembled.cover_height,
        )

    def _prepare_media_directory(self, platform: str, author: str, content_id: str) -> Path:
        """
        Build and create the media save directory, return the Path.

        Args:
            platform: Platform code
            author: Author username or uid
            content_id: Content ID

        Returns:
            Path to the created directory
        """
        save_dir = self.get_content_directory(platform, author, content_id)
        save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir

    def _prepare_author_directory(self, platform: str, author_uid: str) -> Path:
        """
        Build and create the author directory used for profile assets, return the Path.

        Profile assets (avatar / banner) live directly under the author directory,
        one level above content media's per-content_id subdirectories.

        Args:
            platform: Platform code
            author_uid: Author uid

        Returns:
            Path to the created directory
        """
        save_dir = self.get_author_directory(platform, author_uid)
        save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir

    async def download_author_profile_asset(
        self,
        platform: str,
        author_uid: str,
        asset: AuthorProfileAsset,
        url: str,
        on_progress: ProgressCallback | None = None,
        on_download_state: DownloadStateCallback | None = None,
    ) -> str | None:
        """
        Download a single author profile asset (avatar or banner).

        Files are stored under {media_dir}/{platform}/{author_uid}/ and named
        {asset}_{url_hash}{ext}. Always uses the built-in downloader.

        Args:
            platform: Platform code
            author_uid: Author uid (used as the directory name)
            asset: Avatar or banner
            url: Remote asset URL
            on_progress: Optional 0-100 percent callback
            on_download_state: Optional live retry/phase callback

        Returns:
            /media-relative web path, or None if download failed.
        """
        save_dir = self._prepare_author_directory(platform, author_uid)
        headers = {"User-Agent": get_settings().download.user_agent}
        bound = bind_percent_progress(on_progress)
        async with aiohttp.ClientSession(trust_env=True, headers=headers) as session:
            try:
                result = await self._download_file(
                    session,
                    [url],
                    save_dir,
                    None,
                    asset.value,
                    on_byte_progress=bound,
                    on_progress=on_progress,
                    on_download_state=on_download_state,
                )
            except Exception:
                logger.exception(f"Failed to download author {asset.value} for {platform}/{author_uid}")
                return None
        await invoke_progress(on_progress, 100)
        return self._get_relative_media_path(result)

    def _temps_from_plugin_result(self, plugin_result: dict) -> dict[str, Path]:
        """Validate plugin-returned per-role temporary files."""
        raw = plugin_result.get("streams")
        if not isinstance(raw, dict):
            raise RuntimeError("Plugin download result missing 'streams'")
        temps: dict[str, Path] = {}
        for role, path in raw.items():
            if not isinstance(role, str) or not role:
                raise RuntimeError(f"Plugin returned invalid stream role: {role!r}")
            validated = self._validate_plugin_temp_path(path)
            if validated is None:
                raise RuntimeError(f"Plugin returned empty path for stream {role}")
            temps[role] = validated
        return temps

    async def _download_streams_builtin(
        self,
        media: ParserMediaInfo,
        on_progress: ProgressCallback | None = None,
        on_download_state: DownloadStateCallback | None = None,
    ) -> dict[str, Path]:
        """Download each downloadable stream to a temporary file."""
        streams = media.downloadable_streams()
        if not streams:
            await invoke_progress(on_progress, 100)
            return {}

        headers = {"User-Agent": get_settings().download.user_agent}
        progress_roles = {stream.role for stream in streams if stream.role != "cover"}
        combined = _CombinedStreamProgress(on_progress) if len(progress_roles) > 1 else None
        single = bind_percent_progress(on_progress) if combined is None else None

        temps: dict[str, Path] = {}
        try:
            async with aiohttp.ClientSession(trust_env=True, headers=headers) as session:
                tasks = []
                roles: list[str] = []
                for stream in streams:
                    roles.append(stream.role)
                    if combined is not None and stream.role != "cover":
                        byte_progress = combined.bind(stream.role)
                    elif stream.role != "cover":
                        byte_progress = single
                    else:
                        byte_progress = None
                    tasks.append(
                        self._download_to_temp(
                            session,
                            stream.urls,
                            on_byte_progress=byte_progress,
                            on_progress=on_progress if stream.role != "cover" and combined is None else None,
                            on_download_state=on_download_state if stream.role != "cover" else None,
                        )
                    )
                results = await asyncio.gather(*tasks, return_exceptions=True)

            required_error: BaseException | None = None
            for role, result in zip(roles, results, strict=True):
                if isinstance(result, BaseException):
                    if role == "cover":
                        logger.warning(f"Cover download failed, skipping: {result}")
                        continue
                    if required_error is None:
                        required_error = result
                    continue
                temps[role] = result
            if required_error is not None:
                raise required_error
            await invoke_progress(on_progress, 100)
            return temps
        except Exception:
            for path in temps.values():
                path.unlink(missing_ok=True)
            raise

    async def _download_to_temp(
        self,
        session: aiohttp.ClientSession,
        urls: list[str],
        on_byte_progress: BoundPercentProgress | ByteProgressCallback | None = None,
        on_progress: ProgressCallback | None = None,
        on_download_state: DownloadStateCallback | None = None,
    ) -> Path:
        """Download a file to a temporary path with fallback URL support."""
        last_error: Exception = Exception("No URLs provided")
        download_max_retries = get_settings().download.max_retries
        max_attempts = download_max_retries + 1
        url_count = len(urls)

        for url_index, url in enumerate(urls):
            url_last_error: Exception = Exception("Unknown error")
            for retry in range(max_attempts):
                attempt = retry + 1
                if attempt > 1 or url_index > 0:
                    if isinstance(on_byte_progress, BoundPercentProgress):
                        on_byte_progress.reset_attempt()
                    await invoke_progress(on_progress, 0)

                await invoke_download_state(
                    on_download_state,
                    DownloadRetryInfo(
                        attempt=attempt,
                        max_attempts=max_attempts,
                        url_index=url_index,
                        url_count=url_count,
                        phase=DownloadRetryPhase.DOWNLOADING,
                    ),
                )

                tmp_fd, tmp_path_str = tempfile.mkstemp()
                os.close(tmp_fd)
                tmp_path = Path(tmp_path_str)
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response:
                        response.raise_for_status()
                        first_chunk = await response.content.read(4096)
                        if not first_chunk:
                            raise aiohttp.ClientError("Empty response body")

                        total_size = response.content_length
                        downloaded = len(first_chunk)
                        await invoke_byte_progress(on_byte_progress, downloaded, total_size)

                        async with aiofiles.open(tmp_path, "wb") as f:
                            await f.write(first_chunk)
                            async for chunk in response.content.iter_chunked(65536):
                                await f.write(chunk)
                                downloaded += len(chunk)
                                await invoke_byte_progress(on_byte_progress, downloaded, total_size)

                        logger.debug(f"Downloaded stream from {url} -> {tmp_path}")
                        return tmp_path
                except aiohttp.ClientResponseError as e:
                    tmp_path.unlink(missing_ok=True)
                    url_last_error = e
                    if 400 <= e.status < 500:
                        break
                except (TimeoutError, aiohttp.ClientError) as e:
                    tmp_path.unlink(missing_ok=True)
                    url_last_error = e
                except Exception:
                    tmp_path.unlink(missing_ok=True)
                    raise

                if retry < download_max_retries:
                    wait = 2**retry
                    logger.warning(
                        f"Download attempt {attempt}/{max_attempts} "
                        f"failed for {url}, retrying in {wait}s: {url_last_error}"
                    )
                    await invoke_download_state(
                        on_download_state,
                        DownloadRetryInfo(
                            attempt=attempt,
                            max_attempts=max_attempts,
                            url_index=url_index,
                            url_count=url_count,
                            phase=DownloadRetryPhase.RETRYING,
                        ),
                    )
                    await asyncio.sleep(wait)

            last_error = url_last_error
            if url_index < url_count - 1:
                logger.warning(
                    f"Stream URL {url_index + 1}/{url_count} failed ({url}), trying fallback: {urls[url_index + 1]}"
                )
                await invoke_download_state(
                    on_download_state,
                    DownloadRetryInfo(
                        attempt=attempt,
                        max_attempts=max_attempts,
                        url_index=url_index,
                        url_count=url_count,
                        phase=DownloadRetryPhase.SWITCHING_URL,
                    ),
                )

        raise last_error

    async def _download_file(
        self,
        session: aiohttp.ClientSession,
        urls: list[str],
        save_dir: Path,
        index: int | None,
        file_type: str = "media",
        on_byte_progress: BoundPercentProgress | None = None,
        on_progress: ProgressCallback | None = None,
        on_download_state: DownloadStateCallback | None = None,
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
            index: File index used in the filename. Pass None to omit the numeric
                prefix (used for author profile assets that are not part of a media list).
            file_type: File type used in the filename, e.g. "media" or "cover"
            on_byte_progress: Optional bound percent progress (supports reset_attempt)
            on_progress: Optional percent callback (used to emit 0 on attempt reset)
            on_download_state: Optional live retry/phase callback

        Returns:
            Path to the saved file
        """
        last_error: Exception = Exception("No URLs provided")
        download_max_retries = get_settings().download.max_retries
        max_attempts = download_max_retries + 1
        url_count = len(urls)

        for url_index, url in enumerate(urls):
            url_last_error: Exception = Exception("Unknown error")
            for retry in range(max_attempts):
                attempt = retry + 1
                if attempt > 1 or url_index > 0:
                    if on_byte_progress is not None:
                        on_byte_progress.reset_attempt()
                    await invoke_progress(on_progress, 0)

                await invoke_download_state(
                    on_download_state,
                    DownloadRetryInfo(
                        attempt=attempt,
                        max_attempts=max_attempts,
                        url_index=url_index,
                        url_count=url_count,
                        phase=DownloadRetryPhase.DOWNLOADING,
                    ),
                )

                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response:
                        response.raise_for_status()

                        # Read first chunk to detect MIME type from magic bytes
                        first_chunk = await response.content.read(4096)
                        if not first_chunk:
                            raise aiohttp.ClientError("Empty response body")

                        content_type = response.headers.get("content-type", "")
                        ext = self._detect_extension(first_chunk, url, content_type)

                        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                        prefix = "" if index is None else f"{index:03d}_"
                        filename = f"{prefix}{file_type}_{url_hash}{ext}"
                        filepath = save_dir / filename

                        total_size = response.content_length
                        downloaded = len(first_chunk)
                        await invoke_byte_progress(on_byte_progress, downloaded, total_size)

                        # Write first chunk then stream the rest to disk
                        async with aiofiles.open(filepath, "wb") as f:
                            await f.write(first_chunk)
                            async for chunk in response.content.iter_chunked(65536):
                                await f.write(chunk)
                                downloaded += len(chunk)
                                await invoke_byte_progress(on_byte_progress, downloaded, total_size)

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

                if retry < download_max_retries:
                    wait = 2**retry
                    logger.warning(
                        f"Download attempt {attempt}/{max_attempts} "
                        f"failed for {url}, retrying in {wait}s: {url_last_error}"
                    )
                    await invoke_download_state(
                        on_download_state,
                        DownloadRetryInfo(
                            attempt=attempt,
                            max_attempts=max_attempts,
                            url_index=url_index,
                            url_count=url_count,
                            phase=DownloadRetryPhase.RETRYING,
                        ),
                    )
                    await asyncio.sleep(wait)

            # This URL exhausted all retries (or got 4xx); try next fallback
            last_error = url_last_error
            if url_index < url_count - 1:
                logger.warning(
                    f"{file_type} URL {url_index + 1}/{url_count} failed ({url}), "
                    f"trying fallback: {urls[url_index + 1]}"
                )
                await invoke_download_state(
                    on_download_state,
                    DownloadRetryInfo(
                        attempt=attempt,
                        max_attempts=max_attempts,
                        url_index=url_index,
                        url_count=url_count,
                        phase=DownloadRetryPhase.SWITCHING_URL,
                    ),
                )

        raise last_error

    # Normalise extensions that mimetypes.guess_extension returns inconsistently
    # across platforms (e.g. .jpe / .jpeg → .jpg on some systems).
    _EXT_NORMALISE: ClassVar[dict[str, str]] = {
        ".jpe": ".jpg",
        ".jpeg": ".jpg",
        ".htm": ".html",
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
            if mime and mime != "application/octet-stream":
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
            raise RuntimeError(f"Plugin returned a symlink, which is not allowed: {original}")
        try:
            resolved = original.resolve(strict=True)
        except OSError as e:
            raise RuntimeError(f"Plugin returned non-existent path: {original}") from e
        if not resolved.is_file():
            raise RuntimeError(f"Plugin returned invalid path (not a regular file): {resolved}")
        return resolved

    def _move_to_save_dir(self, temp_path: Path, save_dir: Path, index: int, file_type: str, url: str) -> Path:
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

    def _is_within_media_root(self, path: Path) -> bool:
        """
        Check whether a resolved path is safely within the media root directory.

        Args:
            path: Path to validate (need not be pre-resolved)

        Returns:
            True if path is inside media_dir and is not media_dir itself
        """
        return is_path_within_base(path, self.media_dir, allow_base_itself=False)

    def _resolve_media_path(self, relative_path: str) -> Path | None:
        """
        Resolve a /media-relative web path to an absolute path under media_dir.

        Path components are URL-decoded to match `_get_relative_media_path`, which
        stores quoted segments (e.g. spaces as %20).

        Args:
            relative_path: Web path beginning with /media/

        Returns:
            Resolved absolute path, or None if invalid or outside media_dir
        """
        if not relative_path.startswith("/media/"):
            return None
        try:
            encoded = relative_path[len("/media/") :]
            parts = [unquote(part) for part in encoded.split("/") if part != ""]
            abs_path = self.media_dir.joinpath(*parts)
            resolved_path = abs_path.resolve()
            if not self._is_within_media_root(resolved_path):
                return None
            return resolved_path
        except OSError:
            return None

    def media_file_exists(self, relative_path: str | None) -> bool:
        """
        Check whether a /media-relative path maps to an existing file on disk.

        Args:
            relative_path: A web path beginning with /media/, or None

        Returns:
            True if the corresponding file exists, otherwise False.
        """
        if not relative_path:
            return False
        resolved_path = self._resolve_media_path(relative_path)
        return resolved_path is not None and resolved_path.is_file()

    def delete_media_file(self, relative_path: str | None) -> bool:
        """
        Best-effort delete of a single /media-relative file on disk.

        Args:
            relative_path: A web path beginning with /media/, or None

        Returns:
            True if a file was deleted, False if missing, invalid, or deletion failed.
        """
        if not relative_path:
            return False
        try:
            resolved_path = self._resolve_media_path(relative_path)
            if resolved_path is None or not resolved_path.is_file():
                return False
            resolved_path.unlink()
            logger.debug(f"Deleted media file: {resolved_path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to delete media file {relative_path}: {e}")
            return False

    def delete_content_directory(self, platform: str, author_uid: str, content_id: str) -> bool:
        """
        Delete an entire content directory and all files within it.

        Args:
            platform: Platform code
            author_uid: Author uid
            content_id: Content directory name

        Returns:
            True if the directory was deleted, False if it did not exist or deletion failed
        """
        try:
            content_dir = self.get_content_directory(platform, author_uid, content_id)
            resolved_dir = content_dir.resolve()

            if not self._is_within_media_root(resolved_dir):
                logger.warning(f"Attempted to delete directory outside media root: {resolved_dir}")
                return False

            if not resolved_dir.is_dir():
                logger.debug(f"Content directory does not exist: {resolved_dir}")
                return False

            shutil.rmtree(resolved_dir)
            logger.debug(f"Deleted content directory: {resolved_dir}")
            return True
        except Exception as e:
            logger.warning(f"Failed to delete content directory for {platform}/{author_uid}/{content_id}: {e}")
            return False


class _CombinedStreamProgress:
    """Map two-stream byte progress onto a single 0-99 percent callback."""

    def __init__(self, on_progress: ProgressCallback | None):
        self._on_progress = on_progress
        self._lock = asyncio.Lock()
        self._parts: dict[str, tuple[int, int | None]] = {}
        self._last_pct = -1

    def bind(self, part_id: str) -> ByteProgressCallback | None:
        self._parts.setdefault(part_id, (0, None))
        if self._on_progress is None:
            return None

        async def _report(downloaded: int, total: int | None) -> None:
            async with self._lock:
                self._parts[part_id] = (downloaded, total)
                totals = [size for _, size in self._parts.values() if size]
                if len(totals) != len(self._parts) or not totals:
                    return
                done = sum(size for size, _ in self._parts.values())
                pct = min(99, int(done * 100 / sum(totals)))
                if pct <= self._last_pct:
                    return
                self._last_pct = pct
                await invoke_progress(self._on_progress, pct)

        return _report


media_service = MediaService()

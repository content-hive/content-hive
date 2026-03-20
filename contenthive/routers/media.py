"""
Media router for serving media files with optional image transformation.

Supports URL query parameters for on-the-fly image conversion and compression.
Example: /media/xhs/author/content_id/004_media.jpg?format=webp&quality=75&width=800
"""

import asyncio
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from contenthive.config import settings
from contenthive.logger import logger
from contenthive.services.media import media_service, IMAGE_MIME_TYPES

router = APIRouter(tags=["media"])

# Dedicated executor for CPU-bound Pillow work; keeps image transforms from
# saturating the default asyncio thread pool used by the rest of the app.
_transform_executor = ThreadPoolExecutor(
    max_workers=settings.media_transform_max_workers,
    thread_name_prefix="img-transform",
)

# Semaphore caps the number of requests that can wait for a free worker slot.
# Requests that cannot acquire the semaphore within the configured timeout
# receive a 503 rather than queuing indefinitely.
_transform_semaphore = asyncio.Semaphore(settings.media_transform_max_workers)


def shutdown_transform_executor(*, cancel_futures: bool = True) -> None:
    """Shut down the image transform thread pool. Call from app lifespan teardown."""
    _transform_executor.shutdown(wait=True, cancel_futures=cancel_futures)


@router.get("/media/{file_path:path}")
async def serve_media(
    file_path: str,
    output_format: Optional[str] = Query(
        None,
        alias="format",
        pattern="^(jpeg|jpg|png|webp|avif)$",
        description="Target image format for conversion",
    ),
    quality: Optional[int] = Query(
        None,
        ge=1,
        le=100,
        description="Compression quality (1-100, images only). Uses format default when omitted.",
    ),
    width: Optional[int] = Query(
        None,
        ge=1,
        le=10000,
        description="Target width in pixels; preserves aspect ratio when height is omitted",
    ),
    height: Optional[int] = Query(
        None,
        ge=1,
        le=10000,
        description="Target height in pixels; preserves aspect ratio when width is omitted",
    ),
) -> Response:
    """
    Serve a media file, with optional on-the-fly image transformation.

    Args:
        file_path: Relative path under the media directory.
        format:    Output image format (jpeg, png, webp, avif).
        quality:   JPEG/WEBP compression quality (1-100).
        width:     Resize to this width (preserves aspect ratio).
        height:    Resize to this height (preserves aspect ratio).

    Returns:
        HTTP response with file contents (transformed if requested).
    """
    # --- Path traversal protection ---
    media_root = settings.media_dir.resolve()
    target = (settings.media_dir / file_path).resolve()
    if not target.is_relative_to(media_root):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    mime_type, _ = mimetypes.guess_type(str(target))

    # Only transform images when at least one transform parameter is provided
    if (output_format or quality or width or height) and mime_type in IMAGE_MIME_TYPES:
        try:
            try:
                await asyncio.wait_for(
                    _transform_semaphore.acquire(),
                    timeout=settings.media_transform_queue_timeout,
                )
            except asyncio.TimeoutError:
                raise HTTPException(
                    status_code=503,
                    detail="Image transform queue is full; try again later.",
                )
            try:
                loop = asyncio.get_running_loop()
                image_bytes, out_mime = await loop.run_in_executor(
                    _transform_executor,
                    partial(
                        media_service.transform_image,
                        target, output_format, quality, width, height, mime_type,
                    ),
                )
            finally:
                _transform_semaphore.release()
            return Response(
                content=image_bytes,
                media_type=out_mime,
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Content-Length": str(len(image_bytes)),
                },
            )
        except HTTPException:
            raise
        except Exception:
            logger.exception("Image transformation failed for %s; serving original", file_path)

    # Serve file as-is — FileResponse streams the file and supports range requests
    return FileResponse(
        target,
        media_type=mime_type or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=86400"},
    )

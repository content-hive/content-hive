"""
Media router for serving media files with optional image transformation.

Supports URL query parameters for on-the-fly image conversion and compression.
Example: /media/xhs/author/content_id/004_media.jpg?format=webp&quality=75&width=800
"""

import mimetypes
from typing import Optional

import aiofiles
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from contenthive.config import settings
from contenthive.logger import logger
from contenthive.services.media import media_service, IMAGE_MIME_TYPES

router = APIRouter(tags=["media"])


@router.get("/media/{file_path:path}")
async def serve_media(
    file_path: str,
    format: Optional[str] = Query(
        None,
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
    if not str(target).startswith(str(media_root)):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    mime_type, _ = mimetypes.guess_type(str(target))

    # Only transform images when at least one transform parameter is provided
    if (format or width or height) and mime_type in IMAGE_MIME_TYPES:
        try:
            image_bytes, out_mime = await media_service.transform_image(
                target, format, quality, width, height, mime_type
            )
            return Response(
                content=image_bytes,
                media_type=out_mime,
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Content-Length": str(len(image_bytes)),
                },
            )
        except Exception:
            logger.exception("Image transformation failed for %s; serving original", file_path)

    # Serve file as-is
    async with aiofiles.open(target, "rb") as f:
        content = await f.read()

    return Response(
        content=content,
        media_type=mime_type or "application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Length": str(len(content)),
        },
    )

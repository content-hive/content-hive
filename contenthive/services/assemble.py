"""Assemble downloaded streams into archived media files and probe their properties."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from contenthive.logger import logger
from contenthive.models.enumerates import MediaType
from contenthive.plugins.contracts import ParserMediaInfo


@dataclass
class AssembledMedia:
    """Archived files plus probed dimensions."""

    media_path: Path | None
    cover_path: Path | None
    media_duration: int | None
    media_width: int | None
    media_height: int | None
    cover_width: int | None
    cover_height: int | None


async def assemble_streams(media: ParserMediaInfo, temps: dict[str, Path]) -> AssembledMedia:
    """Turn downloaded stream files into archived media and cover files.

    Temporary inputs are unlinked after a successful assemble. The returned
    paths are still temporary; the caller moves them into the media directory.
    """
    media_path: Path | None = None
    cover_path: Path | None = None
    owned_temps: list[Path] = []
    try:
        missing = [
            stream.role
            for stream in media.downloadable_streams()
            if stream.role != "cover" and stream.role not in temps
        ]
        if missing:
            raise RuntimeError(f"Missing downloaded files for streams: {sorted(missing)}")

        video = temps.get("video")
        audio = temps.get("audio")
        image = temps.get("image")
        cover = temps.get("cover")

        if media.type == MediaType.VIDEO and video is not None and audio is not None:
            media_path = await mux_video_audio(video, audio)
            owned_temps.append(media_path)
        elif media.type == MediaType.LIVEPHOTO:
            media_path = video
            cover_path = image
        elif media.type in (MediaType.IMAGE, MediaType.GIF):
            media_path = image
        elif media.type == MediaType.AUDIO:
            media_path = audio
        elif media.type == MediaType.VIDEO:
            media_path = video
        elif media.type == MediaType.LINK:
            media_path = None
        else:
            raise RuntimeError(f"Cannot assemble media type {media.type}")

        if cover_path is None:
            cover_path = cover

        if media.type == MediaType.LIVEPHOTO and (media_path is None or cover_path is None):
            raise RuntimeError("Live photo requires video and still image files")
        if media.type != MediaType.LINK and media_path is None:
            raise RuntimeError(f"Missing archived media file for {media.type.value}")

        media_duration, media_width, media_height = await probe_media(media_path) if media_path else (None, None, None)
        _, cover_width, cover_height = await probe_media(cover_path) if cover_path else (None, None, None)
        return AssembledMedia(
            media_path=media_path,
            cover_path=cover_path,
            media_duration=media_duration,
            media_width=media_width,
            media_height=media_height,
            cover_width=cover_width,
            cover_height=cover_height,
        )
    except Exception:
        for path in owned_temps:
            path.unlink(missing_ok=True)
        raise
    finally:
        keep = {media_path, cover_path}
        for path in temps.values():
            if path not in keep:
                path.unlink(missing_ok=True)


async def mux_video_audio(video_path: Path, audio_path: Path) -> Path:
    """Remux video+audio into a single mp4. Falls back to AAC if stream copy fails."""
    out_fd, out_str = tempfile.mkstemp(suffix=".mp4")
    os.close(out_fd)
    out_path = Path(out_str)
    try:
        try:
            await _run_mux(video_path, audio_path, out_path, copy_audio=True)
        except Exception as e:
            logger.warning(f"ffmpeg stream copy failed, retrying with AAC audio: {e}")
            await _run_mux(video_path, audio_path, out_path, copy_audio=False)
        return out_path
    except FileNotFoundError as e:
        out_path.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg is not available on PATH") from e
    except Exception:
        out_path.unlink(missing_ok=True)
        raise


async def probe_media(path: Path) -> tuple[int | None, int | None, int | None]:
    """Return (duration_ms, width, height) for a local media file.

    Dimensions and duration come from ExifTool. A failed probe leaves them
    empty and logs a warning; the file is still archived.
    """
    try:
        return await _probe_with_exiftool(path)
    except Exception as exc:
        logger.warning(f"Media probe failed, leaving dimensions empty: {path}: {exc}")
        return None, None, None


async def _run_mux(video_path: Path, audio_path: Path, out_path: Path, *, copy_audio: bool) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
    ]
    if copy_audio:
        cmd.extend(["-c", "copy"])
    else:
        cmd.extend(["-c:v", "copy", "-c:a", "aac"])
    cmd.extend(["-movflags", "+faststart", str(out_path)])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        detail = stderr.decode(errors="replace")[-2000:]
        raise RuntimeError(f"ffmpeg mux failed ({proc.returncode}): {detail}")


async def _probe_with_exiftool(path: Path) -> tuple[int | None, int | None, int | None]:
    """Return (duration_ms, width, height) from ExifTool."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "exiftool",
            "-json",
            "-n",
            "-ImageWidth",
            "-ImageHeight",
            "-Duration",
            "-Orientation",
            "-Rotation",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("exiftool is not available on PATH") from exc
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        detail = stderr.decode(errors="replace")[-2000:]
        raise RuntimeError(f"exiftool failed ({proc.returncode}): {detail}")
    try:
        payload = json.loads(stdout.decode())
    except json.JSONDecodeError as exc:
        raise RuntimeError("exiftool returned invalid JSON") from exc
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise RuntimeError("exiftool returned no metadata")
    tags = payload[0]
    return _seconds_to_ms(tags.get("Duration")), *_oriented_size(tags)


def _seconds_to_ms(raw: object) -> int | None:
    if raw is None:
        return None
    try:
        seconds = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return int(seconds * 1000)


def _oriented_size(tags: dict) -> tuple[int | None, int | None]:
    width = _positive_int(tags.get("ImageWidth"))
    height = _positive_int(tags.get("ImageHeight"))
    if width is None or height is None:
        return None, None
    orientation = tags.get("Orientation")
    rotation = tags.get("Rotation")
    if orientation in (6, 8) or rotation in (90, 270):
        return height, width
    return width, height


def _positive_int(raw: object) -> int | None:
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value

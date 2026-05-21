import asyncio
import os
import shutil
from contextlib import suppress
from pathlib import Path
from typing import NamedTuple

from contenthive.config import settings
from contenthive.models.enumerates import MediaStorageType
from contenthive.models.system import (
    DiskInfo,
    MediaStorageInfo,
    MediaTypeStorageInfo,
    StorageItemInfo,
    StorageStatusResponse,
)


class _MediaStat(NamedTuple):
    files: int
    bytes: int


_MEDIA_EXT_MAP: dict[str, MediaStorageType] = {
    ext: MediaStorageType.IMAGE for ext in ("jpg", "jpeg", "png", "webp", "bmp", "tiff", "avif", "heic", "gif")
}
_MEDIA_EXT_MAP.update(
    {ext: MediaStorageType.VIDEO for ext in ("mp4", "mov", "avi", "mkv", "webm", "flv", "wmv", "m4v")}
)
_MEDIA_EXT_MAP.update({ext: MediaStorageType.AUDIO for ext in ("mp3", "wav", "aac", "flac", "ogg", "m4a", "wma")})


def _format_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


def _dir_size(path: Path) -> int:
    total = 0
    if path.exists():
        for dirpath, _, filenames in os.walk(path):
            for fname in filenames:
                with suppress(OSError):
                    total += os.path.getsize(os.path.join(dirpath, fname))
    return total


class StorageService:
    async def get_storage_status(self) -> StorageStatusResponse:
        return await asyncio.to_thread(self._collect)

    def _collect(self) -> StorageStatusResponse:
        disk = shutil.disk_usage(settings.data_dir)
        usage_percent = round(disk.used / disk.total * 100, 2) if disk.total else 0.0

        db_size = settings.database_path.stat().st_size if settings.database_path.exists() else 0

        type_stats: dict[MediaStorageType, _MediaStat] = {t: _MediaStat(0, 0) for t in MediaStorageType}
        if settings.media_dir.exists():
            for dirpath, _, filenames in os.walk(settings.media_dir):
                for fname in filenames:
                    with suppress(OSError):
                        fsize = os.path.getsize(os.path.join(dirpath, fname))
                        ext = os.path.splitext(fname)[1].lstrip(".").lower()
                        mtype = _MEDIA_EXT_MAP.get(ext, MediaStorageType.OTHER)
                        stat = type_stats[mtype]
                        type_stats[mtype] = _MediaStat(stat.files + 1, stat.bytes + fsize)

        total_media_files = sum(v.files for v in type_stats.values())
        total_media_bytes = sum(v.bytes for v in type_stats.values())
        logs_bytes = _dir_size(settings.logs_dir)
        plugins_bytes = _dir_size(settings.plugins_dir)

        return StorageStatusResponse(
            disk=DiskInfo(
                total_bytes=disk.total,
                used_bytes=disk.used,
                free_bytes=disk.free,
                usage_percent=usage_percent,
                total_human=_format_bytes(disk.total),
                used_human=_format_bytes(disk.used),
                free_human=_format_bytes(disk.free),
            ),
            database=StorageItemInfo(size_bytes=db_size, size_human=_format_bytes(db_size)),
            media=MediaStorageInfo(
                total_files=total_media_files,
                total_size_bytes=total_media_bytes,
                total_size_human=_format_bytes(total_media_bytes),
                by_type={
                    t: MediaTypeStorageInfo(
                        files=type_stats[t].files,
                        size_bytes=type_stats[t].bytes,
                        size_human=_format_bytes(type_stats[t].bytes),
                    )
                    for t in MediaStorageType
                },
            ),
            logs=StorageItemInfo(size_bytes=logs_bytes, size_human=_format_bytes(logs_bytes)),
            plugins=StorageItemInfo(size_bytes=plugins_bytes, size_human=_format_bytes(plugins_bytes)),
        )


storage_service = StorageService()

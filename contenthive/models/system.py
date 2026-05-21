"""
Models for system-related operations.
"""

from pydantic import Field

from contenthive.models.api import APIBaseModel
from contenthive.models.enumerates import MediaStorageType


class RestartResponse(APIBaseModel):
    """Response model for application restart operation"""

    type: str = Field(..., description="Restart type (restart / safe_mode)")
    message: str = Field(..., description="Human-readable status message")


class HealthResponse(APIBaseModel):
    """Response model for health check"""

    app: str = Field(..., description="Application name")
    version: str = Field(..., description="Application version")
    plugin_updates_available: bool = Field(..., description="Whether any installed plugin has an update available")


class StorageItemInfo(APIBaseModel):
    """Size info for a single storage item (file or directory)"""

    size_bytes: int = Field(..., description="Size in bytes")
    size_human: str = Field(..., description="Human-readable size (e.g. 1.23 GB)")


class MediaTypeStorageInfo(APIBaseModel):
    """Storage usage for a single media type"""

    files: int = Field(..., description="Number of files")
    size_bytes: int = Field(..., description="Total size in bytes")
    size_human: str = Field(..., description="Human-readable total size")


class MediaStorageInfo(APIBaseModel):
    """Aggregated storage usage for the media directory, broken down by type"""

    total_files: int = Field(..., description="Total number of media files")
    total_size_bytes: int = Field(..., description="Total media size in bytes")
    total_size_human: str = Field(..., description="Human-readable total media size")
    by_type: dict[MediaStorageType, MediaTypeStorageInfo] = Field(..., description="Breakdown by media type")


class DiskInfo(APIBaseModel):
    """Disk partition usage for the mount containing the data directory"""

    total_bytes: int = Field(..., description="Disk partition total capacity in bytes")
    used_bytes: int = Field(..., description="Used space in bytes")
    free_bytes: int = Field(..., description="Available space in bytes")
    usage_percent: float = Field(..., description="Usage percentage (0-100)")
    total_human: str = Field(..., description="Human-readable total capacity")
    used_human: str = Field(..., description="Human-readable used space")
    free_human: str = Field(..., description="Human-readable available space")


class LogEntry(APIBaseModel):
    """A single structured log entry"""

    id: str = Field(..., description="Stable unique identifier: file date + line number (e.g. '2026-05-21:42')")
    timestamp: str = Field(..., description="Log timestamp in UTC ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ)")
    level: str = Field(..., description="Log level (DEBUG/INFO/WARNING/ERROR/CRITICAL)")
    message: str = Field(..., description="Log message")
    traceback: str | None = Field(default=None, description="Exception traceback, if any")


class CursorPaginatedResponse[T](APIBaseModel):
    """Cursor-paginated response"""

    items: list[T] = Field(..., description="Items for this page")
    next_cursor: str | None = Field(default=None, description="Opaque token for the next page; null means no more data")


class StorageStatusResponse(APIBaseModel):
    """Response model for the storage status endpoint"""

    disk: DiskInfo = Field(..., description="Disk partition usage for the data directory mount")
    database: StorageItemInfo = Field(..., description="Database file size")
    media: MediaStorageInfo = Field(..., description="Media directory usage breakdown")
    logs: StorageItemInfo = Field(..., description="Logs directory size")
    plugins: StorageItemInfo = Field(..., description="Plugins directory size")

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
    size_bytes: int = Field(..., description="Size in bytes")
    size_human: str = Field(..., description="Human-readable size (e.g. 1.23 GB)")


class MediaTypeStorageInfo(APIBaseModel):
    files: int = Field(..., description="Number of files")
    size_bytes: int = Field(..., description="Total size in bytes")
    size_human: str = Field(..., description="Human-readable total size")


class MediaStorageInfo(APIBaseModel):
    total_files: int = Field(..., description="Total number of media files")
    total_size_bytes: int = Field(..., description="Total media size in bytes")
    total_size_human: str = Field(..., description="Human-readable total media size")
    by_type: dict[MediaStorageType, MediaTypeStorageInfo] = Field(..., description="Breakdown by media type")


class DiskInfo(APIBaseModel):
    total_bytes: int = Field(..., description="Disk partition total capacity in bytes")
    used_bytes: int = Field(..., description="Used space in bytes")
    free_bytes: int = Field(..., description="Available space in bytes")
    usage_percent: float = Field(..., description="Usage percentage (0-100)")
    total_human: str = Field(..., description="Human-readable total capacity")
    used_human: str = Field(..., description="Human-readable used space")
    free_human: str = Field(..., description="Human-readable available space")


class StorageStatusResponse(APIBaseModel):
    disk: DiskInfo = Field(..., description="Disk partition usage for the data directory mount")
    database: StorageItemInfo = Field(..., description="Database file size")
    media: MediaStorageInfo = Field(..., description="Media directory usage breakdown")
    logs: StorageItemInfo = Field(..., description="Logs directory size")
    plugins: StorageItemInfo = Field(..., description="Plugins directory size")

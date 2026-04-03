"""
Models for plugin-related operations.
"""

from datetime import datetime
from typing import Optional
from pydantic import Field

from contenthive.models.api import APIBaseModel


class PluginInfo(APIBaseModel):
    """Status information for a single plugin"""

    state: str = Field(..., description="Plugin state")
    version: str = Field(..., description="Plugin version")
    name: str = Field(..., description="Plugin display name")
    error: Optional[str] = Field(None, description="Error message if plugin is in FAILED state")
    update_available: Optional[str] = Field(None, description="Latest version if an update is available, otherwise null")


class PluginUpdateInfo(APIBaseModel):
    """Update status for a single plugin"""

    current_version: str = Field(..., description="Currently installed version")
    latest_version: Optional[str] = Field(None, description="Latest available version, null if fetch failed")
    update_available: bool = Field(..., description="Whether a newer version is available")


class PluginListResponse(APIBaseModel):
    """Response model for listing all plugins"""

    plugins: dict[str, PluginInfo] = Field(
        default_factory=dict, description="Plugin status map keyed by domain"
    )


class ReloadResponse(APIBaseModel):
    """Response model for plugin reload operation"""

    message: str = Field(..., description="Human-readable status message")
    plugins: dict[str, str] = Field(
        ..., description="Per-plugin reload result (reloaded / failed / error: ...)"
    )


class CheckConfigResponse(APIBaseModel):
    """Response model for plugin configuration check"""

    valid: bool = Field(..., description="Whether the configuration is valid")
    errors: list[str] = Field(default_factory=list, description="Configuration errors")
    warnings: list[str] = Field(default_factory=list, description="Configuration warnings")
    message: str = Field(..., description="Human-readable summary")


class CheckUpdatesResponse(APIBaseModel):
    """Response model for plugin update check"""

    checked_at: datetime = Field(..., description="Timestamp of the check")
    plugins: dict[str, PluginUpdateInfo] = Field(
        default_factory=dict, description="Per-plugin update status keyed by domain"
    )


class UpdatePluginsRequest(APIBaseModel):
    """Request body for plugin update operation"""

    domains: list[str] = Field(
        default_factory=list,
        description="List of plugin domains to update. Empty list means update all installed plugins."
    )


class UpdatePluginsResponse(APIBaseModel):
    """Response model for plugin update operation"""

    updated: list[str] = Field(default_factory=list, description="Plugins successfully updated and reloaded")
    failed: list[str] = Field(default_factory=list, description="Plugins that failed to download or reload")

"""
Models for plugin-related operations.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from contenthive.models.api import APIBaseModel
from contenthive.plugins.registry import PluginState


class SettingFieldType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ENUM = "enum"


class SettingItem(APIBaseModel):
    """A single setting field with its schema definition and current value."""

    key: str = Field(..., description="Setting key name")
    type: SettingFieldType = Field(..., description="Value type")
    label: str = Field(..., description="Human-readable label for UI display")
    description: str | None = Field(None, description="Detailed description")
    required: bool = Field(False, description="Whether this field is required")
    secret: bool = Field(False, description="Whether this is a sensitive value")
    default: str | int | float | bool | None = Field(None, description="Default value")
    options: list[str] | None = Field(None, description="Valid options for enum type")
    value: str | int | float | bool | None = Field(None, description="Current configured value")


class PluginConfigResponse(APIBaseModel):
    """Response for GET /v1/plugins/{domain}/config"""

    domain: str = Field(..., description="Plugin domain identifier")
    settings: list[SettingItem] = Field(default_factory=list, description="Setting fields with current values")


class UpdatePluginConfigRequest(APIBaseModel):
    """Request body for PUT /v1/plugins/{domain}/config"""

    config: dict[str, Any] = Field(..., description="Key-value pairs to update in plugin config")


class UpdatePluginConfigResponse(APIBaseModel):
    """Response for PUT /v1/plugins/{domain}/config"""

    domain: str = Field(..., description="Plugin domain identifier")
    settings: list[SettingItem] = Field(default_factory=list, description="Setting fields with updated values")


class PluginInfo(APIBaseModel):
    """Status information for a single plugin"""

    state: PluginState = Field(..., description="Plugin state")
    version: str = Field(..., description="Plugin version")
    name: str = Field(..., description="Plugin display name")
    error: str | None = Field(None, description="Error message if plugin is in FAILED state")
    update_available: str | None = Field(None, description="Latest version if an update is available, otherwise null")
    description: str | None = Field(None, description="Plugin description")
    author: list[str] | None = Field(None, description="Plugin author")
    prerelease: bool = Field(False, description="Whether the plugin tracks pre-release (beta) versions")


class PluginStatusResponse(APIBaseModel):
    """Response for GET /v1/plugins/{domain}"""

    domain: str = Field(..., description="Plugin domain identifier")
    state: PluginState = Field(..., description="Plugin state")
    version: str = Field(..., description="Plugin version")
    name: str = Field(..., description="Plugin display name")
    error: str | None = Field(None, description="Error message if plugin is in FAILED state")
    update_available: str | None = Field(None, description="Latest version if an update is available, otherwise null")
    description: str | None = Field(None, description="Plugin description")
    author: list[str] | None = Field(None, description="Plugin author")
    prerelease: bool = Field(False, description="Whether the plugin tracks pre-release (beta) versions")


class PluginUpdateInfo(APIBaseModel):
    """Update status for a single plugin"""

    current_version: str = Field(..., description="Currently installed version")
    latest_version: str | None = Field(None, description="Latest available version, null if fetch failed")
    update_available: bool = Field(..., description="Whether a newer version is available")
    release_notes: str | None = Field(
        None, description="Release notes for the latest remote version when an update is available"
    )


class PluginListResponse(APIBaseModel):
    """Response model for listing all plugins"""

    plugins: dict[str, PluginInfo] = Field(default_factory=dict, description="Plugin status map keyed by domain")


class ReloadResponse(APIBaseModel):
    """Response model for plugin reload operation"""

    message: str = Field(..., description="Human-readable status message")
    plugins: dict[str, str] = Field(
        ..., description="Per-plugin reload result (reloaded / disabled / failed / error: ...)"
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


class AvailablePluginInfo(APIBaseModel):
    """A plugin listed in the plugin catalog"""

    domain: str = Field(..., description="Plugin domain identifier")
    name: str = Field(..., description="Plugin display name")
    version: str = Field(
        ...,
        description=(
            "Version that install/update would use on the plugin's release track. "
            "When installable is false, the version from the other track for display only"
        ),
    )
    description: str | None = Field(None, description="Plugin description")
    author: list[str] | None = Field(None, description="Plugin author")
    disclaimer: str | None = Field(None, description="Risk disclaimer to display before installation")
    release_notes: str | None = Field(None, description="Release notes for the version")
    repository: str = Field(..., description="Plugin GitHub repository as owner/repo")
    prerelease: bool = Field(False, description="Whether the plugin tracks pre-release (beta) versions")
    installable: bool = Field(..., description="Whether the plugin's release track has a version to install")
    installed: bool = Field(..., description="Whether the plugin is currently installed")
    installed_version: str | None = Field(None, description="Installed version, if installed")


class AvailablePluginsResponse(APIBaseModel):
    """Response model for listing all plugins in the plugin catalog"""

    plugins: list[AvailablePluginInfo] = Field(
        default_factory=list,
        description="List of plugins in the plugin catalog",
    )


class UpdatePluginsRequest(APIBaseModel):
    """Request body for plugin update operation"""

    domains: list[str] = Field(
        default_factory=list,
        description="List of plugin domains to install or update. Empty list means every installable catalog plugin.",
    )


class SetPrereleaseRequest(APIBaseModel):
    """Request body for PUT /v1/plugins/{domain}/prerelease"""

    enabled: bool = Field(..., description="Track pre-release (beta) versions for this plugin")


class SetPrereleaseResponse(APIBaseModel):
    """Response for PUT /v1/plugins/{domain}/prerelease"""

    domain: str = Field(..., description="Plugin domain identifier")
    prerelease: bool = Field(..., description="Whether the plugin now tracks pre-release (beta) versions")


class UpdatePluginsResponse(APIBaseModel):
    """Response model for plugin update operation"""

    updated: list[str] = Field(default_factory=list, description="Plugins successfully updated and reloaded")
    failed: list[str] = Field(default_factory=list, description="Plugins that failed to download or reload")

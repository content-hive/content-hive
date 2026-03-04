"""
Models for system-related operations.
"""

from typing import Optional
from pydantic import Field

from contenthive.models.api import APIBaseModel


class RestartResponse(APIBaseModel):
    """Response model for application restart operation"""

    type: str = Field(..., description="Restart type (restart / safe_mode)")
    message: str = Field(..., description="Human-readable status message")


class ReloadResponse(APIBaseModel):
    """Response model for configuration reload operation"""

    message: str = Field(..., description="Human-readable status message")
    plugins: dict[str, str] = Field(
        ..., description="Per-plugin reload result (reloaded / failed / error: ...)"
    )


class CheckConfigResponse(APIBaseModel):
    """Response model for configuration check operation"""

    valid: bool = Field(..., description="Whether the configuration is valid")
    errors: list[str] = Field(default_factory=list, description="Configuration errors")
    warnings: list[str] = Field(default_factory=list, description="Configuration warnings")
    message: str = Field(..., description="Human-readable summary")


class HealthPluginInfo(APIBaseModel):
    """Status information for a single plugin"""

    state: str = Field(..., description="Plugin state")
    version: str = Field(..., description="Plugin version")
    name: str = Field(..., description="Plugin display name")
    error: Optional[str] = Field(None, description="Error message if plugin is in FAILED state")


class HealthResponse(APIBaseModel):
    """Response model for health check"""

    app: str = Field(..., description="Application name")
    version: str = Field(..., description="Application version")
    plugins: dict[str, HealthPluginInfo] = Field(
        default_factory=dict, description="Plugin status map keyed by domain"
    )

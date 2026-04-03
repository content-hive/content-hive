"""
Models for system-related operations.
"""

from pydantic import Field

from contenthive.models.api import APIBaseModel


class RestartResponse(APIBaseModel):
    """Response model for application restart operation"""

    type: str = Field(..., description="Restart type (restart / safe_mode)")
    message: str = Field(..., description="Human-readable status message")


class HealthResponse(APIBaseModel):
    """Response model for health check"""

    app: str = Field(..., description="Application name")
    version: str = Field(..., description="Application version")
    plugin_updates_available: bool = Field(
        ..., description="Whether any installed plugin has an update available"
    )

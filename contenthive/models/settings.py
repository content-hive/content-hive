"""
API models for application settings.
"""

from pydantic import Field

from contenthive.models.api import APIBaseModel


class AuthSettingsUpdate(APIBaseModel):
    """Partial update for authentication token settings."""

    access_token_expire_minutes: int | None = Field(default=None, ge=1)
    refresh_token_expire_days: int | None = Field(default=None, ge=1)


class DownloadSettingsUpdate(APIBaseModel):
    """Partial update for media download settings."""

    max_retries: int | None = Field(default=None, ge=0)
    user_agent: str | None = None


class UpdateAppSettingsRequest(APIBaseModel):
    """Request body for PUT /v1/system/settings."""

    auth: AuthSettingsUpdate | None = None
    download: DownloadSettingsUpdate | None = None

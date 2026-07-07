from typing import Literal

from pydantic import BaseModel, Field

DEFAULT_DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 "
    "Safari/537.36 Edg/143.0.0.0"
)


class PluginSettings(BaseModel):
    """Plugin repository settings."""

    repo_url: str = Field(
        default="https://github.com/content-hive/plugins.git",
        title="Plugin Repository URL",
        description="Git repository URL for plugin distribution",
    )
    repo_ref_type: Literal["branch", "tag", "commit"] = Field(
        default="branch",
        title="Ref Type",
        description="Repository ref type: branch, tag, or commit",
    )
    repo_ref: str = Field(
        default="main",
        title="Ref Value",
        description="Repository ref value (branch name, tag, or commit SHA)",
    )


class AuthSettings(BaseModel):
    """Authentication token settings."""

    access_token_expire_minutes: int = Field(
        default=60,
        ge=1,
        title="Access Token Expiry (minutes)",
    )
    refresh_token_expire_days: int = Field(
        default=30,
        ge=1,
        title="Refresh Token Expiry (days)",
    )


class DownloadSettings(BaseModel):
    """Media download settings."""

    max_retries: int = Field(
        default=3,
        ge=0,
        title="Download Max Retries",
        description="Maximum retries for media download failures",
    )
    user_agent: str = Field(
        default=DEFAULT_DOWNLOAD_USER_AGENT,
        title="Download User-Agent",
        description="HTTP User-Agent header used for media downloads",
    )


class AppSettings(BaseModel):
    """Application settings persisted to settings.yaml."""

    plugins: PluginSettings = Field(default_factory=PluginSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    download: DownloadSettings = Field(default_factory=DownloadSettings)

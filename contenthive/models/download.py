"""API models for live download progress / retry overlay (not persisted)."""

from pydantic import Field

from contenthive.models.api import APIBaseModel
from contenthive.models.enumerates import DownloadRetryPhase


class DownloadRetryInfo(APIBaseModel):
    """Live retry state for an in-flight built-in download (not persisted)."""

    attempt: int = Field(..., description="Current attempt on this URL (1-based)", ge=1)
    max_attempts: int = Field(..., description="Max attempts per URL (max_retries + 1)", ge=1)
    url_index: int = Field(..., description="0-based index into primary + fallback URL list", ge=0)
    url_count: int = Field(..., description="Total URLs being tried", ge=1)
    phase: DownloadRetryPhase = Field(..., description="Current download retry phase")

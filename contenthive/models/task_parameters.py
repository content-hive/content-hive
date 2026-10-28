"""
Typed task parameter models (JSON column payloads validated by TaskType).
"""

from typing import Any

from pydantic import ConfigDict, Field, ValidationError

from contenthive.logger import logger
from contenthive.models.api import APIBaseModel
from contenthive.models.enumerates import AuthorProfileAsset, TaskType
from contenthive.plugins.contracts import ParserMediaInfo


class TaskParametersBase(APIBaseModel):
    """Base for task parameter payloads; ignore unknown keys from legacy JSON."""

    model_config = ConfigDict(extra="ignore")


class ParseContentMainParameters(TaskParametersBase):
    """Main task parameters for PARSE_CONTENT."""

    url: str = Field(..., description="URL to parse")
    plugin_id: str | None = Field(None, description="Optional plugin domain override")


class ParseContentSubParameters(TaskParametersBase):
    """Sub task parameters for PARSE_CONTENT."""

    url: str = Field(..., description="URL to parse")
    plugin_id: str | None = Field(None, description="Optional plugin domain override")


class MediaDownloadSubParameters(TaskParametersBase):
    """Sub task parameters for MEDIA_DOWNLOAD."""

    platform: str = Field(..., description="Platform code")
    author: str = Field(..., description="Author uid")
    content_id: str = Field(..., description="Resolved content ID")
    parse_result_id: int = Field(..., description="Owning parse result ID for skip checks")
    plugin_domain: str | None = Field(None, description="Plugin domain used for download")
    media_index: int = Field(0, description="Index of this media item in the parse result")
    media: ParserMediaInfo = Field(..., description="Media metadata to download")


class AuthorProfileDownloadSubParameters(TaskParametersBase):
    """Sub task parameters for AUTHOR_PROFILE_DOWNLOAD (one asset per sub task)."""

    asset: AuthorProfileAsset = Field(..., description="Avatar or banner")
    platform: str = Field(..., description="Platform code")
    author_uid: str = Field(..., description="Author uid")
    url: str = Field(..., description="Remote asset URL")
    prev_url: str | None = Field(None, description="Previous remote URL before this parse")
    prev_path: str | None = Field(None, description="Previous local /media path")


class ContentAnalysisSubParameters(TaskParametersBase):
    """Sub task parameters for CONTENT_ANALYSIS (placeholder until implemented)."""

    payload: dict[str, Any] | None = Field(None, description="Placeholder analysis inputs")


MainTaskParameters = ParseContentMainParameters

SubTaskParameters = (
    ParseContentSubParameters
    | MediaDownloadSubParameters
    | AuthorProfileDownloadSubParameters
    | ContentAnalysisSubParameters
)


def parse_main_task_parameters(task_type: TaskType, raw: dict[str, Any] | None) -> MainTaskParameters | None:
    """Validate a main task parameters JSON blob for the given task type."""
    if raw is None:
        return None
    try:
        if task_type == TaskType.PARSE_CONTENT:
            return ParseContentMainParameters.model_validate(raw)
        logger.warning(f"No main task parameters model for type {task_type}")
        return None
    except ValidationError:
        logger.warning(f"Invalid main task parameters for type {task_type}: {raw!r}", exc_info=True)
        return None


def parse_sub_task_parameters(task_type: TaskType, raw: dict[str, Any] | None) -> SubTaskParameters | None:
    """Validate a sub task parameters JSON blob for the given task type."""
    if raw is None:
        return None
    try:
        if task_type == TaskType.PARSE_CONTENT:
            return ParseContentSubParameters.model_validate(raw)
        if task_type == TaskType.MEDIA_DOWNLOAD:
            return MediaDownloadSubParameters.model_validate(raw)
        if task_type == TaskType.AUTHOR_PROFILE_DOWNLOAD:
            return AuthorProfileDownloadSubParameters.model_validate(raw)
        if task_type == TaskType.CONTENT_ANALYSIS:
            return ContentAnalysisSubParameters.model_validate(raw)
        logger.warning(f"No sub task parameters model for type {task_type}")
        return None
    except ValidationError:
        logger.warning(f"Invalid sub task parameters for type {task_type}: {raw!r}", exc_info=True)
        return None

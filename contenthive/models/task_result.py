"""
Typed task result models (JSON column payloads validated by TaskType).
"""

from typing import Any

from pydantic import ConfigDict, Field, ValidationError

from contenthive.logger import logger
from contenthive.models.api import APIBaseModel
from contenthive.models.enumerates import AuthorProfileAsset, SubTaskResultStatus, TaskType


class TaskResultBase(APIBaseModel):
    """Base for task result payloads; ignore unknown keys from legacy JSON."""

    model_config = ConfigDict(extra="ignore")


class ParseContentMainResult(TaskResultBase):
    """Main task result for PARSE_CONTENT (summary only; parse_result_id lives on the column)."""

    media_count: int = Field(0, description="Total media items from parse")
    downloaded_count: int = Field(0, description="Successfully downloaded media count")
    skipped_count: int = Field(0, description="Media downloads skipped (already present locally)")
    failed_count: int = Field(0, description="Failed download count")


class ParseContentSubResult(TaskResultBase):
    """Sub task result for PARSE_CONTENT."""

    status: SubTaskResultStatus = Field(..., description="Outcome status")
    platform: str | None = Field(None, description="Platform code")
    author: str | None = Field(None, description="Author username")
    content_id: str | None = Field(None, description="Resolved content ID")
    media_count: int | None = Field(None, description="Number of media items parsed")
    url: str | None = Field(None, description="Canonical content URL")


class MediaDownloadSubResult(TaskResultBase):
    """Sub task result for MEDIA_DOWNLOAD."""

    status: SubTaskResultStatus = Field(..., description="Outcome status")
    media_path: str | None = Field(None, description="Relative path to downloaded media")


class AuthorProfileDownloadSubResult(TaskResultBase):
    """Sub task result for AUTHOR_PROFILE_DOWNLOAD (one asset per sub task)."""

    status: SubTaskResultStatus = Field(..., description="Outcome status")
    asset: AuthorProfileAsset | None = Field(None, description="Avatar or banner")
    path: str | None = Field(None, description="Relative /media path to the downloaded file")


class ContentAnalysisSubResult(TaskResultBase):
    """Sub task result for CONTENT_ANALYSIS (placeholder until implemented)."""

    status: SubTaskResultStatus = Field(..., description="Outcome status")
    sub_task_id: str | None = Field(None, description="Sub task public identifier")
    task_type: str | None = Field(None, description="Task type value")
    parameters: dict[str, Any] | None = Field(None, description="Sub task parameters")
    message: str | None = Field(None, description="Status message")


MainTaskResult = ParseContentMainResult

SubTaskResult = (
    ParseContentSubResult | MediaDownloadSubResult | AuthorProfileDownloadSubResult | ContentAnalysisSubResult
)


def parse_main_task_result(task_type: TaskType, raw: dict[str, Any] | None) -> MainTaskResult | None:
    """Validate a main task result JSON blob for the given task type."""
    if raw is None:
        return None
    try:
        if task_type == TaskType.PARSE_CONTENT:
            return ParseContentMainResult.model_validate(raw)
        logger.warning(f"No main task result model for type {task_type}")
        return None
    except ValidationError:
        logger.warning(f"Invalid main task result for type {task_type}: {raw!r}", exc_info=True)
        return None


def parse_sub_task_result(task_type: TaskType, raw: dict[str, Any] | None) -> SubTaskResult | None:
    """Validate a sub task result JSON blob for the given task type."""
    if raw is None:
        return None
    try:
        if task_type == TaskType.PARSE_CONTENT:
            return ParseContentSubResult.model_validate(raw)
        if task_type == TaskType.MEDIA_DOWNLOAD:
            return MediaDownloadSubResult.model_validate(raw)
        if task_type == TaskType.AUTHOR_PROFILE_DOWNLOAD:
            return AuthorProfileDownloadSubResult.model_validate(raw)
        if task_type == TaskType.CONTENT_ANALYSIS:
            return ContentAnalysisSubResult.model_validate(raw)
        logger.warning(f"No sub task result model for type {task_type}")
        return None
    except ValidationError:
        logger.warning(f"Invalid sub task result for type {task_type}: {raw!r}", exc_info=True)
        return None

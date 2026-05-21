import math
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status

from contenthive.const import APP_NAME, APP_VERSION
from contenthive.core.restart import RestartType, get_restart_manager
from contenthive.logger import logger, parse_log_file
from contenthive.models.api import APIResponse, DetailedHTTPException, ErrorDetail
from contenthive.models.content import PaginatedResponse, PaginationInfo
from contenthive.models.enumerates import ResponseStatus
from contenthive.models.system import HealthResponse, LogEntry, RestartResponse, StorageStatusResponse
from contenthive.models.user import UserModel
from contenthive.plugins.manager import get_plugin_manager
from contenthive.routers.user import get_current_admin_user
from contenthive.services.storage import storage_service

router_v1 = APIRouter(prefix="/v1/system", tags=["system"])


@router_v1.post("/restart", response_model=APIResponse[RestartResponse])
async def restart_application(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
    background_tasks: BackgroundTasks,
    safe_mode: bool = False,
) -> APIResponse[RestartResponse]:
    """
    Restart application (HA style)

    - safe_mode: Whether to restart in safe mode (disable all plugins)
    """
    restart_manager = get_restart_manager()
    if not restart_manager:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(
                code="RESTART_MANAGER_NOT_INITIALIZED",
                message="Restart manager not initialized",
            ),
        )

    restart_type = RestartType.SAFE_MODE if safe_mode else RestartType.RESTART
    logger.warning(f"API restart requested: {restart_type.value}")
    background_tasks.add_task(restart_manager.async_restart, delay=1.0, restart_type=restart_type)

    return APIResponse(
        status=ResponseStatus.SUCCESS,
        data=RestartResponse(type=restart_type.value, message="Application will restart in 1 second"),
    )


@router_v1.get("/health", response_model=APIResponse[HealthResponse])
async def health_check() -> APIResponse[HealthResponse]:
    """Health check"""
    plugin_manager = get_plugin_manager()
    plugin_updates_available = bool(plugin_manager and any(plugin_manager._available_updates.values()))

    return APIResponse(
        status=ResponseStatus.SUCCESS,
        data=HealthResponse(
            app=APP_NAME,
            version=APP_VERSION,
            plugin_updates_available=plugin_updates_available,
        ),
    )


@router_v1.get("/storage", response_model=APIResponse[StorageStatusResponse])
async def get_storage_status(
    _: Annotated[UserModel, Depends(get_current_admin_user)],
) -> APIResponse[StorageStatusResponse]:
    """
    Get server storage usage status (Admin only)
    """
    try:
        return APIResponse(status=ResponseStatus.SUCCESS, data=await storage_service.get_storage_status())
    except Exception as e:
        logger.exception("Failed to collect storage status")
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="STORAGE_STATUS_FAILED", message="Failed to collect storage status"),
        ) from e


@router_v1.get("/logs", response_model=APIResponse[PaginatedResponse[LogEntry]])
async def get_logs(
    _: Annotated[UserModel, Depends(get_current_admin_user)],
    date: str | None = Query(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Filter by date (YYYY-MM-DD). Defaults to the most recent 3 days.",
    ),
    level: str | None = Query(default=None, description="Filter by log level (DEBUG/INFO/WARNING/ERROR/CRITICAL)"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=100, ge=1, le=500, description="Items per page"),
) -> APIResponse[PaginatedResponse[LogEntry]]:
    """
    Query structured application logs (Admin only).

    Returns entries in reverse chronological order (newest first).
    When no date is specified, returns logs from the most recent 3 days.
    """
    try:
        raw = parse_log_file(date)
    except Exception as e:
        logger.exception("Failed to read log file")
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="LOG_READ_FAILED", message="Failed to read log file"),
        ) from e

    raw = list(reversed(raw))

    if level:
        raw = [e for e in raw if e["level"] == level.upper()]

    total = len(raw)
    total_pages = math.ceil(total / page_size) if total else 0
    page_items = [LogEntry(**e) for e in raw[(page - 1) * page_size : page * page_size]]

    return APIResponse(
        status=ResponseStatus.SUCCESS,
        data=PaginatedResponse(
            items=page_items,
            pagination=PaginationInfo(page=page, page_size=page_size, total=total, total_pages=total_pages),
        ),
    )

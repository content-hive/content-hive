from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Query, status

from contenthive.const import APP_NAME, APP_VERSION
from contenthive.core.restart import RestartType, get_restart_manager
from contenthive.logger import logger, query_logs
from contenthive.models.api import APIResponse, DetailedHTTPException, ErrorDetail
from contenthive.models.enumerates import ResponseStatus
from contenthive.models.settings import UpdateAppSettingsRequest
from contenthive.models.system import (
    CursorPaginatedResponse,
    HealthResponse,
    LogEntry,
    RestartResponse,
    StorageStatusResponse,
)
from contenthive.models.user import UserModel
from contenthive.plugins.manager import get_plugin_manager
from contenthive.routers.user import get_current_admin_user
from contenthive.services.settings import SettingsValidationError, settings_service
from contenthive.services.setup import setup_service
from contenthive.services.storage import storage_service
from contenthive.settings.schema import AppSettings

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
    setup_complete = setup_service.is_setup_complete()

    return APIResponse(
        status=ResponseStatus.SUCCESS,
        data=HealthResponse(
            app=APP_NAME,
            version=APP_VERSION,
            plugin_updates_available=plugin_updates_available,
            setup_required=not setup_complete,
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


@router_v1.get("/logs", response_model=APIResponse[CursorPaginatedResponse[LogEntry]])
async def get_logs(
    _: Annotated[UserModel, Depends(get_current_admin_user)],
    from_: datetime | None = Query(
        default=None,
        alias="from",
        description="Start of time range (inclusive). Defaults to 3 days before `to`.",
    ),
    to: datetime | None = Query(
        default=None,
        description=(
            "End of time range (exclusive). Defaults to now. "
            "To query across a large range, tile requests: [t0, t1) then [t1, t2)."
        ),
    ),
    level: str | None = Query(default=None, description="Filter by log level (DEBUG/INFO/WARNING/ERROR/CRITICAL)"),
    limit: int = Query(default=100, ge=1, le=500, description="Max items per page"),
    cursor: str | None = Query(default=None, description="Pagination cursor returned by the previous response"),
) -> APIResponse[CursorPaginatedResponse[LogEntry]]:
    """
    Query structured application logs (Admin only).

    Returns entries in reverse chronological order (newest first).
    Time range is a half-open interval [from, to). Use `next_cursor` from the response
    to fetch the next page; null means no more data.
    """
    now = datetime.now(UTC).replace(tzinfo=None)

    def _to_utc_naive(dt: datetime) -> datetime:
        return dt.replace(tzinfo=None) if dt.tzinfo is None else dt.astimezone(UTC).replace(tzinfo=None)

    resolved_to = _to_utc_naive(to) if to is not None else (now + timedelta(seconds=1))
    resolved_from = _to_utc_naive(from_) if from_ is not None else (resolved_to - timedelta(days=3))

    if resolved_from > resolved_to:
        raise DetailedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(code="INVALID_TIME_RANGE", message="`from` must be before `to`"),
        )

    try:
        items_raw, next_cursor = query_logs(resolved_from, resolved_to, level, limit, cursor)
    except ValueError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(code="INVALID_CURSOR", message=str(e)),
        ) from e
    except Exception as e:
        logger.exception("Failed to read log file")
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="LOG_READ_FAILED", message="Failed to read log file"),
        ) from e

    return APIResponse(
        status=ResponseStatus.SUCCESS,
        data=CursorPaginatedResponse(
            items=[LogEntry(**e) for e in items_raw],
            next_cursor=next_cursor,
        ),
    )


@router_v1.get("/settings", response_model=APIResponse[AppSettings])
async def get_app_settings(
    _: Annotated[UserModel, Depends(get_current_admin_user)],
) -> APIResponse[AppSettings]:
    """Get application settings (Admin only)."""
    try:
        data = settings_service.get_app_settings()
    except SettingsValidationError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ErrorDetail(
                code="PERSISTED_SETTINGS_INVALID",
                message="Stored application settings are invalid and cannot be read",
                details={"errors": e.errors},
            ),
        ) from e
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)


@router_v1.put("/settings", response_model=APIResponse[AppSettings])
async def update_app_settings(
    _: Annotated[UserModel, Depends(get_current_admin_user)],
    body: UpdateAppSettingsRequest = Body(...),
) -> APIResponse[AppSettings]:
    """Update application settings (Admin only)."""
    try:
        data = settings_service.update_app_settings(body)
    except SettingsValidationError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(
                code="SETTINGS_VALIDATION_FAILED",
                message="Application settings validation failed",
                details={"errors": e.errors},
            ),
        ) from e
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)

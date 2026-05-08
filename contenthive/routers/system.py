from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status

from contenthive.const import APP_NAME, APP_VERSION
from contenthive.core.restart import RestartType, get_restart_manager
from contenthive.logger import logger
from contenthive.models.api import APIResponse, DetailedHTTPException, ErrorDetail
from contenthive.models.enumerates import ResponseStatus
from contenthive.models.system import HealthResponse, RestartResponse
from contenthive.models.user import UserModel
from contenthive.plugins.manager import get_plugin_manager
from contenthive.routers.user import get_current_admin_user

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
    background_tasks.add_task(
        restart_manager.async_restart, delay=1.0, restart_type=restart_type
    )

    return APIResponse(
        status=ResponseStatus.SUCCESS,
        data=RestartResponse(
            type=restart_type.value, message="Application will restart in 1 second"
        ),
    )


@router_v1.get("/health", response_model=APIResponse[HealthResponse])
async def health_check() -> APIResponse[HealthResponse]:
    """Health check"""
    plugin_manager = get_plugin_manager()
    plugin_updates_available = bool(
        plugin_manager and any(plugin_manager._available_updates.values())
    )

    return APIResponse(
        status=ResponseStatus.SUCCESS,
        data=HealthResponse(
            app=APP_NAME,
            version=APP_VERSION,
            plugin_updates_available=plugin_updates_available,
        ),
    )

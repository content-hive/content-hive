from typing import Annotated
from fastapi import APIRouter, Depends, BackgroundTasks, status

from contenthive.logger import logger
from contenthive.core.restart import get_restart_manager, RestartType
from contenthive.models.api import APIResponse, DetailedHTTPException, ErrorDetail
from contenthive.models.enumerates import ResponseStatus
from contenthive.models.system import (
    CheckConfigResponse,
    CheckUpdatesResponse,
    HealthResponse,
    ReloadResponse,
    RestartResponse,
    UpdatePluginsRequest,
    UpdatePluginsResponse,
)
from contenthive.models.user import UserModel
from contenthive.routers.user import get_current_admin_user
from contenthive.services.plugin import plugin_service

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
                message="Restart manager not initialized"
            )
        )

    restart_type = RestartType.SAFE_MODE if safe_mode else RestartType.RESTART
    logger.warning(f"API restart requested: {restart_type.value}")
    background_tasks.add_task(restart_manager.async_restart, delay=1.0, restart_type=restart_type)

    return APIResponse(
        status=ResponseStatus.SUCCESS,
        data=RestartResponse(
            type=restart_type.value,
            message="Application will restart in 1 second"
        )
    )


@router_v1.post("/reload", response_model=APIResponse[ReloadResponse])
async def reload_configuration(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
) -> APIResponse[ReloadResponse]:
    """Reload all plugins (HA's reload core config)"""
    try:
        data = await plugin_service.reload_all()
    except RuntimeError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="PLUGIN_MANAGER_NOT_INITIALIZED", message=str(e))
        )
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)


@router_v1.post("/check-config", response_model=APIResponse[CheckConfigResponse])
async def check_configuration(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
) -> APIResponse[CheckConfigResponse]:
    """Validate plugin configuration"""
    try:
        data = plugin_service.check_config()
    except RuntimeError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="PLUGIN_MANAGER_NOT_INITIALIZED", message=str(e))
        )
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)


@router_v1.post("/plugins/update", response_model=APIResponse[UpdatePluginsResponse])
async def update_plugins(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
    body: UpdatePluginsRequest = UpdatePluginsRequest(),
) -> APIResponse[UpdatePluginsResponse]:
    """
    Download and reload plugins from the remote repository.

    - domains: list of plugin domains to update. Empty means update all.
    """
    try:
        data = await plugin_service.update_plugins(body.domains)
    except RuntimeError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="PLUGIN_MANAGER_NOT_INITIALIZED", message=str(e))
        )
    except Exception as e:
        logger.error(f"Plugin update failed: {e}")
        raise DetailedHTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=ErrorDetail(code="PLUGIN_DOWNLOAD_FAILED", message=str(e))
        )
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)


@router_v1.get("/plugins/updates", response_model=APIResponse[CheckUpdatesResponse])
async def check_plugin_updates(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
) -> APIResponse[CheckUpdatesResponse]:
    """
    Check for available plugin updates.
    Results are cached on the plugin manager and reflected in /health responses.
    """
    try:
        data = await plugin_service.check_updates()
    except RuntimeError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="PLUGIN_MANAGER_NOT_INITIALIZED", message=str(e))
        )
    except Exception as e:
        logger.warning(f"Plugin update check failed: {e}")
        raise DetailedHTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=ErrorDetail(code="UPDATE_CHECK_FAILED", message=f"Failed to fetch remote plugin manifest: {e}")
        )
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)


@router_v1.get("/health", response_model=APIResponse[HealthResponse])
async def health_check() -> APIResponse[HealthResponse]:
    """Health check with plugin status"""
    return APIResponse(status=ResponseStatus.SUCCESS, data=plugin_service.get_health())

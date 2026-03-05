from typing import Annotated
from fastapi import APIRouter, Depends, BackgroundTasks, status

from contenthive.logger import logger
from contenthive.core.restart import get_restart_manager, RestartType
from contenthive.plugins.registry import PluginState
from contenthive.config import settings
from contenthive.models.api import APIResponse, DetailedHTTPException, ErrorDetail
from contenthive.models.enumerates import ResponseStatus
from contenthive.models.system import (
    CheckConfigResponse,
    HealthPluginInfo,
    HealthResponse,
    ReloadResponse,
    RestartResponse,
)
from contenthive.models.user import UserModel
from contenthive.routers.user import get_current_admin_user

router_v1 = APIRouter(prefix="/v1/system", tags=["system"])


@router_v1.post("/restart", response_model=APIResponse[RestartResponse])
async def restart_application(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
    background_tasks: BackgroundTasks,
    safe_mode: bool = False
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
    
    # Use background task for async restart, give time to return response
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
    current_user: Annotated[UserModel, Depends(get_current_admin_user)]
) -> APIResponse[ReloadResponse]:
    """
    Reload configuration (HA's reload core config)
    """
    from contenthive.plugins.manager import get_plugin_manager
    
    plugin_manager = get_plugin_manager()
    if not plugin_manager:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(
                code="PLUGIN_MANAGER_NOT_INITIALIZED",
                message="Plugin manager not initialized"
            )
        )
    
    # Reload all plugins
    results: dict[str, str] = {}
    for domain in list(plugin_manager.plugins.keys()):
        try:
            success = await plugin_manager.async_reload(domain)
            results[domain] = "reloaded" if success else "failed"
        except Exception as e:
            results[domain] = f"error: {str(e)}"
            logger.error(f"Failed to reload {domain}: {e}")
    
    return APIResponse(
        status=ResponseStatus.SUCCESS,
        data=ReloadResponse(
            message="Configuration reloaded",
            plugins=results
        )
    )


@router_v1.post("/check-config", response_model=APIResponse[CheckConfigResponse])
async def check_configuration(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)]
) -> APIResponse[CheckConfigResponse]:
    """
    Check configuration validity (HA's config check)
    Validate configuration before restart
    """
    from contenthive.plugins.manager import get_plugin_manager
    
    plugin_manager = get_plugin_manager()
    if not plugin_manager:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(
                code="PLUGIN_MANAGER_NOT_INITIALIZED",
                message="Plugin manager not initialized"
            )
        )
    
    errors: list[str] = []
    warnings: list[str] = []
    
    # Validate plugin configuration
    for domain, record in plugin_manager.plugins.items():
        manifest = record.manifest
        
        # Check required fields
        required_fields = ["domain", "name", "version"]
        for field in required_fields:
            if field not in manifest:
                errors.append(f"{domain}: Missing required field '{field}'")
        
        # Check dependencies
        requirements = manifest.get("requirements", [])
        
        for dep in requirements:
            if dep not in plugin_manager.plugins:
                warnings.append(f"{domain}: Dependency '{dep}' not found")
    
    is_valid = len(errors) == 0
    
    return APIResponse(
        status=ResponseStatus.SUCCESS,
        data=CheckConfigResponse(
            valid=is_valid,
            errors=errors,
            warnings=warnings,
            message="Configuration is valid" if is_valid else "Configuration has errors"
        )
    )


@router_v1.get("/health", response_model=APIResponse[HealthResponse])
async def health_check() -> APIResponse[HealthResponse]:
    """
    Health check endpoint with plugin status information.
    """
    from contenthive.plugins.manager import get_plugin_manager
    
    plugin_manager = get_plugin_manager()
    
    plugin_status: dict[str, HealthPluginInfo] = {}
    if plugin_manager:
        for domain, record in plugin_manager.plugins.items():
            plugin_status[domain] = HealthPluginInfo(
                state=record.state.value,
                version=record.version,
                name=record.name,
                error=record.error if record.state == PluginState.FAILED else None
            )
    
    return APIResponse(
        status=ResponseStatus.SUCCESS,
        data=HealthResponse(
            app=settings.app_name,
            version=settings.app_version,
            plugins=plugin_status
        )
    )
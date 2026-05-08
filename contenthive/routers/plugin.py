from typing import Annotated

from fastapi import APIRouter, Body, Depends, status

from contenthive.logger import logger
from contenthive.models.api import (
    APIResponse,
    DetailedHTTPException,
    ErrorDetail,
    OperationResult,
)
from contenthive.models.enumerates import ResponseStatus
from contenthive.models.plugin import (
    AvailablePluginsResponse,
    CheckConfigResponse,
    CheckUpdatesResponse,
    PluginConfigResponse,
    PluginListResponse,
    ReloadResponse,
    UpdatePluginConfigRequest,
    UpdatePluginConfigResponse,
    UpdatePluginsRequest,
    UpdatePluginsResponse,
)
from contenthive.models.user import UserModel
from contenthive.routers.user import get_current_admin_user
from contenthive.services.plugin import ConfigValidationError, plugin_service

router_v1 = APIRouter(prefix="/v1/plugins", tags=["plugins"])


@router_v1.get("/", response_model=APIResponse[PluginListResponse])
async def list_plugins(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
) -> APIResponse[PluginListResponse]:
    """List all installed plugins with their current state and version info"""
    return APIResponse(
        status=ResponseStatus.SUCCESS, data=plugin_service.list_plugins()
    )


@router_v1.get("/available", response_model=APIResponse[AvailablePluginsResponse])
async def list_available_plugins(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
) -> APIResponse[AvailablePluginsResponse]:
    """List all plugins available in the remote repository, including uninstalled ones"""
    try:
        data = await plugin_service.list_available()
    except Exception as e:
        logger.exception("Failed to fetch available plugins")
        raise DetailedHTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=ErrorDetail(
                code="REMOTE_MANIFEST_FETCH_FAILED",
                message="Failed to fetch remote plugin manifest",
                details={"error": str(e)},
            ),
        )
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)


@router_v1.post("/reload", response_model=APIResponse[ReloadResponse])
async def reload_plugins(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
) -> APIResponse[ReloadResponse]:
    """Reload all plugins"""
    try:
        data = await plugin_service.reload_all()
    except RuntimeError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="PLUGIN_MANAGER_NOT_INITIALIZED", message=str(e)),
        )
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)


@router_v1.post("/check-config", response_model=APIResponse[CheckConfigResponse])
async def check_plugin_config(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
) -> APIResponse[CheckConfigResponse]:
    """Validate plugin configuration"""
    try:
        data = plugin_service.check_config()
    except RuntimeError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="PLUGIN_MANAGER_NOT_INITIALIZED", message=str(e)),
        )
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)


@router_v1.get("/check-updates", response_model=APIResponse[CheckUpdatesResponse])
async def check_plugin_updates(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
) -> APIResponse[CheckUpdatesResponse]:
    """
    Check whether installed plugins have newer versions available in the remote repository.
    """
    try:
        data = await plugin_service.check_updates()
    except RuntimeError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="PLUGIN_MANAGER_NOT_INITIALIZED", message=str(e)),
        )
    except Exception as e:
        logger.warning(f"Plugin update check failed: {e}")
        raise DetailedHTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=ErrorDetail(
                code="UPDATE_CHECK_FAILED",
                message=f"Failed to fetch remote plugin manifest: {e}",
            ),
        )
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)


@router_v1.post("/{domain}/disable", response_model=APIResponse[OperationResult])
async def disable_plugin(
    domain: str,
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
) -> APIResponse[OperationResult]:
    """Disable a plugin and persist the state"""
    try:
        data = await plugin_service.disable(domain)
    except ValueError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorDetail(code="PLUGIN_NOT_FOUND", message=str(e)),
        )
    except RuntimeError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="PLUGIN_DISABLE_FAILED", message=str(e)),
        )
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)


@router_v1.post("/{domain}/enable", response_model=APIResponse[OperationResult])
async def enable_plugin(
    domain: str,
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
) -> APIResponse[OperationResult]:
    """Enable a previously disabled plugin"""
    try:
        data = await plugin_service.enable(domain)
    except ValueError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorDetail(code="PLUGIN_NOT_FOUND", message=str(e)),
        )
    except RuntimeError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="PLUGIN_ENABLE_FAILED", message=str(e)),
        )
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)


@router_v1.delete("/{domain}", response_model=APIResponse[OperationResult])
async def delete_plugin(
    domain: str,
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
) -> APIResponse[OperationResult]:
    """Delete a plugin: unload it and remove its files from disk"""
    try:
        data = await plugin_service.delete(domain)
    except ValueError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorDetail(code="PLUGIN_NOT_FOUND", message=str(e)),
        )
    except RuntimeError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="PLUGIN_DELETE_FAILED", message=str(e)),
        )
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)


@router_v1.get("/{domain}/config", response_model=APIResponse[PluginConfigResponse])
async def get_plugin_config(
    domain: str,
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
) -> APIResponse[PluginConfigResponse]:
    """Get settings schema with current config values for a plugin.
    Returns an empty settings list if the plugin has no CONFIG_SCHEMA declared."""
    try:
        data = plugin_service.get_plugin_settings(domain)
    except ValueError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorDetail(code="PLUGIN_NOT_FOUND", message=str(e)),
        )
    except ConfigValidationError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ErrorDetail(
                code="PERSISTED_CONFIG_INVALID",
                message="Stored plugin config is invalid and cannot be read",
                details={"errors": e.errors},
            ),
        )
    except RuntimeError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="PLUGIN_MANAGER_NOT_INITIALIZED", message=str(e)),
        )
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)


@router_v1.put(
    "/{domain}/config", response_model=APIResponse[UpdatePluginConfigResponse]
)
async def update_plugin_config(
    domain: str,
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
    body: UpdatePluginConfigRequest = Body(...),
) -> APIResponse[UpdatePluginConfigResponse]:
    """Update plugin configuration fields.

    - If the plugin has no CONFIG_SCHEMA, all incoming keys are ignored.
    - If schema exists: framework-reserved keys are rejected, undeclared keys are ignored,
      type checking is enforced, and required fields must be provided.
    """
    try:
        data = plugin_service.update_plugin_settings(domain, body)
    except ValueError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorDetail(code="PLUGIN_NOT_FOUND", message=str(e)),
        )
    except ConfigValidationError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(
                code="CONFIG_VALIDATION_FAILED",
                message="Plugin config validation failed",
                details={"errors": e.errors},
            ),
        )
    except RuntimeError as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="PLUGIN_MANAGER_NOT_INITIALIZED", message=str(e)),
        )
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)


@router_v1.post("/update", response_model=APIResponse[UpdatePluginsResponse])
async def update_plugins(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
    body: UpdatePluginsRequest = Body(default_factory=UpdatePluginsRequest),
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
            detail=ErrorDetail(code="PLUGIN_MANAGER_NOT_INITIALIZED", message=str(e)),
        )
    except Exception as e:
        logger.error(f"Plugin update failed: {e}")
        raise DetailedHTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=ErrorDetail(code="PLUGIN_DOWNLOAD_FAILED", message=str(e)),
        )
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)

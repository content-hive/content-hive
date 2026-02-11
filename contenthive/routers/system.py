from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os

from contenthive.logger import logger
from contenthive.core.restart import get_restart_manager, RestartType
from contenthive.plugins.registry import PluginState
from contenthive.config import settings

router_v1 = APIRouter(prefix="/v1/system", tags=["system"])
security = HTTPBearer()


# Development environment: temporarily disable token verification
# async def verify_admin_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
#     """Verify admin token"""
#     admin_token = os.getenv("ADMIN_TOKEN", "your-secret-admin-token")
#     
#     if credentials.credentials != admin_token:
#         raise HTTPException(status_code=403, detail="Invalid admin token")
#     
#     return credentials.credentials


@router_v1.post("/restart")
async def restart_application(
    background_tasks: BackgroundTasks,
    safe_mode: bool = False
):
    """
    Restart application (HA style)
    
    - safe_mode: Whether to restart in safe mode (disable all plugins)
    """
    restart_manager = get_restart_manager()
    if not restart_manager:
        raise HTTPException(status_code=500, detail="Restart manager not initialized")
    
    restart_type = RestartType.SAFE_MODE if safe_mode else RestartType.RESTART
    
    logger.warning(f"API restart requested: {restart_type.value}")
    
    # Use background task for async restart, give time to return response
    background_tasks.add_task(restart_manager.async_restart, delay=1.0, restart_type=restart_type)
    
    return {
        "status": "restarting",
        "type": restart_type.value,
        "message": "Application will restart in 1 second"
    }


@router_v1.post("/reload")
async def reload_configuration():
    """
    Reload configuration (HA's reload core config)
    """
    from contenthive.plugins.manager import get_plugin_manager
    
    plugin_manager = get_plugin_manager()
    if not plugin_manager:
        raise HTTPException(status_code=500, detail="Plugin manager not initialized")
    
    # Reload all plugins
    results = {}
    for domain in list(plugin_manager.plugins.keys()):
        try:
            success = await plugin_manager.async_reload(domain)
            results[domain] = "reloaded" if success else "failed"
        except Exception as e:
            results[domain] = f"error: {str(e)}"
            logger.error(f"Failed to reload {domain}: {e}")
    
    return {
        "status": "completed",
        "message": "Configuration reloaded",
        "plugins": results
    }


@router_v1.post("/check-config")
async def check_configuration():
    """
    Check configuration validity (HA's config check)
    Validate configuration before restart
    """
    from contenthive.plugins.manager import get_plugin_manager
    
    plugin_manager = get_plugin_manager()
    if not plugin_manager:
        raise HTTPException(status_code=500, detail="Plugin manager not initialized")
    
    errors = []
    warnings = []
    
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
    
    return {
        "valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "message": "Configuration is valid" if is_valid else "Configuration has errors"
    }


@router_v1.get("/health")
async def health_check():
    """
    Health check endpoint with plugin status information.
    """
    from contenthive.plugins.manager import get_plugin_manager
    
    plugin_manager = get_plugin_manager()
    
    plugin_status = {}
    if plugin_manager:
        for domain, record in plugin_manager.plugins.items():
            plugin_status[domain] = {
                "state": record.state.value,
                "version": record.version,
                "name": record.name,
                "error": record.error if record.state == PluginState.FAILED else None
            }
    
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "plugins": plugin_status
    }
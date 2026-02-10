from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from contenthive.plugins.registry import PluginState
from contenthive.routers import api, system
from contenthive.database.db import initialize_db
from contenthive.config import settings, ensure_directories
from contenthive.plugins.manager import get_plugin_manager
from contenthive.plugins.startup import load_plugins_on_startup, shutdown_plugins
from contenthive.logger import logger, setup_file_logging
from contenthive.core.restart import RestartManager, RestartType, set_restart_manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Ensure necessary directories exist FIRST
    ensure_directories()

    # 2. Now that directories exist, setup file logging
    setup_file_logging()
    
    # 3. Initialize restart manager
    restart_manager = RestartManager(settings.data_dir)
    set_restart_manager(restart_manager)
    
    # 4. Check restart flag (safe mode, etc.)
    restart_type = restart_manager.check_restart_flag()
    if restart_type == RestartType.SAFE_MODE:
        logger.warning("Starting in SAFE MODE - plugins disabled")
        skip_plugins = True
    else:
        skip_plugins = False

    # 5. Initialize the database
    initialize_db()

    # 6. Mount static files AFTER directories are created
    app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

    # 7. Load plugins (unless in safe mode)
    if not skip_plugins:
        await load_plugins_on_startup(app, settings.data_dir)
    else:
        logger.warning("Plugins loading skipped (safe mode)")

    logger.info("Application started successfully.")
    yield
    
    # Application shutdown logic
    await shutdown_plugins()
    logger.info("Shutting down application.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan
)

app.include_router(api.router_v1)
app.include_router(system.router)

@app.get("/health", tags=["health"])
async def health_check():
    """
    Health check endpoint with plugin status information.
    """
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
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from contenthive.plugins.registry import PluginState
from contenthive.routers import api
from contenthive.database.db import initialize_db, get_db_connection
from contenthive.config import settings, ensure_directories
from contenthive.plugins.context import PluginContext
from contenthive.plugins.manager import PluginEntryData, PluginManager, get_plugin_manager, set_plugin_manager
from contenthive.logger import logger, setup_file_logging

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Ensure necessary directories exist FIRST
    ensure_directories()

    # 2. Now that directories exist, setup file logging
    setup_file_logging()

    # 3. Initialize the database
    initialize_db()

    # 4. Mount static files AFTER directories are created
    app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

    # 5. Load plugins
    await load_plugins_on_startup()

    logger.info("Application started successfully.")
    yield
    # Application shutdown logic can go here
    await shutdown_plugins()
    logger.info("Shutting down application.")

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan
)

app.include_router(api.router_v1)

async def load_plugins_on_startup():
    """
    Load and enable plugins on application startup.
    """
    context = PluginContext(
        app=app,
        data_dir=settings.data_dir,
        db_factory=get_db_connection,
        logger=logger
    )

    plugin_manager = PluginManager(settings.plugins_dir, context)
    set_plugin_manager(plugin_manager)

    logger.info("Starting plugin discovery and loading.")
    await plugin_manager.async_discover()
    logger.info(f"Discovered {len(plugin_manager.plugins)} plugins.")

    for domain in plugin_manager.plugins:
        logger.info(f"Setting up plugin: {domain}")

        config = _get_plugin_config(domain)
        success = await plugin_manager.async_setup(domain, config)

        if not success:
            logger.error(f"Failed to set up plugin: {domain}")
            continue

        entry = PluginEntryData(
            entry_id=f"{domain}_default",
            domain=domain,
            data=config or {},
        )

        success = await plugin_manager.async_setup_entry(entry)

        if success:
            logger.info(f"Plugin setup entry successful: {domain}")
        else:
            logger.error(f"Plugin setup entry failed: {domain}")

    enabled_count = sum(
        1 for record in plugin_manager.plugins.values()
        if record.state == PluginState.ENABLED
    )
    logger.info(f"Enabled {enabled_count} plugins.")


def _get_plugin_config(domain: str) -> dict:
    """
    Get plugin configuration from settings or config file.
    In the future, this could load from database or config file.
    """
    # Example: Load from environment or settings
    # You can extend this to read from a config file
    configs = {
        "youtube_parser": {
            "api_key": "",
        },
        # Add more plugin configs as needed
    }
    
    return configs.get(domain, {})


async def shutdown_plugins():
    """
    Gracefully shutdown all plugins.
    """
    plugin_manager = get_plugin_manager()
    if not plugin_manager:
        return
    
    logger.info("Shutting down plugins...")
    
    # Unload all config entries
    entries_to_unload = list(plugin_manager.config_entries.keys())
    for entry_id in entries_to_unload:
        await plugin_manager.async_unload_entry(entry_id)
    
    logger.info("All plugins unloaded")


@app.get("/health", tags=["health"])
async def health_check():
    """
    Health check endpoint.
    """
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version  
    }
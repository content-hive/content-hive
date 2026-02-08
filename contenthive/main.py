from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from contenthive.routers import api
from contenthive.database.db import initialize_db, get_db_connection
from contenthive.config import settings, ensure_directories
from contenthive.plugins.context import PluginContext
from contenthive.plugins.manager import PluginManager, set_plugin_manager
from contenthive.logger import logger, setup_file_logging

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Ensure necessary directories exist FIRST
    ensure_directories()

    # 2. Now that directories exist, setup file logging
    setup_file_logging()

    # 3. Initialize the database
    initialize_db()

    # 4. Load plugins
    await load_plugins_on_startup()

    logger.info("Application started successfully.")
    yield
    # Application shutdown logic can go here
    logger.info("Shutting down application.")

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan
)

app.include_router(api.router_v1)
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

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

    plugin_manager.discover()
    for pid in plugin_manager.plugins:
        plugin_manager.load(pid)
        plugin_manager.enable(pid)


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
from fastapi import FastAPI
from contextlib import asynccontextmanager
from contenthive.routers import api
from contenthive.database.db import initialize_db, get_db_connection
from contenthive.config import settings, ensure_directories
from contenthive.plugins.context import PluginContext
from contenthive.plugins.manager import PluginManager, set_plugin_manager
from contenthive.logger import logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure necessary directories exist
    ensure_directories()
    
    # Initialize the database
    initialize_db()

    # Load plugins
    await load_plugins_on_startup()
    
    yield
    # Application shutdown logic can go here
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

import asyncio
import mimetypes
from fastapi import FastAPI
from contextlib import asynccontextmanager
from pillow_heif import register_heif_opener

from contenthive.routers import admin, content, system, user, task, media
from contenthive.database.database import initialize_db
from contenthive.config import settings, ensure_directories
from contenthive.plugins.startup import load_plugins_on_startup, shutdown_plugins
from contenthive.logger import logger, setup_file_logging
from contenthive.core.restart import RestartManager, RestartType, set_restart_manager
from contenthive.models.api import DetailedHTTPException, http_exception_handler
from contenthive.services.task_queue import task_queue

def register_extra_mimetypes() -> None:
    """
    Register extra mimetypes/extensions not covered by the standard library,
    and register pillow-heif so Pillow can open HEIC files.
    """
    mimetypes.add_type("image/webp", ".webp")
    mimetypes.add_type("image/avif", ".avif")
    mimetypes.add_type("image/heic", ".heic")
    try:
        register_heif_opener()
    except ImportError:
        logger.warning("pillow-heif not installed; HEIC image transformation will not be available")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Startup step 1/8: ensuring directories")
    # 1. Ensure necessary directories exist FIRST
    ensure_directories()

    logger.info("Startup step 2/8: enabling file logging")
    # 2. Now that directories exist, setup file logging
    setup_file_logging()
    
    logger.info("Startup step 3/8: initializing restart manager")
    # 3. Initialize restart manager
    restart_manager = RestartManager(settings.data_dir)
    set_restart_manager(restart_manager)
    
    # Check restart flag (safe mode, etc.)
    restart_type = restart_manager.check_restart_flag()
    if restart_type == RestartType.SAFE_MODE:
        logger.warning("Starting in SAFE MODE - plugins disabled")
        skip_plugins = True
    else:
        skip_plugins = False

    logger.info("Startup step 4/8: initializing database")
    # 4. Initialize database synchronously during startup.
    # This avoids thread-related issues while Alembic configures logging.
    initialize_db()

    logger.info("Startup step 5/8: registering extra mimetypes")
    # 5. Register extra MIME types (media is served via router, not StaticFiles)
    register_extra_mimetypes()

    logger.info("Startup step 6/8: loading plugins")
    # 6. Load plugins (unless in safe mode)
    if not skip_plugins:
        try:
            await load_plugins_on_startup(app, settings.data_dir)
        except asyncio.TimeoutError:
            logger.exception("Plugin loading timed out; continuing without plugins")
        except Exception:
            logger.exception("Plugin loading failed; continuing without plugins")
    else:
        logger.warning("Plugins loading skipped (safe mode)")


    logger.info("Startup step 7/8: starting task queue worker")
    # 7. Start task queue worker
    await task_queue.start()

    logger.info("Startup step 8/8: startup completed")
    logger.info("Application started successfully.")
    
    yield

    # Stop task queue worker gracefully
    await task_queue.stop()

    # Shutdown plugins gracefully
    await shutdown_plugins()

    # Application shutdown logic
    logger.info("Shutting down application.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan
)

app.add_exception_handler(DetailedHTTPException, http_exception_handler)

app.include_router(task.router_v1)
app.include_router(content.router_v1)
app.include_router(user.router_v1)
app.include_router(admin.router_v1)
app.include_router(system.router_v1)
app.include_router(media.router)

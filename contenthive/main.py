
import asyncio
import mimetypes
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from contenthive.routers import admin, content, system, user, task
from contenthive.database.database import initialize_db
from contenthive.config import settings, ensure_directories
from contenthive.plugins.startup import load_plugins_on_startup, shutdown_plugins
from contenthive.logger import logger, setup_file_logging
from contenthive.core.restart import RestartManager, RestartType, set_restart_manager
from contenthive.models.api import DetailedHTTPException, http_exception_handler
from contenthive.services.task_queue import task_queue

def register_extra_mimetypes():
    """
    Register extra mimetypes/extensions not covered by the standard library.
    """
    mimetypes.add_type("image/webp", ".webp")
    mimetypes.add_type("image/avif", ".avif")
    mimetypes.add_type("image/heic", ".heic")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    setup_file_logging()

    restart_manager = RestartManager(settings.data_dir)
    set_restart_manager(restart_manager)

    restart_type = restart_manager.check_restart_flag()
    if restart_type == RestartType.SAFE_MODE:
        logger.warning("Starting in SAFE MODE - plugins disabled")
        skip_plugins = True
    else:
        skip_plugins = False

    initialize_db()

    register_extra_mimetypes()
    app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

    if not skip_plugins:
        try:
            await load_plugins_on_startup()
        except asyncio.TimeoutError:
            logger.exception("Plugin loading timed out; continuing without plugins")
        except Exception:
            logger.exception("Plugin loading failed; continuing without plugins")
    else:
        logger.warning("Plugins loading skipped (safe mode)")

    await task_queue.start()

    logger.info("Application started successfully.")

    yield

    await task_queue.stop()
    await shutdown_plugins()
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

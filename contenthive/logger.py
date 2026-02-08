import logging
from logging.handlers import RotatingFileHandler

from contenthive.config import settings

_logger = None
_file_handler_added = False

def setup_logging():
    """
    Setup logging for the application (console only at module load time).
    """
    global _logger
    if _logger is not None:
        return _logger

    formatting = logging.Formatter(
        '%(asctime)s %(levelname)s:\t  %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    app_logger = logging.getLogger("contenthive")
    app_logger.setLevel(logging.DEBUG)

    # Console handler — always safe to create at import time
    app_console_handler = logging.StreamHandler()
    app_console_handler.setLevel(logging.INFO)
    app_console_handler.setFormatter(formatting)
    app_logger.addHandler(app_console_handler)

    _logger = app_logger
    return app_logger


def setup_file_logging():
    """
    Setup file-based logging. Must be called AFTER ensure_directories().
    """
    global _file_handler_added
    if _file_handler_added:
        return

    formatting = logging.Formatter(
        '%(asctime)s %(levelname)s:\t  %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    rotating_file_handler = RotatingFileHandler(
        filename=settings.logs_dir / "contenthive.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5
    )
    rotating_file_handler.setLevel(logging.DEBUG)
    rotating_file_handler.setFormatter(formatting)

    # Add file handler to app logger
    app_logger = logging.getLogger("contenthive")
    app_logger.addHandler(rotating_file_handler)

    # Add file handler to uvicorn logger
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.setLevel(logging.INFO)
    uvicorn_logger.addHandler(rotating_file_handler)

    _file_handler_added = True
    app_logger.info("File logging initialized.")


logger = setup_logging()
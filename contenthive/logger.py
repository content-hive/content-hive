import logging
from logging.handlers import RotatingFileHandler

from contenthive.config import settings

_logger = None

def setup_logging():
    """
    Setup logging for the application.
    """
    global _logger
    if _logger is not None:
        return _logger
    
    formatting = logging.Formatter(
        '%(asctime)s %(levelname)s:\t  %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    rotatingFileHandler = RotatingFileHandler(
        filename=settings.logs_dir / "contenthive.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5
    )

    app_logger = logging.getLogger("contenthive")
    app_logger.setLevel(logging.DEBUG)

    app_file_handler = rotatingFileHandler 
    app_file_handler.setLevel(logging.DEBUG)
    app_file_handler.setFormatter(formatting)
    app_logger.addHandler(app_file_handler)

    app_console_handler = logging.StreamHandler()
    app_console_handler.setLevel(logging.INFO)
    app_console_handler.setFormatter(formatting)
    app_logger.addHandler(app_console_handler)

    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.setLevel(logging.INFO)
    uvicorn_file_handler = rotatingFileHandler
    uvicorn_file_handler.setLevel(logging.DEBUG)
    uvicorn_file_handler.setFormatter(formatting)
    uvicorn_logger.addHandler(uvicorn_file_handler)

    _logger = app_logger
    return app_logger

logger = setup_logging()
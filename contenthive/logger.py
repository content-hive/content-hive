import logging
import logging.config

from contenthive.config import settings

# Shared formatter spec used in every dictConfig call.
_FORMATTER_SPEC = {
    "standard": {
        "format": "%(asctime)s %(levelname)s:\t  %(message)s",
        "datefmt": "%Y-%m-%d %H:%M:%S",
    }
}


def _build_config(log_file: str | None = None) -> dict:
    """
    Build a logging dictConfig dict.

    Args:
        log_file: Absolute path to the rotating log file. When None, only the
                  console handler is included (safe for use at import time).

    Returns:
        A dict suitable for passing to ``logging.config.dictConfig()``.
    """
    handlers: dict = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "level": "INFO",
        }
    }
    root_handlers = ["console"]
    app_handlers = ["console"]

    if log_file:
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "standard",
            "level": "DEBUG",
            "filename": log_file,
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        }
        root_handlers.append("file")
        app_handlers.append("file")

    return {
        "version": 1,
        # Preserve loggers that are not explicitly listed here
        # (e.g., third-party libraries added after startup).
        "disable_existing_loggers": False,
        "formatters": _FORMATTER_SPEC,
        "handlers": handlers,
        "loggers": {
            # Application logger: owns its own handlers, does not propagate to root.
            "contenthive": {
                "handlers": app_handlers,
                "level": "DEBUG",
                "propagate": False,
            },
            # Uvicorn loggers: clear any handlers uvicorn installed by default
            # and propagate to root so a single handler set covers everything.
            # This is equivalent to starting uvicorn with log_config=None.
            "uvicorn": {
                "handlers": [],
                "level": "INFO",
                "propagate": True,
            },
            "uvicorn.error": {
                "handlers": [],
                "level": "INFO",
                "propagate": True,
            },
            "uvicorn.access": {
                "handlers": [],
                "level": "INFO",
                "propagate": True,
            },
        },
        "root": {
            "level": "INFO",
            "handlers": root_handlers,
        },
    }


def setup_logging() -> logging.Logger:
    """
    Apply console-only logging config. Safe to call at module import time
    because it does not touch the filesystem.

    Returns:
        The ``contenthive`` application logger.
    """
    logging.config.dictConfig(_build_config())
    return logging.getLogger("contenthive")


def setup_file_logging() -> None:
    """
    Apply the full logging config (console + rotating file).
    Must be called AFTER ``ensure_directories()`` so the log directory exists.

    Additionally reconfigures uvicorn loggers to propagate to root, effectively
    replacing uvicorn's default log_config with the unified configuration.
    """
    log_file = str(settings.logs_dir / "contenthive.log")
    logging.config.dictConfig(_build_config(log_file=log_file))
    logging.getLogger("contenthive").info("File logging initialized.")


logger = setup_logging()

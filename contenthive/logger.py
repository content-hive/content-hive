import logging
import logging.config
import re
from datetime import date as _date
from datetime import timedelta
from pathlib import Path

from contenthive.config import settings

_LOG_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\w+):\s{2}(.*)$")


def _parse_path(path: Path) -> list[dict]:
    entries: list[dict] = []
    current: dict | None = None
    tb_lines: list[str] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            m = _LOG_LINE_RE.match(line)
            if m:
                if current is not None:
                    current["traceback"] = "\n".join(tb_lines) or None
                    entries.append(current)
                current = {
                    "timestamp": m.group(1),
                    "level": m.group(2),
                    "message": m.group(3),
                    "traceback": None,
                }
                tb_lines = []
            elif current is not None and line:
                tb_lines.append(line)
    if current is not None:
        current["traceback"] = "\n".join(tb_lines) or None
        entries.append(current)
    return entries


def parse_log_file(date_str: str | None = None) -> list[dict]:
    """
    Parse log file(s) and return structured entries in ascending time order.

    - date_str=None: merge the most recent 3 days of logs
    - date_str="YYYY-MM-DD": parse only that day; returns [] if file not found
    """
    today = _date.today().strftime("%Y-%m-%d")

    def _path_for(d: str) -> Path:
        return settings.logs_dir / ("contenthive.log" if d == today else f"contenthive.log.{d}")

    if date_str is not None:
        path = _path_for(date_str)
        return _parse_path(path) if path.exists() else []

    result: list[dict] = []
    today_dt = _date.today()
    for delta in range(2, -1, -1):  # 2 days ago → yesterday → today
        d = (today_dt - timedelta(days=delta)).strftime("%Y-%m-%d")
        path = _path_for(d)
        if path.exists():
            result.extend(_parse_path(path))
    return result


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
            "class": "logging.handlers.TimedRotatingFileHandler",
            "formatter": "standard",
            "level": "DEBUG",
            "filename": log_file,
            "when": "midnight",
            "interval": 1,
            "backupCount": 30,
            "encoding": "utf-8",
            "utc": False,
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
                "level": "WARNING",
                "propagate": False,
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

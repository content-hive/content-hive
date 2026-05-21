import base64
import json
import logging
import logging.config
import re
import time as _time
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path

from contenthive.config import settings

_LOG_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+(\w+):\s+(.*)$")


_CURSOR_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _encode_cursor(ts: str, idx: int) -> str:
    payload = json.dumps({"ts": ts, "idx": idx}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, int]:
    padding = 4 - len(cursor) % 4
    if padding != 4:
        cursor += "=" * padding
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor).decode())
        ts, idx = data["ts"], int(data["idx"])
        if idx < 0:
            raise ValueError("idx must be >= 0")
        datetime.strptime(ts, _CURSOR_TS_FMT)
        return ts, idx
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        raise ValueError("Invalid cursor") from e


def _parse_path_ranged(path: Path, file_date: str, from_dt: datetime, to_dt: datetime) -> list[dict]:
    """Parse a log file, returning only entries in [from_dt, to_dt)."""
    entries: list[dict] = []
    current: dict | None = None
    tb_lines: list[str] = []
    with path.open(encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.rstrip("\n")
            m = _LOG_LINE_RE.match(line)
            if m:
                if current is not None:
                    current["traceback"] = "\n".join(tb_lines) or None
                    entries.append(current)
                current = None
                tb_lines = []
                entry_dt = datetime.strptime(m.group(1), _CURSOR_TS_FMT)
                if entry_dt >= to_dt:
                    break
                if entry_dt < from_dt:
                    continue
                current = {
                    "id": f"{file_date}:{line_num}",
                    "timestamp": m.group(1),
                    "level": m.group(2),
                    "message": m.group(3),
                    "traceback": None,
                }
            elif current is not None and line:
                tb_lines.append(line)
    if current is not None:
        current["traceback"] = "\n".join(tb_lines) or None
        entries.append(current)
    return entries


def query_logs(
    from_dt: datetime,
    to_dt: datetime,
    level: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> tuple[list[dict], str | None]:
    """
    Query log entries in [from_dt, to_dt), newest first.

    Returns (items, next_cursor). next_cursor is None when no more data exists.
    Cursor semantics: skips all entries newer than cursor_ts, then skips the first
    cursor_idx entries at cursor_ts. Out-of-range cursors produce deterministic results:
    cursor_ts < from_dt returns empty; cursor_ts >= to_dt is equivalent to no cursor.
    """
    today = to_dt.date()

    def _path_for(d: _date) -> Path:
        d_str = d.strftime("%Y-%m-%d")
        return settings.logs_dir / ("contenthive.log" if d == today else f"contenthive.log.{d_str}")

    cursor_ts: str | None = None
    cursor_idx: int = 0
    if cursor is not None:
        cursor_ts, cursor_idx = _decode_cursor(cursor)

    level_filter = level.upper() if level else None
    fetched: list[dict] = []
    skipped_at_cursor_ts = 0
    d = to_dt.date()
    from_date = from_dt.date()
    while d >= from_date and len(fetched) <= limit:
        path = _path_for(d)
        if path.exists():
            day_entries = _parse_path_ranged(path, d.strftime("%Y-%m-%d"), from_dt, to_dt)
            if level_filter:
                day_entries = [e for e in day_entries if e["level"] == level_filter]
            for e in reversed(day_entries):
                if cursor_ts is not None:
                    if e["timestamp"] > cursor_ts:
                        continue
                    if e["timestamp"] == cursor_ts and skipped_at_cursor_ts < cursor_idx:
                        skipped_at_cursor_ts += 1
                        continue
                fetched.append(e)
                if len(fetched) > limit:
                    break
        d -= timedelta(days=1)

    items = fetched[:limit]

    next_cursor: str | None = None
    if len(fetched) > limit and items:
        last_ts = items[-1]["timestamp"]
        base_idx = cursor_idx if cursor_ts == last_ts else 0
        same_ts_count = sum(1 for e in items if e["timestamp"] == last_ts)
        next_cursor = _encode_cursor(last_ts, base_idx + same_ts_count)

    return items, next_cursor


class _UTCFormatter(logging.Formatter):
    converter = _time.gmtime


# Shared formatter spec used in every dictConfig call.
_FORMATTER_SPEC = {
    "standard": {
        "()": _UTCFormatter,
        "fmt": "%(asctime)s %(levelname)s:\t  %(message)s",
        "datefmt": "%Y-%m-%dT%H:%M:%SZ",
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
            "utc": True,
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

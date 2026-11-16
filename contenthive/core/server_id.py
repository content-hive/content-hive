import os
import tempfile
import threading
import uuid
from pathlib import Path

from contenthive.config import settings
from contenthive.logger import logger

_lock = threading.Lock()
_cached_server_id: str | None = None


def _server_id_path() -> Path:
    return settings.data_dir / "server.id"


def _read_server_id(path: Path) -> str | None:
    """Return a canonical UUID string, or None when the file is missing or invalid."""
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return None


def _write_server_id(server_id: str) -> None:
    path = _server_id_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".server_id_")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(f"{server_id}\n")
        tmp = Path(tmp_path)
        tmp.chmod(0o600)
        tmp.replace(path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def init_server_id() -> str:
    """Load or create the deployment server id and cache it for the process."""
    global _cached_server_id
    with _lock:
        path = _server_id_path()
        existing = _read_server_id(path) if path.exists() else None
        if existing is None:
            if path.exists():
                logger.warning("server.id is missing or invalid; generating a new server id")
            server_id = str(uuid.uuid4())
            _write_server_id(server_id)
        else:
            server_id = existing
        _cached_server_id = server_id
        return server_id


def get_server_id() -> str:
    """Return the cached server id. Raises if init_server_id() has not run."""
    with _lock:
        if _cached_server_id is None:
            raise RuntimeError("server id is not initialized")
        return _cached_server_id

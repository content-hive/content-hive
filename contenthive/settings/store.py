import tempfile
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML

from contenthive.config import settings
from contenthive.logger import logger
from contenthive.settings.schema import AppSettings

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096

_settings_lock = threading.Lock()
_cached_settings: AppSettings | None = None


def _settings_path() -> Path:
    return settings.data_dir.parent / "settings.yaml"


def _write_yaml(data: dict[str, Any]) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".settings_yaml_")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            _yaml.dump(data, f)
        Path(tmp_path).replace(path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _load_yaml() -> dict[str, Any]:
    """Load settings.yaml. Returns {} if missing or unreadable."""
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = _yaml.load(f)
    except Exception:
        logger.warning("Failed to parse settings.yaml, treating as empty config")
        return {}
    if data is None:
        return {}
    if not isinstance(data, dict):
        logger.warning(
            "settings.yaml has unexpected shape (%s), treating as empty config",
            type(data).__name__,
        )
        return {}
    return data


def load_settings() -> AppSettings:
    """Load settings from settings.yaml.

    Missing keys use schema defaults. Raises ValidationError when persisted values
    are present but invalid. Does not modify the file.
    """
    return AppSettings.model_validate(_load_yaml())


def save_settings(app_settings: AppSettings) -> None:
    """Persist application settings to settings.yaml atomically."""
    global _cached_settings
    with _settings_lock:
        _write_yaml(app_settings.model_dump(mode="json"))
        _cached_settings = app_settings


def get_settings() -> AppSettings:
    """Return cached application settings for internal hot paths.

    On first access, loads from disk. If the file is unreadable, uses schema defaults
    in memory without writing the file. If values are semantically invalid, uses
    schema defaults in memory without modifying the file.
    """
    global _cached_settings
    with _settings_lock:
        if _cached_settings is None:
            try:
                _cached_settings = load_settings()
            except ValidationError:
                logger.error("settings.yaml contains invalid values; using schema defaults in memory")
                _cached_settings = AppSettings()
        return _cached_settings


def init_settings() -> AppSettings:
    """Ensure settings.yaml exists on first start and prime the in-memory cache."""
    global _cached_settings
    path = _settings_path()
    if not path.exists():
        app_settings = AppSettings()
        save_settings(app_settings)
        return app_settings

    try:
        app_settings = load_settings()
    except ValidationError:
        logger.error("settings.yaml contains invalid values; using schema defaults in memory")
        app_settings = AppSettings()

    with _settings_lock:
        _cached_settings = app_settings
    return app_settings

import tempfile
import threading
from pathlib import Path

import yaml

from contenthive.config import settings
from contenthive.logger import logger

_config_lock = threading.Lock()


def _config_path() -> Path:
    return settings.plugins_dir / "plugins.yaml"


def load_plugins_config() -> dict[str, dict]:
    """
    Load plugins.yaml. Returns a dict keyed by domain.
    Example: {"fxtwitter": {"disabled": True}, "youtube_parser": {"disabled": False, "api_key": "..."}}
    Returns {} if the file does not exist or cannot be parsed.
    """
    path = _config_path()
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        logger.warning("Failed to parse plugins.yaml, treating as empty config")
        return {}


def save_plugins_config(config: dict[str, dict]) -> None:
    """Persist the full config dict to plugins.yaml atomically."""
    path = _config_path()
    content = yaml.dump(config, default_flow_style=False, allow_unicode=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".plugins_yaml_")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def get_plugin_config(domain: str) -> dict:
    """Get config block for a single plugin domain. Returns {} if not present."""
    return load_plugins_config().get(domain, {})


def set_plugin_field(domain: str, key: str, value) -> None:
    """Set a single field in a plugin's config block and persist."""
    with _config_lock:
        config = load_plugins_config()
        if domain not in config:
            config[domain] = {}
        config[domain][key] = value
        save_plugins_config(config)

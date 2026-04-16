import json
import tempfile
import threading
from pathlib import Path
from typing import Any

import yaml

from contenthive.config import settings
from contenthive.logger import logger
from contenthive.plugins.contracts import PluginConfigSchema

_config_lock = threading.Lock()

_FRAMEWORK_KEYS = {"disabled"}


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
        data = yaml.safe_load(path.read_text())
    except Exception:
        logger.warning("Failed to parse plugins.yaml, treating as empty config")
        return {}
    if data is None:
        return {}
    if not isinstance(data, dict):
        logger.warning(
            "plugins.yaml has unexpected shape (%s), treating as empty config",
            type(data).__name__,
        )
        return {}
    return data


def _assert_yaml_safe(value: Any) -> None:
    """Raise ValueError if value cannot round-trip through yaml.safe_dump / yaml.safe_load."""
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Config value must be a JSON-serializable primitive (str, int, float, bool, None, list, dict); "
            f"got {type(value).__name__!r}: {exc}"
        ) from exc


def save_plugins_config(config: dict[str, dict]) -> None:
    """Persist the full config dict to plugins.yaml atomically."""
    path = _config_path()
    content = yaml.safe_dump(config, default_flow_style=False, allow_unicode=True, width=4096)
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


def set_plugin_field(domain: str, key: str, value: Any) -> None:
    """Set a single field in a plugin's config block and persist."""
    _assert_yaml_safe(value)
    with _config_lock:
        config = load_plugins_config()
        if domain not in config:
            config[domain] = {}
        config[domain][key] = value
        save_plugins_config(config)


def remove_plugin_config(domain: str) -> None:
    """Remove a plugin's entire config block from plugins.yaml and persist."""
    with _config_lock:
        config = load_plugins_config()
        config.pop(domain, None)
        save_plugins_config(config)


def strip_framework_keys(cfg: dict) -> dict:
    """Remove framework-internal keys (e.g. 'disabled') from a config dict."""
    return {k: v for k, v in cfg.items() if k not in _FRAMEWORK_KEYS}


def plugin_get_config(
    domain: str,
    schema_cls: type[PluginConfigSchema] = PluginConfigSchema,
) -> PluginConfigSchema:
    """Get plugin config as a typed settings object. Excludes framework-internal keys."""
    raw = strip_framework_keys(get_plugin_config(domain))
    return schema_cls.model_validate(raw)


def plugin_save_config(domain: str, config: PluginConfigSchema) -> None:
    """Save all declared fields of a settings object to plugins.yaml atomically.

    Uses model_dump(mode="json") so Enum values are serialized to their primitive
    equivalents before writing, avoiding json.dumps failures on Enum instances.
    The entire domain block is updated under a single lock/save cycle to prevent
    partial writes if an error occurs mid-way.
    """
    new_fields = config.model_dump(mode="json")
    with _config_lock:
        full_config = load_plugins_config()
        domain_config = full_config.get(domain, {})
        domain_config.update(new_fields)
        full_config[domain] = domain_config
        save_plugins_config(full_config)

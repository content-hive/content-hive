import yaml

from contenthive.config import settings


def _config_path():
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
        from contenthive.logger import logger
        logger.warning("Failed to parse plugins.yaml, treating as empty config")
        return {}


def save_plugins_config(config: dict[str, dict]) -> None:
    """Persist the full config dict to plugins.yaml."""
    _config_path().write_text(yaml.dump(config, default_flow_style=False, allow_unicode=True))


def get_plugin_config(domain: str) -> dict:
    """Get config block for a single plugin domain. Returns {} if not present."""
    return load_plugins_config().get(domain, {})


def set_plugin_field(domain: str, key: str, value) -> None:
    """Set a single field in a plugin's config block and persist."""
    config = load_plugins_config()
    if domain not in config:
        config[domain] = {}
    config[domain][key] = value
    save_plugins_config(config)

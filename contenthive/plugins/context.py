import logging
from typing import Any, Callable, Coroutine, Optional

from contenthive.logger import logger as app_logger


class PluginContext:
    """
    Context object passed to plugins.
    Provides access to application resources and utilities.
    """
    def __init__(self, logger: logging.Logger = app_logger):
        self.logger: logging.Logger = logger

        # Plugin data storage (like hass.data)
        self.data: dict[str, Any] = {}

        # HA-style platform methods (injected by manager)
        self.async_forward_entry_setup: Optional[Callable[..., Coroutine[Any, Any, bool]]] = None
        self.async_unload_platforms: Optional[Callable[..., Coroutine[Any, Any, bool]]] = None
        self.register_service: Optional[Callable[[str, str, Callable], None]] = None

        # Config persistence (injected by manager); 'disabled' field is always excluded
        self.get_config: Optional[Callable[[str], dict]] = None
        self.save_config: Optional[Callable[[str, str, Any], None]] = None

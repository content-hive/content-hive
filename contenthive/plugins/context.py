import logging
from collections.abc import Callable, Coroutine
from typing import Any

from contenthive.logger import logger as app_logger
from contenthive.plugins.contracts import PluginConfigSchema


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
        self.async_forward_entry_setup: (
            Callable[..., Coroutine[Any, Any, bool]] | None
        ) = None
        self.async_unload_platforms: Callable[..., Coroutine[Any, Any, bool]] | None = (
            None
        )
        self.register_service: Callable[[str, str, Callable], None] | None = None

        # Config persistence (injected by manager); 'disabled' field is always excluded
        self.get_config: Callable[[str], PluginConfigSchema] | None = None
        self.save_config: Callable[[str, PluginConfigSchema], None] | None = None

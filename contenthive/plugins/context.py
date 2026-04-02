from typing import Any, Callable, Optional, Dict


class PluginContext:
    """
    Context object passed to plugins.
    Provides access to application resources and utilities.
    """
    def __init__(self, logger):
        self.logger = logger

        # Plugin data storage (like hass.data)
        self.data: Dict[str, Any] = {}

        # HA-style platform methods (injected by manager)
        self.async_forward_entry_setup: Optional[Callable] = None
        self.async_unload_platforms: Optional[Callable] = None
        self.register_service: Optional[Callable] = None
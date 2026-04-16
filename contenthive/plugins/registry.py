from enum import Enum
from typing import Optional, Dict, Any

from contenthive.plugins.contracts import PluginConfigSchema

class PluginState(str, Enum):
    """
    Plugin state enumeration (Home Assistant-style).
    
    State transitions:
        INSTALLED: Plugin discovered, manifest loaded
            ↓ (async_setup)
        LOADED: Module loaded, dependencies installed
            ↓ (async_setup_entry)
        ENABLED: Config entry active, plugin running
            ↓ (async_unload_entry)
        DISABLED: Config entry disabled, module still loaded
            ↓ (error or unload)
        FAILED: Setup or runtime error occurred
    """
    INSTALLED = "installed"  # Manifest loaded, not yet set up
    LOADED = "loaded"        # Module loaded, ready for config entry
    ENABLED = "enabled"      # Config entry active, plugin running
    DISABLED = "disabled"    # Explicitly disabled
    FAILED = "failed"        # Setup or runtime error


class PluginRecord:
    """
    Plugin record storing manifest, instance, and state.

    Attributes:
        domain: Unique plugin identifier (from manifest.json)
        manifest: Plugin metadata (name, version, dependencies, etc.)
        instance: Loaded plugin module object (not a class instance)
        state: Current plugin state (PluginState enum)
        error: Error message if state is FAILED
    """
    
    def __init__(self, manifest: Dict[str, Any], instance: Optional[Any]):
        self.domain: str = manifest['domain']
        self.manifest: Dict[str, Any] = manifest
        self.instance: Optional[Any] = instance
        self.state: PluginState = PluginState.INSTALLED
        self.error: Optional[str] = None
    
    @property
    def name(self) -> str:
        """Get plugin display name from manifest"""
        return self.manifest.get('name', self.domain)
    
    @property
    def version(self) -> str:
        """Get plugin version from manifest"""
        return self.manifest.get('version', 'unknown')

    @property
    def author(self) -> list[str] | None:
        """Get plugin author list from manifest"""
        return self.manifest.get('author')

    @property
    def description(self) -> str | None:
        """Get plugin description from manifest"""
        return self.manifest.get('description')

    @property
    def config_schema(self) -> type[PluginConfigSchema] | None:
        """Returns CONFIG_SCHEMA class from loaded module, or None if not defined."""
        if self.instance is None:
            return None
        schema = getattr(self.instance, 'CONFIG_SCHEMA', None)
        if schema is None or not (isinstance(schema, type) and issubclass(schema, PluginConfigSchema)):
            return None
        return schema

    @property
    def is_loaded(self) -> bool:
        """Check if plugin is loaded (module imported)"""
        return self.instance is not None
    
    @property
    def is_enabled(self) -> bool:
        """Check if plugin is enabled (has active config entry)"""
        return self.state == PluginState.ENABLED
    
    def __repr__(self) -> str:
        return f"<PluginRecord domain={self.domain} state={self.state.value}>"

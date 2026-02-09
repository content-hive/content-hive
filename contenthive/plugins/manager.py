import importlib.util
import sys
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from enum import Enum
import asyncio
import subprocess
from datetime import timedelta

from .registry import PluginRecord, PluginState
from .base import PluginBase, ContentParserPlugin


class PluginEntryData:
    """Plugin configuration entry data"""
    def __init__(self, entry_id: str, domain: str, data: Dict[str, Any]):
        self.entry_id = entry_id
        self.domain = domain
        self.data = data
        self.options = {}
        self.state = PluginState.INSTALLED


class EventBus:
    """Simple event bus for plugin communication"""
    def __init__(self):
        self._listeners: Dict[str, List[Callable]] = {}
    
    def listen(self, event_type: str, callback: Callable):
        """Register event listener"""
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(callback)
    
    async def fire(self, event_type: str, data: Dict[str, Any]):
        """Fire event to all listeners"""
        if event_type in self._listeners:
            for callback in self._listeners[event_type]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(data)
                    else:
                        callback(data)
                except Exception as e:
                    print(f"Error in event listener: {e}")


class PluginManager:
    """
    Plugin manager for handling plugin lifecycle and events.
    """
    
    def __init__(self, plugins_dir: Path, context):
        self.plugins_dir = plugins_dir
        self.context = context
        self.plugins: Dict[str, PluginRecord] = {}
        self.config_entries: Dict[str, PluginEntryData] = {}
        self.event_bus = EventBus()
        
        # Plugin data storage (like hass.data[DOMAIN])
        self.data: Dict[str, Any] = {}
        
        # Service registry
        self.services: Dict[str, Dict[str, Callable]] = {}
    
    async def async_discover(self):
        """
        Discover plugins asynchronously from the plugins directory.
        """
        tasks = []
        for plugin_dir in self.plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            
            manifest_path = plugin_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            
            tasks.append(self._async_load_manifest(plugin_dir, manifest_path))
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
        await self.event_bus.fire("plugins_discovered", {
            "count": len(self.plugins)
        })
    
    async def _async_load_manifest(self, plugin_dir: Path, manifest_path: Path):
        """Load plugin manifest"""
        try:
            manifest = json.loads(manifest_path.read_text())
            domain = manifest['domain']
            
            self.plugins[domain] = PluginRecord(manifest, None)
            self.context.logger.info(f"Plugins[Discovered]: {domain}")
            
            await self.event_bus.fire("plugin_discovered", {
                "domain": domain,
                "manifest": manifest
            })
        except Exception as e:
            self.context.logger.error(f"Plugins[Discovery Failed]: {plugin_dir.name} - {e}")
    
    async def async_setup(self, domain: str, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Setup plugin from configuration (similar to async_setup in HA).
        This is called when plugin is configured via YAML-like config.
        """
        record = self.plugins.get(domain)
        if not record:
            self.context.logger.error(f"Plugins[Setup Failed]: {domain} - Not found")
            return False
        
        if record.state not in [PluginState.INSTALLED, PluginState.DISABLED]:
            self.context.logger.warning(f"Plugins[Setup]: {domain} - Already in state {record.state}")
            return True
        
        try:
            # Install dependencies
            if not await self._async_install_dependencies(domain):
                record.state = PluginState.FAILED
                return False
            
            # Load module
            instance = await self._async_load_module(domain)
            if not instance:
                return False
            
            record.instance = instance
            
            # Call setup hook
            if hasattr(instance, "async_setup"):
                result = await instance.async_setup(self.context, config or {})
                if not result:
                    raise Exception("async_setup returned False")
            
            record.state = PluginState.LOADED
            self.context.logger.info(f"Plugins[Setup]: {domain} - Success")
            
            await self.event_bus.fire("plugin_setup", {"domain": domain})
            return True
            
        except Exception as e:
            record.state = PluginState.FAILED
            record.error = str(e)
            self.context.logger.error(f"Plugins[Setup Failed]: {domain} - {e}")
            return False
    
    async def async_setup_entry(self, entry: PluginEntryData) -> bool:
        """
        Setup plugin from config entry (similar to async_setup_entry in HA).
        This is called when plugin is configured via UI.
        """
        domain = entry.domain
        record = self.plugins.get(domain)
        
        if not record:
            self.context.logger.error(f"Plugins[Setup Entry Failed]: {domain} - Not found")
            return False
        
        try:
            # Ensure plugin is loaded
            if record.state == PluginState.INSTALLED:
                if not await self.async_setup(domain):
                    return False
            
            # Call setup entry hook
            if hasattr(record.instance, "async_setup_entry"):
                result = await record.instance.async_setup_entry(self.context, entry)
                if not result:
                    raise Exception("async_setup_entry returned False")
            
            # Store entry
            self.config_entries[entry.entry_id] = entry
            entry.state = PluginState.ENABLED
            record.state = PluginState.ENABLED
            
            self.context.logger.info(f"Plugins[Setup Entry]: {domain} - Success")
            await self.event_bus.fire("plugin_enabled", {"domain": domain, "entry_id": entry.entry_id})
            return True
            
        except Exception as e:
            record.state = PluginState.FAILED
            record.error = str(e)
            self.context.logger.error(f"Plugins[Setup Entry Failed]: {domain} - {e}")
            return False
    
    async def async_unload_entry(self, entry_id: str) -> bool:
        """
        Unload plugin config entry (similar to async_unload_entry in HA).
        """
        entry = self.config_entries.get(entry_id)
        if not entry:
            return False
        
        domain = entry.domain
        record = self.plugins.get(domain)
        
        if not record or not record.instance:
            return False
        
        try:
            # Call unload hook
            if hasattr(record.instance, "async_unload_entry"):
                result = await record.instance.async_unload_entry(self.context, entry)
                if not result:
                    raise Exception("async_unload_entry returned False")
            
            # Remove entry
            del self.config_entries[entry_id]
            entry.state = PluginState.DISABLED
            
            # Check if plugin has other active entries
            has_active = any(
                e.domain == domain and e.state == PluginState.ENABLED
                for e in self.config_entries.values()
            )
            
            if not has_active:
                record.state = PluginState.LOADED
            
            self.context.logger.info(f"Plugins[Unload Entry]: {domain} - Success")
            await self.event_bus.fire("plugin_disabled", {"domain": domain, "entry_id": entry_id})
            return True
            
        except Exception as e:
            self.context.logger.error(f"Plugins[Unload Entry Failed]: {domain} - {e}")
            return False
    
    async def _async_load_module(self, domain: str) -> Optional[PluginBase]:
        """Load plugin module and instantiate plugin class"""
        try:
            module_path = self.plugins_dir / domain / "__init__.py"
            
            spec = importlib.util.spec_from_file_location(f"plugin_{domain}", module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            
            plugin_cls = getattr(module, "Plugin")
            
            # Verify plugin inherits from PluginBase
            if not issubclass(plugin_cls, PluginBase):
                raise TypeError(f"Plugin class must inherit from PluginBase")
            
            instance = plugin_cls()
            return instance
            
        except Exception as e:
            self.context.logger.error(f"Plugins[Load Module Failed]: {domain} - {e}")
            return None
    
    async def _async_install_dependencies(self, domain: str) -> bool:
        """Install plugin dependencies asynchronously"""
        record = self.plugins.get(domain)
        if not record or not record.manifest:
            return True
        
        requirements = record.manifest.get("requirements", [])
        if not requirements:
            return True
        
        try:
            self.context.logger.info(f"Plugins[Dependencies]: {domain} - Installing {len(requirements)} packages")
            
            # Run pip install in executor to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._install_packages,
                requirements
            )
            
            self.context.logger.info(f"Plugins[Dependencies]: {domain} - Installed successfully")
            return True
            
        except Exception as e:
            self.context.logger.error(f"Plugins[Dependencies Failed]: {domain} - {e}")
            return False
    
    def _install_packages(self, requirements: List[str]):
        """Blocking package installation (run in executor)"""
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            *requirements,
            "--quiet",
            "--root-user-action=ignore"
        ])
    
    def register_service(self, domain: str, service: str, callback: Callable):
        """
        Register a service that can be called by other plugins or external code.
        Similar to hass.services.async_register
        """
        if domain not in self.services:
            self.services[domain] = {}
        
        self.services[domain][service] = callback
        self.context.logger.info(f"Plugins[Service Registered]: {domain}.{service}")
    
    async def call_service(self, domain: str, service: str, data: Dict[str, Any]):
        """
        Call a registered service.
        Similar to hass.services.async_call
        """
        if domain not in self.services or service not in self.services[domain]:
            raise ValueError(f"Service {domain}.{service} not found")
        
        callback = self.services[domain][service]
        
        if asyncio.iscoroutinefunction(callback):
            return await callback(data)
        else:
            return callback(data)
    
    def get_parser_plugins(self) -> List[tuple[str, ContentParserPlugin]]:
        """Get all enabled content parser plugins"""
        parsers = []
        for domain, record in self.plugins.items():
            if (record.state == PluginState.ENABLED and 
                isinstance(record.instance, ContentParserPlugin)):
                parsers.append((domain, record.instance))
        
        return parsers
    
    async def async_find_parser_for_url(
        self, 
        url: str, 
        preferred_domain: Optional[str] = None
    ) -> tuple[Optional[str], Optional[ContentParserPlugin]]:
        """
        Find parser plugin for URL asynchronously.
        """
        parsers = self.get_parser_plugins()
        
        # Try preferred parser first
        if preferred_domain:
            for domain, plugin in parsers:
                if domain == preferred_domain:
                    try:
                        if asyncio.iscoroutinefunction(plugin.can_parse):
                            can_parse = await plugin.can_parse(url)
                        else:
                            can_parse = plugin.can_parse(url)
                        
                        if can_parse:
                            return domain, plugin
                    except Exception as e:
                        self.context.logger.error(f"Error checking {domain}: {e}")
        
        # Try all parsers
        for domain, plugin in parsers:
            if preferred_domain and domain == preferred_domain:
                continue
            
            try:
                if asyncio.iscoroutinefunction(plugin.can_parse):
                    can_parse = await plugin.can_parse(url)
                else:
                    can_parse = plugin.can_parse(url)
                
                if can_parse:
                    return domain, plugin
            except Exception as e:
                self.context.logger.error(f"Error checking {domain}: {e}")
        
        return None, None
    
    async def async_reload(self, domain: str) -> bool:
        """
        Reload a plugin (unload and load again).
        """
        # Find all entries for this domain
        entries = [
            entry for entry in self.config_entries.values()
            if entry.domain == domain
        ]
        
        # Unload all entries
        for entry in entries:
            await self.async_unload_entry(entry.entry_id)
        
        # Reload module
        record = self.plugins.get(domain)
        if record:
            record.instance = None
            record.state = PluginState.INSTALLED
        
        # Setup again
        if await self.async_setup(domain):
            # Restore entries
            for entry in entries:
                await self.async_setup_entry(entry)
            return True
        
        return False


# Singleton instance
_plugin_manager: Optional[PluginManager] = None

def set_plugin_manager(manager: PluginManager):
    """Set global plugin manager instance"""
    global _plugin_manager
    _plugin_manager = manager

def get_plugin_manager() -> Optional[PluginManager]:
    """Get global plugin manager instance"""
    return _plugin_manager
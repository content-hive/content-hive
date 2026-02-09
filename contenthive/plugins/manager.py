import importlib.util
import sys
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
import asyncio
import subprocess

from .registry import PluginRecord, PluginState


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
    Home Assistant-style plugin manager.
    Plugins are loaded as modules, not classes.
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
        
        # Platform registry (domain -> platform -> entities)
        self._platforms: Dict[str, Dict[str, List[Any]]] = {}
    
    async def async_discover(self):
        """Discover plugins asynchronously from the plugins directory."""
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
            
            # Store module reference instead of instance
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
        Setup plugin from configuration (HA-style).
        Calls the plugin module's async_setup function.
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
            module = await self._async_load_module(domain)
            if not module:
                return False
            
            record.instance = module  # Store module, not class instance
            
            # Call module-level async_setup function
            if hasattr(module, "async_setup"):
                result = await module.async_setup(self.context, config or {})
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
        Setup plugin from config entry (HA-style).
        Calls the plugin module's async_setup_entry function.
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
            
            module = record.instance
            
            # Call module-level async_setup_entry function
            if hasattr(module, "async_setup_entry"):
                result = await module.async_setup_entry(self.context, entry)
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
    
    async def async_forward_entry_setup(
        self, 
        entry: PluginEntryData, 
        platform: str
    ) -> bool:
        """
        Forward setup to a platform (HA-style).
        Similar to: hass.config_entries.async_forward_entry_setup(entry, "parser")
        
        This loads the platform module (e.g., parser.py) and calls its async_setup_entry.
        """
        domain = entry.domain
        record = self.plugins.get(domain)
        
        if not record:
            return False
        
        try:
            # Load platform module (e.g., plugins/fxtwitter/parser.py)
            platform_module = await self._async_load_platform_module(domain, platform)
            
            if not platform_module:
                raise Exception(f"Platform {platform} not found")
            
            async def async_add_entities(entities: List[Any]):
                """Callback to register entities from platform."""
                if domain not in self._platforms:
                    self._platforms[domain] = {}
                if platform not in self._platforms[domain]:
                    self._platforms[domain][platform] = []
                
                self._platforms[domain][platform].extend(entities)
                self.context.logger.info(
                    f"Registered {len(entities)} {platform} entities for {domain}"
                )
            
            # Call platform's async_setup_entry
            if hasattr(platform_module, "async_setup_entry"):
                await platform_module.async_setup_entry(
                    self.context, 
                    entry, 
                    async_add_entities
                )
            
            return True
            
        except Exception as e:
            self.context.logger.error(f"Failed to setup {platform} platform for {domain}: {e}")
            import traceback
            self.context.logger.error(traceback.format_exc())
            return False
    
    async def async_unload_platforms(
        self, 
        entry: PluginEntryData, 
        platforms: List[str]
    ) -> bool:
        """
        Unload platforms for an entry (HA-style).
        Similar to: hass.config_entries.async_unload_platforms(entry, ["parser"])
        """
        domain = entry.domain
        
        for platform in platforms:
            if domain in self._platforms and platform in self._platforms[domain]:
                entities = self._platforms[domain][platform]
                
                # Call async_will_remove on each entity
                for entity in entities:
                    if hasattr(entity, "async_will_remove"):
                        try:
                            await entity.async_will_remove()
                        except Exception as e:
                            self.context.logger.error(f"Error unloading entity: {e}")
                
                # Remove platform
                del self._platforms[domain][platform]
        
        return True
    
    async def async_unload_entry(self, entry_id: str) -> bool:
        """Unload plugin config entry (HA-style)."""
        entry = self.config_entries.get(entry_id)
        if not entry:
            return False
        
        domain = entry.domain
        record = self.plugins.get(domain)
        
        if not record or not record.instance:
            return False
        
        try:
            module = record.instance
            
            # Call module-level async_unload_entry function
            if hasattr(module, "async_unload_entry"):
                result = await module.async_unload_entry(self.context, entry)
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
    
    async def _async_load_module(self, domain: str):
        """Load plugin module (not a class!)"""
        try:
            module_path = self.plugins_dir / domain / "__init__.py"
            
            spec = importlib.util.spec_from_file_location(
                f"plugin_{domain}", 
                module_path
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            
            return module
            
        except Exception as e:
            self.context.logger.error(f"Plugins[Load Module Failed]: {domain} - {e}")
            return None
    
    async def _async_load_platform_module(self, domain: str, platform: str):
        """Load platform module (e.g., parser.py)"""
        try:
            platform_path = self.plugins_dir / domain / f"{platform}.py"
            
            if not platform_path.exists():
                self.context.logger.error(f"Platform file not found: {platform_path}")
                return None
            
            module_name = f"contenthive_plugin_{domain}_{platform}"
            
            spec = importlib.util.spec_from_file_location(
                module_name,
                platform_path
            )
            
            if spec is None or spec.loader is None:
                self.context.logger.error(f"Failed to create module spec for {platform_path}")
                return None
            
            module = importlib.util.module_from_spec(spec)
            
            sys.modules[module_name] = module
            
            spec.loader.exec_module(module)
            
            self.context.logger.info(f"Loaded platform module: {module_name}")
            return module
            
        except Exception as e:
            self.context.logger.error(f"Failed to load {platform} platform for {domain}: {e}")
            import traceback
            self.context.logger.error(traceback.format_exc())
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
        """Register a service (HA-style)"""
        if domain not in self.services:
            self.services[domain] = {}
        
        self.services[domain][service] = callback
        self.context.logger.info(f"Plugins[Service Registered]: {domain}.{service}")
    
    async def call_service(self, domain: str, service: str, data: Dict[str, Any]):
        """Call a registered service (HA-style)"""
        if domain not in self.services or service not in self.services[domain]:
            raise ValueError(f"Service {domain}.{service} not found")
        
        callback = self.services[domain][service]
        
        if asyncio.iscoroutinefunction(callback):
            return await callback(data)
        else:
            return callback(data)
    
    def get_parser_entities(self) -> List[Any]:
        """Get all registered parser entities from all plugins."""
        parsers = []
        
        for domain, platforms in self._platforms.items():
            if "parser" in platforms:
                parsers.extend(platforms["parser"])
        
        return parsers
    
    async def async_find_parser_for_url(
        self, 
        url: str, 
        preferred_domain: Optional[str] = None
    ) -> tuple[Optional[str], Optional[Any]]:
        """Find parser entity for URL."""
        parsers = self.get_parser_entities()
        
        # Try preferred parser first
        if preferred_domain:
            for parser in parsers:
                if hasattr(parser, "domain") and parser.domain == preferred_domain:
                    try:
                        can_parse = parser.can_parse(url)
                        if can_parse:
                            return preferred_domain, parser
                    except Exception as e:
                        self.context.logger.error(f"Error checking {preferred_domain}: {e}")
        
        # Try all parsers
        for parser in parsers:
            domain = getattr(parser, "domain", "unknown")
            if preferred_domain and domain == preferred_domain:
                continue
            
            try:
                can_parse = parser.can_parse(url)
                if can_parse:
                    return domain, parser
            except Exception as e:
                self.context.logger.error(f"Error checking {domain}: {e}")
        
        return None, None
    
    async def async_reload(self, domain: str) -> bool:
        """Reload a plugin."""
        entries = [
            entry for entry in self.config_entries.values()
            if entry.domain == domain
        ]
        
        for entry in entries:
            await self.async_unload_entry(entry.entry_id)
        
        record = self.plugins.get(domain)
        if record:
            record.instance = None
            record.state = PluginState.INSTALLED
        
        if await self.async_setup(domain):
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
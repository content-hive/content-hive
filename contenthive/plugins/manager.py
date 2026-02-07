import importlib.util
import sys
import json
from pathlib import Path
from typing import Optional
from .registry import PluginRecord, PluginState
from .base import PluginBase, ContentParserPlugin
import subprocess
import inspect

class PluginManager:
    def __init__(self, plugins_dir: Path, context):
        self.plugins_dir = plugins_dir
        self.context = context
        self.plugins = {}

    def discover(self):
        """
        Discover and load plugins from the plugins directory.
        """
        for plugin_dir in self.plugins_dir.iterdir():
            manifest_path = plugin_dir / "manifest.json"
            if not manifest_path.exists():
                continue

            manifest = json.loads(manifest_path.read_text())
            self.plugins[manifest['id']] = PluginRecord(manifest, None)
            self.context.logger.info(f"Plugins[Discovered]: {manifest['id']}")

    def load(self, plugin_id):
        """
        Load the specified plugin with exception isolation.
        """
        record = self.plugins.get(plugin_id)
        if not record:
            self.context.logger.error(f"Plugins[Load Failed]: {plugin_id} - Plugin not found")
            return False

        if not self._install_dependencies(plugin_id):
            record.state = PluginState.FAILED
            return False

        try:
            module_path = self.plugins_dir / plugin_id / "__init__.py"

            spec = importlib.util.spec_from_file_location(f"plugin_{plugin_id}", module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)

            plugin_cls = getattr(module, "Plugin")
            
            # Verify plugin inherits from PluginBase
            if not issubclass(plugin_cls, PluginBase):
                raise TypeError(f"Plugin class must inherit from PluginBase")
            
            instance = plugin_cls()

            if hasattr(instance, "on_load"):
                instance.on_load(self.context)

            record.instance = instance
            record.state = PluginState.LOADED
            self.context.logger.info(f"Plugins[Loaded]: {plugin_id}")
            return True
            
        except Exception as e:
            record.state = PluginState.FAILED
            record.error = str(e)
            self.context.logger.error(f"Plugins[Load Failed]: {plugin_id} - {type(e).__name__}: {e}")
            return False

    def _install_dependencies(self, plugin_id):
        """Install plugin dependencies from requirements.txt"""
        requirements_file = self.plugins_dir / plugin_id / "requirements.txt"
    
        if not requirements_file.exists():
            return True
    
        try:
            self.context.logger.info(f"Plugins[Dependencies]: {plugin_id} - Installing from {requirements_file}")
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", 
                "-r", str(requirements_file), "--quiet",
                "--root-user-action=ignore"
            ])
            self.context.logger.info(f"Plugins[Dependencies]: {plugin_id} - Installed successfully")
            return True
        except subprocess.CalledProcessError as e:
            self.context.logger.error(f"Plugins[Dependencies Failed]: {plugin_id} - {e}")
            return False

    def enable(self, plugin_id):
        """
        Enable the specified plugin with exception isolation.
        """
        record = self.plugins.get(plugin_id)
        if not record or record.state != PluginState.LOADED:
            self.context.logger.warning(f"Plugins[Enable Failed]: {plugin_id} - Invalid state: {record.state if record else 'Not found'}")
            return False
            
        try:
            if hasattr(record.instance, "on_enable"):
                record.instance.on_enable()
            record.state = PluginState.ENABLED
            self.context.logger.info(f"Plugins[Enabled]: {plugin_id}")
            return True
        except Exception as e:
            record.state = PluginState.FAILED
            record.error = str(e)
            self.context.logger.error(f"Plugins[Enable Failed]: {plugin_id} - {type(e).__name__}: {e}")
            return False

    def disable(self, plugin_id):
        """
        Disable the specified plugin with exception isolation.
        """
        record = self.plugins.get(plugin_id)
        if not record or record.state != PluginState.ENABLED:
            self.context.logger.warning(f"Plugins[Disable Failed]: {plugin_id} - Invalid state: {record.state if record else 'Not found'}")
            return False
            
        try:
            if hasattr(record.instance, "on_disable"):
                record.instance.on_disable()
            record.state = PluginState.DISABLED
            self.context.logger.info(f"Plugins[Disabled]: {plugin_id}")
            return True
        except Exception as e:
            record.state = PluginState.FAILED
            record.error = str(e)
            self.context.logger.error(f"Plugins[Disable Failed]: {plugin_id} - {type(e).__name__}: {e}")
            return False

    def unload(self, plugin_id):
        """
        Unload the specified plugin with exception isolation.
        """
        record = self.plugins.get(plugin_id)
        if not record:
            self.context.logger.warning(f"Plugins[Unload Failed]: {plugin_id} - Not found")
            return False
            
        try:
            if hasattr(record.instance, "on_unload"):
                record.instance.on_unload()
            record.instance = None
            record.state = PluginState.INSTALLED
            self.context.logger.info(f"Plugins[Unloaded]: {plugin_id}")
            return True
        except Exception as e:
            record.state = PluginState.FAILED
            record.error = str(e)
            self.context.logger.error(f"Plugins[Unload Failed]: {plugin_id} - {type(e).__name__}: {e}")
            return False

    def get_parser_plugins(self):
        """
        Get all enabled content parser plugins.
        """
        parsers = []
        for plugin_id, record in self.plugins.items():
            if (record.state == PluginState.ENABLED and 
                isinstance(record.instance, ContentParserPlugin)):
                parsers.append((plugin_id, record.instance))
        
        return parsers
    
    def find_parser_for_url(self, url: str, plugin_id: Optional[str] = None):
        """
        Find the first parser plugin that can handle the given URL.
        
        Args:
            url: The URL to parse
            plugin_id: Optional parser plugin ID to use
        Returns:
            Tuple of (plugin_id, plugin_instance) or (None, None)
        """
        for plugin_id, plugin in self.get_parser_plugins():
            if plugin_id and plugin_id != plugin_id:
                continue
            try:
                if plugin.can_parse(url):
                    return plugin_id, plugin
            except Exception as e:
                self.context.logger.error(f"Error checking if {plugin_id} can parse URL: {e}")
        
        return None, None
    

"""
Plugin Manager Singleton
"""

_plugin_manager = None

def set_plugin_manager(manager: PluginManager):
    global _plugin_manager
    _plugin_manager = manager

def get_plugin_manager():
    return _plugin_manager
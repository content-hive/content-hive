from abc import ABC, abstractmethod
from typing import Optional

from contenthive.models.content import URLParserResult
from .context import PluginContext


class PluginBase(ABC):
    """
    Abstract base class for all plugins.
    All plugins must inherit from this class and implement required methods.
    """
    
    def __init__(self):
        self.context: Optional[PluginContext] = None
    
    @abstractmethod
    def on_load(self, context: PluginContext):
        """
        Called when the plugin is loaded.
        Must be implemented by all plugins.
        
        Args:
            context: PluginContext instance
        """
        pass
    
    def on_enable(self):
        """
        Called when the plugin is enabled.
        Optional hook - default implementation does nothing.
        """
        pass
    
    def on_disable(self):
        """
        Called when the plugin is disabled.
        Optional hook - default implementation does nothing.
        """
        pass
    
    def on_unload(self):
        """
        Called when the plugin is unloaded.
        Optional hook - default implementation does nothing.
        """
        pass


class ContentParserPlugin(PluginBase):
    """
    Base class for content parser plugins.
    Plugins that parse content must inherit from this class.
    """
    
    @abstractmethod
    def can_parse(self, url: str) -> bool:
        """
        Check if this plugin can parse the given URL.
        
        Args:
            url: The URL to check
            
        Returns:
            True if this plugin can parse the URL, False otherwise
        """
        pass
    
    @abstractmethod
    def parse(self, url: str) -> URLParserResult:
        """
        Parse the content from the given URL.
        
        Args:
            url: The URL being parsed
            
        Returns:
            URLParserResult containing parsed data
        """
        pass
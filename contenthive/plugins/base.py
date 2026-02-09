from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

from contenthive.models.parser import ParserResult
from .context import PluginContext


class PluginBase(ABC):
    """
    Abstract base class for all plugins (Home Assistant-style).
    
    Plugins can implement two setup patterns:
    
    1. Simple setup (YAML-style):
       - Implement async_setup(context, config)
    
    2. Config Entry setup (UI-style):
       - Implement async_setup_entry(context, entry)
       - Implement async_unload_entry(context, entry)
    
    Lifecycle:
      INSTALLED → async_setup() → LOADED → async_setup_entry() → ENABLED
                                          ← async_unload_entry() ← DISABLED
    """
    
    def __init__(self):
        self.context: Optional[PluginContext] = None
    
    async def async_setup(self, context: PluginContext, config: Dict[str, Any]) -> bool:
        """
        Setup plugin from configuration (similar to Home Assistant's async_setup).
        Called when plugin is configured via YAML-like config.
        
        Args:
            context: PluginContext instance
            config: Plugin configuration dictionary
            
        Returns:
            True if setup successful, False otherwise
            
        Example:
            async def async_setup(self, context, config):
                self.context = context
                self.api_key = config.get("api_key")
                self.api_client = APIClient(self.api_key)
                return True
        """
        self.context = context
        return True
    
    async def async_setup_entry(self, context: PluginContext, entry) -> bool:
        """
        Setup plugin from config entry (similar to Home Assistant's async_setup_entry).
        Called when plugin is configured via UI or when creating a config entry.
        
        This allows multiple instances of the same plugin with different configs.
        
        Args:
            context: PluginContext instance
            entry: PluginEntryData with entry_id, domain, and data
            
        Returns:
            True if setup successful, False otherwise
            
        Example:
            async def async_setup_entry(self, context, entry):
                # Store per-entry data
                if self.domain not in context.data:
                    context.data[self.domain] = {}
                
                context.data[self.domain][entry.entry_id] = {
                    "api": APIClient(entry.data["api_key"])
                }
                return True
        """
        return True
    
    async def async_unload_entry(self, context: PluginContext, entry) -> bool:
        """
        Unload plugin config entry (similar to Home Assistant's async_unload_entry).
        Called when a config entry is being removed or disabled.
        
        Should clean up resources associated with this entry.
        
        Args:
            context: PluginContext instance
            entry: PluginEntryData being unloaded
            
        Returns:
            True if unload successful, False otherwise
            
        Example:
            async def async_unload_entry(self, context, entry):
                # Clean up resources
                if self.domain in context.data:
                    data = context.data[self.domain].pop(entry.entry_id, None)
                    if data and "api" in data:
                        await data["api"].close()
                return True
        """
        return True


class ContentParserPlugin(PluginBase):
    """
    Base class for content parser plugins.
    Plugins that parse content must inherit from this class.
    
    Example implementation:
        class YouTubeParser(ContentParserPlugin):
            async def async_setup(self, context, config):
                self.api_key = config.get("api_key")
                return True
            
            def can_parse(self, url: str) -> bool:
                return "youtube.com" in url or "youtu.be" in url
            
            async def parse(self, url: str) -> ParserResult:
                # Parse video info
                return ParserResult(...)
    """
    
    @abstractmethod
    def can_parse(self, url: str) -> bool:
        """
        Check if this plugin can parse the given URL.
        Can be sync or async.
        
        Args:
            url: The URL to check
            
        Returns:
            True if this plugin can parse the URL, False otherwise
            
        Example:
            def can_parse(self, url: str) -> bool:
                return "youtube.com" in url
        """
        pass
    
    @abstractmethod
    async def parse(self, url: str) -> ParserResult:
        """
        Parse the content from the given URL.
        Must be async.
        
        Args:
            url: The URL being parsed
            
        Returns:
            ParserResult containing parsed data
            
        Example:
            async def parse(self, url: str) -> ParserResult:
                data = await self.api.fetch_video_info(url)
                return ParserResult(
                    title=data["title"],
                    description=data["description"],
                    ...
                )
        """
        pass
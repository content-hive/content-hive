from enum import Enum

class PluginState(str, Enum):
    INSTALLED = "installed"
    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    FAILED = "failed"

class PluginRecord:
    def __init__(self, manifest, instance):
        self.id = manifest['id']
        self.manifest = manifest
        self.instance = instance
        self.state = PluginState.INSTALLED
        self.error = None

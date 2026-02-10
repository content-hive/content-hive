"""
Home Assistant style restart mechanism
"""
import os
import sys
import signal
import asyncio
from enum import Enum
from typing import Optional
from pathlib import Path

from contenthive.logger import logger


class RestartType(Enum):
    """Restart types"""
    RESTART = "restart"  # Full restart
    SAFE_MODE = "safe_mode"  # Safe mode restart (disable all plugins)
    RELOAD = "reload"  # Reload configuration


class RestartManager:
    """
    HA-style restart manager
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.restart_flag_file = data_dir / ".restart"
        self._restart_task: Optional[asyncio.Task] = None
    
    def request_restart(self, restart_type: RestartType = RestartType.RESTART):
        """
        Request restart (HA style)
        Write flag file, then send SIGTERM signal
        """
        logger.warning(f"Restart requested: {restart_type.value}")
        
        # 1. Write restart flag file
        self._write_restart_flag(restart_type)
        
        # 2. Send SIGTERM signal to trigger graceful shutdown
        os.kill(os.getpid(), signal.SIGTERM)
    
    async def async_restart(self, delay: float = 1.0, restart_type: RestartType = RestartType.RESTART):
        """
        Async restart (give time to complete current request)
        """
        if self._restart_task and not self._restart_task.done():
            logger.warning("Restart already scheduled")
            return
        
        async def _do_restart():
            await asyncio.sleep(delay)
            self.request_restart(restart_type)
        
        self._restart_task = asyncio.create_task(_do_restart())
    
    def _write_restart_flag(self, restart_type: RestartType):
        """Write restart flag file"""
        try:
            self.restart_flag_file.write_text(restart_type.value)
            logger.info(f"Restart flag written: {restart_type.value}")
        except Exception as e:
            logger.error(f"Failed to write restart flag: {e}")
    
    def check_restart_flag(self) -> Optional[RestartType]:
        """
        Check restart flag (called at startup)
        This is how HA knows whether to enter safe mode
        """
        if not self.restart_flag_file.exists():
            return None
        
        try:
            content = self.restart_flag_file.read_text().strip()
            self.restart_flag_file.unlink()  # Delete flag file
            
            return RestartType(content)
        except Exception as e:
            logger.error(f"Failed to read restart flag: {e}")
            return None
    
    def clear_restart_flag(self):
        """Clear restart flag"""
        if self.restart_flag_file.exists():
            self.restart_flag_file.unlink()


# Global instance
_restart_manager: Optional[RestartManager] = None


def get_restart_manager() -> Optional[RestartManager]:
    """Get restart manager instance"""
    return _restart_manager


def set_restart_manager(manager: RestartManager):
    """Set restart manager instance"""
    global _restart_manager
    _restart_manager = manager
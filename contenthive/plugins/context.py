from fastapi import FastAPI
import sqlite3
from pathlib import Path
from typing import Any, Callable, Optional, Dict


class PluginContext:
    """
    Context object passed to plugins.
    Provides access to application resources and utilities.
    """
    def __init__(
            self,
            app: FastAPI,
            data_dir: Path,
            db_factory,
            logger
    ):
        """
        Initialize the PluginContext.

        Args:
            app (FastAPI): The FastAPI application instance.
            data_dir (Path): The data directory path.
            db_factory: A callable that returns a new database connection.
            logger: Logger instance for logging.
        """
        self.app = app
        self.data_dir = data_dir
        self._db_factory = db_factory
        self.logger = logger
        
        # Plugin data storage (like hass.data)
        self.data: Dict[str, Any] = {}
        
        # HA-style platform methods (injected by manager)
        self.async_forward_entry_setup: Optional[Callable] = None
        self.async_unload_platforms: Optional[Callable] = None
        self.register_service: Optional[Callable] = None


    def get_db_connection(self) -> sqlite3.Connection:
        """
        Get a new database connection.
        """
        return self._db_factory()
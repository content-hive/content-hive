

from fastapi import FastAPI
import sqlite3
from pathlib import Path


class PluginContext:
    """
    Context object passed to plugins.
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


    def get_db_connection(self) -> sqlite3.Connection:
        """
        Get a new database connection.
        """
        return self._db_factory()
import os
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application configuration settings.
    """

    # Application settings
    environment: str = os.getenv("ENVIRONMENT", "production")
    debug: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

    # Server settings
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "6123"))

    # Directory paths
    app_base: Path = Path(os.getenv("APP_BASE", "/app"))
    data_dir: Path = Path(os.getenv("DATA_DIR", "/config/data"))
    logs_dir: Path = Path(os.getenv("LOGS_DIR", "/config/logs"))
    plugins_dir: Path = Path(os.getenv("PLUGINS_DIR", "/config/plugins"))
    plugins_deps_dir: Path = Path(os.getenv("PLUGINS_DEPS_DIR", "/app/deps"))

    @computed_field
    @property
    def database_path(self) -> Path:
        return self.data_dir / "contenthive.db"

    @computed_field
    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"


# Instantiate settings
settings = Settings()


def ensure_directories():
    """
    Ensure that necessary directories exist.
    """
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.plugins_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)

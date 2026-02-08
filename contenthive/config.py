import os
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Application configuration settings.
    """
    # Application settings
    app_name: str = "Content Hive"
    app_version: str = "0.1.0"
    environment: str = os.getenv("ENVIRONMENT", "production")
    debug: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

    # Server settings
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "6123"))

    # Directory paths
    app_base: Path = Path(os.getenv("APP_BASE", "/app"))
    data_dir: Path = Path(os.getenv("DATA_DIR", "/data"))
    logs_dir: Path = Path(os.getenv("LOGS_DIR", "/logs"))
    plugins_dir: Path = Path(os.getenv("PLUGINS_DIR", "/plugins"))

    database_path: Path = data_dir / "contenthive.db"
    media_dir: Path = data_dir / "media"

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
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import computed_field, Field


class Settings(BaseSettings):
    """
    Application configuration settings.
    """
    
    # Application settings
    app_name: str = "Content Hive"
    app_version: str = os.getenv("APP_VERSION", "1.0.0")
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

    plugins_repo_url: str = os.getenv("PLUGINS_REPO_URL", "https://github.com/content-hive/plugins.git")
    plugins_repo_ref_type: str = os.getenv("PLUGINS_REPO_REF_TYPE", "branch")  # branch, tag, commit
    plugins_repo_ref: str = os.getenv("PLUGINS_REPO_REF", "main")

    # Token settings
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    refresh_token_expire_days: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

    # HTTP download settings
    download_max_retries: int = Field(default=3, ge=0)
    download_timeout_seconds: float = Field(default=60.0, gt=0)
    download_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 "
        "Safari/537.36 Edg/143.0.0.0"
    )

    # Image transformation settings
    media_transform_max_workers: int = Field(default=4, ge=1)
    # Max number of requests allowed to wait for a free worker slot.
    # Requests beyond this cap are rejected immediately with 503.
    media_transform_queue_size: int = Field(default=10, ge=0)
    # Seconds a waiting request may spend blocked on an active worker slot before 503.
    media_transform_queue_timeout: float = Field(default=30.0, gt=0)


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
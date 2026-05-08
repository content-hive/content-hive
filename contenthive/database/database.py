"""Database configuration and initialization"""

import sys
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from alembic import command
from contenthive.config import settings
from contenthive.logger import logger

# SQLAlchemy engine and session factory
_engine = None
_SessionLocal = None


def get_engine():
    """Get SQLAlchemy engine"""
    global _engine
    if _engine is None:
        _engine = create_engine(
            f"sqlite:///{settings.database_path}",
            connect_args={"check_same_thread": False},
            echo=False,
        )
    return _engine


def get_session_local():
    """Get SessionLocal factory"""
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(bind=engine)
    return _SessionLocal


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_migrations() -> None:
    """Run Alembic migrations to bring database schema up to date."""
    alembic_cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    command.upgrade(alembic_cfg, "head")


def initialize_db():
    """Initialize database and run all pending Alembic migrations."""
    _run_migrations()

    from contenthive.services.user import user_service

    try:
        result = user_service.create_admin_user()
        if result:
            _write_admin_credentials(result[0], result[1])
    except ValueError:
        logger.debug("Initial admin user already exists")


def _write_admin_credentials(username: str, password: str) -> None:
    """
    Securely write admin credentials to a file with restricted permissions.
    Only called on first-time admin user creation.
    """
    credentials_file = settings.data_dir / ".admin_credentials"

    try:
        # Write credentials to file
        credentials_file.write_text(
            f"Admin Credentials (First-time setup)\n"
            f"=====================================\n"
            f"Username: {username}\n"
            f"Password: {password}\n\n"
            f"IMPORTANT: Change this password immediately after first login.\n"
            f"This file should be deleted after you've recorded the credentials.\n"
        )

        # Set restrictive permissions (owner read/write only)
        credentials_file.chmod(0o600)

        logger.info("Admin credentials saved to: %s", credentials_file)
        logger.warning("Please retrieve admin credentials and delete the credentials file")

    except Exception as e:
        logger.exception("Could not write admin credentials file: %s", e)
        # Print directly to stderr (bypasses rotating log files) so the
        # password is not silently lost if the data directory is unavailable.
        print(
            "\n"
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
            "  ADMIN CREDENTIALS (credentials file could not be written)\n"
            "  Username : " + username + "\n"
            "  Password : " + password + "\n"
            "  Change this password immediately after first login.\n"
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n",
            file=sys.stderr,
            flush=True,
        )

"""Database configuration and initialization"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from alembic.config import Config
from alembic import command

from contenthive.config import settings
from contenthive.database.orm_models import Base
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
            echo=False
        )
    return _engine


def get_session_local():
    """Get SessionLocal factory"""
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(bind=engine)
    return _SessionLocal


def _run_migrations() -> None:
    """Run Alembic migrations to bring database schema up to date."""
    logger.info("Running Alembic migrations...")
    alembic_cfg = Config(settings.app_base / "alembic.ini")
    alembic_cfg.set_main_option("script_location", str(settings.app_base / "alembic"))
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic migrations completed")


def initialize_db():
    """Initialize database and run all pending Alembic migrations."""
    logger.info("Database initialization started")
    _run_migrations()

    # Create admin user if not exists
    from contenthive.services.user import user_service
    try:
        logger.info("Checking initial admin user")
        result = user_service.create_admin_user()
        if result:
            _write_admin_credentials(result[0], result[1])
    except ValueError:
        logger.info("Initial admin user already exists")

    logger.info("Database initialization finished")


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
        
        logger.info("Admin user created successfully")
        logger.info("Credentials saved to: %s", credentials_file)
        logger.info("Credentials file permissions set to -rw-------")
        logger.warning("Please retrieve admin credentials and delete the credentials file")
        
    except Exception as e:
        # If file write fails, we have no choice but to print to stderr
        # This is a fallback and should be rare
        logger.exception("Could not write admin credentials file: %s", e)
        logger.error("Admin credentials fallback - Username: %s", username)
        logger.error("Please change the password immediately after first login")

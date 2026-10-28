"""Database configuration and initialization"""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from alembic import command
from contenthive.config import settings

# SQLAlchemy engine and session factory
_engine = None
_SessionLocal = None


def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """Enable SQLite foreign keys on each new DBAPI connection.

    SQLite disables FK enforcement per connection unless this PRAGMA is set.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine():
    """Get SQLAlchemy engine"""
    global _engine
    if _engine is None:
        _engine = create_engine(
            f"sqlite:///{settings.database_path}",
            connect_args={"check_same_thread": False},
            echo=False,
        )
        event.listen(_engine, "connect", enable_sqlite_foreign_keys)
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

"""Database configuration and initialization"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from contenthive.config import settings
from contenthive.database.orm_models import Base

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


def initialize_db():
    """Initialize database and create all tables"""
    engine = get_engine()
    
    # Create all tables based on ORM models
    Base.metadata.create_all(engine)

    # Create admin user if not exists
    from contenthive.services.user import user_service
    try:
        result = user_service.create_admin_user()
        if result:
            _write_admin_credentials(result[0], result[1])
    except ValueError:
        pass  # Admin user already exists


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
        
        # Print location only, not the password itself
        print(f"\n{'='*60}")
        print(f"Admin user created successfully!")
        print(f"Credentials saved to: {credentials_file}")
        print(f"File permissions: -rw------- (owner read/write only)")
        print(f"Please retrieve the password from this file and delete it.")
        print(f"{'='*60}\n")
        
    except Exception as e:
        # If file write fails, we have no choice but to print to stderr
        # This is a fallback and should be rare
        import sys
        print(f"WARNING: Could not write credentials file: {e}", file=sys.stderr)
        print(f"Admin credentials - Username: {username}, Password: {password}", file=sys.stderr)
        print(f"Please change the password immediately after first login.", file=sys.stderr)

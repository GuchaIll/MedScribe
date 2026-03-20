"""
Database session management and connection pooling.
Provides FastAPI dependencies for database access.
"""

from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from app.config.settings import get_settings

_db_cfg = get_settings().database

# Create SQLAlchemy engine with connection pooling
engine = create_engine(
    _db_cfg.url,
    echo=_db_cfg.echo,  # Log SQL queries in development
    poolclass=QueuePool,
    pool_size=_db_cfg.pool_size,
    max_overflow=_db_cfg.max_overflow,
    pool_pre_ping=True,  # Verify connections before using
    pool_recycle=3600,  # Recycle connections after 1 hour
    connect_args={"connect_timeout": 3},  # Fail fast (3s) instead of OS default (~30s)
)

# Create SessionLocal class for creating database sessions
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,  # Don't expire objects after commit
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session.

    Usage:
        @app.get("/items")
        def read_items(db: Session = Depends(get_db)):
            items = db.query(Item).all()
            return items

    Yields:
        Database session

    The session is automatically closed when the request completes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_context():
    """
    Context manager for database sessions outside of FastAPI.

    Usage:
        with get_db_context() as db:
            user = db.query(User).filter_by(username="john").first()

    Returns:
        Context manager that yields a database session
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """
    Initialize the database by creating all tables.
    This should only be used in development/testing.
    In production, use Alembic migrations instead.
    """
    from app.database.base import Base

    # Import all models to ensure they're registered with Base
    from app.database import models  # noqa: F401

    # Create all tables
    Base.metadata.create_all(bind=engine)
    print("[SUCCESS] Database tables created successfully")


def drop_db():
    """
    Drop all database tables.
    WARNING: This will delete all data! Only use in development/testing.
    """
    from app.database.base import Base

    # Import all models
    from app.database import models  # noqa: F401

    # Drop all tables
    Base.metadata.drop_all(bind=engine)
    print("[WARNING] Database tables dropped")


def check_db_connection() -> bool:
    """
    Check if database connection is working.

    Returns:
        True if connection successful, False otherwise
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"[ERROR] Database connection failed: {e}")
        return False


# Database utilities for common operations
class DatabaseManager:
    """Helper class for database operations."""

    @staticmethod
    def create_session() -> Session:
        """Create a new database session."""
        return SessionLocal()

    @staticmethod
    def close_session(db: Session):
        """Close a database session."""
        if db:
            db.close()

    @staticmethod
    def commit(db: Session):
        """Commit current transaction."""
        db.commit()

    @staticmethod
    def rollback(db: Session):
        """Rollback current transaction."""
        db.rollback()

    @staticmethod
    def refresh(db: Session, instance):
        """Refresh an instance from the database."""
        db.refresh(instance)


# Export for convenience
__all__ = [
    "engine",
    "SessionLocal",
    "get_db",
    "get_db_context",
    "init_db",
    "drop_db",
    "check_db_connection",
    "DatabaseManager",
]

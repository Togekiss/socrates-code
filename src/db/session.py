import os
from contextlib import contextmanager
from typing import Optional
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from .models import Base
from utils import exceptions as exc


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Configures high-concurrency WAL mode and foreign key enforcement for SQLite."""
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


_central_engine = None
_engine_cache = {}


def get_engine(backup_id: Optional[str] = None, backup_path: Optional[str] = None) -> Engine:
    """
    Returns a database engine.
    - If DATABASE_URL is set (e.g. Postgres in Cloud SQL): uses the central database.
    - Otherwise: uses the SQLite database for the specific backup.
    """
    global _central_engine
    database_url = os.environ.get("DATABASE_URL")

    if database_url:
        if _central_engine is None:
            _central_engine = create_engine(database_url, pool_pre_ping=True)
        return _central_engine

    # SQLite per-backup mode
    if not backup_path:
        if not backup_id:
            raise exc.DatabaseConnectionError("Either backup_id or backup_path must be provided for SQLite database.")
        from utils.tricks import get_backup_path
        try:
            backup_path = get_backup_path(backup_id)
        except Exception as e:
            raise exc.DatabaseConnectionError(f"Failed to resolve path for backup_id '{backup_id}': {e}") from e

    sqlite_path = os.path.join(backup_path, "backup.sqlite")
    
    if sqlite_path not in _engine_cache:
        normalized_path = os.path.abspath(sqlite_path).replace("\\", "/")
        _engine_cache[sqlite_path] = create_engine(
            f"sqlite:///{normalized_path}",
            connect_args={"check_same_thread": False}
        )

    return _engine_cache[sqlite_path]


def get_db_session(backup_id: Optional[str] = None, backup_path: Optional[str] = None) -> Session:
    """Creates a new SQLAlchemy session for the specified backup."""
    engine = get_engine(backup_id=backup_id, backup_path=backup_path)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return session_factory()


def init_db(engine_or_backup_id=None, backup_path: Optional[str] = None) -> Engine:
    """Initializes tables for the target engine or backup."""
    if hasattr(engine_or_backup_id, "connect"):
        engine = engine_or_backup_id
    else:
        engine = get_engine(backup_id=engine_or_backup_id, backup_path=backup_path)
    Base.metadata.create_all(bind=engine)
    return engine


@contextmanager
def db_session(backup_id: Optional[str] = None, backup_path: Optional[str] = None):
    """
    Context manager providing a transactional database session.
    Commits automatically on success, rolls back on exception, and always closes.
    """
    session = get_db_session(backup_id=backup_id, backup_path=backup_path)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_sqlite_path(backup_path: str) -> str:
    """Returns the path to backup.sqlite in the specified backup folder."""
    if not backup_path:
        return ""
    return os.path.join(backup_path, "backup.sqlite")


def has_sqlite_db(backup_path: str) -> bool:
    """Returns True if backup.sqlite exists in the backup folder."""
    if not backup_path:
        return False
    return os.path.exists(get_sqlite_path(backup_path))


def require_sqlite_db(backup_path: str) -> None:
    """Raises DatabaseConnectionError if backup.sqlite does not exist in backup_path."""
    if not has_sqlite_db(backup_path):
        raise exc.DatabaseConnectionError(
            f"SQLite database 'backup.sqlite' not found in '{backup_path}'. Please run migration or initialize the backup first."
        )


def close_all_engines() -> None:
    """Disposes and clears all cached SQLAlchemy database engines to release file locks."""
    global _central_engine, _engine_cache
    if _central_engine:
        _central_engine.dispose()
        _central_engine = None
    for eng in list(_engine_cache.values()):
        eng.dispose()
    _engine_cache.clear()



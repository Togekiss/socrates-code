import atexit
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import Pool
from .models import Base, SchemaVersionModel, CURRENT_SCHEMA_VERSION
from utils import exceptions as exc


def _checkpoint_dbapi_wal(dbapi_connection, mode: str = "TRUNCATE") -> None:
    """Flushes committed SQLite WAL frames back into the main .sqlite file cleanly."""
    if dbapi_connection is None or not dbapi_connection.__class__.__module__.startswith("sqlite3"):
        return
    if getattr(dbapi_connection, "in_transaction", False):
        return
    try:
        cursor = dbapi_connection.cursor()
        try:
            row = cursor.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
            if mode == "TRUNCATE" and row and row[0] != 0:
                cursor.execute("PRAGMA wal_checkpoint(PASSIVE)")
        finally:
            cursor.close()
    except Exception:
        pass


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Configures high-concurrency WAL mode, RAM cache, and foreign key enforcement for SQLite."""
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()
        if connection_record is not None:
            connection_record.info["last_total_changes"] = getattr(dbapi_connection, "total_changes", 0)
            connection_record.info["needs_wal_checkpoint"] = False
            connection_record.info["ddl_written"] = False


@event.listens_for(Engine, "before_cursor_execute")
def _track_sqlite_ddl(conn, cursor, statement, parameters, context, executemany):
    """Marks DDL statements so schema creation/drops also trigger WAL checkpoints on commit."""
    if conn.dialect.name == "sqlite" and conn.connection is not None:
        stmt_upper = statement.lstrip().upper()
        if stmt_upper.startswith(("CREATE", "DROP", "ALTER", "VACUUM")):
            conn.connection.info["ddl_written"] = True


@event.listens_for(Engine, "commit")
def _mark_wal_checkpoint_on_commit(conn):
    """Marks pooled SQLite connections for WAL checkpointing whenever a transaction committed writes."""
    if conn.dialect.name == "sqlite" and conn.connection is not None:
        rec_info = conn.connection.info
        cur_changes = getattr(conn.connection.dbapi_connection, "total_changes", 0)
        if cur_changes > rec_info.get("last_total_changes", 0) or rec_info.pop("ddl_written", False):
            rec_info["last_total_changes"] = cur_changes
            rec_info["needs_wal_checkpoint"] = True


@event.listens_for(Engine, "rollback")
def _clear_wal_checkpoint_on_rollback(conn):
    """Resets write tracking on rolled-back SQLite transactions."""
    if conn.dialect.name == "sqlite" and conn.connection is not None:
        rec_info = conn.connection.info
        rec_info["ddl_written"] = False
        rec_info["last_total_changes"] = getattr(conn.connection.dbapi_connection, "total_changes", 0)


@event.listens_for(Pool, "checkin")
def _checkpoint_sqlite_on_checkin(dbapi_connection, connection_record):
    """Checkpoints SQLite WAL back to the main DB file when a write-dirty connection is returned."""
    if dbapi_connection is None or not dbapi_connection.__class__.__module__.startswith("sqlite3"):
        return
    if connection_record is not None and connection_record.info.pop("needs_wal_checkpoint", False):
        _checkpoint_dbapi_wal(dbapi_connection, mode="TRUNCATE")
        connection_record.info["last_total_changes"] = getattr(dbapi_connection, "total_changes", 0)


_central_engine = None
_engine_cache = {}
_initialized_engines = {}  # id(engine) -> bool (True if check_version=True passed)


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
            connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
            _central_engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
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


def get_db_schema_version(engine: Engine) -> int:
    """Returns the current schema version recorded in the database, or 0 if unversioned/legacy."""
    from sqlalchemy import inspect
    inspector = inspect(engine)
    if "schema_version" not in inspector.get_table_names():
        _initialized_engines.pop(id(engine), None)
        return 0
    with Session(engine) as session:
        latest = session.query(SchemaVersionModel).order_by(SchemaVersionModel.version.desc()).first()
        ver = latest.version if latest else 0
        if ver < CURRENT_SCHEMA_VERSION:
            _initialized_engines.pop(id(engine), None)
        return ver


def stamp_schema_version(
    engine_or_session,
    version: int = CURRENT_SCHEMA_VERSION,
    description: str = "Schema creation or upgrade",
) -> None:
    """Stamps the schema_version table with the specified version in one unified place."""
    record = SchemaVersionModel(
        version=version,
        applied_at=datetime.now(timezone.utc),
        description=description,
    )
    if isinstance(engine_or_session, Session):
        engine_or_session.add(record)
        engine_or_session.flush()
        try:
            bind = engine_or_session.get_bind()
            if bind is not None:
                _initialized_engines.pop(id(bind), None)
        except Exception:
            _initialized_engines.clear()
    else:
        with Session(engine_or_session) as session:
            session.add(record)
            session.commit()
        _initialized_engines.pop(id(engine_or_session), None)


def init_db(
    engine_or_backup_id=None,
    backup_path: Optional[str] = None,
    backup_id: Optional[str] = None,
    check_version: bool = True
) -> Engine:
    """Initializes tables for the target engine or backup and verifies schema version."""
    target_id = engine_or_backup_id if engine_or_backup_id is not None else backup_id
    if hasattr(target_id, "connect"):
        engine = target_id
    else:
        engine = get_engine(backup_id=target_id, backup_path=backup_path)

    is_managed_engine = (engine is _central_engine) or (engine in _engine_cache.values())
    eng_key = id(engine)
    if is_managed_engine and eng_key in _initialized_engines:
        if not check_version or _initialized_engines[eng_key]:
            return engine

    from sqlalchemy import inspect
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    if not existing_tables:
        # Brand-new database: create all tables and stamp current schema version
        Base.metadata.create_all(bind=engine)
        stamp_schema_version(engine, CURRENT_SCHEMA_VERSION, description="Initial schema creation")
        if is_managed_engine:
            _initialized_engines[eng_key] = True
        return engine

    # Database has existing tables: check schema version
    version = get_db_schema_version(engine)
    if version < CURRENT_SCHEMA_VERSION:
        if check_version:
            raise exc.DatabaseSchemaMismatchError(
                f"Database schema version {version} is older than required version {CURRENT_SCHEMA_VERSION}. "
                f"Please run 'python src/db/upgrade.py --backup-id <backup_id>' to upgrade the database schema."
            )
        # Never mutate an outdated database with create_all() during read-only inspection
        if is_managed_engine:
            _initialized_engines[eng_key] = False
        return engine

    # Ensure any new tables from latest Base.metadata are created
    Base.metadata.create_all(bind=engine)
    if is_managed_engine:
        _initialized_engines[eng_key] = True
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


def has_db(backup_path: Optional[str] = None, backup_id: Optional[str] = None) -> bool:
    """
    Returns True if a database is configured/available for the specified backup.
    - When DATABASE_URL is set, returns True (central/external database via SQLAlchemy).
    - Otherwise, checks whether the local SQLite database file exists for the backup.
    """
    if os.environ.get("DATABASE_URL"):
        return True
    if not backup_path and backup_id:
        from utils.tricks import get_backup_path
        try:
            backup_path = get_backup_path(backup_id)
        except Exception:
            return False
    if not backup_path:
        return False
    return os.path.exists(get_sqlite_path(backup_path))


def require_db(backup_path: Optional[str] = None, backup_id: Optional[str] = None) -> None:
    """Raises DatabaseConnectionError if no database is available for the specified backup."""
    if not has_db(backup_path=backup_path, backup_id=backup_id):
        raise exc.DatabaseConnectionError(
            f"Database not found in '{backup_path}'. Please run migration or initialize the backup first."
        )


def has_sqlite_db(backup_path: str) -> bool:
    """Returns True if the database is available (compatibility alias for has_db)."""
    return has_db(backup_path=backup_path)


def require_sqlite_db(backup_path: str) -> None:
    """Raises DatabaseConnectionError if the database is not available (compatibility alias for require_db)."""
    require_db(backup_path=backup_path)


def checkpoint_wal(
    engine_or_backup_id=None,
    backup_path: Optional[str] = None,
    mode: str = "TRUNCATE",
) -> None:
    """Explicitly checkpoints SQLite WAL frames into the main .sqlite database file."""
    try:
        if hasattr(engine_or_backup_id, "connect"):
            engine = engine_or_backup_id
        else:
            engine = get_engine(backup_id=engine_or_backup_id, backup_path=backup_path)
        if engine.dialect.name != "sqlite":
            return
        with engine.connect() as conn:
            conn.execute(text(f"PRAGMA wal_checkpoint({mode})"))
    except Exception:
        pass


def close_all_engines() -> None:
    """Checkpoints active WALs, disposes cached SQLAlchemy engines, and closes log handlers."""
    global _central_engine, _engine_cache
    if _central_engine:
        checkpoint_wal(_central_engine)
        _central_engine.dispose()
        _central_engine = None
    for eng in list(_engine_cache.values()):
        checkpoint_wal(eng)
        eng.dispose()
    _engine_cache.clear()
    _initialized_engines.clear()
    try:
        from utils.tricks import close_log_handlers
        close_log_handlers()
    except Exception:
        pass


atexit.register(close_all_engines)



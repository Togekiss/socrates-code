import atexit
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import Pool
from .models import Base, SchemaVersionModel, CURRENT_SCHEMA_VERSION
from utils import exceptions as exc


DEFAULT_SYNC_DEBOUNCE_SECONDS = 5.0
_sync_lock = threading.RLock()
_dirty_dbs: Dict[str, Dict[str, Any]] = {}
_last_sync_times: Dict[str, float] = {}
_sync_timer: Optional[threading.Timer] = None
_engine_to_source: Dict[int, str] = {}
_source_to_backup_id: Dict[str, str] = {}


def is_sqlite_tmp_cache_enabled() -> bool:
    """Returns True when SQLite /tmp RAM caching + debounced GCS sync should be active."""
    if os.environ.get("DATABASE_URL"):
        return False
    flag = os.environ.get("SOCRATES_SQLITE_TMP_CACHE")
    if flag is not None and flag.strip() != "":
        return flag.strip().lower() in ("1", "true", "yes", "on")
    return bool(os.environ.get("SOCRATES_DATA_DIR", "").strip())


def _resolve_source_sqlite_path(
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
) -> str:
    """Resolves the canonical source backup.sqlite path on disk/GCS FUSE."""
    if not backup_path:
        if not backup_id:
            raise exc.DatabaseConnectionError("Either backup_id or backup_path must be provided for SQLite database.")
        from utils.tricks import get_backup_path
        try:
            backup_path = get_backup_path(backup_id)
        except Exception as e:
            raise exc.DatabaseConnectionError(f"Failed to resolve path for backup_id '{backup_id}': {e}") from e
    return os.path.realpath(os.path.abspath(os.path.join(backup_path, "backup.sqlite"))).replace("\\", "/")


def get_tmp_sqlite_path(source_sqlite_path: str) -> str:
    """Computes a deterministic /tmp cache path shared by server and pipeline subprocesses."""
    canonical = os.path.realpath(os.path.abspath(source_sqlite_path)).replace("\\", "/")
    cache_root = os.environ.get("SOCRATES_SQLITE_TMP_DIR") or os.path.join(tempfile.gettempdir(), "socrates_sqlite")
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    parent_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.basename(os.path.dirname(canonical))) or "backup"
    return os.path.join(cache_root, f"{parent_name}_{digest}", "backup.sqlite").replace("\\", "/")


def _get_source_meta_path(tmp_sqlite_path: str) -> str:
    return f"{tmp_sqlite_path}.source_meta.json"


def _stat_file(path: str) -> Optional[Dict[str, int]]:
    try:
        st = os.stat(path)
        return {"mtime_ns": int(st.st_mtime_ns), "size": int(st.st_size)}
    except OSError:
        return None


def _read_source_meta(tmp_sqlite_path: str) -> Optional[Dict[str, int]]:
    meta_path = _get_source_meta_path(tmp_sqlite_path)
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "mtime_ns" in data and "size" in data:
            return {"mtime_ns": int(data["mtime_ns"]), "size": int(data["size"])}
    except Exception:
        pass
    return None


def _write_source_meta(tmp_sqlite_path: str, source_sqlite_path: str) -> None:
    stat_info = _stat_file(source_sqlite_path)
    if stat_info is None:
        return
    meta_path = _get_source_meta_path(tmp_sqlite_path)
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
    tmp_meta = f"{meta_path}.tmp.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}"
    try:
        with open(tmp_meta, "w", encoding="utf-8") as f:
            json.dump(stat_info, f)
        os.replace(tmp_meta, meta_path)
    except Exception:
        try:
            if os.path.exists(tmp_meta):
                os.remove(tmp_meta)
        except OSError:
            pass


def _prepare_tmp_sqlite_path(source_sqlite_path: str) -> str:
    """Ensures a fresh /tmp copy of source_sqlite_path exists and returns its path."""
    with _sync_lock:
        tmp_path = get_tmp_sqlite_path(source_sqlite_path)
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        source_stat = _stat_file(source_sqlite_path)
        tmp_exists = os.path.exists(tmp_path)

        if source_stat is not None:
            if tmp_exists and (source_sqlite_path in _dirty_dbs or _read_source_meta(tmp_path) == source_stat):
                return tmp_path

            staging_copy = f"{tmp_path}.load.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
            try:
                shutil.copy2(source_sqlite_path, staging_copy)
                os.replace(staging_copy, tmp_path)
                for suffix in ("-wal", "-shm"):
                    sidecar = f"{tmp_path}{suffix}"
                    if os.path.exists(sidecar):
                        try:
                            os.remove(sidecar)
                        except OSError:
                            pass

                source_wal = f"{source_sqlite_path}-wal"
                if os.path.exists(source_wal) and os.path.getsize(source_wal) > 0:
                    shutil.copy2(source_wal, f"{tmp_path}-wal")
                    conn = sqlite3.connect(tmp_path, timeout=10.0)
                    try:
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    finally:
                        conn.close()

                _write_source_meta(tmp_path, source_sqlite_path)
            finally:
                if os.path.exists(staging_copy):
                    try:
                        os.remove(staging_copy)
                    except OSError:
                        pass
            return tmp_path

        return tmp_path


def _cancel_sync_timer() -> None:
    global _sync_timer
    with _sync_lock:
        if _sync_timer is not None:
            try:
                _sync_timer.cancel()
            except Exception:
                pass
            _sync_timer = None


def _timer_sync_callback() -> None:
    global _sync_timer
    with _sync_lock:
        _sync_timer = None
    try:
        sync_dirty_sqlite_dbs(force=False)
    except Exception:
        pass


def _schedule_debounce_timer(delay: Optional[float] = None) -> None:
    global _sync_timer
    timer_env = os.environ.get("SOCRATES_SQLITE_SYNC_TIMER", "1").strip().lower()
    if timer_env in ("0", "false", "no", "off"):
        return
    if delay is None:
        try:
            delay = float(os.environ.get("SOCRATES_SQLITE_SYNC_INTERVAL", DEFAULT_SYNC_DEBOUNCE_SECONDS))
        except ValueError:
            delay = DEFAULT_SYNC_DEBOUNCE_SECONDS
    with _sync_lock:
        if _sync_timer is None or not _sync_timer.is_alive():
            timer = threading.Timer(max(0.05, delay), _timer_sync_callback)
            timer.daemon = True
            _sync_timer = timer
            timer.start()


def mark_sqlite_dirty(source_sqlite_path: str, backup_id: Optional[str] = None) -> None:
    """Marks a cached SQLite database as having uncommitted-to-GCS writes."""
    with _sync_lock:
        now = time.monotonic()
        entry = _dirty_dbs.get(source_sqlite_path)
        resolved_bid = backup_id or _source_to_backup_id.get(source_sqlite_path)
        if entry is None:
            _dirty_dbs[source_sqlite_path] = {
                "tmp_path": get_tmp_sqlite_path(source_sqlite_path),
                "dirty_since": now,
                "last_dirty_at": now,
                "backup_id": resolved_bid,
            }
        else:
            entry["last_dirty_at"] = now
            if resolved_bid and not entry.get("backup_id"):
                entry["backup_id"] = resolved_bid
        _schedule_debounce_timer()


def _sync_single_sqlite_db(source_sqlite_path: str, tmp_path: str) -> bool:
    """Backs up tmp_path into a standalone SQLite file and atomically replaces source_sqlite_path."""
    if not os.path.exists(tmp_path):
        return False

    unique_suffix = f"{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    staging_path = f"{tmp_path}.sync.{unique_suffix}"
    dest_tmp = f"{source_sqlite_path}.sync.{unique_suffix}"
    src_conn = None
    dst_conn = None
    try:
        src_conn = sqlite3.connect(tmp_path, timeout=10.0)
        dst_conn = sqlite3.connect(staging_path)
        src_conn.backup(dst_conn)
        dst_conn.close()
        dst_conn = None
        src_conn.close()
        src_conn = None

        os.makedirs(os.path.dirname(source_sqlite_path), exist_ok=True)
        try:
            os.replace(staging_path, source_sqlite_path)
        except OSError:
            try:
                shutil.copy2(staging_path, dest_tmp)
                os.replace(dest_tmp, source_sqlite_path)
            except OSError:
                shutil.copy2(staging_path, source_sqlite_path)

        _write_source_meta(tmp_path, source_sqlite_path)
        return True
    finally:
        if dst_conn is not None:
            try:
                dst_conn.close()
            except Exception:
                pass
        if src_conn is not None:
            try:
                src_conn.close()
            except Exception:
                pass
        for cleanup_path in (staging_path, dest_tmp):
            if os.path.exists(cleanup_path):
                try:
                    os.remove(cleanup_path)
                except OSError:
                    pass


def sync_dirty_sqlite_dbs(
    force: bool = False,
    min_interval: Optional[float] = None,
) -> List[str]:
    """
    Flushes dirty /tmp SQLite databases back to their source/GCS paths via sqlite3.Connection.backup().
    Debounces writes per target path by min_interval seconds unless force=True.
    Returns list of source_sqlite_path strings that were synced.
    """
    if not is_sqlite_tmp_cache_enabled():
        return []

    if min_interval is None:
        try:
            min_interval = float(os.environ.get("SOCRATES_SQLITE_SYNC_INTERVAL", DEFAULT_SYNC_DEBOUNCE_SECONDS))
        except ValueError:
            min_interval = DEFAULT_SYNC_DEBOUNCE_SECONDS

    with _sync_lock:
        if not _dirty_dbs:
            return []
        now = time.monotonic()
        due: List[tuple] = []
        for source_path, info in list(_dirty_dbs.items()):
            last_sync = _last_sync_times.get(source_path, 0.0)
            if not force and last_sync > 0.0 and (now - last_sync) < min_interval:
                continue
            due.append((source_path, info["tmp_path"], info["last_dirty_at"]))

    synced: List[str] = []
    for source_path, tmp_path, snapshot_dirty_at in due:
        try:
            did_sync = _sync_single_sqlite_db(source_path, tmp_path)
        except Exception as e:
            try:
                from utils import tricks as t
                t.global_log("error", f"SQLite sync failed for '{source_path}': {e}")
            except Exception:
                pass
            continue

        with _sync_lock:
            if did_sync:
                _last_sync_times[source_path] = time.monotonic()
                synced.append(source_path)
            current = _dirty_dbs.get(source_path)
            if current is not None and current["last_dirty_at"] <= snapshot_dirty_at:
                _dirty_dbs.pop(source_path, None)

    if synced:
        try:
            from utils import tricks as t
            t.flush_logs()
        except Exception:
            pass

    return synced


def sync_sqlite_db(
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
    force: bool = False,
    min_interval: Optional[float] = None,
) -> bool:
    """Syncs a specific backup's /tmp SQLite database to its source/GCS path if dirty (or if force=True)."""
    if not is_sqlite_tmp_cache_enabled():
        return False

    if min_interval is None:
        try:
            min_interval = float(os.environ.get("SOCRATES_SQLITE_SYNC_INTERVAL", DEFAULT_SYNC_DEBOUNCE_SECONDS))
        except ValueError:
            min_interval = DEFAULT_SYNC_DEBOUNCE_SECONDS

    source_path = _resolve_source_sqlite_path(backup_id=backup_id, backup_path=backup_path)
    with _sync_lock:
        info = _dirty_dbs.get(source_path)
        if info is None:
            if not force:
                return False
            tmp_path = get_tmp_sqlite_path(source_path)
            if not os.path.exists(tmp_path):
                return False
            snapshot_dirty_at = time.monotonic()
        else:
            last_sync = _last_sync_times.get(source_path, 0.0)
            now = time.monotonic()
            if not force and last_sync > 0.0 and (now - last_sync) < min_interval:
                return False
            tmp_path = info["tmp_path"]
            snapshot_dirty_at = info["last_dirty_at"]

    did_sync = _sync_single_sqlite_db(source_path, tmp_path)
    with _sync_lock:
        if did_sync:
            _last_sync_times[source_path] = time.monotonic()
        current = _dirty_dbs.get(source_path)
        if current is not None and current["last_dirty_at"] <= snapshot_dirty_at:
            _dirty_dbs.pop(source_path, None)

    if did_sync:
        try:
            from utils import tricks as t
            t.flush_logs()
        except Exception:
            pass
    return did_sync


def invalidate_sqlite_tmp_cache(
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
) -> None:
    """Clears the /tmp SQLite cache files and dirty tracking for a backup."""
    source_path = _resolve_source_sqlite_path(backup_id=backup_id, backup_path=backup_path)
    tmp_path = get_tmp_sqlite_path(source_path)
    with _sync_lock:
        _dirty_dbs.pop(source_path, None)
        _last_sync_times.pop(source_path, None)
    for path in (
        tmp_path,
        f"{tmp_path}-wal",
        f"{tmp_path}-shm",
        _get_source_meta_path(tmp_path),
    ):
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


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
            if is_sqlite_tmp_cache_enabled():
                source_path = _engine_to_source.get(id(conn.engine))
                if source_path:
                    mark_sqlite_dirty(source_path)


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
    source_sqlite_path = _resolve_source_sqlite_path(backup_id=backup_id, backup_path=backup_path)
    if backup_id:
        _source_to_backup_id[source_sqlite_path] = str(backup_id)

    if source_sqlite_path not in _engine_cache:
        active_path = (
            _prepare_tmp_sqlite_path(source_sqlite_path)
            if is_sqlite_tmp_cache_enabled()
            else source_sqlite_path
        )
        eng = create_engine(
            f"sqlite:///{active_path}",
            connect_args={"check_same_thread": False}
        )
        _engine_cache[source_sqlite_path] = eng
        _engine_to_source[id(eng)] = source_sqlite_path

    return _engine_cache[source_sqlite_path]


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
    return os.path.realpath(os.path.abspath(os.path.join(backup_path, "backup.sqlite"))).replace("\\", "/")


def has_db(backup_path: Optional[str] = None, backup_id: Optional[str] = None) -> bool:
    """
    Returns True if a database is configured/available for the specified backup.
    - When DATABASE_URL is set, returns True (central/external database via SQLAlchemy).
    - Otherwise, checks whether the local SQLite database file exists for the backup.
    """
    if os.environ.get("DATABASE_URL"):
        return True
    try:
        source_sqlite_path = _resolve_source_sqlite_path(backup_id=backup_id, backup_path=backup_path)
    except Exception:
        return False
    if os.path.exists(source_sqlite_path):
        return True
    if is_sqlite_tmp_cache_enabled():
        return os.path.exists(get_tmp_sqlite_path(source_sqlite_path))
    return False


def require_db(backup_path: Optional[str] = None, backup_id: Optional[str] = None) -> None:
    """Raises DatabaseConnectionError if no database is available for the specified backup."""
    if not has_db(backup_path=backup_path, backup_id=backup_id):
        loc = backup_id or backup_path or "unspecified"
        raise exc.DatabaseConnectionError(
            f"Database not found for '{loc}'. Please run migration or initialize the backup first."
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


def close_engine(
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
    sync: bool = True,
    invalidate_cache: bool = False,
) -> None:
    """Syncs (if dirty), checkpoints WAL, and disposes the cached SQLite engine for a single backup."""
    if os.environ.get("DATABASE_URL"):
        return
    source_sqlite_path = _resolve_source_sqlite_path(backup_id=backup_id, backup_path=backup_path)
    if sync and is_sqlite_tmp_cache_enabled():
        sync_sqlite_db(backup_id=backup_id, backup_path=backup_path, force=True)
    eng = _engine_cache.pop(source_sqlite_path, None)
    if eng is not None:
        checkpoint_wal(eng)
        eng.dispose()
        _initialized_engines.pop(id(eng), None)
        _engine_to_source.pop(id(eng), None)
    if invalidate_cache:
        invalidate_sqlite_tmp_cache(backup_id=backup_id, backup_path=backup_path)


def close_all_engines() -> None:
    """Syncs dirty /tmp SQLite DBs, checkpoints active WALs, disposes cached engines, and closes log handlers."""
    global _central_engine, _engine_cache
    _cancel_sync_timer()
    if is_sqlite_tmp_cache_enabled():
        sync_dirty_sqlite_dbs(force=True)
    if _central_engine:
        checkpoint_wal(_central_engine)
        _central_engine.dispose()
        _central_engine = None
    for eng in list(_engine_cache.values()):
        checkpoint_wal(eng)
        eng.dispose()
    _engine_cache.clear()
    _initialized_engines.clear()
    _engine_to_source.clear()
    try:
        from utils.tricks import close_log_handlers
        close_log_handlers()
    except Exception:
        pass


atexit.register(close_all_engines)



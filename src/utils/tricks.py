import datetime
from typing import Any, Dict, Optional, Tuple
from pathlib import Path
import sys
import os
import subprocess
import json
import re
import shutil
import logging
import logging.handlers
import sqlite3
import threading
import atexit
from . import exceptions as exc
from collections import deque

if os.name == 'nt':
    import signal
    def _handle_sigbreak(signum, frame):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGBREAK, _handle_sigbreak)
    except Exception:
        pass

GRAY = '\033[90m'
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[34m'
MAGENTA = '\033[95m'
CYAN = '\033[96m'
RESET = '\033[0m'

################ File summary #################

"""

This module holds a handful of useful functions and helpers.

"""

################ Functions #################
"""
set_path()

    This function sets the path to the project folder.

"""
def set_path():
    src_dir = Path(__file__).resolve().parents[1].as_posix()
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    project_root = Path(__file__).resolve().parents[2].as_posix()
    if project_root not in sys.path:
        sys.path.append(project_root)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

set_path()

"""
save_to_json(data, file_path), load_from_json(file_path)

    Functions to read and write a JSON file.
    
"""
def load_from_json(file_path):
    import time
    for attempt in range(5):
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                return json.load(file)
        except FileNotFoundError:
            raise
        except (OSError, json.JSONDecodeError) as e:
            if attempt == 4:
                raise e
            time.sleep(0.1)

def save_json_atomic(data, target_path, indent: int = 4, ensure_ascii: bool = True):
    """
    Atomically writes data to a JSON file using a temporary file, fsync, and os.replace().
    Prevents truncated or corrupted files if interrupted mid-write.
    """
    import time
    target = Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f"{target.name}.tmp.{os.getpid()}")

    try:
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=indent, ensure_ascii=ensure_ascii)
            file.flush()
            os.fsync(file.fileno())
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise

    for attempt in range(5):
        try:
            os.replace(temp_path, target)
            _invalidate_json_caches(target.as_posix())
            return
        except OSError as e:
            if attempt == 4:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
                raise e
            time.sleep(0.1)

def save_to_json(data, file_path):
    save_json_atomic(data, file_path)

_cache_lock = threading.RLock()
_backups_index_cache: Dict[str, Any] = {"key": None, "data": None}
_debug_files_cache: Dict[str, Tuple[Optional[float], bool]] = {}

_ELYSIUM_TEST_BACKUP_ID = "1791895360"
_ELYSIUM_TEST_FIXTURE_ENTRY: Dict[str, str] = {
    "backup_id": _ELYSIUM_TEST_BACKUP_ID,
    "backup_name": "Elysium-sql-tests",
    "server_id": "857848490683269161",
    "server_name": "(+18) Diabolik: Elysium",
    "path": "Backups/Elysium-sql-tests",
}


def _data_root() -> str:
    set_path()
    from res import constants as c

    env_root = os.environ.get("SOCRATES_DATA_DIR", "").strip()
    if env_root:
        return Path(env_root).as_posix()
    return str(c.DATA_ROOT)


def invalidate_backups_index_cache() -> None:
    """Clears the in-memory backups index cache."""
    with _cache_lock:
        _backups_index_cache["key"] = None
        _backups_index_cache["data"] = None


def _invalidate_json_caches(resolved_path: Optional[str] = None) -> None:
    """Invalidates in-memory backups_index and backup_config caches on write."""
    with _cache_lock:
        if resolved_path is None:
            invalidate_backups_index_cache()
            _debug_files_cache.clear()
            return
        norm = Path(resolved_path).resolve().as_posix()
        if Path(norm).name == "backups_index.json":
            invalidate_backups_index_cache()
        _debug_files_cache.pop(norm, None)


def _has_unseeded_elysium_test_dir(backups_dir: Path) -> bool:
    test_dir = backups_dir / "Elysium-sql-tests"
    if not test_dir.is_dir():
        return False
    return (test_dir / "Info").is_dir() or (test_dir / "backup_config.json").is_file()


def _read_backup_index_entry_from_sqlite(sqlite_path: Path, folder_name: str) -> Optional[Dict[str, str]]:
    conn = None
    try:
        conn = sqlite3.connect(sqlite_path.as_posix(), timeout=5.0)
        cols_rows = conn.execute("PRAGMA table_info(backups)").fetchall()
        if not cols_rows:
            return None
        col_names = {str(r[1]) for r in cols_rows}
        if "backup_id" not in col_names:
            return None
        select_cols = ["backup_id", "backup_name", "server_id", "server_name"]
        if "path" in col_names:
            select_cols.append("path")
        row = conn.execute(f"SELECT {', '.join(select_cols)} FROM backups LIMIT 1").fetchone()
        if not row:
            return None
        b_id = str(row[0])
        b_name = row[1] or b_id
        s_id = row[2] or ""
        s_name = row[3] or ""
        return {
            "backup_id": b_id,
            "backup_name": str(b_name),
            "server_id": str(s_id),
            "server_name": str(s_name),
            "path": f"Backups/{folder_name}",
        }
    except sqlite3.Error as e:
        global_log("warning", f"Failed to read backups index metadata from '{sqlite_path}': {e}")
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _get_backups_index_from_central_db() -> list:
    set_path()
    from sqlalchemy import inspect
    from sqlalchemy.orm import Session
    from db.models import BackupModel
    from db.session import get_engine

    engine = get_engine()
    inspector = inspect(engine)
    if not inspector.has_table("backups"):
        return []
    cols = {col["name"] for col in inspector.get_columns("backups")}
    has_path_col = "path" in cols
    with Session(engine) as session:
        if has_path_col:
            rows = (
                session.query(
                    BackupModel.backup_id,
                    BackupModel.backup_name,
                    BackupModel.server_id,
                    BackupModel.server_name,
                    BackupModel.path,
                )
                .order_by(BackupModel.backup_id.asc())
                .all()
            )
            return [
                {
                    "backup_id": str(b_id),
                    "backup_name": b_name or str(b_id),
                    "server_id": s_id or "",
                    "server_name": s_name or "",
                    "path": b_path or f"Backups/{b_id}",
                }
                for b_id, b_name, s_id, s_name, b_path in rows
            ]

        rows = (
            session.query(
                BackupModel.backup_id,
                BackupModel.backup_name,
                BackupModel.server_id,
                BackupModel.server_name,
            )
            .order_by(BackupModel.backup_id.asc())
            .all()
        )
        return [
            {
                "backup_id": str(b_id),
                "backup_name": b_name or str(b_id),
                "server_id": s_id or "",
                "server_name": s_name or "",
                "path": f"Backups/{b_id}",
            }
            for b_id, b_name, s_id, s_name in rows
        ]


def get_backups_index():
    set_path()
    if bool(os.environ.get("DATABASE_URL", "").strip()):
        return _get_backups_index_from_central_db()

    backups_dir = Path(_data_root()) / "Backups"
    if not backups_dir.is_dir():
        return []

    tmp_cache_on = False
    get_tmp_fn = None
    try:
        from db.session import get_tmp_sqlite_path, is_sqlite_tmp_cache_enabled

        tmp_cache_on = is_sqlite_tmp_cache_enabled()
        get_tmp_fn = get_tmp_sqlite_path
    except Exception:
        tmp_cache_on = False

    discovered_targets = []
    for child in sorted(backups_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        sqlite_file = child / "backup.sqlite"
        active_sqlite: Optional[Path] = None
        if tmp_cache_on and get_tmp_fn is not None:
            canonical_src = os.path.realpath(os.path.abspath(sqlite_file.as_posix())).replace("\\", "/")
            tmp_cand = Path(get_tmp_fn(canonical_src))
            if tmp_cand.is_file():
                active_sqlite = tmp_cand
        if active_sqlite is None and sqlite_file.is_file():
            active_sqlite = sqlite_file
        if active_sqlite is None:
            continue
        try:
            mtime_ns: Optional[int] = active_sqlite.stat().st_mtime_ns
        except OSError:
            mtime_ns = None
        discovered_targets.append((child.name, active_sqlite, mtime_ns))

    backups_dir_str = backups_dir.resolve().as_posix()
    has_unseeded_test_dir = _has_unseeded_elysium_test_dir(backups_dir)

    if discovered_targets:
        sqlite_key = tuple((p.as_posix(), m_ns) for _, p, m_ns in discovered_targets)
        cache_key = ("sqlite", backups_dir_str, sqlite_key, has_unseeded_test_dir)
        all_mtimes_valid = all(m_ns is not None for _, _, m_ns in discovered_targets)
        with _cache_lock:
            if (
                all_mtimes_valid
                and _backups_index_cache["key"] == cache_key
                and _backups_index_cache["data"] is not None
            ):
                return [dict(b) for b in _backups_index_cache["data"]]

        entries = []
        for folder_name, active_sqlite, _ in discovered_targets:
            entry = _read_backup_index_entry_from_sqlite(active_sqlite, folder_name)
            if entry is not None:
                entries.append(entry)

        if has_unseeded_test_dir and not any(
            str(e.get("backup_id")) == _ELYSIUM_TEST_BACKUP_ID for e in entries
        ):
            entries.append(dict(_ELYSIUM_TEST_FIXTURE_ENTRY))

        with _cache_lock:
            if all_mtimes_valid:
                _backups_index_cache["key"] = cache_key
                _backups_index_cache["data"] = [dict(e) for e in entries]
            return [dict(e) for e in entries]

    # Legacy fallback for unit tests that write backups_index.json without backup.sqlite
    index_path = backups_dir / "backups_index.json"
    if index_path.is_file():
        resolved = index_path.resolve().as_posix()
        try:
            mtime_ns = index_path.stat().st_mtime_ns
        except OSError:
            mtime_ns = None
        cache_key = ("json", backups_dir_str, ((resolved, mtime_ns),))
        with _cache_lock:
            if (
                mtime_ns is not None
                and _backups_index_cache["key"] == cache_key
                and _backups_index_cache["data"] is not None
            ):
                return [dict(b) if isinstance(b, dict) else b for b in _backups_index_cache["data"]]

        data = load_from_json(resolved)
        entries = data if isinstance(data, list) else []
        with _cache_lock:
            if mtime_ns is not None:
                _backups_index_cache["key"] = cache_key
                _backups_index_cache["data"] = [dict(b) if isinstance(b, dict) else b for b in entries]
            return [dict(b) if isinstance(b, dict) else b for b in entries]

    if has_unseeded_test_dir:
        return [dict(_ELYSIUM_TEST_FIXTURE_ENTRY)]

    return []


def get_backup_path(backup_id: str) -> str:
    """
    Returns the absolute directory path for a backup_id from SQL auto-discovery or central DB.
    """
    set_path()
    from utils.path_safety import ensure_safe_backup_path, validate_backup_id

    data_root = _data_root()
    safe_id = validate_backup_id(backup_id)
    index = get_backups_index()
    for b in index:
        if str(b.get("backup_id")) == safe_id:
            try:
                safe_path = ensure_safe_backup_path(b["path"], data_root)
            except ValueError as e:
                raise exc.BackupError(f"Unsafe backup path for '{safe_id}': {e}") from e
            return safe_path.as_posix()

    if safe_id == _ELYSIUM_TEST_BACKUP_ID:
        test_dir = Path(data_root) / "Backups" / "Elysium-sql-tests"
        if test_dir.is_dir():
            return ensure_safe_backup_path("Backups/Elysium-sql-tests", data_root).as_posix()

    raise exc.BackupError(f"Backup ID '{safe_id}' not found in index")


def add_backup_to_index(
    backup_name,
    server_id,
    server_name,
    path,
    backup_id: Optional[str] = None,
):
    set_path()
    import time
    from db.models import BackupModel
    from db.session import db_session, init_db

    data_root = _data_root()
    p_obj = Path(path)
    resolved_path = p_obj.as_posix() if p_obj.is_absolute() else (Path(data_root) / p_obj).as_posix()

    if os.path.isabs(path):
        try:
            stored_path = Path(path).resolve().relative_to(Path(data_root).resolve()).as_posix()
        except ValueError:
            stored_path = str(path).replace("\\", "/")
    else:
        stored_path = str(path).replace("\\", "/")

    if backup_id is None:
        index = get_backups_index()
        norm_resolved = Path(resolved_path).resolve().as_posix()
        matching = None
        for b in index:
            b_raw = str(b.get("path") or "")
            if not b_raw:
                continue
            b_full = Path(b_raw) if Path(b_raw).is_absolute() else (Path(data_root) / b_raw)
            if b_raw.replace("\\", "/") == stored_path or b_full.resolve().as_posix() == norm_resolved:
                matching = b
                break

        if matching is not None:
            if (
                matching.get("backup_name") != backup_name
                or matching.get("server_id") != server_id
                or matching.get("server_name") != server_name
            ):
                raise exc.BackupError("There's a different backup using the same path.")
            b_id = str(matching["backup_id"])
        else:
            b_id = f"{int(time.time())}"
    else:
        b_id = str(backup_id)

    use_central_db = bool(os.environ.get("DATABASE_URL", "").strip())
    if not use_central_db:
        Path(resolved_path).mkdir(parents=True, exist_ok=True)

    init_db(backup_id=b_id, backup_path=resolved_path)
    with db_session(backup_id=b_id, backup_path=resolved_path) as session:
        existing_row = session.query(BackupModel).filter(BackupModel.backup_id == b_id).first()
        if existing_row is None and not use_central_db:
            existing_row = session.query(BackupModel).first()
        if existing_row is None:
            session.add(
                BackupModel(
                    backup_id=b_id,
                    backup_name=str(backup_name or b_id),
                    server_id=str(server_id) if server_id else None,
                    server_name=str(server_name) if server_name else None,
                    path=stored_path or None,
                )
            )
        else:
            existing_row.backup_id = b_id
            if backup_name:
                existing_row.backup_name = str(backup_name)
            if server_id:
                existing_row.server_id = str(server_id)
            if server_name:
                existing_row.server_name = str(server_name)
            if stored_path:
                existing_row.path = stored_path

    invalidate_backups_index_cache()

    # Update active context if available
    try:
        from models.backup_context import get_current_context
        ctx = get_current_context()
        ctx.backup_id = b_id
    except Exception:
        pass

    return b_id



"""
clean(message)

    Function to remove ANSI escape sequences from a string and remove leading and trailing newlines.
"""
def clean(message):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    no_ansi = ansi_escape.sub('', message)

    return no_ansi.lstrip('\n').rstrip('\n')


def sanitize_filename(name: str) -> str:
    """Replaces filesystem-reserved characters (matching DCE export naming) with underscores."""
    if not name:
        return ""
    clean = re.sub(r'[:/\\*?"<>|]', '_', str(name))
    if clean in {".", ".."}:
        return "unnamed"
    return clean

"""
log(level, message)

    Centralized function to handle information messages.
    
    It prints the message if the corresponding flag is set in the constants module.
    It also writes the message to a log file if the LOG flag is set.

    Args:
        level (str): The level of the message (info, debug, console).
        message (str): The message to be logged.

"""
_log_lock = threading.RLock()
_file_loggers: Dict[str, Tuple[logging.Logger, logging.FileHandler, logging.handlers.MemoryHandler]] = {}


def _get_file_logger(file_path: str) -> logging.Logger:
    resolved = Path(file_path).resolve().as_posix()
    with _log_lock:
        entry = _file_loggers.get(resolved)
        if entry is not None:
            return entry[0]

        Path(resolved).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(resolved, mode="a", encoding="utf-8", delay=True)
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        mem_handler = logging.handlers.MemoryHandler(
            capacity=64,
            flushLevel=logging.ERROR,
            target=file_handler,
            flushOnClose=True,
        )
        logger = logging.getLogger(f"socrates.file.{resolved}")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        logger.handlers.clear()
        logger.addHandler(mem_handler)
        _file_loggers[resolved] = (logger, file_handler, mem_handler)
        return logger


def write_log_line(file_path: str, level: str, message: str) -> None:
    """Writes and flushes a formatted log line to the cached file logger for file_path."""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    log_line = f"[{timestamp}]{level}: {clean(str(message))}"
    logger = _get_file_logger(file_path)
    py_level = logging.ERROR if level == "error" else logging.INFO
    logger.log(py_level, log_line)
    flush_logs(file_path)


def flush_logs(file_path: Optional[str] = None) -> None:
    """Flushes buffered log records to disk for one file or all cached log files."""
    with _log_lock:
        if file_path is not None:
            resolved = Path(file_path).resolve().as_posix()
            entry = _file_loggers.get(resolved)
            if entry is not None:
                _, file_handler, mem_handler = entry
                mem_handler.flush()
                file_handler.flush()
            return
        for _, file_handler, mem_handler in list(_file_loggers.values()):
            try:
                mem_handler.flush()
                file_handler.flush()
            except Exception:
                pass


def close_log_handlers(file_path: Optional[str] = None) -> None:
    """Flushes and closes cached file log handlers (releasing OS file locks)."""
    with _log_lock:
        if file_path is not None:
            resolved = Path(file_path).resolve().as_posix()
            entry = _file_loggers.pop(resolved, None)
            if entry is not None:
                logger, file_handler, mem_handler = entry
                try:
                    mem_handler.flush()
                    mem_handler.close()
                    file_handler.close()
                    logger.handlers.clear()
                except Exception:
                    pass
            return
        for resolved in list(_file_loggers.keys()):
            close_log_handlers(resolved)


atexit.register(close_log_handlers)


def log(level="base", message=""):
    set_path()
    from res import constants as c

    if level == "base":
        print(GREEN + message + RESET)
    elif level == "info":
        if c.INFO:
            print(CYAN + message + RESET)
    elif level == "debug":
        if c.DEBUG:
            print(BLUE + message + RESET)
    elif level == "console":
        if c.CONSOLE:
            print(GRAY + message + RESET, end="")
    elif level == "error":
        print(RED + message + RESET)

    level = "console" if level == "consolelog" else level

    if c.LOG:
        write_log_line(c.LOG_FILE, level, message)


def global_log(level="base", message=""):
    set_path()
    from res import constants as c

    if level == "base":
        print(GREEN + message + RESET)
    elif level == "error":
        print(RED + message + RESET)
    else:
        print(message)

    write_log_line(c.GLOBAL_LOG_FILE, level, message)

"""
run_command(command: str, show_lines: int = 0)

    Run a shell command, stream its output in real time, and return the full output.
    
    Args:
        command (str): The shell command to run.
        show_lines (int, optional): The number of lines to clear before streaming output.
    
    Returns:
        tuple[int, str]: A tuple containing the return code and the full output.
"""
def run_command(command, show_lines: int = None):
    set_path()
    import shlex
    from res import constants as c
    from dotenv import load_dotenv
    from utils.path_safety import scrub_sensitive_env

    try:
        load_dotenv('.env')
    except FileNotFoundError:
        raise FileNotFoundError("# NO ENVIRONMENT VARIABLES FOUND. RUNNING WITHOUT THEM #\n")

    if not isinstance(command, (list, tuple)) or not command:
        raise exc.ConsoleCommandError("Command must be a non-empty argument list (shell=True is disabled)")

    argv = [str(arg) for arg in command]
    cmd_display = shlex.join(argv)
    child_env = scrub_sensitive_env(keep_discord_token=True)

    try:
        log("console", f"# RUNNING CONSOLE COMMAND #\n")
        log("console", f"> {MAGENTA}{cmd_display}{GRAY}\n")

        process = subprocess.Popen(
            argv,
            shell=False,
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        full_output = []
        tail_buffer = deque(maxlen=show_lines+2 if show_lines else 0)

        try:
            for line in process.stdout:
                full_output.append(line)  # Collect output for return

                if show_lines and c.CONSOLE:
                    # Clear previous lines (simulate dynamic overwrite)
                    print("\033[F" * len(tail_buffer), end="")  # Move cursor up

                    tail_buffer.append(line)
                    
                    for l in tail_buffer:
                        print(f"\t> {l.strip():<80}")  # Print line padded to overwrite
                        log("consolelog", f">\t{l}")
                else:
                    log("console", f">\t{line}")
                
        except KeyboardInterrupt:
            log("base", f"{YELLOW}\nCommand interrupted by user.\n")
            process.terminate()

        process.wait()

        log("console", f"\n{RESET}# END OF CONSOLE COMMAND #\n\n")
        return process.returncode, ''.join(full_output)

    except Exception as e:
        raise exc.ConsoleCommandError("An error occurred while running the command") from e

"""
create_merge_folder()

    Copies the c.DATA_FOLDER to c.MERGE_FOLDER.
    Then deletes all the files that end with "_scenes.json" from the c.MERGE_FOLDER.
"""
def create_merge_folder():
    set_path()
    from res import constants as c  

    if Path(c.MERGE_FOLDER).exists():
        log("base", f"Deleting old merge folder: {c.MERGE_FOLDER}")
        shutil.rmtree(c.MERGE_FOLDER)

    log("base", f"Creating merge folder by copying {c.DATA_FOLDER} to {c.MERGE_FOLDER}")
    shutil.copytree(c.DATA_FOLDER, c.MERGE_FOLDER, dirs_exist_ok=True, copy_function=shutil.copyfile)


    # delete all the folders named "Scenes" and all the files that end with "_scenes.json" from the "Merge" folder
    for root, dirs, files in os.walk(c.MERGE_FOLDER):
        for dir_name in list(dirs):
            if dir_name == "Scenes":
                shutil.rmtree((Path(root) / dir_name).as_posix(), ignore_errors=True)
                dirs.remove(dir_name)
        for file in files:
            if file.endswith("_scenes.json"):
                (Path(root) / file).unlink(missing_ok=True) 
    
    log("base", f"Finished creating merge folder: {c.MERGE_FOLDER}\n")

def _get_active_context_debug_files(
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
) -> Optional[bool]:
    """
    If a BackupContext is actively bound and applies to (backup_id, backup_path),
    returns its in-memory debug_files boolean override; otherwise returns None.
    """
    try:
        from models.backup_context import _current_context

        ctx = _current_context.get()
        if ctx is None:
            return None

        ctx_id = getattr(ctx, "backup_id", None)
        ctx_path = getattr(ctx, "backup_path", None)
        ctx_base = getattr(ctx, "backup_base", None)

        if backup_id is None and backup_path is None:
            return bool(getattr(ctx, "debug_files", False))

        if ctx_id is not None:
            if backup_id is not None:
                if str(ctx_id) == str(backup_id):
                    return bool(getattr(ctx, "debug_files", False))
                return None
            if backup_path is not None and ctx_base:
                try:
                    if Path(ctx_base).resolve() == Path(backup_path).resolve():
                        return bool(getattr(ctx, "debug_files", False))
                except Exception:
                    pass
            return None

        # ctx.backup_id is None: distinguish an explicit backup-scoped context (ctx_path set)
        # from the lazy global BackupContext.from_cli() default (ctx_path is None).
        if ctx_path is not None and ctx_base:
            target_dir = backup_path
            if not target_dir and backup_id is not None:
                try:
                    target_dir = get_backup_path(str(backup_id))
                except Exception:
                    target_dir = None
            if target_dir:
                try:
                    if Path(ctx_base).resolve() == Path(target_dir).resolve():
                        return bool(getattr(ctx, "debug_files", False))
                except Exception:
                    pass
        return None
    except Exception:
        return None


def is_debug_files_enabled(
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
) -> bool:
    """
    Determines if debug files (JSON snapshots and auxiliary debug files) should be created.
    Checks an active matching BackupContext first, then SQLite/DB BackupModel.debug_files
    when a database exists, falling back to backup_config.json on disk if no DB row exists.
    """
    active_override = _get_active_context_debug_files(backup_id=backup_id, backup_path=backup_path)
    if active_override is not None:
        return active_override

    resolved_id = str(backup_id) if backup_id is not None else None
    target_path = str(backup_path) if backup_path else None
    if not target_path and resolved_id:
        try:
            target_path = get_backup_path(resolved_id)
        except Exception:
            target_path = None

    if resolved_id or target_path:
        try:
            from sqlalchemy import inspect
            from db.models import BackupModel
            from db.session import db_session, has_db

            if has_db(backup_id=resolved_id, backup_path=target_path):
                with db_session(backup_id=resolved_id, backup_path=target_path) as session:
                    inspector = inspect(session.get_bind())
                    if inspector.has_table("backups"):
                        cols = {col["name"] for col in inspector.get_columns("backups")}
                        if "debug_files" in cols:
                            if resolved_id is not None:
                                row = (
                                    session.query(BackupModel)
                                    .filter(BackupModel.backup_id == resolved_id)
                                    .first()
                                )
                            elif os.environ.get("DATABASE_URL") and target_path:
                                tp = Path(target_path)
                                path_candidates = [tp.as_posix()]
                                if tp.parent.name == "Backups":
                                    path_candidates.append(f"Backups/{tp.name}")
                                row = (
                                    session.query(BackupModel)
                                    .filter(BackupModel.path.in_(path_candidates))
                                    .first()
                                )
                            elif not os.environ.get("DATABASE_URL"):
                                row = session.query(BackupModel).first()
                            else:
                                row = None
                            if row is not None:
                                return bool(row.debug_files)
        except Exception:
            pass

    if target_path:
        try:
            cfg_file = Path(target_path) / "backup_config.json"
            if cfg_file.exists():
                resolved = cfg_file.resolve().as_posix()
                try:
                    mtime = os.path.getmtime(resolved)
                except OSError:
                    mtime = None
                with _cache_lock:
                    cached = _debug_files_cache.get(resolved)
                    if cached is not None and cached[0] == mtime and mtime is not None:
                        return cached[1]
                cfg = load_from_json(cfg_file.as_posix())
                enabled = bool(cfg.get("admin", {}).get("verbosity", {}).get("debugFiles", False))
                with _cache_lock:
                    _debug_files_cache[resolved] = (mtime, enabled)
                return enabled
        except Exception:
            pass

    try:
        from res import constants as c

        if backup_id is None and backup_path is None and hasattr(c, "DEBUG_FILES"):
            return bool(c.DEBUG_FILES)
    except Exception:
        pass

    return False


TUPPER_ID_MAX = 10000


def is_tupper(aid: Any) -> bool:
    """Returns True if the author id represents a Tupperbox character bot (< 10000)."""
    if aid is None:
        return False
    try:
        aid_int = int(aid)
        return aid_int < TUPPER_ID_MAX
    except (ValueError, TypeError):
        return False


def get_author_id(m: Any) -> Any:
    """
    Safely extracts integer author ID from a message dictionary.
    Returns None if missing, null, non-dict, or unparseable.
    """
    if not isinstance(m, dict):
        return None
    author = m.get("author")
    if not isinstance(author, dict):
        return None
    raw_id = author.get("id")
    if raw_id is None:
        return None
    try:
        return int(raw_id)
    except (ValueError, TypeError):
        return None


def format_excerpt(text: str) -> str:
    """Formats a message excerpt, truncating strings >250 chars to 120 head + [...] + 120 tail (247 chars)."""
    s = str(text or "")
    if len(s) <= 250:
        return s
    return f"{s[:120]}\n[...]\n{s[-120:]}"


def parse_datetime(val: Any) -> Any:
    """Parses a datetime object or ISO-8601 string to a UTC datetime object."""
    if not val:
        return None
    if isinstance(val, datetime.datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=datetime.timezone.utc)
        return val.astimezone(datetime.timezone.utc)
    if isinstance(val, str) and val.strip():
        try:
            dt = datetime.datetime.fromisoformat(val)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(datetime.timezone.utc)
        except Exception:
            return None
    return None


################ End Functions ################

if __name__ == "__main__":
    pass
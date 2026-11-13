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

def save_json_atomic(data, target_path):
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
            json.dump(data, file, indent=4)
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
_backups_index_cache: Dict[str, Any] = {"path": None, "mtime": None, "data": None}
_debug_files_cache: Dict[str, Tuple[Optional[float], bool]] = {}


def _invalidate_json_caches(resolved_path: Optional[str] = None) -> None:
    """Invalidates in-memory backups_index and backup_config caches on write."""
    with _cache_lock:
        if resolved_path is None:
            _backups_index_cache["path"] = None
            _backups_index_cache["mtime"] = None
            _backups_index_cache["data"] = None
            _debug_files_cache.clear()
            return
        norm = Path(resolved_path).resolve().as_posix()
        cached_idx_path = _backups_index_cache.get("path")
        if cached_idx_path and Path(cached_idx_path).resolve().as_posix() == norm:
            _backups_index_cache["mtime"] = None
            _backups_index_cache["data"] = None
        _debug_files_cache.pop(norm, None)


def get_backups_index():
    set_path()
    from res import constants as c

    index_path = Path(c.BACKUPS_INDEX)
    if not index_path.exists():
        return []

    resolved = index_path.resolve().as_posix()
    try:
        mtime = os.path.getmtime(resolved)
    except OSError:
        mtime = None

    with _cache_lock:
        if (
            _backups_index_cache["path"] == resolved
            and _backups_index_cache["mtime"] == mtime
            and _backups_index_cache["data"] is not None
            and mtime is not None
        ):
            return [dict(b) if isinstance(b, dict) else b for b in _backups_index_cache["data"]]

    data = load_from_json(c.BACKUPS_INDEX)
    with _cache_lock:
        _backups_index_cache["path"] = resolved
        _backups_index_cache["mtime"] = mtime
        _backups_index_cache["data"] = data if isinstance(data, list) else []
        return [dict(b) if isinstance(b, dict) else b for b in _backups_index_cache["data"]]

def get_backup_path(backup_id: str) -> str:
    """
    Returns the absolute directory path for a backup_id found in backups_index.json.
    """
    set_path()
    from res import constants as c

    index = get_backups_index()
    for b in index:
        if str(b.get("backup_id")) == str(backup_id):
            return (Path(c.DATA_ROOT) / b["path"]).as_posix()
    raise exc.BackupError(f"Backup ID '{backup_id}' not found in index")

def add_backup_to_index(backup_name, server_id, server_name, path):
    set_path()
    from res import constants as c

    index = get_backups_index()

    matching = next((b for b in index if b["path"] == path), None)
    if matching is None:
        # Generate backup id
        import time
        backup_id = f"{int(time.time())}"

        # Add backup to index
        index.append({
            "backup_id": backup_id,
            "backup_name": backup_name,
            "server_id": server_id,
            "server_name": server_name,
            "path": path
        })

        save_json_atomic(index, c.BACKUPS_INDEX)
    else:
        # If there's conflict with the path, and other fields don't match, raise error
        if matching["backup_name"] != backup_name or matching["server_id"] != server_id or matching["server_name"] != server_name:
            raise exc.BackupError("There's a different backup using the same path.")
        backup_id = str(matching["backup_id"])

    # Update active context if available
    try:
        from models.backup_context import get_current_context
        ctx = get_current_context()
        ctx.backup_id = backup_id
    except Exception:
        pass

    return backup_id



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
    return re.sub(r'[:/\\*?"<>|]', '_', str(name))

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
    """Buffers a formatted log line to the cached file logger for file_path."""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    log_line = f"[{timestamp}]{level}: {clean(str(message))}"
    logger = _get_file_logger(file_path)
    py_level = logging.ERROR if level == "error" else logging.INFO
    logger.log(py_level, log_line)


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
def run_command(command: str, show_lines: int = None):
    set_path()
    from res import constants as c
    from dotenv import load_dotenv

    try:
        load_dotenv('.env')
    except FileNotFoundError:
        raise FileNotFoundError("# NO ENVIRONMENT VARIABLES FOUND. RUNNING WITHOUT THEM #\n")

    try:
        log("console", f"# RUNNING CONSOLE COMMAND #\n")
        log("console", f"> {MAGENTA}{command}{GRAY}\n")

        process = subprocess.Popen(
            command,
            shell=True,
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
    shutil.copytree(c.DATA_FOLDER, c.MERGE_FOLDER, dirs_exist_ok=True)


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

def is_debug_files_enabled(backup_id=None, backup_path=None) -> bool:
    """
    Determines if debug files (JSON snapshots and auxiliary debug files) should be created.
    Checks the active BackupContext first, falling back to inspecting backup_config.json on disk.
    """
    try:
        from res import constants as c
        ctx_id = getattr(c, "BACKUP_ID", None)
        if backup_id is None or ctx_id is None or str(ctx_id) == str(backup_id):
            if hasattr(c, "DEBUG_FILES"):
                return bool(c.DEBUG_FILES)
    except Exception:
        pass

    try:
        target_path = backup_path
        if not target_path and backup_id:
            target_path = get_backup_path(str(backup_id))
        if target_path:
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
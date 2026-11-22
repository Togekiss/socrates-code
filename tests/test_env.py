import asyncio
import atexit
from contextlib import contextmanager
import os
import selectors
import shutil
import sys
import tempfile
import threading
_UNITTEST_PRELOADED = "unittest" in sys.modules
_IS_TEST_RUNNER = _UNITTEST_PRELOADED or os.environ.get("SOCRATES_TEST_SUITE", "").strip() == "1"
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
for _p in (SRC_DIR.as_posix(), PROJECT_ROOT.as_posix()):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from db.test_backup_service import stage_tmp_test_data_root  # noqa: E402, F401

_staged_tmp_data_dir: Optional[str] = None

_INITIAL_IS_PROD = (
    bool(os.environ.get("K_SERVICE", "").strip())
    or os.environ.get("SOCRATES_ENV", "").strip().lower() == "production"
    or os.environ.get("SOCRATES_PRODUCTION_TESTS_ONLY", "").strip().lower() in ("1", "true", "yes")
)

if (
    _IS_TEST_RUNNER
    and not os.environ.get("JWT_SECRET", "").strip()
    and (bool(os.environ.get("K_SERVICE", "").strip()) or os.environ.get("SOCRATES_ENV", "").strip().lower() == "production")
):
    os.environ["SOCRATES_PRODUCTION_TESTS_ONLY"] = "1"
    os.environ["JWT_SECRET"] = "prod_unittest_ephemeral_placeholder_secret_32b"


def is_production_test_run() -> bool:
    return (
        _INITIAL_IS_PROD
        or os.environ.get("SOCRATES_PRODUCTION_TESTS_ONLY", "").strip().lower() in ("1", "true", "yes")
    )


def get_active_data_root() -> Path:
    raw = os.environ.get("SOCRATES_DATA_DIR", "").strip()
    return Path(raw or PROJECT_ROOT.as_posix())


def _is_sqlite_fixture_locked(data_root: Path) -> bool:
    """
    Returns True if any SQLite database or sidecar file in Backups/Elysium-sql-tests
    is currently locked by an external process (e.g. a running uvicorn server on Windows).
    """
    test_backup_dir = data_root / "Backups" / "Elysium-sql-tests"
    if not test_backup_dir.is_dir():
        return False
    sqlite_names = (
        "backup.sqlite",
        "backup.sqlite-wal",
        "backup.sqlite-shm",
        "skeletons.sqlite",
        "skeletons.sqlite-wal",
        "skeletons.sqlite-shm",
        "audit.sqlite",
        "audit.sqlite-wal",
        "audit.sqlite-shm",
    )
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        generic_read = 0x80000000
        open_existing = 3
        file_attribute_normal = 0x80
        invalid_handle_value = wintypes.HANDLE(-1).value

        for fname in sqlite_names:
            target = test_backup_dir / fname
            if not target.exists():
                continue
            handle = kernel32.CreateFileW(
                str(target),
                generic_read,
                0,
                None,
                open_existing,
                file_attribute_normal,
                None,
            )
            if handle == invalid_handle_value:
                err = ctypes.get_last_error()
                if err in (32, 33):
                    return True
            else:
                kernel32.CloseHandle(handle)
    return False


def _update_loaded_constants_paths(data_root: Path) -> None:
    """Updates DATA_ROOT / BACKUPS_DIR / OUT_DIR if res.constants is already imported."""
    root_str = data_root.as_posix()
    for mod_name in ("res.constants", "constants"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "DATA_ROOT"):
            mod.DATA_ROOT = root_str
            mod.BACKUPS_DIR = (data_root / "Backups").as_posix()
            mod.BACKUPS_INDEX = (data_root / "Backups" / "backups_index.json").as_posix()
            mod.OUT_DIR = (data_root / "out").as_posix()
            mod.GLOBAL_LOG_FILE = (data_root / "out" / "log.txt").as_posix()


def _cleanup_staged_tmp_data_dir() -> None:
    global _staged_tmp_data_dir
    if not _staged_tmp_data_dir:
        return
    try:
        from db.session import close_all_engines
        close_all_engines()
    except Exception:
        pass
    try:
        shutil.rmtree(_staged_tmp_data_dir, ignore_errors=True)
    finally:
        _staged_tmp_data_dir = None


_should_stage_isolated_root = (
    os.environ.get("SOCRATES_TEST_DATA_STAGE_DONE") != "1"
    and _IS_TEST_RUNNER
    and (
        is_production_test_run()
        or (
            not os.environ.get("SOCRATES_DATA_DIR", "").strip()
            and (
                os.environ.get("SOCRATES_ISOLATE_TESTS", "").strip().lower() in ("1", "true", "yes")
                or _is_sqlite_fixture_locked(get_active_data_root())
            )
        )
    )
)

if _should_stage_isolated_root:
    _initial_data_root = get_active_data_root()
    _staged_tmp_data_dir = tempfile.mkdtemp(prefix="socrates_test_data_")
    stage_tmp_test_data_root(_initial_data_root, _staged_tmp_data_dir)
    os.environ["SOCRATES_DATA_DIR"] = Path(_staged_tmp_data_dir).as_posix()
    os.environ["SOCRATES_GLOBAL_AUDIT_DB_PATH"] = (Path(_staged_tmp_data_dir) / "out" / "global_audit.sqlite").as_posix()
    os.environ["SOCRATES_SQLITE_TMP_CACHE"] = "0"
    os.environ["SOCRATES_TEST_DATA_STAGE_DONE"] = "1"
    _update_loaded_constants_paths(Path(_staged_tmp_data_dir))
    atexit.register(_cleanup_staged_tmp_data_dir)

DATA_ROOT = get_active_data_root()


def has_local_test_backup_fixture() -> bool:
    return (get_active_data_root() / "Backups" / "Elysium-sql-tests-clean").exists()


def has_local_live_backup_fixture() -> bool:
    root = get_active_data_root()
    return (root / "Backups" / "Elysium").exists() and (root / "Backups" / "el_meu_server").exists()


def skip_in_production_or_missing_fixture(
    reason: str = "Skipped when Backups/Elysium-sql-tests-clean fixture is unavailable",
):
    import unittest
    return unittest.skipUnless(has_local_test_backup_fixture(), reason)


def skip_in_production_or_missing_live_backups(
    reason: str = "Skipped when Backups/Elysium or Backups/el_meu_server is unavailable",
):
    import unittest
    return unittest.skipUnless(has_local_live_backup_fixture(), reason)


def skip_in_production(reason: str = "Skipped in production environment"):
    import unittest
    return unittest.skipIf(is_production_test_run(), reason)


class _SocketFreeWakeSelector(selectors.BaseSelector):
    """Socket-free selector for offline asyncio tests in sandboxed Windows environments."""

    def __init__(self):
        self._cond = threading.Condition()
        self._woken = False
        self._map = {}

    def register(self, fileobj, events, data=None):
        return selectors.SelectorKey(fileobj, 0, events, data)

    def unregister(self, fileobj):
        return None

    def modify(self, fileobj, events, data=None):
        return None

    def select(self, timeout=None):
        with self._cond:
            if not self._woken:
                self._cond.wait(timeout=timeout)
            self._woken = False
        return []

    def close(self):
        with self._cond:
            self._woken = True
            self._cond.notify_all()

    def get_map(self):
        return self._map


class SocketFreeTestEventLoop(asyncio.SelectorEventLoop):
    """SelectorEventLoop without TCP self-pipe sockets for in-memory MockTransport tests."""

    def __init__(self):
        self._wake_sel = _SocketFreeWakeSelector()
        super().__init__(selector=self._wake_sel)

    def _make_self_pipe(self):
        pass

    def _close_self_pipe(self):
        pass

    def _write_to_self(self):
        with self._wake_sel._cond:
            self._wake_sel._woken = True
            self._wake_sel._cond.notify_all()


class _SocketFreeEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def new_event_loop(self):
        return SocketFreeTestEventLoop()


@contextmanager
def use_socket_free_asyncio():
    """Temporarily installs SocketFreeTestEventLoop policy for offline asyncio tests."""
    prev_policy = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(_SocketFreeEventLoopPolicy())
    try:
        yield
    finally:
        asyncio.set_event_loop_policy(prev_policy)

import atexit
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
for _p in (SRC_DIR.as_posix(), PROJECT_ROOT.as_posix()):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_TEST_FIXTURE_CACHE_LOCK = threading.Lock()
_staged_tmp_data_dir: Optional[str] = None

_INITIAL_IS_PROD = (
    bool(os.environ.get("K_SERVICE", "").strip())
    or os.environ.get("SOCRATES_ENV", "").strip().lower() == "production"
    or os.environ.get("SOCRATES_PRODUCTION_TESTS_ONLY", "").strip().lower() in ("1", "true", "yes")
)

if (
    "unittest" in sys.modules
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


def stage_tmp_test_data_root(source_data_root: Union[str, Path], target_data_root: Union[str, Path]) -> Path:
    """
    Stages isolated `/tmp` test fixtures and `backups_index.json` from `source_data_root`
    into `target_data_root` so test suites never mutate live backups or hit GCS FUSE 429s.
    """
    src_root = Path(source_data_root)
    dst_root = Path(target_data_root)
    backups_dir = dst_root / "Backups"
    out_dir = dst_root / "out"
    backups_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    src_clean = src_root / "Backups" / "Elysium-sql-tests-clean"
    if src_clean.exists():
        digest = hashlib.sha256(os.path.realpath(src_clean).encode("utf-8")).hexdigest()[:16]
        cache_dir = Path(tempfile.gettempdir()) / "socrates_test_fixture_cache" / f"clean_{digest}"
        with _TEST_FIXTURE_CACHE_LOCK:
            if not ((cache_dir / "backup_config.json").exists() or (cache_dir / "Info").exists()):
                shutil.rmtree(cache_dir, ignore_errors=True)
                cache_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src_clean, cache_dir)

        dst_clean = backups_dir / "Elysium-sql-tests-clean"
        dst_test = backups_dir / "Elysium-sql-tests"
        shutil.copytree(cache_dir, dst_clean, dirs_exist_ok=True)
        shutil.copytree(cache_dir, dst_test, dirs_exist_ok=True)
        update_dir = dst_test / "Update"
        if update_dir.exists():
            shutil.rmtree(update_dir, ignore_errors=True)

    for live_name in ("Elysium", "el_meu_server"):
        if (src_root / "Backups" / live_name).exists():
            (backups_dir / live_name).mkdir(parents=True, exist_ok=True)

    index_entries = [
        {
            "backup_id": "1",
            "backup_name": "Elysium",
            "server_id": "857848490683269161",
            "server_name": "(+18) Diabolik: Elysium",
            "path": "Backups/Elysium",
        },
        {
            "backup_id": "1789899843",
            "backup_name": "el meu server",
            "server_id": "442481942794076161",
            "server_name": "el meu server",
            "path": "Backups/el_meu_server",
        },
        {
            "backup_id": "1791895360",
            "backup_name": "Elysium-sql-tests",
            "server_id": "857848490683269161",
            "server_name": "(+18) Diabolik: Elysium",
            "path": "Backups/Elysium-sql-tests",
        },
    ]
    (backups_dir / "backups_index.json").write_text(
        json.dumps(index_entries, indent=4),
        encoding="utf-8",
    )
    return dst_root


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


if (
    "unittest" in sys.modules
    and is_production_test_run()
    and os.environ.get("SOCRATES_TEST_DATA_STAGE_DONE") != "1"
):
    _initial_data_root = get_active_data_root()
    _staged_tmp_data_dir = tempfile.mkdtemp(prefix="socrates_test_data_")
    stage_tmp_test_data_root(_initial_data_root, _staged_tmp_data_dir)
    os.environ["SOCRATES_DATA_DIR"] = Path(_staged_tmp_data_dir).as_posix()
    os.environ["SOCRATES_GLOBAL_AUDIT_DB_PATH"] = (Path(_staged_tmp_data_dir) / "out" / "global_audit.sqlite").as_posix()
    os.environ["SOCRATES_SQLITE_TMP_CACHE"] = "0"
    os.environ["SOCRATES_TEST_DATA_STAGE_DONE"] = "1"
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
    return unittest.skipUnless(has_local_test_backup_fixture(), reason)


def skip_in_production_or_missing_live_backups(
    reason: str = "Skipped when Backups/Elysium or Backups/el_meu_server is unavailable",
):
    return unittest.skipUnless(has_local_live_backup_fixture(), reason)


def skip_in_production(reason: str = "Skipped in production environment"):
    return unittest.skipIf(is_production_test_run(), reason)

import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("SOCRATES_DATA_DIR", PROJECT_ROOT.as_posix()))
SRC_DIR = PROJECT_ROOT / "src"
for p in (SRC_DIR.as_posix(), PROJECT_ROOT.as_posix()):
    if p not in sys.path:
        sys.path.insert(0, p)

# pyrefly: ignore [missing-import]
import utils.tricks as t


def reset_test_backup() -> bool:
    src_copy = DATA_ROOT / "Backups" / "Elysium-sql-tests-clean"
    target = DATA_ROOT / "Backups" / "Elysium-sql-tests"

    if not src_copy.exists():
        t.log("error", f"Error: Source copy does not exist at {src_copy}")
        return False

    try:
        # pyrefly: ignore [missing-import]
        from db.session import close_all_engines
        # pyrefly: ignore [missing-import]
        from models import SceneManager
        SceneManager.clear_cache()
        close_all_engines()
        import gc
        gc.collect()
    except Exception:
        pass

    target.mkdir(parents=True, exist_ok=True)

    # 1. Clean files in target that do not exist in src_copy (e.g. backup.sqlite, generated scenes)
    for root, dirs, files in os.walk(target, topdown=False):
        rel_root = Path(root).relative_to(target)
        src_root = src_copy / rel_root
        for f in files:
            target_file = Path(root) / f
            src_file = src_root / f
            if not src_file.exists():
                try:
                    target_file.unlink()
                except OSError:
                    pass
        for d in dirs:
            target_dir = Path(root) / d
            src_dir = src_root / d
            if not src_dir.exists():
                try:
                    target_dir.rmdir()
                except OSError:
                    pass

    # 2. Copy pristine files from src_copy to target
    for root, dirs, files in os.walk(src_copy):
        rel_root = Path(root).relative_to(src_copy)
        dest_root = target / rel_root
        dest_root.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(Path(root) / f, dest_root / f)

    # 3. Remove Update/ folder
    update_dir = target / "Update"
    if update_dir.exists():
        try:
            shutil.rmtree(update_dir)
        except OSError:
            pass
    
    t.log("console", "Successfully restored Backups/Elysium-sql-tests from pristine copy.")
    return True


if __name__ == "__main__":
    reset_test_backup()

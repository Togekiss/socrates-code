import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
for p in (SRC_DIR.as_posix(), PROJECT_ROOT.as_posix()):
    if p not in sys.path:
        sys.path.insert(0, p)

DATA_ROOT = Path(os.environ.get("SOCRATES_DATA_DIR") or PROJECT_ROOT.as_posix())

# pyrefly: ignore [missing-import]
from db.test_backup_service import reset_test_backup_dir  # noqa: E402


def reset_test_backup() -> bool:
    return reset_test_backup_dir(DATA_ROOT)


if __name__ == "__main__":
    reset_test_backup()

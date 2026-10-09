import os
import sys
from pathlib import Path

# Basic application paths that remain constant across all runs
ROOT_DIR = Path(__file__).resolve().parent.parent.as_posix()
DATA_ROOT = Path(os.environ.get("SOCRATES_DATA_DIR", ROOT_DIR)).as_posix()

BACKUPS_DIR = (Path(DATA_ROOT) / "Backups").as_posix()
BACKUPS_INDEX = (Path(BACKUPS_DIR) / 'backups_index.json').as_posix()
OUT_DIR = (Path(DATA_ROOT) / "out").as_posix()
GLOBAL_LOG_FILE = (Path(OUT_DIR) / 'log.txt').as_posix()
RES_DIR = (Path(ROOT_DIR) / "res").as_posix()
GLOBAL_CONFIG = (Path(RES_DIR) / 'config.json').as_posix()

# Ensure src directory is in sys.path so models can be imported
_SRC_DIR = (Path(ROOT_DIR) / "src").as_posix()
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from models.backup_context import BackupContext, get_current_context


def __getattr__(name: str):
    """
    PEP 562 dynamic attribute resolver.
    Intercepts access to dynamic backup-specific constants (e.g. c.DATA_FOLDER, c.LOG_FILE)
    and resolves them from the currently active BackupContext.
    """
    ctx = get_current_context()
    if hasattr(ctx, name):
        return getattr(ctx, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def __dir__():
    """Returns available module attributes including those from active context for autocompletion."""
    ctx = get_current_context()
    return sorted(list(globals().keys()) + dir(ctx))

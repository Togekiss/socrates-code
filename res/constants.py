import json
import os
from pathlib import Path
import sys

# Basic paths
ROOT_DIR = Path(__file__).resolve().parent.parent.as_posix()
DATA_ROOT = Path(os.environ.get("SOCRATES_DATA_DIR", ROOT_DIR)).as_posix()

BACKUPS_DIR = (Path(DATA_ROOT) / "Backups").as_posix()
BACKUPS_INDEX = (Path(BACKUPS_DIR) / 'backups_index.json').as_posix()
OUT_DIR = (Path(DATA_ROOT) / "out").as_posix()
GLOBAL_LOG_FILE = (Path(OUT_DIR) / 'log.txt').as_posix()
RES_DIR = (Path(ROOT_DIR) / "res").as_posix()
GLOBAL_CONFIG = (Path(RES_DIR) / 'config.json').as_posix()

# Get backup_id from command line arguments
_backup_id = None
for i, arg in enumerate(sys.argv):
    if arg == '--backup-id' and i + 1 < len(sys.argv):
        _backup_id = sys.argv[i + 1]
        break

# Get backup path and config
_backup_path = None
if _backup_id:
    # Read backups_index.json
    try:
        with open(BACKUPS_INDEX, 'r', encoding='utf-8') as f:
            _backups_index = json.load(f)
    except FileNotFoundError:
        raise ValueError(f"Backup index file '{BACKUPS_INDEX}' not found.")
    
    # Find if there is a backup with the provided id
    _backup_in_index = next((b for b in _backups_index if b["backup_id"] == _backup_id), None)

    if _backup_in_index:
        _backup_path = _backup_in_index['path']
        CONFIG_FILE = (Path(DATA_ROOT) / _backup_path / 'backup_config.json').as_posix()
    else:
        raise ValueError(f"Backup with ID '{_backup_id}' not found in {BACKUPS_INDEX}")
else:
    CONFIG_FILE = GLOBAL_CONFIG

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

admin_cfg = config.get('admin', {})
user_cfg = config.get('user', {})
verbosity = admin_cfg.get('verbosity', {})
filters = user_cfg.get('filters', {})

# Path parameters
SERVER_NAME = admin_cfg.get('serverName', "")
BACKUP_NAME = admin_cfg.get('backupName', SERVER_NAME)
PATH_FROM_CFG = admin_cfg.get('path', "")

if _backup_path:
    BACKUP_BASE = (Path(DATA_ROOT) / _backup_path).as_posix()
elif PATH_FROM_CFG:
    BACKUP_BASE = (Path(DATA_ROOT) / PATH_FROM_CFG).as_posix()
else:
    BACKUP_BASE = (Path(BACKUPS_DIR) / BACKUP_NAME).as_posix()


LOG_FILE = (Path(BACKUP_BASE) / 'log.txt').as_posix()
DATA_FOLDER = (Path(BACKUP_BASE) / 'Data').as_posix()
UPDATE_FOLDER = (Path(BACKUP_BASE) / 'Update').as_posix()
MERGE_FOLDER = (Path(BACKUP_BASE) / 'Merge').as_posix()
INFO_FOLDER = (Path(BACKUP_BASE) / 'Info').as_posix()
BACKUP_INFO = (Path(INFO_FOLDER) / 'backup_info.json').as_posix()
BACKUP_INFO_UPDATE = (Path(INFO_FOLDER) / 'backup_info_update.json').as_posix()
CHARACTER_LIST = (Path(INFO_FOLDER) / 'character_list.json').as_posix()
FIXED_MESSAGES = (Path(INFO_FOLDER) / 'fixed_messages.json').as_posix()
BAD_MESSAGES = (Path(INFO_FOLDER) / 'bad_messages.json').as_posix()
BAD_END_MESSAGES = (Path(INFO_FOLDER) / 'bad_end_messages.json').as_posix()


# Discord parameters
SERVER_ID = admin_cfg.get('serverId', "")
DM_CATEGORIES = admin_cfg.get('dmCategories', [])
CATEGORIES_TO_IGNORE = set(admin_cfg.get('categoriesToIgnore', []))
CATEGORIES_TO_KEEP = set(admin_cfg.get('categoriesToKeep', []))
KEEP_MODE = admin_cfg.get('keepMode', False)

# Feedback settings
INFO = verbosity.get('info', True)
DEBUG = verbosity.get('debug', True)
CONSOLE = verbosity.get('console', True)
LOG = verbosity.get('log', True)
DRY_RUN = verbosity.get('dryRun', True)
DEBUG_FILES = verbosity.get('debugFiles', False)

# Search parameters
SEARCH_FOLDER = user_cfg.get('searchFolder', "")
CHARACTER = user_cfg.get('character', "")

INCLUDE_ALL_WRITERS = user_cfg.get('includeAllWriters', False)
INCLUDE_ALTER_EGOS = user_cfg.get('includeAlterEgos', True)
INCLUDE_FAMILIARS = user_cfg.get('includeFamiliars', True)
INCLUDE_NPCS = user_cfg.get('includeNpcs', True)

# Result filters - are applied when creating the list of links and downloading full scenes
STATUS = filters.get('status', "all")
TYPE = filters.get('type', "all")
MODE = filters.get('mode', "end")

# Result file parameters
OUTPUT_SCENES = (Path(OUT_DIR) / CHARACTER / 'scenes.json').as_posix()
OUTPUT_LINKS = (Path(OUT_DIR) / CHARACTER / 'scene-links.txt').as_posix()

import json
import os
import sys

# Basic paths
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.environ.get("SOCRATES_DATA_DIR", ROOT_DIR)

BACKUPS_DIR = os.path.join(DATA_ROOT, "Backups")
BACKUPS_INDEX = os.path.join(BACKUPS_DIR, 'backups_index.json')
OUT_DIR = os.path.join(DATA_ROOT, "out")
GLOBAL_LOG_FILE = os.path.join(OUT_DIR, 'log.txt')
RES_DIR = os.path.join(ROOT_DIR, "res")
GLOBAL_CONFIG = os.path.join(RES_DIR, 'config.json')

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
        CONFIG_FILE = os.path.join(DATA_ROOT,_backup_path, 'backup_config.json')
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
    BACKUP_BASE = os.path.join(DATA_ROOT, _backup_path)
elif PATH_FROM_CFG:
    BACKUP_BASE = os.path.join(DATA_ROOT, PATH_FROM_CFG)
else:
    BACKUP_BASE = os.path.join(BACKUPS_DIR, BACKUP_NAME)


LOG_FILE = os.path.join(BACKUP_BASE, 'log.txt')
DATA_FOLDER = os.path.join(BACKUP_BASE, 'Data')
UPDATE_FOLDER = os.path.join(BACKUP_BASE, 'Update')
MERGE_FOLDER = os.path.join(BACKUP_BASE, 'Merge')
INFO_FOLDER = os.path.join(BACKUP_BASE, 'Info')
BACKUP_INFO = os.path.join(INFO_FOLDER, 'backup_info.json')
BACKUP_INFO_UPDATE = os.path.join(INFO_FOLDER, 'backup_info_update.json')
CHARACTER_LIST = os.path.join(INFO_FOLDER, 'character_list.json')
FIXED_MESSAGES = os.path.join(INFO_FOLDER, 'fixed_messages.json')
BAD_MESSAGES = os.path.join(INFO_FOLDER, 'bad_messages.json')
BAD_END_MESSAGES = os.path.join(INFO_FOLDER, 'bad_end_messages.json')


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
OUTPUT_SCENES = os.path.join(OUT_DIR, CHARACTER, 'scenes.json')
OUTPUT_LINKS = os.path.join(OUT_DIR, CHARACTER, 'scene-links.txt')

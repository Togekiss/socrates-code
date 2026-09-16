import json
import os
import sys

_backup_id = None
for i, arg in enumerate(sys.argv):
    if arg == '--backup-id' and i + 1 < len(sys.argv):
        _backup_id = sys.argv[i + 1]
        break

_backup_path = None
if _backup_id:
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
    # pyrefly: ignore [missing-import]
    import utils.tricks as t
    
    _backups_index = t.get_backups_index()
    _backup_info = next((b for b in _backups_index if b["backup_id"] == _backup_id), None)
    if _backup_info:
        _backup_path = _backup_info['path']
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), _backup_path, 'backup_config.json')
    else:
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
else:
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')

with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)

admin_cfg = config.get('admin', {})
user_cfg = config.get('user', {})
verbosity = admin_cfg.get('verbosity', {})
filters = user_cfg.get('filters', {})

# Discord parameters
SERVER_NAME = admin_cfg.get('serverName', "")
SERVER_ID = admin_cfg.get('serverId', "")
DM_CATEGORIES = admin_cfg.get('dmCategories', [])
CATEGORIES_TO_IGNORE = set(admin_cfg.get('categoriesToIgnore', []))
CATEGORIES_TO_KEEP = set(admin_cfg.get('categoriesToKeep', []))
KEEP_MODE = admin_cfg.get('keepMode', False)

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

# Feedback settings
INFO = verbosity.get('info', True)
DEBUG = verbosity.get('debug', True)
CONSOLE = verbosity.get('console', True)
LOG = verbosity.get('log', True)
DRY_RUN = verbosity.get('dryRun', True)
DEBUG_FILES = verbosity.get('debugFiles', False)

# Result file parameters
OUTPUT_SCENES = f"out/{CHARACTER}/scenes.json"
OUTPUT_LINKS = f"out/{CHARACTER}/scene-links.txt"
# File parameters
BACKUPS_FOLDER = "Backups"
if _backup_path:
    BACKUP_BASE = _backup_path
else:
    BACKUP_BASE = f"{BACKUPS_FOLDER}/{SERVER_NAME}"

LOG_FILE = f"{BACKUP_BASE}/log.txt"
GLOBAL_LOG_FILE = "out/log.txt"
DATA_FOLDER = f"{BACKUP_BASE}/Data"
UPDATE_FOLDER = f"{BACKUP_BASE}/Update"
MERGE_FOLDER = f"{BACKUP_BASE}/Merge"
INFO_FOLDER = f"{BACKUP_BASE}/Info"
BACKUP_INFO = f"{INFO_FOLDER}/backup_info.json"
BACKUP_INFO_UPDATE = f"{INFO_FOLDER}/backup_info_update.json"
CHARACTER_LIST = f"{INFO_FOLDER}/character_list.json"
FIXED_MESSAGES = f"{INFO_FOLDER}/fixed_messages.json"
BAD_MESSAGES =  f"{INFO_FOLDER}/bad_messages.json"
BAD_END_MESSAGES = f"{INFO_FOLDER}/bad_end_messages.json"


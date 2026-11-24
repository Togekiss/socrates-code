from dataclasses import dataclass, field
from contextvars import ContextVar, Token
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Set, List, Dict, Any
import json
import os
import sys

from utils.path_safety import strip_category_prefix

# Global static paths that do not depend on the active backup
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.as_posix()
DATA_ROOT = Path(os.environ.get("SOCRATES_DATA_DIR", ROOT_DIR)).as_posix()

BACKUPS_DIR = (Path(DATA_ROOT) / "Backups").as_posix()
BACKUPS_INDEX = (Path(BACKUPS_DIR) / 'backups_index.json').as_posix()
OUT_DIR = (Path(DATA_ROOT) / "out").as_posix()
GLOBAL_LOG_FILE = (Path(OUT_DIR) / 'log.txt').as_posix()
RES_DIR = (Path(ROOT_DIR) / "res").as_posix()
GLOBAL_CONFIG = (Path(RES_DIR) / 'config.json').as_posix()

_current_context: ContextVar[Optional['BackupContext']] = ContextVar('current_backup_context', default=None)


def _active_data_root() -> str:
    env_root = os.environ.get("SOCRATES_DATA_DIR", "").strip()
    if env_root:
        return Path(env_root).as_posix()
    return DATA_ROOT


@dataclass
class BackupContext:
    """
    Encapsulates all runtime paths, configuration settings, and flags
    for a specific backup run or default state.
    """
    # Context identification
    backup_id: Optional[str] = None
    backup_path: Optional[str] = None
    config_file: str = GLOBAL_CONFIG

    # Raw configurations
    config: Dict[str, Any] = field(default_factory=dict)
    admin_cfg: Dict[str, Any] = field(default_factory=dict)
    user_cfg: Dict[str, Any] = field(default_factory=dict)
    verbosity: Dict[str, Any] = field(default_factory=dict)
    filters: Dict[str, Any] = field(default_factory=dict)

    # Path parameters
    server_name: str = ""
    backup_name: str = ""
    path_from_cfg: str = ""
    backup_base: str = ""

    # File paths
    log_file: str = ""
    data_folder: str = ""
    update_folder: str = ""
    merge_folder: str = ""
    info_folder: str = ""
    backup_info: str = ""
    backup_info_update: str = ""
    character_list: str = ""
    fixed_messages: str = ""
    bad_messages: str = ""
    bad_end_messages: str = ""
    sqlite_db: str = ""

    # Discord parameters
    server_id: str = ""
    dm_categories: List[str] = field(default_factory=list)
    chatroom_categories: List[str] = field(default_factory=list)
    event_categories: List[str] = field(default_factory=list)
    categories_to_ignore: Set[str] = field(default_factory=set)
    categories_to_keep: Set[str] = field(default_factory=set)
    keep_mode: bool = False

    # Verbosity & Feedback settings
    info: bool = True
    debug: bool = True
    console: bool = True
    log: bool = True
    dry_run: bool = False
    debug_files: bool = False

    # Search parameters
    search_folder: str = ""
    character: str = ""
    include_all_writers: bool = False
    include_alter_egos: bool = True
    include_familiars: bool = True
    include_npcs: bool = True

    # Filter parameters
    status: str = "all"
    type: str = "all"
    mode: str = "end"

    # Result file parameters
    output_scenes: str = ""
    output_links: str = ""

    # Static application paths accessible via context instance
    ROOT_DIR: str = ROOT_DIR
    DATA_ROOT: str = DATA_ROOT
    BACKUPS_DIR: str = BACKUPS_DIR
    BACKUPS_INDEX: str = BACKUPS_INDEX
    OUT_DIR: str = OUT_DIR
    GLOBAL_LOG_FILE: str = GLOBAL_LOG_FILE
    RES_DIR: str = RES_DIR
    GLOBAL_CONFIG: str = GLOBAL_CONFIG

    # Internal token for context manager restoration
    _token: Optional[Token] = field(default=None, repr=False)

    def __getattr__(self, name: str) -> Any:
        # Support uppercase attribute access (e.g. ctx.DATA_FOLDER -> ctx.data_folder)
        lower_name = name.lower()
        if lower_name in self.__dict__:
            return self.__dict__[lower_name]
        if name in ("_backup_id", "BACKUP_ID"):
            return self.backup_id
        if name in ("_backup_path", "BACKUP_PATH"):
            return self.backup_path
        if name in ("CONFIG_FILE",):
            return self.config_file
        if name in ("BACKUP_BASE",):
            return self.backup_base
        if name in ("PATH_FROM_CFG",):
            return self.path_from_cfg
        if name in ("SQLITE_DB",):
            return self.sqlite_db
        raise AttributeError(f"'BackupContext' object has no attribute '{name}'")

    @classmethod
    def create(
        cls,
        backup_id: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        config_file: Optional[str] = None,
        backup_path: Optional[str] = None,
        config_path: Optional[str] = None,
    ) -> 'BackupContext':
        _backup_id = str(backup_id) if backup_id is not None else None
        _backup_path = backup_path
        _explicit_cfg_file = config_file or config_path

        active_data_root = _active_data_root()
        active_backups_dir = (Path(active_data_root) / "Backups").as_posix()
        active_out_dir = (Path(active_data_root) / "out").as_posix()
        active_backups_index = (Path(active_backups_dir) / "backups_index.json").as_posix()
        active_global_log = (Path(active_out_dir) / "log.txt").as_posix()

        if _backup_id and not _backup_path:
            from utils import tricks as t
            try:
                _backup_path = t.get_backup_path(_backup_id)
            except Exception:
                if not os.environ.get("DATABASE_URL", "").strip():
                    raise

        # Determine BACKUP_BASE if _backup_path is available
        backup_base = None
        if _backup_path:
            path_obj = Path(_backup_path)
            backup_base = path_obj.as_posix() if path_obj.is_absolute() else (Path(active_data_root) / path_obj).as_posix()

        # Auto-resolve _backup_id from auto-discovered backups index by matching backup_base
        if not _backup_id and backup_base:
            try:
                from utils import tricks as t
                norm_base = Path(backup_base).resolve().as_posix()
                for b in t.get_backups_index():
                    entry_path = b.get("path", "")
                    if not entry_path:
                        continue
                    entry_full = Path(entry_path) if Path(entry_path).is_absolute() else (Path(active_data_root) / entry_path)
                    if entry_full.resolve().as_posix() == norm_base:
                        _backup_id = str(b.get("backup_id"))
                        break
            except Exception:
                pass

        # Determine CONFIG_FILE and load config dictionary if not explicitly provided
        if _explicit_cfg_file:
            _config_file = _explicit_cfg_file
            if config is None:
                if Path(_config_file).exists():
                    with open(_config_file, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                else:
                    config = {}
        elif _backup_id or backup_base:
            local_cfg = (Path(backup_base) / 'backup_config.json').as_posix() if backup_base else GLOBAL_CONFIG
            _config_file = local_cfg if (backup_base and Path(local_cfg).exists()) else GLOBAL_CONFIG
            if config is None:
                from db.config_service import load_backup_config_dict
                config = load_backup_config_dict(backup_id=_backup_id, backup_path=backup_base)
        else:
            _config_file = GLOBAL_CONFIG
            if config is None:
                if Path(_config_file).exists():
                    with open(_config_file, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                else:
                    config = {}

        admin_cfg = config.get('admin', {})
        user_cfg = config.get('user', {})
        verbosity = admin_cfg.get('verbosity', {})
        filters = user_cfg.get('filters', {})

        server_name = admin_cfg.get('serverName', "")
        backup_name = admin_cfg.get('backupName', server_name)
        path_from_cfg = admin_cfg.get('path', "")

        # If backup_base wasn't set from _backup_path, calculate from config
        if not backup_base:
            if path_from_cfg:
                cfg_path_obj = Path(path_from_cfg)
                backup_base = cfg_path_obj.as_posix() if cfg_path_obj.is_absolute() else (Path(active_data_root) / cfg_path_obj).as_posix()
            elif backup_name:
                backup_base = (Path(active_backups_dir) / backup_name).as_posix()
            elif _backup_id:
                backup_base = (Path(active_backups_dir) / _backup_id).as_posix()
            else:
                backup_base = active_backups_dir

        info_folder = (Path(backup_base) / 'Info').as_posix()
        character = user_cfg.get('character', "")

        return cls(
            backup_id=_backup_id,
            backup_path=_backup_path,
            config_file=_config_file,
            config=config,
            admin_cfg=admin_cfg,
            user_cfg=user_cfg,
            verbosity=verbosity,
            filters=filters,
            server_name=server_name,
            backup_name=backup_name,
            path_from_cfg=path_from_cfg,
            backup_base=backup_base,
            log_file=(Path(backup_base) / 'log.txt').as_posix(),
            data_folder=(Path(backup_base) / 'Data').as_posix(),
            update_folder=(Path(backup_base) / 'Update').as_posix(),
            merge_folder=(Path(backup_base) / 'Merge').as_posix(),
            info_folder=info_folder,
            backup_info=(Path(info_folder) / 'backup_info.json').as_posix(),
            backup_info_update=(Path(info_folder) / 'backup_info_update.json').as_posix(),
            character_list=(Path(info_folder) / 'character_list.json').as_posix(),
            fixed_messages=(Path(info_folder) / 'fixed_messages.json').as_posix(),
            bad_messages=(Path(info_folder) / 'bad_messages.json').as_posix(),
            bad_end_messages=(Path(info_folder) / 'bad_end_messages.json').as_posix(),
            sqlite_db=(Path(backup_base) / 'backup.sqlite').as_posix(),
            server_id=admin_cfg.get('serverId', ""),
            dm_categories=[strip_category_prefix(x) for x in admin_cfg.get('dmCategories', []) if strip_category_prefix(x)],
            chatroom_categories=[strip_category_prefix(x) for x in admin_cfg.get('chatroomCategories', []) if strip_category_prefix(x)],
            event_categories=[strip_category_prefix(x) for x in admin_cfg.get('eventCategories', []) if strip_category_prefix(x)],
            categories_to_ignore={strip_category_prefix(x) for x in admin_cfg.get('categoriesToIgnore', []) if strip_category_prefix(x)},
            categories_to_keep={strip_category_prefix(x) for x in admin_cfg.get('categoriesToKeep', []) if strip_category_prefix(x)},
            keep_mode=admin_cfg.get('keepMode', False),
            info=verbosity.get('info', True),
            debug=verbosity.get('debug', True),
            console=verbosity.get('console', True),
            log=verbosity.get('log', True),
            dry_run=bool(verbosity.get('dryRun', False)),
            debug_files=verbosity.get('debugFiles', False),
            search_folder=user_cfg.get('searchFolder', ""),
            character=character,
            include_all_writers=user_cfg.get('includeAllWriters', False),
            include_alter_egos=user_cfg.get('includeAlterEgos', True),
            include_familiars=user_cfg.get('includeFamiliars', True),
            include_npcs=user_cfg.get('includeNpcs', True),
            status=filters.get('status', "all"),
            type=filters.get('type', "all"),
            mode=filters.get('mode', "end"),
            output_scenes=(Path(active_out_dir) / character / 'scenes.json').as_posix(),
            output_links=(Path(active_out_dir) / character / 'scene-links.txt').as_posix(),
            DATA_ROOT=active_data_root,
            BACKUPS_DIR=active_backups_dir,
            BACKUPS_INDEX=active_backups_index,
            OUT_DIR=active_out_dir,
            GLOBAL_LOG_FILE=active_global_log,
        )

    @classmethod
    def from_backup_id(cls, backup_id: str) -> 'BackupContext':
        return cls.create(backup_id=backup_id)

    @classmethod
    def from_config_dict(cls, config: Dict[str, Any], backup_id: Optional[str] = None) -> 'BackupContext':
        return cls.create(backup_id=backup_id, config=config)

    @classmethod
    def default(cls) -> 'BackupContext':
        return cls.create()

    @classmethod
    def from_cli(cls) -> 'BackupContext':
        backup_id = None
        for i, arg in enumerate(sys.argv):
            if arg == '--backup-id' and i + 1 < len(sys.argv):
                backup_id = sys.argv[i + 1]
                break
        if backup_id:
            return cls.from_backup_id(backup_id)
        return cls.default()

    def __enter__(self) -> 'BackupContext':
        self._token = _current_context.set(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._token is not None:
            _current_context.reset(self._token)
            self._token = None

    @classmethod
    @contextmanager
    def activate(
        cls,
        backup_id: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        context: Optional['BackupContext'] = None
    ):
        """
        Activates a BackupContext within a scoped context manager block.
        Restores previous context automatically upon exit.
        """
        if context is not None:
            ctx = context
        elif config is not None:
            ctx = cls.from_config_dict(config, backup_id=backup_id)
        elif backup_id is not None:
            ctx = cls.from_backup_id(backup_id)
        else:
            ctx = cls.from_cli()

        token = _current_context.set(ctx)
        try:
            yield ctx
        finally:
            _current_context.reset(token)


def get_current_context() -> BackupContext:
    """
    Retrieves the active BackupContext in the current execution context (async task or thread).
    If no context is explicitly active, initializes and caches one based on CLI arguments or default config.
    """
    ctx = _current_context.get()
    if ctx is None:
        ctx = BackupContext.from_cli()
        _current_context.set(ctx)
    return ctx

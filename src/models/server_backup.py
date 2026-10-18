from dataclasses import dataclass, field
from copy import deepcopy
from enum import StrEnum
import json
from pathlib import Path
from typing import Optional, Any, Dict, List
from utils import exceptions as exc
from .category import Category
from .channel import Channel
from .thread import Thread

class Status(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class Step(StrEnum):
    GET_INFO = "get_info"
    CLEAN_INFO = "clean_info"
    DOWNLOAD = "download"
    VERIFY = "verify"
    ASSIGN_IDS = "assign_ids"
    COMPARE = "compare"
    MERGE = "merge"
    FIX_MESSAGES = "fix_messages"
    INDEX_SCENES = "index_scenes"
    UPDATE = "update"

DEFAULT_STEPS: dict[Step, Status] = {step: Status.PENDING for step in Step}

@dataclass
class ServerBackup:

    #  ============== Basic info =============
    id: str
    name: str
    updated_at: str
    exported_from: str = ""
    exported_at: str = ""
    path: str = ""
    scope: str = "base"
    steps: dict[Step, Status] = field(
        default_factory=lambda: deepcopy(DEFAULT_STEPS),
        repr=False
    )
    categories: list[Category] = field(default_factory=list, repr=False)
    _channel_index: dict[str, Channel] = field(init=False, repr=False)
    _thread_index: dict[str, Thread] = field(init=False, repr=False)
    _category_by_channel_index: dict[str, Category] = field(init=False, repr=False)

    def __post_init__(self):
        self.build_indexes()

    @property
    def backup_id(self) -> str:
        from res import constants as c
        b_id = getattr(c, "BACKUP_ID", None)
        if b_id:
            return str(b_id)
        try:
            from models.backup_context import get_current_context
            ctx = get_current_context()
            if ctx.backup_id:
                return str(ctx.backup_id)
        except Exception:
            pass
        return self.id

    @property
    def backup_name(self) -> str:
        from res import constants as c
        b_name = getattr(c, "BACKUP_NAME", None)
        if b_name:
            return str(b_name)
        try:
            from models.backup_context import get_current_context
            ctx = get_current_context()
            if ctx.backup_name:
                return str(ctx.backup_name)
        except Exception:
            pass
        return self.name

    @property
    def number_of_categories(self):
        return len(self.categories)
    
    @property
    def number_of_channels(self):
        return sum(category.number_of_channels for category in self.categories)
    
    @property
    def number_of_threads(self):
        return sum(category.number_of_threads for category in self.categories)
    
    @property
    def number_of_scenes(self):
        return sum(category.number_of_scenes for category in self.categories)
    
    def _effective_steps(self):
        return (s for s in self.steps if s is not Step.UPDATE)

    @property
    def status(self):
        if all(value == Status.SUCCESS for step, value in self.steps.items() if step != Step.UPDATE):
            return Status.SUCCESS
        elif any(value == Status.FAILED for step, value in self.steps.items() if step != Step.UPDATE):
            return Status.FAILED
        elif any(value == Status.RUNNING for step, value in self.steps.items() if step != Step.UPDATE):
            return Status.RUNNING
        else:
            return Status.PENDING
    
    #  =============== Parsers & Loaders ================
    @classmethod
    def from_dict(cls, data: dict, scope: str = "base") -> "ServerBackup":
        raw_steps = data.get("steps", deepcopy(DEFAULT_STEPS))
        normalized_steps: dict[Step, Status] = {}
        for st in Step:
            val = raw_steps.get(st.value, raw_steps.get(st, Status.PENDING))
            normalized_steps[st] = Status(val) if isinstance(val, str) else val

        return cls(
            id=data["id"],
            name=data["name"],
            updated_at=data["updated_at"],
            exported_from=data.get("exported_from", ""),
            exported_at=data.get("exported_at", ""),
            scope=scope,
            steps=normalized_steps,
            categories=[
                Category.from_dict(category_data)
                for category_data in data.get("categories", [])
            ],
        )

    @classmethod
    def load(
        cls,
        scope: str = "base",
        backup_id: Optional[str] = None,
        backup_path: Optional[str] = None
    ) -> "ServerBackup":
        """
        Loads the ServerBackup state directly from SQLite via status_service.load_backup_state.
        """
        from res import constants as c
        from db import status_service

        b_id = backup_id or getattr(c, "BACKUP_ID", None)
        b_path = backup_path or getattr(c, "BACKUP_BASE", None)
        if not b_id or not b_path:
            from models.backup_context import get_current_context
            ctx = get_current_context()
            b_id = b_id or ctx.backup_id
            b_path = b_path or ctx.backup_base

        if not b_id or not b_path:
            raise exc.ServerBackupClassError("Cannot load ServerBackup without backup_id and backup_path.")

        data = status_service.load_backup_state(b_id, b_path, scope=scope)
        obj = cls.from_dict(data, scope=scope)
        obj.path = b_path
        return obj

    @classmethod
    def init_export(
        cls,
        scope: str = "base",
        backup_id: Optional[str] = None,
        backup_path: Optional[str] = None,
        backup_name: Optional[str] = None,
        server_id: Optional[str] = None,
        server_name: Optional[str] = None,
        updated_at: Optional[Any] = None,
    ) -> "ServerBackup":
        """
        Initializes the SQLite database tables and export record, returning a loaded ServerBackup instance.
        """
        from res import constants as c
        from db import status_service

        b_id = backup_id or getattr(c, "BACKUP_ID", None)
        b_path = backup_path or getattr(c, "BACKUP_BASE", None)
        b_name = backup_name or getattr(c, "BACKUP_NAME", None) or getattr(c, "SERVER_NAME", "Backup")
        s_id = server_id or getattr(c, "SERVER_ID", None)
        s_name = server_name or getattr(c, "SERVER_NAME", None)

        if not b_id or not b_path:
            from models.backup_context import get_current_context
            ctx = get_current_context()
            b_id = b_id or ctx.backup_id
            b_path = b_path or ctx.backup_base

        status_service.init_backup_export(
            backup_id=b_id,
            backup_path=b_path,
            backup_name=b_name,
            server_id=s_id,
            server_name=s_name,
            scope=scope,
            updated_at=updated_at,
        )
        return cls.load(scope=scope, backup_id=b_id, backup_path=b_path)
    
    @classmethod
    def from_json(cls, path: str) -> "ServerBackup":
        """
        Compatibility loader delegating to load() via SQLite.
        Falls back to JSON file loading only during bootstrap/migration.
        """
        scope = "update" if "update" in Path(path).name.lower() else "base"
        from res import constants as c
        b_path = (Path(path).parent.parent.as_posix() if "Info" in path else getattr(c, "BACKUP_BASE", None))
        try:
            return cls.load(scope=scope, backup_path=b_path)
        except Exception:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            obj = cls.from_dict(data, scope=scope)
            obj.path = path
            return obj
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "updated_at": self.updated_at,
            "exported_from": self.exported_from,
            "exported_at": self.exported_at,
            "status": self.status,
            "steps": {st.value if hasattr(st, "value") else str(st): (v.value if hasattr(v, "value") else str(v)) for st, v in self.steps.items()},
            "number_of_categories": self.number_of_categories,
            "number_of_channels": self.number_of_channels,
            "number_of_threads": self.number_of_threads,
            "number_of_scenes": self.number_of_scenes,
            "categories": [category.to_dict() for category in self.categories]
        }
    
    def to_json(self):
        """Saves state to SQLite and exports the backup_info snapshot."""
        self.save(write_snapshot=True)

    def build_indexes(self):
        self._channel_index = {}
        self._thread_index = {}
        self._category_by_channel_index = {}
        
        for category in self.categories:
            for channel in category.channels:
                self._channel_index[channel.id] = channel
                self._category_by_channel_index[channel.id] = category
                for thread in channel.threads:
                    self._thread_index[thread.id] = thread
    
    def save(self, write_snapshot: bool = False):
        """
        Persists state to SQLite via status_service.save_backup_state.
        """
        self.build_indexes()
        from db import status_service
        from res import constants as c
        backup_id = getattr(c, "BACKUP_ID", None) or self.id
        backup_path = getattr(c, "BACKUP_BASE", None) or self.path
        if backup_id and backup_path:
            status_service.save_backup_state(
                backup_id=backup_id,
                backup_path=backup_path,
                backup_obj=self,
                scope=self.scope,
                write_snapshot=write_snapshot
            )

    def _set_step_status(self, step: Step, status: Status, error: Optional[str] = None):
        self.steps[step] = status
        write_snapshot = (status in (Status.SUCCESS, Status.FAILED))
        from db import status_service
        from res import constants as c
        backup_id = getattr(c, "BACKUP_ID", None) or self.id
        backup_path = getattr(c, "BACKUP_BASE", None) or self.path
        if backup_id and backup_path:
            status_service.update_step_status(
                backup_id=backup_id,
                backup_path=backup_path,
                step=step,
                status=status,
                scope=self.scope,
                error=error,
                write_snapshot=write_snapshot
            )
        else:
            self.save(write_snapshot=write_snapshot)

    # =============== Status Checks & Step Transitions ================

    def is_running(self) -> bool:
        return any(
            status == Status.RUNNING
            for st, status in self.steps.items()
            if st != Step.UPDATE
        )

    def is_other_step_running(self, current_step: Step) -> bool:
        return any(
            status == Status.RUNNING
            for st, status in self.steps.items()
            if st != current_step and st != Step.UPDATE
        )
    
    def is_failed(self) -> bool:
        return self.status == Status.FAILED
    
    def set_failed(self, error: Optional[str] = None):
        for step in self.steps:
            if self.steps[step] == Status.RUNNING:
                self.steps[step] = Status.FAILED
        from db import status_service
        from res import constants as c
        backup_id = getattr(c, "BACKUP_ID", None) or self.id
        backup_path = getattr(c, "BACKUP_BASE", None) or self.path
        if backup_id and backup_path:
            status_service.fail_running_steps(
                backup_id=backup_id,
                backup_path=backup_path,
                scope=self.scope,
                error=error,
                write_snapshot=True
            )
        else:
            self.save(write_snapshot=True)
    
    def is_success(self) -> bool:
        return self.status == Status.SUCCESS

    def needs_update(self) -> bool:
        return self.updated_at is not None and self.steps[Step.DOWNLOAD] == Status.SUCCESS
    
    def start_update(self):
        self._set_step_status(Step.UPDATE, Status.RUNNING)

    def can_finish_update(self) -> bool:
        return self.can_fix_messages() 
    
    def finish_update(self, success: bool = True, error: Optional[str] = None):
        self.steps[Step.UPDATE] = Status.SUCCESS if success else Status.FAILED
        if success:
            self.steps[Step.FIX_MESSAGES] = Status.PENDING
            self.steps[Step.INDEX_SCENES] = Status.PENDING
        self.save(write_snapshot=True)

    def is_updating(self) -> bool:
        return self.steps[Step.UPDATE] == Status.RUNNING
    
    def start_get_info(self):
        self._set_step_status(Step.GET_INFO, Status.RUNNING)
    
    def finish_get_info(self, success: bool = True, error: Optional[str] = None):
        self._set_step_status(Step.GET_INFO, Status.SUCCESS if success else Status.FAILED, error=error)
    
    def start_clean_info(self):
        self._set_step_status(Step.CLEAN_INFO, Status.RUNNING)

    def finish_clean_info(self, success: bool = True, error: Optional[str] = None):
        if success:
            self.steps[Step.CLEAN_INFO] = Status.SUCCESS
            self.save(write_snapshot=True)
        else:
            self._set_step_status(Step.CLEAN_INFO, Status.FAILED, error=error)

    def can_download(self) -> bool:
        return self.steps[Step.GET_INFO] == Status.SUCCESS and self.steps[Step.CLEAN_INFO] == Status.SUCCESS
    
    def start_download(self):
        self.steps[Step.DOWNLOAD] = Status.RUNNING
        self.save(write_snapshot=False)

    def finish_download(self, success: bool = True, error: Optional[str] = None):
        if success:
            self.steps[Step.DOWNLOAD] = Status.SUCCESS
            self.save(write_snapshot=True)
        else:
            self._set_step_status(Step.DOWNLOAD, Status.FAILED, error=error)

    def can_verify(self) -> bool:
        return self.steps[Step.DOWNLOAD] == Status.SUCCESS

    def start_verify(self):
        self._set_step_status(Step.VERIFY, Status.RUNNING)

    def finish_verify(self, success: bool = True, error: Optional[str] = None):
        if success:
            self.steps[Step.VERIFY] = Status.SUCCESS
            self.save(write_snapshot=True)
        else:
            self._set_step_status(Step.VERIFY, Status.FAILED, error=error)
    
    def can_assign_ids(self) -> bool:
        return self.steps[Step.VERIFY] == Status.SUCCESS

    def start_assign_ids(self):
        self._set_step_status(Step.ASSIGN_IDS, Status.RUNNING)
    
    def finish_assign_ids(self, success: bool = True, error: Optional[str] = None):
        if success:
            self.steps[Step.ASSIGN_IDS] = Status.SUCCESS
            self.save(write_snapshot=True)
        else:
            self._set_step_status(Step.ASSIGN_IDS, Status.FAILED, error=error)

    def can_compare(self) -> bool:
        return self.steps[Step.VERIFY] == Status.SUCCESS
    
    def start_compare(self):
        self._set_step_status(Step.COMPARE, Status.RUNNING)

    def finish_compare(self, success: bool = True, error: Optional[str] = None):
        if success:
            self.steps[Step.COMPARE] = Status.SUCCESS
            self.save(write_snapshot=True)
        else:
            self._set_step_status(Step.COMPARE, Status.FAILED, error=error)

    def can_merge(self) -> bool:
        return self.steps[Step.COMPARE] == Status.SUCCESS
    
    def start_merge(self):
        self._set_step_status(Step.MERGE, Status.RUNNING)

    def finish_merge(self, success: bool = True, error: Optional[str] = None):
        if success:
            self.steps[Step.MERGE] = Status.SUCCESS
            self.save(write_snapshot=True)
        else:
            self._set_step_status(Step.MERGE, Status.FAILED, error=error)

    def can_fix_messages(self) -> bool:
        return self.steps[Step.MERGE] == Status.SUCCESS and self.steps[Step.ASSIGN_IDS] == Status.SUCCESS
    
    def start_fix_messages(self):
        self._set_step_status(Step.FIX_MESSAGES, Status.RUNNING)

    def finish_fix_messages(self, success: bool = True, error: Optional[str] = None):
        if success:
            self.steps[Step.FIX_MESSAGES] = Status.SUCCESS
            self.save(write_snapshot=True)
        else:
            self._set_step_status(Step.FIX_MESSAGES, Status.FAILED, error=error)

    def can_index_scenes(self) -> bool:
        return self.steps[Step.FIX_MESSAGES] == Status.SUCCESS

    def start_index_scenes(self):
        self._set_step_status(Step.INDEX_SCENES, Status.RUNNING)
    
    def finish_index_scenes(self, success: bool = True, error: Optional[str] = None):
        if success:
            self.steps[Step.INDEX_SCENES] = Status.SUCCESS
            self.save(write_snapshot=True)
        else:
            self._set_step_status(Step.INDEX_SCENES, Status.FAILED, error=error)

    def can_find_scenes(self) -> bool:
        return self.steps[Step.INDEX_SCENES] == Status.SUCCESS

        
    # ============== Working with data ==============

    def sort_categories(self):
        self.categories.sort(key=lambda cat: cat.position)
        self.build_indexes()

    def add_new_category(self, category: Category):
        self.categories.append(category)

    def add_category_from_update(self, category: Category):
        category.channels.clear()
        self.categories.append(category)
        self.sort_categories()
        self.save()

    def add_new_channel(self, channel: Channel):
        if not self.categories:
            raise exc.ServerBackupClassError("Cannot add a channel without a category. Add a category first.")
        self.categories[-1].add_channel(channel)
    
    def add_new_thread(self, thread: Thread):
        if not self.categories or not self.categories[-1].channels:
            raise exc.ServerBackupClassError("Cannot add a thread without a channel. Add a category and a channel first.")
        self.categories[-1].channels[-1].add_thread(thread)

    def remove_categories(self, category_names: set[str]):
        self.categories = [
            category for category in self.categories
            if category.name not in category_names
        ]
    
    def keep_categories(self, category_names: set[str]):
        self.categories = [
            category for category in self.categories
            if category.name in category_names
        ]
    
    def has_category(self, category_id: str) -> bool:
        return any(category.id == category_id for category in self.categories)
    
    def has_category_at_position(self, position: int) -> bool:
        return any(category.position == position for category in self.categories)
    
    def get_category_by_id(self, category_id: str) -> Category | None:
        for category in self.categories:
            if category.id == category_id:
                return category
        return None
    
    def has_channel(self, channel_id: str) -> bool:
        if not hasattr(self, '_channel_index'):
            self.build_indexes()
        return channel_id in self._channel_index
    
    def has_thread(self, thread_id: str) -> bool:
        if not hasattr(self, '_thread_index'):
            self.build_indexes()
        return thread_id in self._thread_index
    
    def get_channel_by_id(self, channel_id: str) -> Channel | None:
        if not hasattr(self, '_channel_index'):
            self.build_indexes()
        return self._channel_index.get(channel_id)
    
    def get_thread_by_id(self, item_id: str) -> Thread | None:
        if not hasattr(self, '_thread_index'):
            self.build_indexes()
        return self._thread_index.get(item_id)
    
    def get_parent_category_of_channel(self, channel_id: str) -> Category | None:
        if not hasattr(self, '_category_by_channel_index'):
            self.build_indexes()
        return self._category_by_channel_index.get(channel_id)
    
    def get_all_paths(self) -> list[str]:
        paths = []
        for category in self.categories:
            for channel in category.channels:
                paths.append(channel.path)
                for thread in channel.threads:
                    paths.append(thread.path)
        return paths
    
    def get_all_ids(self) -> list[str]:
        ids = []
        for category in self.categories:
            ids.append(category.id)
            for channel in category.channels:
                ids.append(channel.id)
                for thread in channel.threads:
                    ids.append(thread.id)
        return ids
    
    def repeated_id(self) -> str | None:
        ids = set()
        for category in self.categories:
            if category.id in ids:
                return category.id
            ids.add(category.id)
            for channel in category.channels:
                if channel.id in ids:
                    return channel.id
                ids.add(channel.id)
                for thread in channel.threads:
                    if thread.id in ids:
                        return thread.id
                    ids.add(thread.id)
        return None

    def repeated_position(self) -> str | None:
        positions = set()
        positions_channels = set()
        positions_threads = set()

        for category in self.categories:
            if (
                not category.is_deleted
                and (category.new_position if category.new_position is not None else category.position) in positions
            ):
                return category.id
            positions.add(category.new_position if category.new_position is not None else category.position)

            positions_channels.clear()

            for channel in category.channels:
                if (
                    not channel.is_deleted
                    and (channel.new_position if channel.new_position is not None else channel.position) in positions_channels
                ):
                    return channel.id
                positions_channels.add(channel.new_position if channel.new_position is not None else channel.position)

                positions_threads.clear()

                for thread in channel.threads:
                    if (
                        not thread.is_deleted
                        and (thread.new_position if thread.new_position is not None else thread.position) in positions_threads
                    ):
                        return thread.id
                    positions_threads.add(thread.new_position if thread.new_position is not None else thread.position)
        
        return None
    
    def update_message_count(self, item_id: str, message_count: int):
        """Mutates in-memory channel or thread message count without writing to disk or database."""
        if self.has_channel(item_id):
            self.get_channel_by_id(item_id).messages = message_count
        elif self.has_thread(item_id):
            self.get_thread_by_id(item_id).messages = message_count

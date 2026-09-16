from dataclasses import dataclass, field
from copy import deepcopy
from enum import StrEnum
import json
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
    steps: dict[Step, Status] = field(
        default_factory=lambda: deepcopy(DEFAULT_STEPS),
        repr=False
    )
    categories: list[Category] = field(default_factory=list, repr=False)
    _channel_index: dict[str, Channel] = field(init=False, repr=False)
    _thread_index: dict[str, Thread] = field(init=False, repr=False)
    _category_by_channel_index: dict[str, Category] = field(init=False, repr=False)

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
    
    #  =============== Parsers ================
    @classmethod
    def from_dict(cls, data: dict) -> "ServerBackup":
        return cls(
            id=data["id"],
            name=data["name"],
            updated_at=data["updated_at"],
            exported_from=data.get("exported_from", ""),
            exported_at=data.get("exported_at", ""),
            steps=data.get("steps", deepcopy(DEFAULT_STEPS)),
            categories=[
                Category.from_dict(category_data)
                for category_data in data.get("categories", [])
            ],
        )
    
    @classmethod
    def from_json(cls, path: str) -> "ServerBackup":
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            obj = cls.from_dict(data)
            obj.path = path
            return obj
        except FileNotFoundError as e:
            raise e
        except Exception as e:
            raise exc.ServerBackupClassError(
                f"Failed to load ServerBackup from JSON file: {e}"
            ) from e
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "updated_at": self.updated_at,
            "exported_from": self.exported_from,
            "exported_at": self.exported_at,
            "status": self.status,
            "steps": self.steps,
            "number_of_categories": self.number_of_categories,
            "number_of_channels": self.number_of_channels,
            "number_of_threads": self.number_of_threads,
            "number_of_scenes": self.number_of_scenes,
            "categories": [category.to_dict() for category in self.categories]
        }
    
    def to_json(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=4)

        except Exception as e:
            raise exc.ServerBackupClassError(
                f"Failed to write backup info file: {self.path}"
            ) from e

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
    
    def save(self):
        self.build_indexes()
        self.to_json()

    # =============== Status ================

    def is_running(self) -> bool:
        return self.status == Status.RUNNING
    
    def is_failed(self) -> bool:
        return self.status == Status.FAILED
    
    def is_success(self) -> bool:
        return self.status == Status.SUCCESS

    def needs_update(self) -> bool:
        return self.updated_at is not None and self.steps[Step.DOWNLOAD] == Status.SUCCESS
    
    def start_update(self):
        self.steps[Step.UPDATE] = Status.RUNNING
        self.to_json()

    def can_finish_update(self) -> bool:
        return self.can_fix_messages() 
    
    def finish_update(self, success: bool = True):
        self.steps[Step.UPDATE] = Status.SUCCESS if success else Status.FAILED
        if success:
            self.steps[Step.FIX_MESSAGES] = Status.PENDING
            self.steps[Step.INDEX_SCENES] = Status.PENDING
        self.to_json()

    def is_updating(self) -> bool:
        return self.steps[Step.UPDATE] == Status.RUNNING
    
    def start_get_info(self):
        self.steps[Step.GET_INFO] = Status.RUNNING
        self.to_json()
    
    def finish_get_info(self, success: bool = True):
        self.steps[Step.GET_INFO] = Status.SUCCESS if success else Status.FAILED
        self.to_json()
    
    def start_clean_info(self):
        self.steps[Step.CLEAN_INFO] = Status.RUNNING
        self.to_json()

    def finish_clean_info(self, success: bool = True):
        self.steps[Step.CLEAN_INFO] = Status.SUCCESS if success else Status.FAILED
        self.to_json()

    def can_download(self) -> bool:
        return self.steps[Step.GET_INFO] == Status.SUCCESS and self.steps[Step.CLEAN_INFO] == Status.SUCCESS
    
    def start_download(self):
        self.steps[Step.DOWNLOAD] = Status.RUNNING
        self.to_json()

    def finish_download(self, success: bool = True):
        self.steps[Step.DOWNLOAD] = Status.SUCCESS if success else Status.FAILED
        self.to_json()

    def can_verify(self) -> bool:
        return self.steps[Step.DOWNLOAD] == Status.SUCCESS

    def start_verify(self):
        self.steps[Step.VERIFY] = Status.RUNNING
        self.to_json()

    def finish_verify(self, success: bool = True):
        self.steps[Step.VERIFY] = Status.SUCCESS if success else Status.FAILED
        self.to_json()
    
    def can_assign_ids(self) -> bool:
        return self.steps[Step.VERIFY] == Status.SUCCESS

    def start_assign_ids(self):
        self.steps[Step.ASSIGN_IDS] = Status.RUNNING
        self.to_json()
    
    def finish_assign_ids(self, success: bool = True):
        self.steps[Step.ASSIGN_IDS] = Status.SUCCESS if success else Status.FAILED
        self.to_json()

    def can_compare(self) -> bool:
        return self.steps[Step.VERIFY] == Status.SUCCESS
    
    def start_compare(self):
        self.steps[Step.COMPARE] = Status.RUNNING
        self.to_json()

    def finish_compare(self, success: bool = True):
        self.steps[Step.COMPARE] = Status.SUCCESS if success else Status.FAILED
        self.to_json()

    def can_merge(self) -> bool:
        return self.steps[Step.COMPARE] == Status.SUCCESS
    
    def start_merge(self):
        self.steps[Step.MERGE] = Status.RUNNING
        self.to_json()

    def finish_merge(self, success: bool = True):
        self.steps[Step.MERGE] = Status.SUCCESS if success else Status.FAILED
        self.to_json()

    def can_fix_messages(self) -> bool:
        return self.steps[Step.MERGE] == Status.SUCCESS and self.steps[Step.ASSIGN_IDS] == Status.SUCCESS
    
    def start_fix_messages(self):
        self.steps[Step.FIX_MESSAGES] = Status.RUNNING
        self.to_json()

    def finish_fix_messages(self, success: bool = True):
        self.steps[Step.FIX_MESSAGES] = Status.SUCCESS if success else Status.FAILED
        self.to_json()

    def can_index_scenes(self) -> bool:
        return self.steps[Step.FIX_MESSAGES] == Status.SUCCESS

    def start_index_scenes(self):
        self.steps[Step.INDEX_SCENES] = Status.RUNNING
        self.to_json()
    
    def finish_index_scenes(self, success: bool = True):
        self.steps[Step.INDEX_SCENES] = Status.SUCCESS if success else Status.FAILED
        self.to_json()

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
        if self.has_channel(item_id):
            self.get_channel_by_id(item_id).messages = message_count
        elif self.has_thread(item_id):
            self.get_thread_by_id(item_id).messages = message_count
        self.to_json()

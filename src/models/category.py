from dataclasses import dataclass, field
from .channel import Channel
from .thread import Thread

@dataclass
class Category:
    id: str
    name: str
    position: int
    path: str = ""
    is_deleted: bool = False
    channels: list[Channel] = field(default_factory=list, repr=False)

    # Indexes, used for faster lookups. Not included in JSON
    _channel_index: dict[str, Channel] = field(init=False, repr=False)
    _thread_index: dict[str, Thread] = field(init=False, repr=False)
    _channel_by_thread: dict[str, Channel] = field(init=False, repr=False)

    # Helpers during updates. Not included in JSON
    new_name: str = None
    new_position: int = None
    new_path: str = None

    def add_channel(self, channel: Channel):
        self.channels.append(channel)

    @property
    def number_of_channels(self):
        return len(self.channels)

    @property
    def number_of_threads(self):
        return sum(channel.number_of_threads for channel in self.channels)
    
    @property
    def number_of_scenes(self):
        return sum((channel.scenes + channel.number_of_threads) for channel in self.channels)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "position": self.position,
            "path": self.path,
            "is_deleted": self.is_deleted,
            "number_of_scenes": self.number_of_scenes,
            "number_of_channels": self.number_of_channels,
            "number_of_threads": self.number_of_threads,
            "channels": [channel.to_dict() for channel in self.channels]
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Category":
        return cls(
            id=data["id"],
            name=data["name"],
            position=data["position"],
            path=data["path"],
            is_deleted=data.get("is_deleted", False),
            channels=[
                Channel.from_dict(channel_data)
                for channel_data in data.get("channels", [])
            ],
        )
    
    def build_indexes(self):
        self._channel_index = {channel.id: channel for channel in self.channels}
        self._thread_index = {thread.id: thread for channel in self.channels for thread in channel.threads}
        self._channel_by_thread = {thread.id: channel for channel in self.channels for thread in channel.threads}
        self._channel_by_position = {channel.position: channel for channel in self.channels}

    def sort_channels(self):
        self.channels.sort(key=lambda c: c.position)
        self.build_indexes()

    def add_channel_from_update(self, channel: Channel):
        self.channels.append(channel)
        self.sort_channels()
        self.build_indexes()

    def remove_channel_by_id(self, channel_id: str):
        self.channels = [channel for channel in self.channels if channel.id != channel_id]
        self.build_indexes()
    
    def has_channel(self, channel_id: str) -> bool:
        if not hasattr(self, '_channel_index'):
            self.build_indexes()
        return channel_id in self._channel_index
    
    def get_channel_by_id(self, channel_id: str) -> Channel | None:
        return self._channel_index.get(channel_id) if self.has_channel(channel_id) else None
    
    def has_thread(self, thread_id: str) -> bool:
        if not hasattr(self, '_thread_index'):
            self.build_indexes()
        return thread_id in self._thread_index
    
    def get_thread_by_id(self, thread_id: str) -> Thread | None:
        return self._thread_index.get(thread_id) if self.has_thread(thread_id) else None
    
    def get_channel_of_thread(self, thread_id: str) -> Channel | None:
        if not hasattr(self, '_channel_by_thread'):
            self.build_indexes()
        return self._channel_by_thread.get(thread_id) if self.has_thread(thread_id) else None

    def get_thread_and_parent_channel(self, thread_id: str) -> tuple[Thread | None, Channel | None]:
        thread = self.get_thread_by_id(thread_id)
        channel = self.get_channel_of_thread(thread_id)
        return thread, channel
    
    def update(self, new_name=None, new_position=None, new_path=None):
        self.new_name = new_name
        self.new_position = new_position
        self.new_path = new_path

    def is_updated(self):
        return self.new_name is not None or self.new_position is not None or self.new_path is not None 
    
    def save_updates(self):
        self.name = self.new_name if self.new_name is not None else self.name
        self.position = self.new_position if self.new_position is not None else self.position
        self.path = self.new_path if self.new_path is not None else self.path
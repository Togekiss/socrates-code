from dataclasses import dataclass, field
from .thread import Thread

@dataclass
class Channel:
    id: str
    name: str
    position: int
    messages: int = 0
    scenes: int = 0
    path: str = ""
    is_deleted: bool = False
    threads: list[Thread] = field(default_factory=list, repr=False)

    # Helpers during updates. Not included in JSON
    new_name: str = None
    new_position: int = None
    new_path: str = None

    def add_thread(self, thread: Thread):
        self.threads.append(thread)

    @property
    def number_of_threads(self):
        return len(self.threads)
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "position": self.position,
            "path": self.path,
            "is_deleted": self.is_deleted,
            "number_of_messages": self.messages,
            "number_of_scenes": self.scenes,
            "number_of_threads": self.number_of_threads,
            "threads": [thread.to_dict() for thread in self.threads]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Channel":
        return cls(
            id=data["id"],
            name=data["name"],
            position=data["position"],
            messages=data["number_of_messages"],
            scenes=data["number_of_scenes"],
            path=data["path"],
            is_deleted=data.get("is_deleted", False),
            threads=[
                Thread.from_dict(thread_data)
                for thread_data in data.get("threads", [])
            ],
        )

    def get_thread_by_id(self, thread_id: str) -> Thread | None:
        for thread in self.threads:
            if thread.id == thread_id:
                return thread
        return None
    
    def sort_threads(self):
        self.threads.sort(key=lambda thread: thread.position)

    def add_thread_from_update(self, thread: Thread):
        self.threads.append(thread)
        self.sort_threads()

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
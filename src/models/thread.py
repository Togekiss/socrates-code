from dataclasses import dataclass

@dataclass
class Thread:
    id: str
    name: str
    position: int
    messages: int = 0
    path: str = ""
    is_deleted: bool = False

    # Helpers during updates. Not included in JSON
    new_name: str = None
    new_position: int = None
    new_path: str = None

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "position": self.position,
            "path": self.path,
            "is_deleted": self.is_deleted,
            "number_of_messages": self.messages
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Thread":
        return cls(
            id=data["id"],
            name=data["name"],
            position=data["position"],
            messages=data["number_of_messages"],
            path=data["path"],
            is_deleted=data.get("is_deleted", False),
        )

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
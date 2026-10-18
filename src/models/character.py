try:
    from utils.exceptions import AssignIDError
except ModuleNotFoundError:
    from src.utils.exceptions import AssignIDError

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any


@dataclass
class Character:
    id: int
    names: List[str]
    writer: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    other_versions: List['Character'] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> 'Character':
        return cls(
            id=data["id"],
            names=data.get("names", []),
            writer=data.get("writer", []),
            tags=data.get("tags", []),
            other_versions=[cls.from_dict(v) for v in data.get("other_versions", [])]
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "names": self.names,
            "writer": self.writer,
            "tags": self.tags,
            "other_versions": [v.to_dict() for v in self.other_versions]
        }


class CharacterList:
    def __init__(
        self,
        characters: List[Character],
        backup_id: Optional[str] = None,
        base_path: Optional[str] = None
    ):
        self.characters = characters
        self.backup_id = backup_id
        self.base_path = base_path
        self._name_to_id: Dict[str, int] = {}
        self._id_to_name: Dict[int, str] = {}
        self._new_characters: List[Tuple[int, str]] = []
        self._init_lookups()

    def _init_lookups(self):
        self._name_to_id = {}
        self._id_to_name = {}
        max_id = 0
        for char in self.characters:
            max_id = max(max_id, char.id)
            if char.names:
                self._id_to_name[char.id] = char.names[0]
            for n in char.names:
                self._name_to_id[n.strip().lower()] = char.id

            for version in char.other_versions:
                max_id = max(max_id, version.id)
                if version.names:
                    self._id_to_name[version.id] = version.names[0]
                for n in version.names:
                    self._name_to_id[n.strip().lower()] = version.id

        self._next_id = max_id + 1

    @classmethod
    def load(
        cls,
        path: Optional[str] = None,
        backup_id: Optional[str] = None,
        base_path: Optional[str] = None
    ) -> 'CharacterList':
        """Loads CharacterList from SQLite via character_service, falling back to JSON only during migration."""
        from res import constants as c
        from db import character_service

        b_id = backup_id or getattr(c, "BACKUP_ID", None)
        b_path = base_path or getattr(c, "BACKUP_BASE", None)
        if not b_path and path:
            b_path = Path(path).parent.parent.as_posix() if "Info" in path else path

        if not b_id or not b_path:
            try:
                from models.backup_context import get_current_context
                ctx = get_current_context()
                b_id = b_id or ctx.backup_id
                b_path = b_path or ctx.backup_base
            except Exception:
                pass

        try:
            if b_id and b_path:
                raw_chars = character_service.get_characters(b_id, b_path, format_type="legacy")
                char_objs = [Character.from_dict(d) for d in raw_chars]
                return cls(char_objs, backup_id=b_id, base_path=b_path)
        except Exception:
            pass



        return cls([], backup_id=b_id, base_path=b_path)

    def save(self, path: Optional[str] = None):
        """Batch-inserts any newly added characters into SQLite and exports character_list.json snapshot."""
        from db import character_service
        from res import constants as c

        b_id = self.backup_id or getattr(c, "BACKUP_ID", None)
        b_path = self.base_path or getattr(c, "BACKUP_BASE", None)

        if not b_id or not b_path:
            try:
                from models.backup_context import get_current_context
                ctx = get_current_context()
                b_id = b_id or ctx.backup_id
                b_path = b_path or ctx.backup_base
            except Exception:
                pass

        if self._new_characters and b_id and b_path:
            character_service.save_new_characters(
                backup_id=b_id,
                base_path=b_path,
                new_characters=self._new_characters,
                write_snapshot=True
            )
            self._new_characters.clear()
        elif b_id and b_path:
            from db.session import db_session
            from db.snapshots import export_character_list_snapshot
            with db_session(backup_id=b_id, backup_path=b_path) as session:
                export_character_list_snapshot(session, b_id, write_to_disk=True)
        else:
            raise AssignIDError("No backup_id or backup_path provided.")

    def get_next_id(self) -> int:
        return self._next_id

    def find_character(self, char_id: int) -> Tuple[Optional[Character], Optional[Character]]:
        """Returns a tuple of (character, parent_character). Parent is None if it's a main character."""
        for char in self.characters:
            if char.id == char_id:
                return char, None
            for version in char.other_versions:
                if version.id == char_id:
                    return version, char
        return None, None

    def get_character_name(self, char_id: int) -> Optional[str]:
        """Retrieves the name of a character with the given unique ID in O(1) time."""
        if char_id in self._id_to_name:
            return self._id_to_name[char_id]
        char, _ = self.find_character(char_id)
        if char and char.names:
            self._id_to_name[char_id] = char.names[0]
            return char.names[0]
        return None

    def get_all_character_ids(self, name: str) -> List[int]:
        """Retrieves the unique IDs of all versions/family members of a character with the given name."""
        from db import character_service
        from res import constants as c

        b_id = self.backup_id or getattr(c, "BACKUP_ID", None)
        b_path = self.base_path or getattr(c, "BACKUP_BASE", None)

        if not b_id or not b_path:
            try:
                from models.backup_context import get_current_context
                ctx = get_current_context()
                b_id = b_id or ctx.backup_id
                b_path = b_path or ctx.backup_base
            except Exception:
                pass

        if b_id and b_path:
            try:
                return character_service.get_character_family_ids(
                    backup_id=b_id,
                    base_path=b_path,
                    name=name,
                    include_all_writers=c.INCLUDE_ALL_WRITERS,
                    include_alter_egos=c.INCLUDE_ALTER_EGOS,
                    include_familiars=c.INCLUDE_FAMILIARS,
                    include_npcs=c.INCLUDE_NPCS,
                )
            except Exception:
                pass

        # In-memory fallback
        ids = []
        target = name.strip().lower()
        for char in self.characters:
            char_names = [n.strip().lower() for n in char.names]
            if target in char_names:
                ids.append(char.id)
                for alt in char.other_versions:
                    if c.INCLUDE_ALL_WRITERS and "has_other_writers" in alt.tags:
                        ids.append(alt.id)
                    if c.INCLUDE_ALTER_EGOS and "alter_ego" in alt.tags:
                        ids.append(alt.id)
                    if c.INCLUDE_FAMILIARS and "familiar" in alt.tags:
                        ids.append(alt.id)
                    if c.INCLUDE_NPCS and "npc" in alt.tags:
                        ids.append(alt.id)

            for alt in char.other_versions:
                alt_names = [n.strip().lower() for n in alt.names]
                if target in alt_names:
                    ids.append(alt.id)
        return ids

    def find_id_by_name(self, search_name: str) -> Optional[int]:
        """Finds the ID of a character by their name in O(1) time."""
        clean = search_name.strip().lower()
        return self._name_to_id.get(clean)

    def add_character(self, name: str) -> Character:
        """Adds a new character, queues it for SQLite persistence, and returns it."""
        clean_name = name.strip()
        lower_name = clean_name.lower()
        if lower_name in self._name_to_id:
            char_id = self._name_to_id[lower_name]
            char, _ = self.find_character(char_id)
            if char:
                return char

        new_id = self._next_id
        self._next_id += 1
        new_char = Character(id=new_id, names=[clean_name])
        self.characters.append(new_char)
        self._name_to_id[lower_name] = new_id
        self._id_to_name[new_id] = clean_name
        self._new_characters.append((new_id, clean_name))
        return new_char

    def merge_characters(self, source_id: int, target_id: int):
        """Merges source character into target character, deleting source."""
        source, source_parent = self.find_character(source_id)
        target, target_parent = self.find_character(target_id)
        
        if not source or not target:
            raise ValueError("Source or target character not found")
            
        for name in source.names:
            if name not in target.names:
                target.names.append(name)
        for writer in source.writer:
            if writer not in target.writer:
                target.writer.append(writer)
                
        if source_parent:
            source_parent.other_versions = [v for v in source_parent.other_versions if v.id != source_id]
        else:
            self.characters = [c for c in self.characters if c.id != source_id]
        self._init_lookups()

    def nest_character(self, child_id: int, parent_id: int, version_type: str):
        """Nests child under parent and assigns the version_type tag."""
        child, child_parent = self.find_character(child_id)
        parent, parent_parent = self.find_character(parent_id)
        
        if not child or not parent:
            raise ValueError("Child or parent character not found")
        if parent_parent is not None:
            raise ValueError("Cannot nest under a character that is already nested (max 1 level depth)")
        if child.other_versions:
            raise ValueError("Cannot nest a character that has its own other_versions")
            
        if child_parent:
            child_parent.other_versions = [v for v in child_parent.other_versions if v.id != child_id]
        else:
            self.characters = [c for c in self.characters if c.id != child_id]
            
        valid_tags = ["npc", "familiar", "alter_ego"]
        if version_type in valid_tags and version_type not in child.tags:
            child.tags.append(version_type)
            
        parent.other_versions.append(child)
        self._init_lookups()

    def unnest_character(self, char_id: int):
        """Moves a nested character to the root level."""
        child, parent = self.find_character(char_id)
        if not child:
            raise ValueError("Character not found")
        if not parent:
            raise ValueError("Character is already at the root level")
            
        parent.other_versions = [v for v in parent.other_versions if v.id != char_id]
        self.characters.append(child)
        self._init_lookups()

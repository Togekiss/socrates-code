import json
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

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
    def __init__(self, characters: List[Character]):
        self.characters = characters

    @classmethod
    def load(cls, path: str) -> 'CharacterList':
        import os
        if not os.path.exists(path):
            return cls([])
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls([Character.from_dict(d) for d in data])

    def save(self, path: str):
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        # Sort by ID
        self.characters.sort(key=lambda c: c.id)
        for char in self.characters:
            char.other_versions.sort(key=lambda c: c.id)
            
        with open(path, 'w', encoding='utf-8') as f:
            json.dump([c.to_dict() for c in self.characters], f, indent=4)

    def get_next_id(self) -> int:
        max_id = 0
        for char in self.characters:
            max_id = max(max_id, char.id)
            for version in char.other_versions:
                max_id = max(max_id, version.id)
        return max_id + 1

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
        """Retrieves the name of a character with the given unique ID."""
        char, _ = self.find_character(char_id)
        if char and char.names:
            return char.names[0]
        return None

    def get_all_character_ids(self, name: str) -> List[int]:
        """Retrieves the unique IDs of all versions of a character with the given name."""
        from res import constants as c
        ids = []
        for char in self.characters:
            if name in char.names:
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
            
            # If the user inputted an alt's name, just return the alt
            for alt in char.other_versions:
                if name in alt.names:
                    ids.append(alt.id)
        return ids

    def find_id_by_name(self, search_name: str) -> Optional[int]:
        """Finds the ID of a character by their name."""
        for char in self.characters:
            if search_name in char.names:
                return char.id
            for version in char.other_versions:
                if search_name in version.names:
                    return version.id
        return None

    def add_character(self, name: str) -> Character:
        """Adds a new character and returns it."""
        new_id = self.get_next_id()
        new_char = Character(id=new_id, names=[name])
        self.characters.append(new_char)
        return new_char

    def merge_characters(self, source_id: int, target_id: int):
        """Merges source character into target character, deleting source."""
        source, source_parent = self.find_character(source_id)
        target, target_parent = self.find_character(target_id)
        
        if not source or not target:
            raise ValueError("Source or target character not found")
            
        # Merge names and writers (avoid duplicates)
        for name in source.names:
            if name not in target.names:
                target.names.append(name)
        for writer in source.writer:
            if writer not in target.writer:
                target.writer.append(writer)
                
        # Remove source from its list
        if source_parent:
            source_parent.other_versions = [v for v in source_parent.other_versions if v.id != source_id]
        else:
            self.characters = [c for c in self.characters if c.id != source_id]
            
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
            
        # Remove child from its current location
        if child_parent:
            child_parent.other_versions = [v for v in child_parent.other_versions if v.id != child_id]
        else:
            self.characters = [c for c in self.characters if c.id != child_id]
            
        # Assign the correct tag (npc, familiar, alter_ego)
        valid_tags = ["npc", "familiar", "alter_ego"]
        if version_type in valid_tags and version_type not in child.tags:
            child.tags.append(version_type)
            
        parent.other_versions.append(child)
        
    def unnest_character(self, char_id: int):
        """Moves a nested character to the root level."""
        child, parent = self.find_character(char_id)
        if not child:
            raise ValueError("Character not found")
        if not parent:
            raise ValueError("Character is already at the root level")
            
        # Remove from parent and add to root
        parent.other_versions = [v for v in parent.other_versions if v.id != char_id]
        self.characters.append(child)

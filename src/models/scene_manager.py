import os
import json
from typing import List, Dict, Any, Optional

class SceneManager:
    _instance = None
    
    def __init__(self, backup_id: str, base_path: str, scenes_path: Optional[str] = None):
        self.backup_id = backup_id
        self.base_path = base_path
        self.scenes = []
        self._load_scenes(scenes_path)
        
    @classmethod
    def get_instance(cls, backup_id: str, base_path: str) -> 'SceneManager':
        # Simple caching for one backup at a time
        if cls._instance is None or cls._instance.backup_id != backup_id:
            cls._instance = cls(backup_id, base_path)
        return cls._instance

    def _load_scenes(self, custom_path: Optional[str] = None):
        scenes_path = custom_path or os.path.join(self.base_path, 'Data', '_scenes.json')
        if os.path.exists(scenes_path):
            with open(scenes_path, 'r', encoding='utf-8') as f:
                self.scenes = json.load(f)
        else:
            self.scenes = []

    def filter_scenes(self, 
                      categories: Optional[List[str]] = None,
                      statuses: Optional[List[str]] = None,
                      types: Optional[List[str]] = None,
                      character_ids: Optional[List[int]] = None,
                      character_logic: str = 'OR',
                      include_alter_egos: bool = False,
                      include_familiars: bool = False,
                      include_npcs: bool = False,
                      writer_names: Optional[List[str]] = None,
                      writer_logic: str = 'OR',
                      char_list = None,
                      before: Optional[str] = None,
                      after: Optional[str] = None) -> List[Dict[str, Any]]:
        """Filters the in-memory scenes based on the criteria."""
        filtered = []
        
        for scene in self.scenes:
            # 1. OR Filters
            if categories and scene.get('category') not in categories:
                continue
            if statuses and scene.get('status') not in statuses:
                continue
            if types and scene.get('type') not in types:
                continue
                
            # Date filters (ISO 8601 strings)
            start_timestamp = scene.get('start', {}).get('timestamp', '')
            if before and start_timestamp and start_timestamp >= before:
                continue
            if after and start_timestamp and start_timestamp <= after:
                continue
                
            scene_chars = set(scene.get('characters', []))
            
            # 2. Characters logic
            if character_ids:
                if character_logic == 'AND':
                    valid = True
                    for cid in character_ids:
                        family = {cid}
                        if char_list:
                            main = next((c for c in char_list if c.get('id') == cid), None)
                            if main and main.get('other_versions'):
                                for v in main['other_versions']:
                                    tags = v.get('tags', [])
                                    if include_alter_egos and 'alter_ego' in tags: family.add(v['id'])
                                    if include_familiars and 'familiar' in tags: family.add(v['id'])
                                    if include_npcs and 'npc' in tags: family.add(v['id'])
                        if not family.intersection(scene_chars):
                            valid = False
                            break
                    if not valid:
                        continue
                else: # OR
                    any_match = False
                    for cid in character_ids:
                        family = {cid}
                        if char_list:
                            main = next((c for c in char_list if c.get('id') == cid), None)
                            if main and main.get('other_versions'):
                                for v in main['other_versions']:
                                    tags = v.get('tags', [])
                                    if include_alter_egos and 'alter_ego' in tags: family.add(v['id'])
                                    if include_familiars and 'familiar' in tags: family.add(v['id'])
                                    if include_npcs and 'npc' in tags: family.add(v['id'])
                        if family.intersection(scene_chars):
                            any_match = True
                            break
                    if not any_match:
                        continue
                        
            # 3. Writers logic
            if writer_names and char_list:
                scene_writers = set()
                for cid in scene_chars:
                    char, _ = char_list.find_character(cid)
                    if char:
                        for w in char.writer:
                            scene_writers.add(w)
                            
                target_writers = set(writer_names)
                if writer_logic == 'AND':
                    if not target_writers.issubset(scene_writers):
                        continue
                else: # OR
                    if not target_writers.intersection(scene_writers):
                        continue
                        
            filtered.append(scene)
            
        return filtered

    def get_paginated_scenes(self, page: int, per_page: int, **kwargs) -> Dict[str, Any]:
        filtered = self.filter_scenes(**kwargs)
        total_items = len(filtered)
        total_pages = (total_items + per_page - 1) // per_page
        
        # Guard page range
        page = max(1, min(page, max(1, total_pages)))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        
        return {
            "scenes": filtered[start_idx:end_idx],
            "total_pages": total_pages,
            "current_page": page,
            "total_items": total_items
        }

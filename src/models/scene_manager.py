from pathlib import Path
from typing import List, Dict, Any, Optional


class SceneManager:
    _instances: Dict[str, 'SceneManager'] = {}

    def __init__(self, backup_id: str, base_path: str, scenes_path: Optional[str] = None):
        self.backup_id = str(backup_id)
        self.base_path = str(base_path)

    @classmethod
    def get_instance(cls, backup_id: Optional[str] = None, base_path: Optional[str] = None) -> 'SceneManager':
        from res import constants as c
        b_id = backup_id or getattr(c, "BACKUP_ID", None)
        b_path = base_path or getattr(c, "BACKUP_BASE", None)

        if not b_id or not b_path:
            try:
                from models.backup_context import get_current_context
                ctx = get_current_context()
                b_id = b_id or ctx.backup_id
                b_path = b_path or ctx.backup_base
            except Exception:
                pass

        b_id = str(b_id or "")
        b_path = str(b_path or "")
        if b_id not in cls._instances or cls._instances[b_id].base_path != b_path:
            cls._instances[b_id] = cls(b_id, b_path)
        return cls._instances[b_id]

    @classmethod
    def clear_cache(cls, backup_id: Optional[str] = None):
        if backup_id is not None:
            cls._instances.pop(str(backup_id), None)
        else:
            cls._instances.clear()

    @property
    def has_sqlite(self) -> bool:
        from db.session import has_sqlite_db
        return has_sqlite_db(self.base_path)

    def save_scenes(
        self,
        scenes: List[Dict[str, Any]],
        bad_scenes: Optional[List[Dict[str, Any]]] = None,
        debug_files: bool = False
    ) -> None:
        """Persists indexed scenes into SQLite via scene_service."""
        from db import scene_service
        scene_service.save_indexed_scenes(
            backup_id=self.backup_id,
            base_path=self.base_path,
            scenes=scenes,
            bad_scenes=bad_scenes,
            debug_files=debug_files
        )

    def filter_scenes(
        self,
        categories: Optional[List[str]] = None,
        statuses: Optional[List[str]] = None,
        status: str = "all",
        types: Optional[List[str]] = None,
        character_ids: Optional[List[int]] = None,
        character_logic: str = 'OR',
        writer_names: Optional[List[str]] = None,
        writer_logic: str = 'OR',
        include_alter_egos: bool = False,
        include_familiars: bool = False,
        include_npcs: bool = False,
        search_folder: str = "",
        before: Optional[str] = None,
        after: Optional[str] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Delegates scene filtering directly to SQLite via scene_service."""
        from db import scene_service
        return scene_service.query_scenes(
            backup_id=self.backup_id,
            base_path=self.base_path,
            categories=categories,
            statuses=statuses,
            status=status,
            types=types,
            character_ids=character_ids,
            character_logic=character_logic,
            writer_names=writer_names,
            writer_logic=writer_logic,
            include_alter_egos=include_alter_egos,
            include_familiars=include_familiars,
            include_npcs=include_npcs,
            search_folder=search_folder,
            before=before,
            after=after,
            page=None,
            **kwargs
        )

    def get_paginated_scenes(
        self,
        page: int = 1,
        per_page: int = 50,
        **kwargs
    ) -> Dict[str, Any]:
        """Delegates paginated scene queries directly to SQLite via scene_service."""
        from db import scene_service
        return scene_service.query_scenes(
            backup_id=self.backup_id,
            base_path=self.base_path,
            page=page,
            per_page=per_page,
            **kwargs
        )

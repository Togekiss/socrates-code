from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import or_, and_, func

from db.session import db_session, require_sqlite_db, has_sqlite_db
from db.models import (
    CharacterModel,
    CharacterNameModel,
    CharacterGroupModel,
    GroupNameModel,
    WriterModel,
    WriterAliasModel,
    SceneParticipantModel,
)
from db.snapshots import export_character_list_snapshot
from utils import tricks as t


def get_character_count(backup_id: str, base_path: str) -> int:
    """Returns the total number of top-level characters in SQLite."""
    require_sqlite_db(base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        return session.query(func.count(CharacterModel.pk)).filter(
            CharacterModel.backup_id == str(backup_id),
            CharacterModel.parent_pk.is_(None)
        ).scalar() or 0


def get_characters(
    backup_id: str,
    base_path: str,
    format_type: str = "legacy",
    by_writer_name: Optional[str] = None,
    by_writer_id: Optional[int] = None,
) -> Any:
    """
    Retrieves characters for a backup directly from SQLite.
    If format_type == 'legacy', returns hierarchical list matching character_list.json.
    If format_type == 'normalized', returns { writers, groups, characters }.
    Supports optional filtering by writer ID or writer name / alias.
    """
    require_sqlite_db(base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        target_writer_pk = None
        if by_writer_id is not None:
            w_obj = session.query(WriterModel.pk).filter(
                WriterModel.backup_id == str(backup_id),
                WriterModel.pk == by_writer_id
            ).first()
            if not w_obj:
                return [] if format_type == "legacy" else {"writers": [], "groups": [], "characters": []}
            target_writer_pk = w_obj[0]
        elif by_writer_name is not None and by_writer_name.strip():
            w_name = by_writer_name.strip().lower()
            w_obj = session.query(WriterModel.pk).outerjoin(WriterAliasModel).filter(
                WriterModel.backup_id == str(backup_id),
                or_(
                    func.lower(WriterModel.display_name) == w_name,
                    func.lower(WriterAliasModel.alias) == w_name
                )
            ).first()
            if not w_obj:
                return [] if format_type == "legacy" else {"writers": [], "groups": [], "characters": []}
            target_writer_pk = w_obj[0]

        if format_type in ("normalized", "db"):
            data = export_character_list_snapshot(session, backup_id, write_to_disk=False)
            if target_writer_pk is not None:
                data["characters"] = [c for c in data.get("characters", []) if c.get("writer_id") == target_writer_pk]
            return data

        query = session.query(CharacterModel).filter(
            CharacterModel.backup_id == str(backup_id),
            CharacterModel.parent_pk.is_(None)
        )

        if target_writer_pk is not None:
            child_pks = session.query(CharacterModel.parent_pk).filter(
                CharacterModel.backup_id == str(backup_id),
                CharacterModel.parent_pk.isnot(None),
                CharacterModel.writer_pk == target_writer_pk
            )
            query = query.filter(
                or_(
                    CharacterModel.writer_pk == target_writer_pk,
                    CharacterModel.pk.in_(child_pks)
                )
            )

        top_characters = query.order_by(CharacterModel.char_id).all()

        results = []
        for c in top_characters:
            names = [n.name for n in sorted(c.names, key=lambda x: x.position)]
            writer_list = []
            if c.writer:
                writer_list.append(c.writer.display_name)
                for a in c.writer.aliases:
                    if a.alias not in writer_list:
                        writer_list.append(a.alias)

            tags = []
            if c.origin: tags.append(c.origin)
            if c.activity: tags.append(c.activity)
            if c.version_type: tags.append(c.version_type)
            if c.group_pk: tags.append("has_other_writers")

            other_versions = []
            for child in sorted(c.children, key=lambda ch: ch.char_id):
                child_names = [n.name for n in sorted(child.names, key=lambda x: x.position)]
                child_writer = []
                if child.writer:
                    child_writer.append(child.writer.display_name)
                    for a in child.writer.aliases:
                        if a.alias not in child_writer:
                            child_writer.append(a.alias)

                child_tags = []
                if child.origin: child_tags.append(child.origin)
                if child.activity: child_tags.append(child.activity)
                if child.version_type: child_tags.append(child.version_type)

                other_versions.append({
                    "id": child.char_id,
                    "names": child_names,
                    "writer": child_writer,
                    "tags": child_tags,
                    "other_versions": [],
                })

            results.append({
                "id": c.char_id,
                "names": names,
                "writer": writer_list,
                "tags": tags,
                "other_versions": other_versions,
            })

        return results


def save_new_characters(
    backup_id: str,
    base_path: str,
    new_characters: List[Tuple[int, str]],
    write_snapshot: bool = True
) -> None:
    """Batch-inserts newly discovered characters/Tuppers into SQLite."""
    if not new_characters:
        return
    require_sqlite_db(base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        for char_id, name in new_characters:
            existing = session.query(CharacterModel).filter(
                CharacterModel.backup_id == str(backup_id),
                CharacterModel.char_id == char_id
            ).first()
            if not existing:
                char_model = CharacterModel(
                    backup_id=str(backup_id),
                    char_id=char_id,
                    origin="canon",
                    activity="active",
                )
                session.add(char_model)
                session.flush()

                session.add(CharacterNameModel(
                    character_pk=char_model.pk,
                    name=name,
                    position=0
                ))
            else:
                # Add name if not already attached
                name_exists = any(n.name == name for n in existing.names)
                if not name_exists:
                    session.add(CharacterNameModel(
                        character_pk=existing.pk,
                        name=name,
                        position=len(existing.names)
                    ))
        session.flush()

        if write_snapshot:
            export_character_list_snapshot(session, backup_id, write_to_disk=True)


def get_character_family_ids(
    backup_id: str,
    base_path: str,
    name: str,
    include_all_writers: bool = False,
    include_alter_egos: bool = True,
    include_familiars: bool = True,
    include_npcs: bool = True
) -> List[int]:
    """
    Resolves the unique char_ids for all versions/family members of a character with the given name.
    """
    require_sqlite_db(base_path)
    target_name = name.strip().lower()
    matched_ids: List[int] = []

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        all_chars = session.query(CharacterModel).filter(
            CharacterModel.backup_id == str(backup_id)
        ).all()

        groups = session.query(CharacterGroupModel).filter(
            CharacterGroupModel.backup_id == str(backup_id)
        ).all()

        matching_groups = []
        for g in groups:
            for gn in g.names:
                if gn.name.strip().lower() == target_name:
                    matching_groups.append(g)
                    break

        if include_all_writers:
            for g in matching_groups:
                for c in g.characters:
                    matched_ids.append(c.char_id)

        for char in all_chars:
            names = [n.name.strip().lower() for n in char.names]
            if target_name in names:
                if char.parent_pk is not None:
                    matched_ids.append(char.char_id)
                else:
                    matched_ids.append(char.char_id)
                    for child in char.children:
                        v_type = child.version_type
                        if include_alter_egos and v_type == "alter_ego":
                            matched_ids.append(child.char_id)
                        elif include_familiars and v_type == "familiar":
                            matched_ids.append(child.char_id)
                        elif include_npcs and v_type == "npc":
                            matched_ids.append(child.char_id)
                    if include_all_writers and char.group_pk is not None and char.group:
                        for sibling in char.group.characters:
                            matched_ids.append(sibling.char_id)

    seen = set()
    result = []
    for cid in matched_ids:
        if cid not in seen:
            seen.add(cid)
            result.append(cid)
    return result


def merge_characters(backup_id: str, base_path: str, source_id: int, target_id: int) -> None:
    """Merges source character into target character, re-linking scenes and children."""
    require_sqlite_db(base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        source = session.query(CharacterModel).filter(
            CharacterModel.backup_id == str(backup_id),
            CharacterModel.char_id == source_id
        ).first()
        target = session.query(CharacterModel).filter(
            CharacterModel.backup_id == str(backup_id),
            CharacterModel.char_id == target_id
        ).first()

        if not source or not target:
            raise ValueError(f"Source ({source_id}) or target ({target_id}) character not found.")

        # Merge names
        target_name_set = {n.name for n in target.names}
        for n in source.names:
            if n.name not in target_name_set:
                session.add(CharacterNameModel(
                    character_pk=target.pk,
                    name=n.name,
                    position=len(target.names)
                ))
                target_name_set.add(n.name)

        # Inherit writer if target has none
        if not target.writer_pk and source.writer_pk:
            target.writer_pk = source.writer_pk

        # Re-point children of source to target
        for child in source.children:
            child.parent_pk = target.pk

        # Re-point scene participations
        source_participations = session.query(SceneParticipantModel).filter(
            SceneParticipantModel.character_pk == source.pk
        ).all()

        for sp in source_participations:
            target_in_scene = session.query(SceneParticipantModel).filter(
                SceneParticipantModel.scene_pk == sp.scene_pk,
                SceneParticipantModel.character_pk == target.pk
            ).first()

            if target_in_scene:
                session.delete(sp)
            else:
                sp.character_pk = target.pk

        # Delete source character
        session.delete(source)
        session.flush()

        # Export updated snapshot
        export_character_list_snapshot(session, backup_id, write_to_disk=True)


def nest_character(backup_id: str, base_path: str, child_id: int, parent_id: int, version_type: str = "npc") -> None:
    """Nests child character under parent character."""
    require_sqlite_db(base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        child = session.query(CharacterModel).filter(
            CharacterModel.backup_id == str(backup_id),
            CharacterModel.char_id == child_id
        ).first()
        parent = session.query(CharacterModel).filter(
            CharacterModel.backup_id == str(backup_id),
            CharacterModel.char_id == parent_id
        ).first()

        if not child or not parent:
            raise ValueError("Child or parent character not found")
        if parent.parent_pk is not None:
            raise ValueError("Cannot nest under a character that is already nested (max 1 level depth)")
        if child.children:
            raise ValueError("Cannot nest a character that has its own children")

        child.parent_pk = parent.pk
        child.version_type = version_type
        child.group_pk = None
        session.flush()

        export_character_list_snapshot(session, backup_id, write_to_disk=True)


def unnest_character(backup_id: str, base_path: str, char_id: int) -> None:
    """Moves nested character to the root level."""
    require_sqlite_db(base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        child = session.query(CharacterModel).filter(
            CharacterModel.backup_id == str(backup_id),
            CharacterModel.char_id == char_id
        ).first()

        if not child:
            raise ValueError("Character not found")
        if child.parent_pk is None:
            raise ValueError("Character is already at root level")

        child.parent_pk = None
        child.version_type = None
        session.flush()

        export_character_list_snapshot(session, backup_id, write_to_disk=True)


def update_character(
    backup_id: str,
    base_path: str,
    char_id: int,
    names: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    writer: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Updates character attributes (names, tags, writer) in SQLite and exports snapshot."""
    require_sqlite_db(base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        char = session.query(CharacterModel).filter(
            CharacterModel.backup_id == str(backup_id),
            CharacterModel.char_id == char_id
        ).first()

        if not char:
            raise ValueError(f"Character {char_id} not found")

        if names is not None:
            session.query(CharacterNameModel).filter(
                CharacterNameModel.character_pk == char.pk
            ).delete()
            for pos, n in enumerate(names):
                session.add(CharacterNameModel(character_pk=char.pk, name=n, position=pos))

        if tags is not None:
            char.origin = "canon" if "canon" in tags else "oc"
            char.activity = "active" if "active" in tags else "inactive"
            vt_match = None
            for vt in ("alter_ego", "npc", "familiar"):
                if vt in tags:
                    vt_match = vt
                    break
            if char.parent_pk is not None:
                char.version_type = vt_match or "alter_ego"
            else:
                char.version_type = vt_match

        if writer is not None:
            w_list = writer if isinstance(writer, list) else [writer]
            cleaned_w = [w.strip() for w in w_list if w and w.strip()]
            if cleaned_w:
                primary_w = cleaned_w[0]
                w_lower = [w.lower() for w in cleaned_w]

                w_model = session.query(WriterModel).outerjoin(WriterAliasModel).filter(
                    WriterModel.backup_id == str(backup_id),
                    or_(
                        func.lower(WriterModel.display_name).in_(w_lower),
                        func.lower(WriterAliasModel.alias).in_(w_lower)
                    )
                ).first()

                if not w_model:
                    w_model = WriterModel(
                        backup_id=str(backup_id),
                        display_name=primary_w
                    )
                    session.add(w_model)
                    session.flush()
                    for alias_name in cleaned_w:
                        session.add(WriterAliasModel(writer_pk=w_model.pk, alias=alias_name))

                char.writer_pk = w_model.pk
            else:
                char.writer_pk = None

        session.flush()
        export_character_list_snapshot(session, backup_id, write_to_disk=True)

        char_names = [n.name for n in sorted(char.names, key=lambda x: x.position)]
        char_writer = []
        if char.writer:
            char_writer.append(char.writer.display_name)
            for a in char.writer.aliases:
                if a.alias not in char_writer:
                    char_writer.append(a.alias)

        result_tags = []
        if char.origin: result_tags.append(char.origin)
        if char.activity: result_tags.append(char.activity)
        if char.version_type: result_tags.append(char.version_type)
        if char.group_pk: result_tags.append("has_other_writers")

        return {
            "id": char.char_id,
            "names": char_names,
            "writer": char_writer,
            "tags": result_tags,
            "other_versions": [],
        }


def get_writers(backup_id: str, base_path: str) -> List[str]:
    """Retrieves all distinct writer names and aliases."""
    require_sqlite_db(base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        writers = session.query(WriterModel).filter(
            WriterModel.backup_id == str(backup_id)
        ).all()

        distinct_writers = set()
        for w in writers:
            distinct_writers.add(w.display_name)
            for a in w.aliases:
                distinct_writers.add(a.alias)
        return sorted(list(distinct_writers))


def get_groups(backup_id: str, base_path: str) -> List[Dict[str, Any]]:
    """Retrieves all character groups for the backup."""
    require_sqlite_db(base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        groups = session.query(CharacterGroupModel).filter(
            CharacterGroupModel.backup_id == str(backup_id)
        ).order_by(CharacterGroupModel.pk).all()

        results = []
        for g in groups:
            results.append({
                "id": g.pk,
                "names": [n.name for n in sorted(g.names, key=lambda x: x.position)],
                "members": [c.char_id for c in sorted(g.characters, key=lambda x: x.char_id)],
            })
        return results


def create_group(backup_id: str, base_path: str, names: List[str], member_ids: List[int]) -> Dict[str, Any]:
    """Creates a character group and associates member characters."""
    require_sqlite_db(base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        group = CharacterGroupModel(backup_id=str(backup_id))
        session.add(group)
        session.flush()

        for pos, name in enumerate(names):
            session.add(GroupNameModel(group_pk=group.pk, name=name, position=pos))

        for cid in member_ids:
            char = session.query(CharacterModel).filter(
                CharacterModel.backup_id == str(backup_id),
                CharacterModel.char_id == cid
            ).first()
            if char:
                char.group_pk = group.pk
                char.parent_pk = None

        session.flush()
        export_character_list_snapshot(session, backup_id, write_to_disk=True)
        return {
            "id": group.pk,
            "names": names,
            "members": member_ids,
        }


def update_group(
    backup_id: str,
    base_path: str,
    group_id: int,
    names: Optional[List[str]] = None,
    member_ids: Optional[List[int]] = None
) -> Dict[str, Any]:
    """Updates group names or associated member characters."""
    require_sqlite_db(base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        group = session.query(CharacterGroupModel).filter(
            CharacterGroupModel.pk == group_id,
            CharacterGroupModel.backup_id == str(backup_id)
        ).first()

        if not group:
            raise ValueError(f"Group {group_id} not found.")

        if names is not None:
            session.query(GroupNameModel).filter(GroupNameModel.group_pk == group.pk).delete()
            for pos, name in enumerate(names):
                session.add(GroupNameModel(group_pk=group.pk, name=name, position=pos))

        if member_ids is not None:
            session.query(CharacterModel).filter(
                CharacterModel.group_pk == group.pk
            ).update({"group_pk": None})

            for cid in member_ids:
                char = session.query(CharacterModel).filter(
                    CharacterModel.backup_id == str(backup_id),
                    CharacterModel.char_id == cid
                ).first()
                if char:
                    char.group_pk = group.pk
                    char.parent_pk = None

        session.flush()
        export_character_list_snapshot(session, backup_id, write_to_disk=True)
        return {"status": "success"}

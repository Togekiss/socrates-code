import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import BigInteger, func, case, cast, and_, or_, select
from sqlalchemy.orm import selectinload, joinedload

import re
from db.models import (
    BackupModel,
    ChannelModel,
    EventModel,
    CharacterNameModel,
    CharacterGroupModel,
    CharacterModel,
    FlaggedMessageModel,
    IssueKind,
    IssueReason,
    IssueResolution,
    FlaggedKind,
    FlaggedResolution,
    SceneIssueModel,
    SceneKind,
    SceneModel,
    SceneParticipantModel,
    SceneStatus,
    SeenDiscordUserModel,
    WriterAliasModel,
    WriterModel,
    get_default_resolution,
    is_action_performed,
)
from db.session import db_session, require_db, init_db, skeleton_db_session, has_skeleton_db
from db.skeleton_models import (
    MessageSkeletonModel,
    SkeletonFlags,
    compute_skeleton_flags,
)
from db.scene_service import (
    assign_channel_scene_keys,
    snowflake_int,
    resolve_effective_skeleton,
    load_channel_skeletons,
    compute_scene_counts_from_skeletons,
    fetch_message_excerpt,
)
from db.snapshots import export_character_list_snapshot, export_curation_snapshots
from db.event_service import update_event_metadata, merge_events, split_event
from db.character_service import get_character_activity_stats
from find_character_scenes import MENTION_ONLY_PAT, EXCERPT_MAX_LEN, has_end_tag
from utils import exceptions as exc
import utils.tricks as t


def _load_skeletons_or_json_fallback(
    backup_id: str,
    base_path: str,
    channel: ChannelModel,
    start_message_id: Optional[Any] = None,
    end_message_id: Optional[Any] = None,
) -> List[Any]:
    """
    Loads skeletons from skeletons.sqlite; falls back to in-memory skeleton objects
    constructed from Data/<channel.path> only when skeletons.sqlite has no rows for the channel.
    """
    rows = load_channel_skeletons(
        backup_id,
        base_path,
        channel.discord_id,
        start_message_id=start_message_id,
        end_message_id=end_message_id,
    )
    if rows:
        return rows

    if channel.path and base_path:
        c_path = Path(channel.path)
        for f_path in (Path(base_path) / c_path, Path(base_path) / "Data" / c_path):
            if f_path.exists():
                chan_data = t.load_from_json(f_path.as_posix())
                raw_msgs = chan_data.get("messages", [])
                start_sf = snowflake_int(start_message_id) if start_message_id is not None else None
                end_sf = snowflake_int(end_message_id) if end_message_id is not None else None
                fallback_rows = []
                for m in raw_msgs:
                    mid_str = str(m.get("id", ""))
                    if not mid_str.isdigit():
                        continue
                    mid_int = int(mid_str)
                    if start_sf is not None and mid_int < start_sf:
                        continue
                    if end_sf is not None and mid_int > end_sf:
                        continue
                    aid = t.get_author_id(m) or 0
                    dt = t.parse_datetime(m.get("timestamp"))
                    fallback_rows.append(
                        MessageSkeletonModel(
                            channel_discord_id=int(channel.discord_id) if str(channel.discord_id).isdigit() else 0,
                            message_id=mid_int,
                            author_id=int(aid),
                            timestamp_unix=int(dt.timestamp()) if dt else 0,
                            flags=compute_skeleton_flags(m, author_id=int(aid)),
                        )
                    )
                fallback_rows.sort(key=lambda r: int(r.message_id))
                return fallback_rows
    return []


_parse_dt = t.parse_datetime


# --- WRITERS MANAGEMENT ---


def get_writers_detailed(backup_id: str, base_path: str) -> List[Dict[str, Any]]:
    """Retrieves all writers with their aliases, discord_user_id, and written characters."""
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        writers = (
            session.query(WriterModel)
            .options(
                selectinload(WriterModel.aliases),
                selectinload(WriterModel.characters).selectinload(CharacterModel.names),
            )
            .filter(WriterModel.backup_id == str(backup_id))
            .order_by(WriterModel.display_name)
            .all()
        )

        result = []
        for w in writers:
            aliases = [a.alias for a in sorted(w.aliases, key=lambda x: x.pk)]
            chars = []
            for c in w.characters:
                c_names = [n.name for n in sorted(c.names, key=lambda x: x.position)]
                chars.append({
                    "id": c.char_id,
                    "name": c_names[0] if c_names else f"Character #{c.char_id}",
                    "names": c_names,
                    "origin": c.origin,
                    "activity": c.activity,
                })
            result.append({
                "id": w.pk,
                "display_name": w.display_name,
                "discord_user_id": w.discord_user_id,
                "aliases": aliases,
                "character_count": len(chars),
                "characters": chars,
            })
        return result


def create_writer(
    backup_id: str,
    base_path: str,
    display_name: str,
    aliases: Optional[List[str]] = None,
    discord_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates a new writer and associated aliases."""
    if not display_name or not display_name.strip():
        raise ValueError("Writer display name cannot be empty.")

    clean_name = display_name.strip()
    clean_uid = discord_user_id.strip() if discord_user_id and discord_user_id.strip() else None

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        # Check duplicate display name
        existing = (
            session.query(WriterModel)
            .filter(
                WriterModel.backup_id == str(backup_id),
                func.lower(WriterModel.display_name) == clean_name.lower(),
            )
            .first()
        )
        if existing:
            raise ValueError(f"Writer '{clean_name}' already exists.")

        writer = WriterModel(
            backup_id=str(backup_id),
            display_name=clean_name,
            discord_user_id=clean_uid,
        )
        session.add(writer)
        session.flush()

        alias_set = {clean_name}
        if aliases:
            for a in aliases:
                if a and a.strip():
                    alias_set.add(a.strip())

        for a in alias_set:
            session.add(WriterAliasModel(writer_pk=writer.pk, alias=a))

        session.flush()
        export_character_list_snapshot(session, backup_id, write_to_disk=True)

        return {
            "id": writer.pk,
            "display_name": writer.display_name,
            "discord_user_id": writer.discord_user_id,
            "aliases": sorted(list(alias_set)),
            "character_count": 0,
            "characters": [],
        }


def update_writer(
    backup_id: str,
    base_path: str,
    writer_id: int,
    display_name: Optional[str] = None,
    aliases: Optional[List[str]] = None,
    discord_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Updates a writer's display name, aliases, or discord_user_id."""
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        writer = (
            session.query(WriterModel)
            .filter(
                WriterModel.pk == writer_id,
                WriterModel.backup_id == str(backup_id),
            )
            .first()
        )
        if not writer:
            raise ValueError(f"Writer #{writer_id} not found.")

        if display_name is not None and display_name.strip():
            writer.display_name = display_name.strip()

        if discord_user_id is not None:
            clean_uid = discord_user_id.strip() if discord_user_id.strip() else None
            # Check unique constraint on discord_user_id
            if clean_uid:
                clash = (
                    session.query(WriterModel)
                    .filter(
                        WriterModel.backup_id == str(backup_id),
                        WriterModel.discord_user_id == clean_uid,
                        WriterModel.pk != writer_id,
                    )
                    .first()
                )
                if clash:
                    raise ValueError(
                        f"Discord ID '{clean_uid}' is already linked to writer '{clash.display_name}'."
                    )
            writer.discord_user_id = clean_uid

        if aliases is not None:
            session.query(WriterAliasModel).filter(
                WriterAliasModel.writer_pk == writer.pk
            ).delete()
            alias_set = {writer.display_name}
            for a in aliases:
                if a and a.strip():
                    alias_set.add(a.strip())
            for a in alias_set:
                session.add(WriterAliasModel(writer_pk=writer.pk, alias=a))

        session.flush()
        export_character_list_snapshot(session, backup_id, write_to_disk=True)

        res_aliases = [a.alias for a in sorted(writer.aliases, key=lambda x: x.pk)]
        return {
            "id": writer.pk,
            "display_name": writer.display_name,
            "discord_user_id": writer.discord_user_id,
            "aliases": res_aliases,
            "character_count": len(writer.characters),
        }


def delete_writer(backup_id: str, base_path: str, writer_id: int) -> Dict[str, Any]:
    """Deletes a writer and disassociates its characters."""
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        writer = (
            session.query(WriterModel)
            .filter(
                WriterModel.pk == writer_id,
                WriterModel.backup_id == str(backup_id),
            )
            .first()
        )
        if not writer:
            raise ValueError(f"Writer #{writer_id} not found.")

        # Disassociate characters
        session.query(CharacterModel).filter(
            CharacterModel.writer_pk == writer.pk
        ).update({"writer_pk": None})

        session.delete(writer)
        session.flush()
        export_character_list_snapshot(session, backup_id, write_to_disk=True)

        return {"status": "success", "deleted_writer_id": writer_id}


def get_writer_link_suggestions(backup_id: str, base_path: str) -> List[Dict[str, Any]]:
    """Returns heuristic suggestions for linking Discord user IDs to unlinked writers."""
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    try:
        from find_writer_links import find_writer_link_suggestions
        return find_writer_link_suggestions(backup_id, base_path)
    except ImportError:
        return []


def get_seen_discord_users(backup_id: str, base_path: str) -> List[Dict[str, Any]]:
    """Returns all recorded Discord users for a backup with any currently linked writer info."""
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        seen_users = (
            session.query(SeenDiscordUserModel)
            .filter(SeenDiscordUserModel.backup_id == str(backup_id))
            .order_by(
                func.lower(SeenDiscordUserModel.username).asc(),
                SeenDiscordUserModel.discord_user_id.asc(),
            )
            .all()
        )
        linked_writers = (
            session.query(WriterModel.pk, WriterModel.display_name, WriterModel.discord_user_id)
            .filter(
                WriterModel.backup_id == str(backup_id),
                WriterModel.discord_user_id.isnot(None),
            )
            .all()
        )
        writer_by_uid: Dict[str, Tuple[int, str]] = {
            str(w.discord_user_id).strip(): (w.pk, w.display_name)
            for w in linked_writers
            if w.discord_user_id and str(w.discord_user_id).strip()
        }

        result: List[Dict[str, Any]] = []
        for u in seen_users:
            uid = str(u.discord_user_id).strip()
            linked_w = writer_by_uid.get(uid)
            result.append({
                "discord_user_id": uid,
                "username": u.username,
                "global_name": u.global_name,
                "nickname": u.nickname,
                "is_current_member": bool(u.is_current_member),
                "message_count": int(u.message_count or 0),
                "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
                "linked_writer_id": linked_w[0] if linked_w else None,
                "linked_writer_name": linked_w[1] if linked_w else None,
            })
        return result


def accept_all_writer_link_suggestions(backup_id: str, base_path: str) -> Dict[str, Any]:
    """Accepts all non-conflicting heuristic Discord link suggestions in confidence order."""
    suggestions = get_writer_link_suggestions(backup_id, base_path)
    if not suggestions:
        return {"status": "success", "linked_count": 0, "skipped_count": 0, "linked": []}

    linked: List[Dict[str, Any]] = []
    skipped_count = 0

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        writers = (
            session.query(WriterModel)
            .filter(WriterModel.backup_id == str(backup_id))
            .all()
        )
        writers_by_pk = {w.pk: w for w in writers}
        used_discord_ids: Set[str] = {
            str(w.discord_user_id).strip()
            for w in writers
            if w.discord_user_id and str(w.discord_user_id).strip()
        }

        for sugg in suggestions:
            raw_wpk = sugg.get("writer_id") if sugg.get("writer_id") is not None else sugg.get("writer_pk")
            discord_id = str(
                sugg.get("suggested_discord_id") or sugg.get("suggested_discord_user_id") or ""
            ).strip()
            try:
                writer_pk = int(raw_wpk) if raw_wpk is not None else None
            except (TypeError, ValueError):
                writer_pk = None

            writer = writers_by_pk.get(writer_pk) if writer_pk is not None else None
            if (
                writer is None
                or (writer.discord_user_id and str(writer.discord_user_id).strip())
                or not discord_id
                or discord_id in used_discord_ids
            ):
                skipped_count += 1
                continue

            writer.discord_user_id = discord_id
            used_discord_ids.add(discord_id)
            linked.append({
                "writer_id": writer.pk,
                "display_name": writer.display_name,
                "discord_user_id": discord_id,
            })

        if linked:
            session.flush()
            export_character_list_snapshot(session, backup_id, write_to_disk=True)

    return {
        "status": "success",
        "linked_count": len(linked),
        "skipped_count": skipped_count,
        "linked": linked,
    }


def _unique_writer_display_name(
    base_name: str,
    discord_user_id: str,
    taken_names_lower: Set[str],
) -> str:
    """Returns a display_name <= 64 chars not already present in taken_names_lower."""
    candidate = base_name.strip()[:64] or f"User #{discord_user_id}"[:64]
    if candidate.lower() not in taken_names_lower:
        return candidate
    suffix = f" ({discord_user_id})"
    tagged = f"{candidate[: max(1, 64 - len(suffix))]}{suffix}"
    if tagged.lower() not in taken_names_lower:
        return tagged
    counter = 2
    while True:
        c_suffix = f" ({discord_user_id}-{counter})"
        numbered = f"{candidate[: max(1, 64 - len(c_suffix))]}{c_suffix}"
        if numbered.lower() not in taken_names_lower:
            return numbered
        counter += 1


def create_writers_from_seen_discord_users(backup_id: str, base_path: str) -> Dict[str, Any]:
    """
    Creates Writer profiles for every seen Discord user who is neither linked to an
    existing writer nor targeted by an active writer link suggestion.
    """
    suggestions = get_writer_link_suggestions(backup_id, base_path)
    suggested_discord_ids: Set[str] = {
        str(s.get("suggested_discord_id") or s.get("suggested_discord_user_id") or "").strip()
        for s in suggestions
    }
    suggested_discord_ids.discard("")

    created: List[Dict[str, Any]] = []

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        existing_writers = (
            session.query(WriterModel)
            .filter(WriterModel.backup_id == str(backup_id))
            .all()
        )
        linked_discord_ids: Set[str] = {
            str(w.discord_user_id).strip()
            for w in existing_writers
            if w.discord_user_id and str(w.discord_user_id).strip()
        }
        taken_names_lower: Set[str] = {
            w.display_name.strip().lower()
            for w in existing_writers
            if w.display_name and w.display_name.strip()
        }

        seen_users = (
            session.query(SeenDiscordUserModel)
            .filter(SeenDiscordUserModel.backup_id == str(backup_id))
            .order_by(
                func.lower(SeenDiscordUserModel.username).asc(),
                SeenDiscordUserModel.discord_user_id.asc(),
            )
            .all()
        )

        for u in seen_users:
            uid = str(u.discord_user_id or "").strip()
            if not uid or uid in linked_discord_ids or uid in suggested_discord_ids:
                continue

            raw_username = (u.username or "").strip() or f"User #{uid}"
            display_name = _unique_writer_display_name(raw_username, uid, taken_names_lower)
            taken_names_lower.add(display_name.lower())
            linked_discord_ids.add(uid)

            writer = WriterModel(
                backup_id=str(backup_id),
                display_name=display_name,
                discord_user_id=uid,
            )
            session.add(writer)
            session.flush()

            alias_set: Set[str] = {display_name}
            for raw_alias in (u.global_name, u.nickname):
                if raw_alias and str(raw_alias).strip():
                    alias_set.add(str(raw_alias).strip()[:64])

            sorted_aliases = sorted(alias_set)
            for alias_str in sorted_aliases:
                session.add(WriterAliasModel(writer_pk=writer.pk, alias=alias_str))

            created.append({
                "id": writer.pk,
                "display_name": writer.display_name,
                "discord_user_id": writer.discord_user_id,
                "aliases": sorted_aliases,
                "character_count": 0,
                "characters": [],
            })

        if created:
            session.flush()
            export_character_list_snapshot(session, backup_id, write_to_disk=True)

    return {
        "status": "success",
        "created_count": len(created),
        "writers": created,
    }


# --- UNASSIGNED CHARACTERS QUEUE ---


def get_unassigned_characters(backup_id: str, base_path: str) -> List[Dict[str, Any]]:
    """Retrieves characters that currently have no writer assigned (writer_pk IS NULL)."""
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        stats_by_pk, _ = get_character_activity_stats(session, backup_id)
        chars = (
            session.query(CharacterModel)
            .options(
                selectinload(CharacterModel.names),
                joinedload(CharacterModel.parent),
            )
            .filter(
                CharacterModel.backup_id == str(backup_id),
                CharacterModel.writer_pk.is_(None),
            )
            .order_by(CharacterModel.char_id)
            .all()
        )

        result = []
        for c in chars:
            c_names = [n.name for n in sorted(c.names, key=lambda x: x.position)]
            st = stats_by_pk.get(c.pk, {"scene_count": 0, "last_active_at": None, "last_channel_name": None})
            result.append({
                "id": c.char_id,
                "names": c_names,
                "origin": c.origin,
                "activity": c.activity,
                "version_type": c.version_type,
                "group_id": c.group_pk,
                "parent_id": c.parent.char_id if c.parent else None,
                "scene_count": st["scene_count"],
                "last_active_at": st["last_active_at"],
                "last_channel_name": st["last_channel_name"],
            })
        return result


def assign_character_writer(
    backup_id: str, base_path: str, char_id: int, writer_id: int
) -> Dict[str, Any]:
    """Assigns an unassigned character to a writer."""
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        char = (
            session.query(CharacterModel)
            .filter(
                CharacterModel.backup_id == str(backup_id),
                CharacterModel.char_id == char_id,
            )
            .first()
        )
        if not char:
            raise ValueError(f"Character #{char_id} not found.")

        writer = (
            session.query(WriterModel)
            .filter(
                WriterModel.backup_id == str(backup_id),
                WriterModel.pk == writer_id,
            )
            .first()
        )
        if not writer:
            raise ValueError(f"Writer #{writer_id} not found.")

        char.writer_pk = writer.pk
        session.flush()
        export_character_list_snapshot(session, backup_id, write_to_disk=True)

        return {
            "status": "success",
            "char_id": char.char_id,
            "writer_id": writer.pk,
            "writer_display_name": writer.display_name,
        }


# --- CHARACTER GROUPS MANAGEMENT ---


def delete_group(backup_id: str, base_path: str, group_id: int) -> Dict[str, Any]:
    """Deletes a character group and disassociates member characters."""
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        group = (
            session.query(CharacterGroupModel)
            .filter(
                CharacterGroupModel.pk == group_id,
                CharacterGroupModel.backup_id == str(backup_id),
            )
            .first()
        )
        if not group:
            raise ValueError(f"Character group #{group_id} not found.")

        # Disassociate characters
        session.query(CharacterModel).filter(
            CharacterModel.group_pk == group.pk
        ).update({"group_pk": None})

        session.delete(group)
        session.flush()
        export_character_list_snapshot(session, backup_id, write_to_disk=True)

        return {"status": "success", "deleted_group_id": group_id}


# --- SCENE ISSUES REVIEW QUEUE ---


def get_scene_issues(
    backup_id: str,
    base_path: str,
    kind: Optional[str] = None,
    reason: Optional[str] = None,
    status: Optional[str] = "unresolved",
    channel_id: Optional[str] = None,
    scene_type: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> Dict[str, Any]:
    """Queries scene issues with filtering by kind, resolution status, and channel."""
    if not isinstance(kind, str):
        kind = None
    if not isinstance(reason, str):
        reason = None
    if not isinstance(status, str):
        status = "unresolved"
    if not isinstance(channel_id, str):
        channel_id = None
    if not isinstance(scene_type, str) or not scene_type.strip():
        scene_type = None
    if not isinstance(page, int) or page < 1:
        page = 1
    if not isinstance(per_page, int) or per_page < 1:
        per_page = 50
    per_page = min(per_page, 200)

    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
        server_id = backup.server_id if backup else ""

        query = (
            session.query(SceneIssueModel)
            .outerjoin(SceneModel, SceneIssueModel.scene_pk == SceneModel.pk)
            .options(
                joinedload(SceneIssueModel.scene).joinedload(SceneModel.channel),
                joinedload(SceneIssueModel.next_scene),
            )
        )
        query = query.filter(SceneIssueModel.backup_id == str(backup_id))

        # TODO: Should not happen after migration
        if kind == "possible_split":
            kind = IssueKind.SOFT_BOUNDARY.value
        if kind:
            query = query.filter(SceneIssueModel.kind == kind)
        if reason:
            query = query.filter(SceneIssueModel.reason == reason)
        if scene_type:
            query = query.filter(SceneModel.kind == scene_type)

        if status == "unresolved":
            query = query.filter(SceneIssueModel.resolved_at.is_(None))
        elif status == "resolved":
            query = query.filter(SceneIssueModel.resolved_at.isnot(None))

        if channel_id:
            query = query.join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
            query = query.filter(ChannelModel.discord_id == str(channel_id))

        total_items = query.count()

        # Compute status counts for the review queue
        counts_query = session.query(
            func.count(SceneIssueModel.pk).label("total"),
            func.coalesce(func.sum(case((SceneIssueModel.resolved_at.is_(None), 1), else_=0)), 0).label("unresolved"),
            func.coalesce(func.sum(case((SceneIssueModel.resolved_at.isnot(None), 1), else_=0)), 0).label("resolved"),
        ).filter(SceneIssueModel.backup_id == str(backup_id))

        if kind:
            counts_query = counts_query.filter(SceneIssueModel.kind == kind)
        if reason:
            counts_query = counts_query.filter(SceneIssueModel.reason == reason)
        if scene_type or channel_id:
            counts_query = counts_query.join(SceneModel, SceneIssueModel.scene_pk == SceneModel.pk)
            if scene_type:
                counts_query = counts_query.filter(SceneModel.kind == scene_type)
            if channel_id:
                counts_query = counts_query.join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
                counts_query = counts_query.filter(ChannelModel.discord_id == str(channel_id))

        counts_row = counts_query.first()
        status_counts = {
            "all": int(counts_row.total) if counts_row and counts_row.total is not None else 0,
            "unresolved": int(counts_row.unresolved) if counts_row and counts_row.unresolved is not None else 0,
            "resolved": int(counts_row.resolved) if counts_row and counts_row.resolved is not None else 0,
        }

        # Compute scope counts filtered by status, kind, reason, channel_id
        scope_query = (
            session.query(
                func.count(SceneIssueModel.pk).label("all_count"),
                func.coalesce(func.sum(case((SceneModel.kind == SceneKind.SCENE.value, 1), else_=0)), 0).label("scene_count"),
                func.coalesce(func.sum(case((SceneModel.kind == SceneKind.SESSION.value, 1), else_=0)), 0).label("session_count"),
                func.coalesce(func.sum(case((SceneModel.kind == SceneKind.EVENT.value, 1), else_=0)), 0).label("event_count"),
            )
            .outerjoin(SceneModel, SceneIssueModel.scene_pk == SceneModel.pk)
            .filter(SceneIssueModel.backup_id == str(backup_id))
        )
        if status == "unresolved":
            scope_query = scope_query.filter(SceneIssueModel.resolved_at.is_(None))
        elif status == "resolved":
            scope_query = scope_query.filter(SceneIssueModel.resolved_at.isnot(None))

        if kind:
            scope_query = scope_query.filter(SceneIssueModel.kind == kind)
        if reason:
            scope_query = scope_query.filter(SceneIssueModel.reason == reason)
        if channel_id:
            scope_query = scope_query.join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
            scope_query = scope_query.filter(ChannelModel.discord_id == str(channel_id))

        scope_row = scope_query.first()
        scope_counts = {
            "all": int(scope_row.all_count) if scope_row and scope_row.all_count is not None else 0,
            "scene": int(scope_row.scene_count) if scope_row and scope_row.scene_count is not None else 0,
            "session": int(scope_row.session_count) if scope_row and scope_row.session_count is not None else 0,
            "event": int(scope_row.event_count) if scope_row and scope_row.event_count is not None else 0,
        }

        query = query.order_by(SceneIssueModel.created_at.desc(), SceneIssueModel.pk.desc())
        offset = (page - 1) * per_page
        issues_raw = query.offset(offset).limit(per_page).all()

        # Collect character IDs to resolve display names
        char_ids = set()
        for iss in issues_raw:
            if iss.previous_chars:
                for cid in iss.previous_chars:
                    if isinstance(cid, int):
                        char_ids.add(cid)
            if iss.next_chars:
                for cid in iss.next_chars:
                    if isinstance(cid, int):
                        char_ids.add(cid)

        char_name_map: Dict[int, str] = {}
        if char_ids:
            chars = (
                session.query(CharacterModel)
                .options(joinedload(CharacterModel.names))
                .filter(
                    CharacterModel.backup_id == str(backup_id),
                    CharacterModel.char_id.in_(char_ids),
                )
                .all()
            )
            for ch in chars:
                sorted_names = sorted(ch.names, key=lambda n: n.position)
                if sorted_names and sorted_names[0].name:
                    char_name_map[ch.char_id] = sorted_names[0].name
                else:
                    char_name_map[ch.char_id] = f"Character #{ch.char_id}"

        # Batch-check IS_DELETED in skeletons.sqlite for candidate messages if present
        deleted_candidate_keys: Set[Tuple[str, str]] = set()
        if issues_raw and has_skeleton_db(base_path, backup_id=backup_id):
            chan_ids_chk = set()
            msg_ids_chk = set()
            for iss in issues_raw:
                ch = iss.scene.channel if iss.scene else None
                if ch and str(ch.discord_id).isdigit() and iss.candidate_message_id and str(iss.candidate_message_id).isdigit():
                    chan_ids_chk.add(int(ch.discord_id))
                    msg_ids_chk.add(int(iss.candidate_message_id))
            if chan_ids_chk and msg_ids_chk:
                try:
                    with skeleton_db_session(backup_id=backup_id, backup_path=base_path) as skel_session:
                        rows = (
                            skel_session.query(
                                MessageSkeletonModel.channel_discord_id,
                                MessageSkeletonModel.message_id,
                                MessageSkeletonModel.flags,
                            )
                            .filter(
                                MessageSkeletonModel.channel_discord_id.in_(chan_ids_chk),
                                MessageSkeletonModel.message_id.in_(msg_ids_chk),
                            )
                            .all()
                        )
                        for ch_id, m_id, fl in rows:
                            if int(fl or 0) & SkeletonFlags.IS_DELETED:
                                deleted_candidate_keys.add((str(ch_id), str(m_id)))
                except Exception:
                    pass

        formatted = []
        for iss in issues_raw:
            scene = iss.scene
            channel = scene.channel if scene else None
            chan_id = channel.discord_id if channel else ""
            chan_name = channel.name if channel else ""
            start_msg_id = scene.start_message_id if scene else ""
            channel_is_deleted = bool(channel and channel.is_deleted)
            candidate_is_deleted = bool(
                iss.candidate_message_id and (chan_id, str(iss.candidate_message_id)) in deleted_candidate_keys
            )

            discord_link = ""
            if server_id and chan_id and start_msg_id:
                discord_link = f"https://discord.com/channels/{server_id}/{chan_id}/{start_msg_id}"

            candidate_discord_link = ""
            if server_id and chan_id and iss.candidate_message_id:
                candidate_discord_link = f"https://discord.com/channels/{server_id}/{chan_id}/{iss.candidate_message_id}"

            prev_ids = iss.previous_chars or []
            next_ids = iss.next_chars or []
            prev_names = [char_name_map.get(cid, f"#{cid}") for cid in prev_ids]
            next_names = [char_name_map.get(cid, f"#{cid}") for cid in next_ids]

            formatted.append({
                "id": iss.pk,
                "kind": iss.kind,
                "reason": iss.reason,
                "scene_pk": scene.pk if scene else None,
                "scene_key": scene.scene_key if scene else "",
                "scene_kind": scene.kind if scene else "scene",
                "channel_name": chan_name,
                "channel_discord_id": chan_id,
                "channel_is_deleted": channel_is_deleted,
                "candidate_is_deleted": candidate_is_deleted,
                "is_deleted": bool(channel_is_deleted or candidate_is_deleted),
                "next_scene_pk": iss.next_scene_pk,
                "next_scene_key": iss.next_scene.scene_key if iss.next_scene else None,
                "candidate_message_id": iss.candidate_message_id,
                "candidate_index": iss.candidate_index,
                "candidate_excerpt": iss.candidate_excerpt,
                "previous_chars": prev_ids,
                "next_chars": next_ids,
                "previous_char_names": prev_names,
                "next_char_names": next_names,
                "action_performed": is_action_performed(iss.kind, iss.resolution),
                "discord_link": discord_link,
                "candidate_discord_link": candidate_discord_link,
                "created_at": iss.created_at.isoformat() if iss.created_at else None,
                "resolved_at": iss.resolved_at.isoformat() if iss.resolved_at else None,
                "resolved_note": iss.resolved_note,
                "resolution": iss.resolution,
            })

        total_pages = math.ceil(total_items / per_page) if per_page > 0 else 1
        return {
            "total_items": total_items,
            "current_page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "status_counts": status_counts,
            "scope_counts": scope_counts,
            "issues": formatted,
        }


def _merge_scenes(
    session,
    backup_id: str,
    base_path: str,
    s1: SceneModel,
    s2: SceneModel,
) -> SceneModel:
    """
    Merges adjacent scenes s1 and s2 in the same channel.
    s1 absorbs s2's end bounds, status and participants; s2 is deleted;
    channel scene keys are renumbered tmp- then 1..N.
    """
    if s1.channel_pk != s2.channel_pk:
        raise exc.ValidationError("Cannot merge scenes belonging to different channels.")

    s1_start_sf = snowflake_int(s1.start_message_id)
    s1_end_sf = snowflake_int(s1.end_message_id)
    s2_start_sf = snowflake_int(s2.start_message_id)
    s2_end_sf = snowflake_int(s2.end_message_id)

    if s2_start_sf <= s1_end_sf:
        raise exc.ValidationError(
            f"Scene 2 (start={s2.start_message_id}) must start after Scene 1 (end={s1.end_message_id})."
        )

    # Adjacency check: verify no other scene in this channel starts between s1 and s2
    intervening = (
        session.query(SceneModel)
        .filter(
            SceneModel.backup_id == str(backup_id),
            SceneModel.channel_pk == s1.channel_pk,
            cast(SceneModel.start_message_id, BigInteger) > s1_end_sf,
            cast(SceneModel.start_message_id, BigInteger) < s2_start_sf,
        )
        .first()
    )
    if intervening:
        raise exc.ValidationError(
            f"Cannot merge non-adjacent scenes: Scene #{intervening.pk} ({intervening.scene_key}) "
            f"starts between Scene {s1.scene_key} and Scene {s2.scene_key}."
        )

    s1_key = s1.scene_key
    s2_key = s2.scene_key

    # Extend s1 bounds and status to cover s2
    s1.end_message_id = s2.end_message_id
    s1.end_index = s2.end_index
    s1.end_at = s2.end_at
    s1.end_author_id = s2.end_author_id
    s1.end_excerpt = s2.end_excerpt
    s1.status = s2.status
    s1.message_count = int(s1.message_count or 0) + int(s2.message_count or 0)

    # Combine participants
    s1_parts = {p.character_pk: p for p in s1.participants}
    for p2 in s2.participants:
        if p2.character_pk in s1_parts:
            p1 = s1_parts[p2.character_pk]
            p1.message_count = int(p1.message_count or 1) + int(p2.message_count or 1)
            if p2.last_at or p2.last_message_id:
                p1.last_message_id = p2.last_message_id
                p1.last_at = p2.last_at
        else:
            new_p = SceneParticipantModel(
                scene_pk=s1.pk,
                character_pk=p2.character_pk,
                position=len(s1_parts),
                message_count=int(p2.message_count or 1),
                first_message_id=p2.first_message_id,
                first_at=p2.first_at,
                last_message_id=p2.last_message_id,
                last_at=p2.last_at,
            )
            session.add(new_p)
            s1_parts[p2.character_pk] = new_p

    session.flush()

    # Re-normalize positions ordered by first_at (or existing position if first_at is None)
    all_merged_parts = session.query(SceneParticipantModel).filter_by(scene_pk=s1.pk).all()
    all_merged_parts.sort(key=lambda p: (p.first_at or datetime.min.replace(tzinfo=timezone.utc), p.position or 0, p.character_pk))
    for pos, p in enumerate(all_merged_parts):
        p.position = pos

    s1_event_pk = s1.event_pk
    s2_event_pk = s2.event_pk

    # Re-link any other issues that were associated with s2 to s1
    session.query(SceneIssueModel).filter(
        SceneIssueModel.backup_id == str(backup_id),
        SceneIssueModel.scene_pk == s2.pk,
    ).update({"scene_pk": s1.pk}, synchronize_session="fetch")

    session.query(SceneIssueModel).filter(
        SceneIssueModel.backup_id == str(backup_id),
        SceneIssueModel.next_scene_pk == s2.pk,
    ).update({"next_scene_pk": s1.pk}, synchronize_session="fetch")

    # Delete s2
    session.delete(s2)
    session.flush()

    # Renumber scene keys and recompute events
    if s1_event_pk is not None:
        from db.models import EventModel
        from db.event_service import _recompute_event_from_scenes

        # Cross-event merge: s2 was from a different event
        if s2_event_pk is not None and s2_event_pk != s1_event_pk:
            ev2 = session.query(EventModel).filter_by(pk=s2_event_pk, backup_id=str(backup_id)).first()
            if ev2:
                ev2_scenes = (
                    session.query(SceneModel)
                    .filter_by(event_pk=ev2.pk, backup_id=str(backup_id))
                    .order_by(SceneModel.start_at, SceneModel.pk)
                    .all()
                )
                if ev2_scenes:
                    for sc in ev2_scenes:
                        sc.scene_key = f"tmp-ev-{sc.pk}"
                    session.flush()
                    for idx, sc in enumerate(ev2_scenes, start=1):
                        sc.scene_key = f"{ev2.event_key}-{idx}"
                    session.flush()
                    _recompute_event_from_scenes(ev2, ev2_scenes)
                    ev2.is_curated = True
                    cleaned_ev2_movements = {}
                    for cid_str, hops in (ev2.character_movements or {}).items():
                        filtered = [h for h in hops if (h.get("scene_id") != s2_key and h.get("scene_key") != s2_key)]
                        if filtered:
                            cleaned_ev2_movements[str(cid_str)] = filtered
                    ev2.character_movements = cleaned_ev2_movements
                else:
                    session.delete(ev2)
                session.flush()

        # Recompute ev1 (s1.event)
        ev1 = session.query(EventModel).filter_by(pk=s1_event_pk, backup_id=str(backup_id)).first()
        if ev1:
            ev1_scenes = (
                session.query(SceneModel)
                .filter_by(event_pk=ev1.pk, backup_id=str(backup_id))
                .order_by(SceneModel.start_at, SceneModel.pk)
                .all()
            )
            for sc in ev1_scenes:
                sc.scene_key = f"tmp-ev-{sc.pk}"
            session.flush()
            for idx, sc in enumerate(ev1_scenes, start=1):
                sc.scene_key = f"{ev1.event_key}-{idx}"
            session.flush()
            _recompute_event_from_scenes(ev1, ev1_scenes)
            ev1.is_curated = True

            updated_ev1_movements = {}
            for cid_str, hops in (ev1.character_movements or {}).items():
                upd_hops = []
                for h in hops:
                    h_copy = dict(h)
                    if h_copy.get("scene_id") == s2_key or h_copy.get("scene_key") == s2_key:
                        h_copy["scene_id"] = s1.scene_key
                        h_copy["scene_key"] = s1.scene_key
                    upd_hops.append(h_copy)
                updated_ev1_movements[str(cid_str)] = upd_hops
            ev1.character_movements = updated_ev1_movements
    else:
        if s2_event_pk is not None:
            from db.models import EventModel
            from db.event_service import _recompute_event_from_scenes
            ev2 = session.query(EventModel).filter_by(pk=s2_event_pk, backup_id=str(backup_id)).first()
            if ev2:
                ev2_scenes = (
                    session.query(SceneModel)
                    .filter_by(event_pk=ev2.pk, backup_id=str(backup_id))
                    .order_by(SceneModel.start_at, SceneModel.pk)
                    .all()
                )
                if ev2_scenes:
                    _recompute_event_from_scenes(ev2, ev2_scenes)
                    ev2.is_curated = True
                else:
                    session.delete(ev2)
                session.flush()

        channel_scenes = (
            session.query(SceneModel)
            .filter(
                SceneModel.channel_pk == s1.channel_pk,
                SceneModel.backup_id == str(backup_id),
            )
            .order_by(cast(SceneModel.start_message_id, BigInteger).asc(), SceneModel.start_at.asc())
            .all()
        )
        key_prefix = s1_key.rsplit("-", 1)[0]
        assign_channel_scene_keys(
            session,
            str(backup_id),
            int(s1.channel_pk),
            key_prefix,
            channel_scenes=channel_scenes,
        )

    # Clear SceneManager cache
    try:
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
    except Exception as e:
        t.log("error", f"SceneManager clear_cache error: {e}")

    return s1


def _split_scene_at(
    session,
    backup_id: str,
    base_path: str,
    scene: SceneModel,
    candidate_message_id: Optional[str] = None,
    candidate_index: Optional[int] = None,
    exclude_issue_pk: Optional[int] = None,
) -> Tuple[SceneModel, SceneModel]:
    """
    Splits scene into two scenes at candidate_message_id using skeletons.sqlite + Snowflake bounds.
    The left half (scene) always receives status "no_end_tag".
    The right half (scene2) inherits the original scene's end bounds and status.
    Participants are partitioned, counts recomputed, other issues re-linked, and channel keys renumbered.
    Returns (scene, scene2).
    """
    channel = scene.channel
    if not channel:
        raise exc.NotFoundError(f"Channel for scene #{scene.pk} not found in database.")

    scene_start_sf = snowflake_int(scene.start_message_id)
    scene_end_sf = snowflake_int(scene.end_message_id)

    # Validate explicit candidate Snowflake against scene bounds BEFORE querying bounded skeletons,
    # so out-of-range message IDs consistently raise ValidationError (HTTP 400) rather than NotFoundError (404).
    if candidate_message_id and str(candidate_message_id).isdigit():
        cand_sf_pre = int(candidate_message_id)
        if cand_sf_pre <= scene_start_sf or cand_sf_pre > scene_end_sf:
            raise exc.ValidationError(
                f"Candidate split point {cand_sf_pre} is outside Scene boundaries ({scene.start_message_id}..{scene.end_message_id})."
            )

    # Load channel skeletons (bounded to scene if candidate_message_id is provided, else full channel for index fallback)
    if candidate_message_id and str(candidate_message_id).isdigit():
        skeletons = _load_skeletons_or_json_fallback(
            backup_id,
            base_path,
            channel,
            start_message_id=scene.start_message_id,
            end_message_id=scene.end_message_id,
        )
    else:
        skeletons = _load_skeletons_or_json_fallback(backup_id, base_path, channel)

    if not skeletons:
        raise exc.NotFoundError(f"Channel skeletons not found for channel #{channel.discord_id}")

    cand_pos = None
    cand_sk = None
    if candidate_message_id and str(candidate_message_id).isdigit():
        target_mid_int = int(candidate_message_id)
        for idx, sk in enumerate(skeletons):
            if int(sk.message_id) == target_mid_int:
                cand_pos = idx
                cand_sk = sk
                break
    elif candidate_index is not None and 0 <= int(candidate_index) < len(skeletons):
        cand_pos = int(candidate_index)
        cand_sk = skeletons[cand_pos]

    if cand_sk is None or cand_pos is None:
        raise exc.NotFoundError(
            f"Candidate message {candidate_message_id or candidate_index} not found in channel skeletons."
        )

    cand_sf = int(cand_sk.message_id)
    if cand_sf <= scene_start_sf or cand_sf > scene_end_sf:
        raise exc.ValidationError(
            f"Candidate split point {cand_sf} is outside Scene boundaries ({scene.start_message_id}..{scene.end_message_id})."
        )

    resolved_flags = get_resolved_flags_map(backup_id, base_path, session=session)

    # Find prev_sk: last valid Default non-mention-only non-ignored message before cand_sf within scene bounds
    prev_sk = None
    prev_eff = None
    prev_pos = None
    for i in range(cand_pos - 1, -1, -1):
        sk = skeletons[i]
        if int(sk.message_id) < scene_start_sf:
            break
        eff = resolve_effective_skeleton(sk, resolved_flags_map=resolved_flags)
        if eff and eff["is_valid"]:
            prev_sk = sk
            prev_eff = eff
            prev_pos = i
            break
    if prev_sk is None:
        if cand_pos == 0:
            raise exc.ValidationError("No preceding message found before split point.")
        prev_pos = cand_pos - 1
        prev_sk = skeletons[prev_pos]
        prev_eff = resolve_effective_skeleton(prev_sk, resolved_flags_map=resolved_flags)

    cand_eff = resolve_effective_skeleton(cand_sk, resolved_flags_map=resolved_flags)

    orig_end_msg_id = scene.end_message_id
    orig_end_index = scene.end_index
    orig_end_at = scene.end_at
    orig_end_author_id = scene.end_author_id
    orig_end_excerpt = scene.end_excerpt
    orig_status = scene.status
    orig_scene_key = scene.scene_key

    prev_msg_id = str(prev_sk.message_id)
    cand_msg_id = str(cand_sk.message_id)

    # Hydrate excerpts from FlaggedMessageModel -> local JSON (if present) -> extensible hook -> None
    flagged_rows = (
        session.query(FlaggedMessageModel)
        .filter(
            FlaggedMessageModel.backup_id == str(backup_id),
            FlaggedMessageModel.message_id.in_([prev_msg_id, cand_msg_id]),
        )
        .all()
    )
    flagged_content_map: Dict[str, str] = {}
    for fr in flagged_rows:
        if fr.resolution == FlaggedResolution.OVERRIDE.value and fr.override_content is not None:
            flagged_content_map[str(fr.message_id)] = fr.override_content
        else:
            flagged_content_map[str(fr.message_id)] = fr.content

    prev_excerpt = fetch_message_excerpt(
        backup_id, base_path, channel, prev_msg_id, flagged_content_map=flagged_content_map
    )
    cand_excerpt = fetch_message_excerpt(
        backup_id, base_path, channel, cand_msg_id, flagged_content_map=flagged_content_map
    )

    prev_idx_val = (scene.start_index or 0) + prev_pos if len(skeletons) == 0 or int(skeletons[0].message_id) >= scene_start_sf else prev_pos
    cand_idx_val = (scene.start_index or 0) + cand_pos if int(skeletons[0].message_id) >= scene_start_sf else cand_pos

    # Partition skeletons into left and right scenes and compute counts + participants
    skels_left = [sk for sk in skeletons if scene_start_sf <= int(sk.message_id) <= int(prev_msg_id)]
    skels_right = [sk for sk in skeletons if cand_sf <= int(sk.message_id) <= scene_end_sf]

    chars = session.query(CharacterModel).filter_by(backup_id=str(backup_id)).all()
    char_id_to_pk = {c.char_id: c.pk for c in chars}

    part1_msg_count, part1_details = compute_scene_counts_from_skeletons(
        skels_left, char_id_to_pk, resolved_flags_map=resolved_flags
    )
    part2_msg_count, part2_details = compute_scene_counts_from_skeletons(
        skels_right, char_id_to_pk, resolved_flags_map=resolved_flags
    )

    # Truncate Scene 1 (left half is ALWAYS "no_end_tag")
    scene.end_message_id = prev_msg_id
    scene.end_index = prev_idx_val
    scene.message_count = part1_msg_count
    scene.end_at = (
        (prev_eff["timestamp_dt"] if prev_eff else None)
        or (datetime.fromtimestamp(int(prev_sk.timestamp_unix), tz=timezone.utc) if prev_sk.timestamp_unix else None)
        or scene.end_at
    )
    scene.end_author_id = str(prev_eff["author_id"] if prev_eff else prev_sk.author_id)
    scene.end_excerpt = prev_excerpt
    scene.status = SceneStatus.NO_END_TAG.value

    cand_author_id = str(cand_eff["author_id"] if cand_eff else cand_sk.author_id)
    cand_at = (
        (cand_eff["timestamp_dt"] if cand_eff else None)
        or (datetime.fromtimestamp(int(cand_sk.timestamp_unix), tz=timezone.utc) if cand_sk.timestamp_unix else None)
        or scene.start_at
    )

    orig_event_pk = scene.event_pk
    new_ev = None
    if orig_event_pk is not None:
        from db.models import EventModel
        from db.event_service import _recompute_event_from_scenes

        orig_ev = session.query(EventModel).filter_by(pk=orig_event_pk, backup_id=str(backup_id)).first()

        existing_keys = [
            r[0] for r in session.query(EventModel.event_key).filter_by(backup_id=str(backup_id)).all()
        ]
        max_idx = 0
        for k in existing_keys:
            if k and k.startswith("ev-"):
                try:
                    num = int(k.split("-")[1])
                    if num > max_idx:
                        max_idx = num
                except (ValueError, IndexError):
                    pass
        new_event_key = f"ev-{max_idx + 1}"

        new_ev = EventModel(
            backup_id=str(backup_id),
            event_key=new_event_key,
            name=None,
            status=orig_status,
            start_at=cand_at,
            end_at=orig_end_at,
            message_count=part2_msg_count,
            is_curated=True,
            character_movements={},
        )
        session.add(new_ev)
        session.flush()
        target_event_pk = new_ev.pk
    else:
        orig_ev = None
        target_event_pk = None

    scene2 = SceneModel(
        backup_id=str(backup_id),
        scene_key="tmp-split-new",
        channel_pk=scene.channel_pk,
        category_pk=scene.category_pk,
        event_pk=target_event_pk,
        custom_name=scene.custom_name,
        kind=scene.kind,
        status=orig_status,
        start_message_id=cand_msg_id,
        end_message_id=orig_end_msg_id,
        start_index=cand_idx_val,
        end_index=orig_end_index,
        message_count=part2_msg_count,
        start_at=cand_at,
        end_at=orig_end_at,
        start_author_id=cand_author_id,
        end_author_id=orig_end_author_id,
        start_excerpt=cand_excerpt,
        end_excerpt=orig_end_excerpt,
    )
    session.add(scene2)
    session.flush()

    session.query(SceneParticipantModel).filter_by(scene_pk=scene.pk).delete()
    session.flush()

    for p_info in part1_details:
        session.add(SceneParticipantModel(
            scene_pk=scene.pk,
            character_pk=p_info["character_pk"],
            position=p_info["position"],
            message_count=p_info["message_count"],
            first_message_id=p_info["first_message_id"],
            first_at=p_info["first_at"],
            last_message_id=p_info["last_message_id"],
            last_at=p_info["last_at"],
        ))

    for p_info in part2_details:
        session.add(SceneParticipantModel(
            scene_pk=scene2.pk,
            character_pk=p_info["character_pk"],
            position=p_info["position"],
            message_count=p_info["message_count"],
            first_message_id=p_info["first_message_id"],
            first_at=p_info["first_at"],
            last_message_id=p_info["last_message_id"],
            last_at=p_info["last_at"],
        ))

    # Renumber scenes (across event if event_pk is set, else within channel)
    if orig_event_pk is not None and new_ev is not None:
        session.flush()
        from db.models import EventModel
        from db.event_service import _recompute_event_from_scenes

        if orig_ev:
            orig_ev_scenes = (
                session.query(SceneModel)
                .filter_by(event_pk=orig_ev.pk, backup_id=str(backup_id))
                .order_by(SceneModel.start_at, SceneModel.pk)
                .all()
            )
            for sc in orig_ev_scenes:
                sc.scene_key = f"tmp-ev-{sc.pk}"
            session.flush()
            for idx, sc in enumerate(orig_ev_scenes, start=1):
                sc.scene_key = f"{orig_ev.event_key}-{idx}"
            session.flush()

            scene2.scene_key = f"{new_ev.event_key}-1"
            session.flush()

            orig_movements: Dict[str, List[Dict[str, Any]]] = {}
            new_movements: Dict[str, List[Dict[str, Any]]] = {}
            chan_id_str = str(channel.discord_id if channel else scene.channel_pk)

            for cid_str, hops in (orig_ev.character_movements or {}).items():
                rem_hops = []
                ext_hops = []
                for hop in hops:
                    h_copy = dict(hop)
                    first_at_dt = t.parse_datetime(hop.get("first_at"))
                    if str(hop.get("channel_id") or "") == chan_id_str:
                        if first_at_dt and scene2.start_at and first_at_dt >= scene2.start_at:
                            h_copy["scene_id"] = scene2.scene_key
                            h_copy["scene_key"] = scene2.scene_key
                            ext_hops.append(h_copy)
                        else:
                            h_copy["scene_id"] = scene.scene_key
                            h_copy["scene_key"] = scene.scene_key
                            rem_hops.append(h_copy)
                    else:
                        rem_hops.append(h_copy)
                if rem_hops:
                    orig_movements[str(cid_str)] = rem_hops
                if ext_hops:
                    new_movements[str(cid_str)] = ext_hops

            orig_ev.character_movements = orig_movements
            new_ev.character_movements = new_movements
            orig_ev.is_curated = True
            new_ev.is_curated = True

            _recompute_event_from_scenes(orig_ev, orig_ev_scenes)
            _recompute_event_from_scenes(new_ev, [scene2])
    else:
        channel_scenes = (
            session.query(SceneModel)
            .filter(SceneModel.channel_pk == scene.channel_pk, SceneModel.backup_id == str(backup_id))
            .order_by(cast(SceneModel.start_message_id, BigInteger).asc(), SceneModel.start_at.asc())
            .all()
        )
        key_prefix = orig_scene_key.rsplit("-", 1)[0]
        assign_channel_scene_keys(
            session,
            str(backup_id),
            int(scene.channel_pk),
            key_prefix,
            channel_scenes=channel_scenes,
        )

    # Re-link other issues that were on Scene 1 at or after cand_sf to Scene 2
    relink_q = session.query(SceneIssueModel).filter(
        SceneIssueModel.backup_id == str(backup_id),
        SceneIssueModel.scene_pk == scene.pk,
        SceneIssueModel.candidate_message_id.isnot(None),
        cast(SceneIssueModel.candidate_message_id, BigInteger) >= cand_sf,
    )
    if exclude_issue_pk is not None:
        relink_q = relink_q.filter(SceneIssueModel.pk != exclude_issue_pk)
    relink_q.update({"scene_pk": scene2.pk}, synchronize_session="fetch")

    try:
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
    except Exception as e:
        t.log("error", f"SceneManager clear_cache error: {e}")

    return scene, scene2


def get_resolved_boundary_decisions(backup_id: str, base_path: str) -> Dict[str, str]:
    """
    Returns a dictionary mapping candidate_message_id -> resolution ("merged" | "split")
    for all resolved scene issues in SQLite for this backup.
    If two decisions share a candidate id, the latest resolved_at wins.
    """
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        issues = (
            session.query(SceneIssueModel)
            .filter(
                SceneIssueModel.backup_id == str(backup_id),
                SceneIssueModel.resolved_at.isnot(None),
                SceneIssueModel.candidate_message_id.isnot(None),
            )
            .order_by(SceneIssueModel.resolved_at.asc())
            .all()
        )
        decisions: Dict[str, str] = {}
        for iss in issues:
            if iss.candidate_message_id and iss.resolution:
                decisions[str(iss.candidate_message_id)] = str(iss.resolution)
        return decisions


def resolve_scene_issue(
    backup_id: str,
    base_path: str,
    issue_id: int,
    resolution: str,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolves a scene issue with 'split' or 'merged'.
    If resolution equals the kind default: marks resolved.
    If resolution is the opposite: executes merge or split via helpers.
    """
    if resolution not in (IssueResolution.SPLIT.value, IssueResolution.MERGED.value):
        raise exc.ValidationError(
            f"Invalid resolution '{resolution}'. Must be 'split' or 'merged'."
        )

    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        issue = (
            session.query(SceneIssueModel)
            .filter(
                SceneIssueModel.pk == issue_id,
                SceneIssueModel.backup_id == str(backup_id),
            )
            .first()
        )
        if not issue:
            raise exc.NotFoundError(f"Scene issue #{issue_id} not found.")

        if issue.resolved_at is not None:
            raise exc.ValidationError(
                f"Issue #{issue_id} is already resolved. Reopen it first before applying a different resolution."
            )

        default_res = get_default_resolution(issue.kind)

        # 1. No action needed: mark resolved
        if resolution == default_res:
            issue.resolved_at = datetime.now(timezone.utc)
            issue.resolution = resolution
            default_note = "Accepted split" if issue.kind == IssueKind.AUTO_SPLIT.value else "Accepted merge"
            issue.resolved_note = note.strip() if note and note.strip() else default_note
            session.flush()
            return {
                "status": "success",
                "issue_id": issue.pk,
                "resolved_at": issue.resolved_at.isoformat(),
                "resolved_note": issue.resolved_note,
                "resolution": issue.resolution,
                "action_performed": False,
            }

        # 2. Action needed: Auto-Split + Merged (merge Scene 1 and Scene 2)
        if issue.kind == IssueKind.AUTO_SPLIT.value and resolution == IssueResolution.MERGED.value:
            if not issue.scene_pk or not issue.next_scene_pk:
                raise exc.ValidationError(
                    f"Issue #{issue_id} is missing scene references (scene_pk={issue.scene_pk}, next_scene_pk={issue.next_scene_pk})."
                )
            s1 = session.query(SceneModel).filter_by(pk=issue.scene_pk, backup_id=str(backup_id)).first()
            s2 = session.query(SceneModel).filter_by(pk=issue.next_scene_pk, backup_id=str(backup_id)).first()
            if not s1 or not s2:
                raise exc.NotFoundError(f"Target scenes to merge (Scene 1 #{issue.scene_pk}, Scene 2 #{issue.next_scene_pk}) not found in database.")

            s2_key = s2.scene_key
            _merge_scenes(session, backup_id, base_path, s1, s2)

            issue.next_scene_pk = None
            issue.resolved_at = datetime.now(timezone.utc)
            issue.resolution = IssueResolution.MERGED.value
            issue.resolved_note = note.strip() if note and note.strip() else f"Merged Scene {s1.scene_key} and {s2_key} by reviewer"
            session.flush()

            return {
                "status": "success",
                "action": "merge",
                "issue_id": issue.pk,
                "scene_pk": s1.pk,
                "scene_key": s1.scene_key,
                "merged_scene_key": s2_key,
                "resolution": issue.resolution,
                "resolved_at": issue.resolved_at.isoformat(),
                "resolved_note": issue.resolved_note,
                "action_performed": True,
            }

        # 3. Action needed: Soft-Boundary + Split (split Scene 1 at candidate point)
        if issue.kind == IssueKind.SOFT_BOUNDARY.value and resolution == IssueResolution.SPLIT.value:
            if not issue.scene_pk:
                raise exc.ValidationError(f"Issue #{issue_id} is missing scene reference (scene_pk is None).")
            scene = session.query(SceneModel).filter_by(pk=issue.scene_pk, backup_id=str(backup_id)).first()
            if not scene:
                raise exc.NotFoundError(f"Target scene #{issue.scene_pk} not found in database.")

            s1, s2 = _split_scene_at(
                session,
                backup_id,
                base_path,
                scene,
                candidate_message_id=issue.candidate_message_id,
                candidate_index=issue.candidate_index,
                exclude_issue_pk=issue.pk,
            )

            issue.next_scene_pk = s2.pk
            issue.resolved_at = datetime.now(timezone.utc)
            issue.resolution = IssueResolution.SPLIT.value
            issue.resolved_note = note.strip() if note and note.strip() else f"Split at message {issue.candidate_message_id} by reviewer"
            session.flush()

            return {
                "status": "success",
                "action": "split",
                "issue_id": issue.pk,
                "scene_pk": s1.pk,
                "scene_key": s1.scene_key,
                "next_scene_pk": s2.pk,
                "next_scene_key": s2.scene_key,
                "resolution": issue.resolution,
                "resolved_at": issue.resolved_at.isoformat(),
                "resolved_note": issue.resolved_note,
                "action_performed": True,
            }

        raise exc.ValidationError(f"Invalid resolution '{resolution}' for issue kind '{issue.kind}'.")


def reopen_scene_issue(backup_id: str, base_path: str, issue_id: int) -> Dict[str, Any]:
    """
    Reopens a previously resolved scene issue.
    If an action was performed (merge or split), undoes the action:
      - auto_split + merged: splits scene_pk at candidate point and restores next_scene_pk
      - soft_boundary + split: merges scene_pk and next_scene_pk and clears next_scene_pk
    If no action was performed: only clears resolution fields.
    """
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        issue = (
            session.query(SceneIssueModel)
            .filter(
                SceneIssueModel.pk == issue_id,
                SceneIssueModel.backup_id == str(backup_id),
            )
            .first()
        )
        if not issue:
            raise exc.NotFoundError(f"Scene issue #{issue_id} not found.")

        if is_action_performed(issue.kind, issue.resolution):
            if issue.kind == IssueKind.AUTO_SPLIT.value:
                # Was merged, undo by splitting at candidate point
                if not issue.scene_pk:
                    raise exc.ValidationError(f"Issue #{issue_id} is missing scene_pk for undoing merge.")
                s1 = session.query(SceneModel).filter_by(pk=issue.scene_pk, backup_id=str(backup_id)).first()
                if not s1:
                    raise exc.NotFoundError(f"Scene #{issue.scene_pk} not found in database.")
                s1, new_s2 = _split_scene_at(
                    session,
                    backup_id,
                    base_path,
                    s1,
                    candidate_message_id=issue.candidate_message_id,
                    candidate_index=issue.candidate_index,
                    exclude_issue_pk=issue.pk,
                )
                issue.next_scene_pk = new_s2.pk

            elif issue.kind == IssueKind.SOFT_BOUNDARY.value:
                # Was split, undo by merging scene_pk and next_scene_pk
                if not issue.scene_pk or not issue.next_scene_pk:
                    raise exc.ValidationError(
                        f"Issue #{issue_id} missing scene references for undoing split: scene_pk={issue.scene_pk}, next_scene_pk={issue.next_scene_pk}."
                    )
                s1 = session.query(SceneModel).filter_by(pk=issue.scene_pk, backup_id=str(backup_id)).first()
                s2 = session.query(SceneModel).filter_by(pk=issue.next_scene_pk, backup_id=str(backup_id)).first()
                if not s1 or not s2:
                    raise exc.NotFoundError(f"Target scenes to merge for undo not found (Scene 1 #{issue.scene_pk}, Scene 2 #{issue.next_scene_pk}).")
                _merge_scenes(session, backup_id, base_path, s1, s2)
                issue.next_scene_pk = None

        issue.resolved_at = None
        issue.resolved_note = None
        issue.resolution = None
        session.flush()

        return {
            "status": "success",
            "issue_id": issue.pk,
            "reopened": True,
        }


def merge_auto_split_scenes(backup_id: str, base_path: str, issue_id: int, note: Optional[str] = None) -> Dict[str, Any]:
    return resolve_scene_issue(backup_id, base_path, issue_id, resolution=IssueResolution.MERGED.value, note=note)


def split_possible_split_scene(backup_id: str, base_path: str, issue_id: int, note: Optional[str] = None) -> Dict[str, Any]:
    return resolve_scene_issue(backup_id, base_path, issue_id, resolution=IssueResolution.SPLIT.value, note=note)


# --- FLAGGED MESSAGES & OVERRIDES ---


def suggest_character_for_non_tupper(
    session,
    backup_id: str,
    discord_user_id: Optional[str],
    content: Optional[str] = "",
    scene_tupper_char_ids: Optional[List[int]] = None,
    writer_cache: Optional[Dict[str, Any]] = None,
    all_chars_cache: Optional[List[Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Resolves a suggested tupper character for a non-tupper message posted by discord_user_id.
    Heuristics:
      1. Priority 1 (name_prefix): content starts with '<CharName>:' (writer's characters, or any if unlinked).
      2. Priority 2 (active_in_scene): intersect writer's characters with scene's tupper characters.
      3. Priority 3 (only_character): if writer only owns 1 top-level character.
    """
    clean_uid = str(discord_user_id).strip() if discord_user_id else None
    content_clean = (content or "").lstrip()

    writer = None
    if clean_uid:
        if writer_cache is not None:
            writer = writer_cache.get(clean_uid)
        else:
            writer = (
                session.query(WriterModel)
                .options(
                    selectinload(WriterModel.characters).selectinload(CharacterModel.names)
                )
                .filter(
                    WriterModel.backup_id == str(backup_id),
                    WriterModel.discord_user_id == clean_uid,
                )
                .first()
            )

    writer_characters = list(writer.characters) if writer else []

    # Priority 1: name_prefix
    if content_clean:
        if writer:
            for c in writer_characters:
                c_names = [n.name for n in sorted(c.names, key=lambda x: x.position)]
                primary_name = c_names[0] if c_names else f"Character #{c.char_id}"
                for name in c_names:
                    if name and content_clean.lower().startswith(f"{name.lower()}:"):
                        return {
                            "char_id": c.char_id,
                            "name": primary_name,
                            "writer_name": writer.display_name,
                            "reason": "name_prefix",
                        }
        else:
            if all_chars_cache is not None:
                all_chars = all_chars_cache
            else:
                all_chars = (
                    session.query(CharacterModel)
                    .options(
                        selectinload(CharacterModel.names),
                        joinedload(CharacterModel.writer),
                    )
                    .filter(CharacterModel.backup_id == str(backup_id))
                    .all()
                )
            for c in all_chars:
                c_names = [n.name for n in sorted(c.names, key=lambda x: x.position)]
                primary_name = c_names[0] if c_names else f"Character #{c.char_id}"
                for name in c_names:
                    if name and content_clean.lower().startswith(f"{name.lower()}:"):
                        w_name = c.writer.display_name if c.writer else None
                        return {
                            "char_id": c.char_id,
                            "name": primary_name,
                            "writer_name": w_name,
                            "reason": "name_prefix",
                        }

    # Priority 2: active_in_scene
    if writer and scene_tupper_char_ids:
        active = [c for c in writer_characters if c.char_id in scene_tupper_char_ids]
        if active:
            chosen = active[0]
            c_names = [n.name for n in sorted(chosen.names, key=lambda x: x.position)]
            primary_name = c_names[0] if c_names else f"Character #{chosen.char_id}"
            return {
                "char_id": chosen.char_id,
                "name": primary_name,
                "writer_name": writer.display_name,
                "reason": "active_in_scene",
            }

    # Priority 3: only_character
    if writer:
        top_level = [c for c in writer_characters if c.parent_pk is None]
        chosen = None
        if len(top_level) == 1:
            chosen = top_level[0]
        elif len(writer_characters) == 1:
            chosen = writer_characters[0]

        if chosen:
            c_names = [n.name for n in sorted(chosen.names, key=lambda x: x.position)]
            primary_name = c_names[0] if c_names else f"Character #{chosen.char_id}"
            return {
                "char_id": chosen.char_id,
                "name": primary_name,
                "writer_name": writer.display_name,
                "reason": "only_character",
            }

    return None


def _query_resolved_flags_map(session, backup_id: str) -> Dict[str, Dict[str, Any]]:
    flags = session.query(FlaggedMessageModel).filter(
        FlaggedMessageModel.backup_id == str(backup_id),
        FlaggedMessageModel.resolved_at.isnot(None),
    ).all()
    return {
        str(f.message_id): {
            "resolution": f.resolution,
            "override_content": f.override_content,
            "override_author": f.override_author,
            "override_flags": f.override_flags,
        }
        for f in flags
    }


def get_resolved_flags_map(
    backup_id: str,
    base_path: str,
    session=None,
) -> Dict[str, Dict[str, Any]]:
    """
    Returns a dictionary mapping message_id -> {"resolution": ..., "override_content": ..., "override_author": ..., "override_flags": ...}
    for all resolved flagged messages in SQLite for this backup.
    Reuses the caller's active SQLAlchemy session when provided so uncommitted flushes are visible.
    """
    if session is not None:
        session.flush()
        return _query_resolved_flags_map(session, str(backup_id))
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as own_session:
        return _query_resolved_flags_map(own_session, str(backup_id))


def get_preserved_flagged_message_ids(backup_id: str, base_path: str) -> Set[str]:
    """
    Returns the set of message_ids that must NOT be overwritten or deleted during re-indexing.
    Includes all resolved messages (resolved_at IS NOT NULL) and all manually added messages (kind == 'manual').
    """
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        flags = session.query(FlaggedMessageModel.message_id).filter(
            FlaggedMessageModel.backup_id == str(backup_id),
            (FlaggedMessageModel.resolved_at.isnot(None)) | (FlaggedMessageModel.kind == FlaggedKind.MANUAL.value)
        ).all()
        return {str(r[0]) for r in flags}


def _recompute_scene_participants(session, backup_id: str, base_path: str, scene: SceneModel) -> None:
    """Recomputes and syncs scene_participants and message_count for a single SceneModel from skeletons.sqlite."""
    channel = scene.channel
    if not channel:
        return

    skeletons = _load_skeletons_or_json_fallback(
        backup_id,
        base_path,
        channel,
        start_message_id=scene.start_message_id,
        end_message_id=scene.end_message_id,
    )
    if not skeletons:
        return

    resolved_flags = get_resolved_flags_map(backup_id, base_path, session=session)
    chars = session.query(CharacterModel).filter_by(backup_id=str(backup_id)).all()
    char_id_to_pk = {c.char_id: c.pk for c in chars}

    msg_count, part_details = compute_scene_counts_from_skeletons(
        skeletons, char_id_to_pk, resolved_flags_map=resolved_flags
    )
    scene.message_count = msg_count
    session.query(SceneParticipantModel).filter_by(scene_pk=scene.pk).delete()
    for p_info in part_details:
        session.add(SceneParticipantModel(
            scene_pk=scene.pk,
            character_pk=p_info["character_pk"],
            position=p_info["position"],
            message_count=p_info["message_count"],
            first_message_id=p_info["first_message_id"],
            first_at=p_info["first_at"],
            last_message_id=p_info["last_message_id"],
            last_at=p_info["last_at"],
        ))
    session.flush()


def _renumber_channel_scenes(session, backup_id: str, channel_pk: int) -> None:
    """Renumbers scene keys tmp- then 1..N within a channel after scene addition or deletion."""
    channel_scenes = (
        session.query(SceneModel)
        .filter(
            SceneModel.channel_pk == channel_pk,
            SceneModel.backup_id == str(backup_id),
            SceneModel.event_pk.is_(None),
        )
        .order_by(cast(SceneModel.start_message_id, BigInteger).asc(), SceneModel.start_at.asc())
        .all()
    )
    if not channel_scenes:
        return
    key_prefix = channel_scenes[0].scene_key.rsplit("-", 1)[0]
    assign_channel_scene_keys(
        session,
        str(backup_id),
        int(channel_pk),
        key_prefix,
        channel_scenes=channel_scenes,
    )


def _sync_scene_after_message_resolution(
    session, backup_id: str, base_path: str, flagged: FlaggedMessageModel
) -> None:
    """
    Applies immediate live SQLite mutations to scenes and scene_issues following
    a message resolution using skeletons.sqlite + Snowflake bounds.
    Returns immediately with zero skeleton/JSON reads when resolution == 'kept'.
    """
    res = flagged.resolution
    if res == FlaggedResolution.KEPT.value:
        return

    msg_id = str(flagged.message_id)
    msg_sf = snowflake_int(msg_id)

    start_scenes = session.query(SceneModel).filter(
        SceneModel.backup_id == str(backup_id),
        SceneModel.start_message_id == msg_id,
    ).all()

    end_scenes = session.query(SceneModel).filter(
        SceneModel.backup_id == str(backup_id),
        SceneModel.end_message_id == msg_id,
    ).all()

    candidate_issues = session.query(SceneIssueModel).filter(
        SceneIssueModel.backup_id == str(backup_id),
        SceneIssueModel.candidate_message_id == msg_id,
    ).all()

    if res == FlaggedResolution.OVERRIDE.value:
        eff_author = flagged.override_author if flagged.override_author is not None else flagged.author
        o_author_id = str((eff_author or {}).get("id") or "")
        o_content = flagged.override_content if flagged.override_content is not None else flagged.content
        eff_excerpt = t.format_excerpt(str(o_content or ""))

        for sc in start_scenes:
            sc.start_author_id = o_author_id
            sc.start_excerpt = eff_excerpt
            _recompute_scene_participants(session, backup_id, base_path, sc)

        for sc in end_scenes:
            sc.end_author_id = o_author_id
            sc.end_excerpt = eff_excerpt
            _recompute_scene_participants(session, backup_id, base_path, sc)

        if not start_scenes and not end_scenes and flagged.channel_pk and msg_sf > 0:
            mid_scenes = session.query(SceneModel).filter(
                SceneModel.backup_id == str(backup_id),
                SceneModel.channel_pk == flagged.channel_pk,
                cast(SceneModel.start_message_id, BigInteger) <= msg_sf,
                cast(SceneModel.end_message_id, BigInteger) >= msg_sf,
            ).all()
            for sc in mid_scenes:
                _recompute_scene_participants(session, backup_id, base_path, sc)

        for iss in candidate_issues:
            iss.candidate_excerpt = eff_excerpt

    elif res == FlaggedResolution.IGNORED.value:
        # 1. Unresolved soft boundaries on candidate message are obsolete -> delete them
        for iss in candidate_issues:
            if iss.kind == IssueKind.SOFT_BOUNDARY.value and iss.resolved_at is None:
                session.delete(iss)

        chan_model = session.query(ChannelModel).filter_by(pk=flagged.channel_pk).first() if flagged.channel_pk else None
        chan_skeletons = (
            _load_skeletons_or_json_fallback(backup_id, base_path, chan_model)
            if chan_model and (start_scenes or end_scenes or candidate_issues)
            else []
        )
        resolved_flags = get_resolved_flags_map(backup_id, base_path, session=session) if chan_skeletons else {}

        def _find_first_valid_forward(skels: List[Any], after_sf: int, end_sf: int) -> Optional[Tuple[Any, Dict[str, Any]]]:
            for sk in skels:
                mid_i = int(sk.message_id)
                if mid_i <= after_sf:
                    continue
                if mid_i > end_sf:
                    break
                eff = resolve_effective_skeleton(sk, resolved_flags_map=resolved_flags)
                if eff and eff["is_valid"]:
                    return sk, eff
            return None

        def _find_last_valid_backward(skels: List[Any], start_sf: int, before_sf: int) -> Optional[Tuple[Any, Dict[str, Any]]]:
            for sk in reversed(skels):
                mid_i = int(sk.message_id)
                if mid_i >= before_sf:
                    continue
                if mid_i < start_sf:
                    break
                eff = resolve_effective_skeleton(sk, resolved_flags_map=resolved_flags)
                if eff and eff["is_valid"]:
                    return sk, eff
            return None

        # 2. Start boundary shrinking
        shifted_scene_starts: Dict[int, Tuple[str, Optional[str]]] = {}
        for sc in start_scenes:
            if chan_skeletons:
                found = _find_first_valid_forward(
                    chan_skeletons,
                    after_sf=snowflake_int(sc.start_message_id),
                    end_sf=snowflake_int(sc.end_message_id),
                )
                if found:
                    sk, eff = found
                    m_id = eff["message_id_str"]
                    new_excerpt = fetch_message_excerpt(backup_id, base_path, chan_model, m_id)
                    sc.start_message_id = m_id
                    if eff["timestamp_dt"]:
                        sc.start_at = eff["timestamp_dt"]
                    sc.start_author_id = str(eff["author_id"])
                    sc.start_excerpt = new_excerpt
                    shifted_scene_starts[sc.pk] = (m_id, new_excerpt)
                    _recompute_scene_participants(session, backup_id, base_path, sc)
                else:
                    chan_pk = sc.channel_pk
                    session.delete(sc)
                    session.flush()
                    _renumber_channel_scenes(session, backup_id, chan_pk)

        # 3. For auto_split or split issues on this message: sync issue candidate to shifted start
        for iss in candidate_issues:
            if iss.resolution == IssueResolution.SPLIT.value or iss.kind == IssueKind.AUTO_SPLIT.value:
                target_sc_pk = iss.next_scene_pk or iss.scene_pk
                if target_sc_pk in shifted_scene_starts:
                    new_mid, new_exc = shifted_scene_starts[target_sc_pk]
                    iss.candidate_message_id = new_mid
                    iss.candidate_excerpt = new_exc
                else:
                    sc2 = session.query(SceneModel).filter_by(pk=target_sc_pk).first()
                    if sc2 and chan_skeletons:
                        found = _find_first_valid_forward(
                            chan_skeletons,
                            after_sf=snowflake_int(sc2.start_message_id),
                            end_sf=snowflake_int(sc2.end_message_id),
                        )
                        if found:
                            sk, eff = found
                            m_id = eff["message_id_str"]
                            new_excerpt = fetch_message_excerpt(backup_id, base_path, chan_model, m_id)
                            sc2.start_message_id = m_id
                            if eff["timestamp_dt"]:
                                sc2.start_at = eff["timestamp_dt"]
                            sc2.start_author_id = str(eff["author_id"])
                            sc2.start_excerpt = new_excerpt
                            iss.candidate_message_id = m_id
                            iss.candidate_excerpt = new_excerpt
                            _recompute_scene_participants(session, backup_id, base_path, sc2)
                        else:
                            chan_pk = sc2.channel_pk
                            session.delete(sc2)
                            session.flush()
                            _renumber_channel_scenes(session, backup_id, chan_pk)

        # 4. End boundary shrinking
        for sc in end_scenes:
            if chan_skeletons:
                found = _find_last_valid_backward(
                    chan_skeletons,
                    start_sf=snowflake_int(sc.start_message_id),
                    before_sf=snowflake_int(sc.end_message_id),
                )
                if found:
                    sk, eff = found
                    m_id = eff["message_id_str"]
                    new_excerpt = fetch_message_excerpt(backup_id, base_path, chan_model, m_id)
                    sc.end_message_id = m_id
                    if eff["timestamp_dt"]:
                        sc.end_at = eff["timestamp_dt"]
                    sc.end_author_id = str(eff["author_id"])
                    sc.end_excerpt = new_excerpt
                    _recompute_scene_participants(session, backup_id, base_path, sc)
                else:
                    chan_pk = sc.channel_pk
                    session.delete(sc)
                    session.flush()
                    _renumber_channel_scenes(session, backup_id, chan_pk)

    try:
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
    except Exception as e:
        t.log("debug", f"SceneManager clear cache: {e}")


def get_flagged_messages(
    backup_id: str,
    base_path: str,
    status: Optional[str] = "unresolved",
    kind: Optional[str] = None,
    resolution: Optional[str] = None,
    channel_id: Optional[str] = None,
    scene_type: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> Dict[str, Any]:
    """Queries flagged messages with status, kind, resolution, channel, and scene_type filters."""
    if not isinstance(status, str):
        status = "unresolved"
    if not isinstance(kind, str):
        kind = None
    if not isinstance(resolution, str):
        resolution = None
    if not isinstance(channel_id, str):
        channel_id = None
    if not isinstance(scene_type, str) or not scene_type.strip():
        scene_type = None
    if not isinstance(page, int) or page < 1:
        page = 1
    if not isinstance(per_page, int) or per_page < 1:
        per_page = 50
    per_page = min(per_page, 200)

    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
        server_id = backup.server_id if backup else ""

        unresolved_count = session.query(func.count(FlaggedMessageModel.pk)).filter(
            FlaggedMessageModel.backup_id == str(backup_id),
            FlaggedMessageModel.resolved_at.is_(None),
        ).scalar() or 0

        resolved_count = session.query(func.count(FlaggedMessageModel.pk)).filter(
            FlaggedMessageModel.backup_id == str(backup_id),
            FlaggedMessageModel.resolved_at.isnot(None),
        ).scalar() or 0

        all_count = session.query(func.count(FlaggedMessageModel.pk)).filter(
            FlaggedMessageModel.backup_id == str(backup_id)
        ).scalar() or 0

        # Determine scope subquery for flagged messages based on channel scenes
        kind_subq = (
            select(SceneModel.kind)
            .where(
                SceneModel.channel_pk == FlaggedMessageModel.channel_pk,
                SceneModel.backup_id == FlaggedMessageModel.backup_id,
            )
            .limit(1)
            .scalar_subquery()
        )
        msg_scope = func.coalesce(kind_subq, SceneKind.SCENE.value)

        # Compute scope counts filtered by status, kind, resolution, channel_id
        scope_counts_query = (
            session.query(
                func.count(FlaggedMessageModel.pk).label("all_count"),
                func.coalesce(func.sum(case((msg_scope == SceneKind.SCENE.value, 1), else_=0)), 0).label("scene_count"),
                func.coalesce(func.sum(case((msg_scope == SceneKind.SESSION.value, 1), else_=0)), 0).label("session_count"),
                func.coalesce(func.sum(case((msg_scope == SceneKind.EVENT.value, 1), else_=0)), 0).label("event_count"),
            )
            .filter(FlaggedMessageModel.backup_id == str(backup_id))
        )
        if status == "unresolved":
            scope_counts_query = scope_counts_query.filter(FlaggedMessageModel.resolved_at.is_(None))
        elif status == "resolved":
            scope_counts_query = scope_counts_query.filter(FlaggedMessageModel.resolved_at.isnot(None))

        if kind:
            scope_counts_query = scope_counts_query.filter(FlaggedMessageModel.kind == kind)
        if resolution:
            scope_counts_query = scope_counts_query.filter(FlaggedMessageModel.resolution == resolution)
        if channel_id:
            scope_counts_query = scope_counts_query.join(ChannelModel, FlaggedMessageModel.channel_pk == ChannelModel.pk).filter(
                ChannelModel.discord_id == str(channel_id)
            )

        scope_row = scope_counts_query.first()
        scope_counts = {
            "all": int(scope_row.all_count) if scope_row and scope_row.all_count is not None else 0,
            "scene": int(scope_row.scene_count) if scope_row and scope_row.scene_count is not None else 0,
            "session": int(scope_row.session_count) if scope_row and scope_row.session_count is not None else 0,
            "event": int(scope_row.event_count) if scope_row and scope_row.event_count is not None else 0,
        }

        query = session.query(FlaggedMessageModel).filter(FlaggedMessageModel.backup_id == str(backup_id))

        if status == "unresolved":
            query = query.filter(FlaggedMessageModel.resolved_at.is_(None))
        elif status == "resolved":
            query = query.filter(FlaggedMessageModel.resolved_at.isnot(None))

        if kind:
            query = query.filter(FlaggedMessageModel.kind == kind)
        if resolution:
            query = query.filter(FlaggedMessageModel.resolution == resolution)
        if channel_id:
            query = query.join(ChannelModel, FlaggedMessageModel.channel_pk == ChannelModel.pk).filter(
                ChannelModel.discord_id == str(channel_id)
            )
        if scene_type:
            query = query.filter(msg_scope == scene_type)

        total_items = query.count()
        query = query.order_by(FlaggedMessageModel.flagged_at.desc(), FlaggedMessageModel.pk.desc())
        offset = (page - 1) * per_page
        msgs_raw = query.offset(offset).limit(per_page).all()

        # Batch-fetch scenes and writers to prevent N+1 queries
        chan_pks = {f.channel_pk for f in msgs_raw if f.channel_pk}
        chan_scenes_map: Dict[int, List[SceneModel]] = {}
        if chan_pks:
            fetched_scenes = (
                session.query(SceneModel)
                .options(
                    selectinload(SceneModel.participants).joinedload(SceneParticipantModel.character)
                )
                .filter(SceneModel.channel_pk.in_(chan_pks))
                .all()
            )
            for sc in fetched_scenes:
                chan_scenes_map.setdefault(sc.channel_pk, []).append(sc)

        page_author_ids = {
            str(f.author.get("id")).strip()
            for f in msgs_raw
            if isinstance(f.author, dict) and f.author.get("id")
        }
        page_writers = (
            session.query(WriterModel)
            .options(
                selectinload(WriterModel.characters).selectinload(CharacterModel.names)
            )
            .filter(
                WriterModel.backup_id == str(backup_id),
                WriterModel.discord_user_id.in_(page_author_ids),
            )
            .all()
        ) if page_author_ids else []
        writer_cache = {str(w.discord_user_id).strip(): w for w in page_writers if w.discord_user_id}

        # Batch-check IS_DELETED in skeletons.sqlite if present
        deleted_flagged_keys: set = set()
        if msgs_raw and has_skeleton_db(base_path, backup_id=backup_id):
            chan_ids_chk = {int(f.channel.discord_id) for f in msgs_raw if f.channel and str(f.channel.discord_id).isdigit()}
            msg_ids_chk = {int(f.message_id) for f in msgs_raw if str(f.message_id).isdigit()}
            if chan_ids_chk and msg_ids_chk:
                try:
                    with skeleton_db_session(backup_id=backup_id, backup_path=base_path) as skel_session:
                        rows = (
                            skel_session.query(
                                MessageSkeletonModel.channel_discord_id,
                                MessageSkeletonModel.message_id,
                                MessageSkeletonModel.flags,
                            )
                            .filter(
                                MessageSkeletonModel.channel_discord_id.in_(chan_ids_chk),
                                MessageSkeletonModel.message_id.in_(msg_ids_chk),
                            )
                            .all()
                        )
                        for ch_id, m_id, fl in rows:
                            if int(fl or 0) & SkeletonFlags.IS_DELETED:
                                deleted_flagged_keys.add((str(ch_id), str(m_id)))
                except Exception:
                    pass

        formatted = []
        for f in msgs_raw:
            channel = f.channel
            c_discord_id = channel.discord_id if channel else ""
            c_name = channel.name if channel else ""

            discord_link = ""
            if server_id and c_discord_id and f.message_id:
                discord_link = f"https://discord.com/channels/{server_id}/{c_discord_id}/{f.message_id}"

            author_id = f.author.get("id") if isinstance(f.author, dict) else None
            scene_tupper_char_ids = None
            if f.channel_pk:
                chan_scenes = chan_scenes_map.get(f.channel_pk, [])
                if chan_scenes:
                    chosen_scene = None
                    try:
                        f_mid = int(f.message_id)
                        for sc in chan_scenes:
                            s_mid = int(sc.start_message_id) if sc.start_message_id and str(sc.start_message_id).isdigit() else 0
                            e_mid = int(sc.end_message_id) if sc.end_message_id and str(sc.end_message_id).isdigit() else 0
                            if s_mid <= f_mid <= e_mid:
                                chosen_scene = sc
                                break
                        if not chosen_scene:
                            chosen_scene = min(
                                chan_scenes,
                                key=lambda sc: min(
                                    abs(f_mid - (int(sc.start_message_id) if sc.start_message_id and str(sc.start_message_id).isdigit() else 0)),
                                    abs(f_mid - (int(sc.end_message_id) if sc.end_message_id and str(sc.end_message_id).isdigit() else 0))
                                )
                            )
                    except (ValueError, TypeError):
                        chosen_scene = chan_scenes[0]

                    if chosen_scene:
                        scene_tupper_char_ids = [
                            p.character.char_id
                            for p in chosen_scene.participants
                            if p.character and t.is_tupper(p.character.char_id)
                        ]

            suggested = suggest_character_for_non_tupper(
                session=session,
                backup_id=str(backup_id),
                discord_user_id=author_id,
                content=f.content,
                scene_tupper_char_ids=scene_tupper_char_ids,
                writer_cache=writer_cache,
            )

            item_scene_type = SceneKind.SCENE.value
            if f.channel_pk and f.channel_pk in chan_scenes_map and chan_scenes_map[f.channel_pk]:
                item_scene_type = chan_scenes_map[f.channel_pk][0].kind or SceneKind.SCENE.value

            channel_is_deleted = bool(channel and channel.is_deleted)
            message_is_deleted = bool((c_discord_id, str(f.message_id)) in deleted_flagged_keys)

            formatted.append({
                "id": f.pk,
                "message_id": f.message_id,
                "kind": f.kind,
                "scene_type": item_scene_type,
                "channel_name": c_name,
                "channel_discord_id": c_discord_id,
                "content": f.content,
                "is_excerpt_truncated": bool(getattr(f, "is_excerpt_truncated", False)),
                "channel_is_deleted": channel_is_deleted,
                "message_is_deleted": message_is_deleted,
                "is_deleted": bool(channel_is_deleted or message_is_deleted),
                "author": f.author,
                "discord_link": discord_link,
                "flagged_at": f.flagged_at.isoformat() if f.flagged_at else None,
                "resolution": f.resolution,
                "override_content": f.override_content,
                "override_author": f.override_author,
                "override_flags": getattr(f, "override_flags", None),
                "resolved_at": f.resolved_at.isoformat() if f.resolved_at else None,
                "resolved_note": f.resolved_note,
                "suggested_character": suggested,
            })

        total_pages = math.ceil(total_items / per_page) if per_page > 0 else 1
        return {
            "total_items": total_items,
            "current_page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "status_counts": {
                "unresolved": unresolved_count,
                "resolved": resolved_count,
                "all": all_count,
            },
            "scope_counts": scope_counts,
            "messages": formatted,
        }


def resolve_flagged_message(
    backup_id: str,
    base_path: str,
    message_id: str,
    resolution: str,
    note: Optional[str] = None,
    override_content: Optional[str] = None,
    override_author: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Resolves a flagged message with 'override', 'ignored', or 'kept'.
    Executes live scene boundary and issue synchronization.
    """
    valid_resolutions = (
        FlaggedResolution.OVERRIDE.value,
        FlaggedResolution.IGNORED.value,
        FlaggedResolution.KEPT.value,
    )
    if resolution not in valid_resolutions:
        raise exc.ValidationError(
            f"Invalid resolution '{resolution}'. Must be one of: {', '.join(valid_resolutions)}."
        )

    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        flagged = (
            session.query(FlaggedMessageModel)
            .filter(
                FlaggedMessageModel.backup_id == str(backup_id),
                FlaggedMessageModel.message_id == str(message_id),
            )
            .first()
        )
        if not flagged:
            raise exc.NotFoundError(f"Flagged message #{message_id} not found.")

        now_utc = datetime.now(timezone.utc)
        flagged.resolution = resolution
        flagged.resolved_at = now_utc
        flagged.resolved_note = note.strip() if note and note.strip() else f"Resolved as {resolution}"

        if resolution == FlaggedResolution.OVERRIDE.value:
            target_author = override_author if override_author is not None else flagged.author
            resolved_aid_int = None
            if isinstance(target_author, dict) and "id" in target_author:
                target_author = dict(target_author)
                clean_id = str(target_author["id"]).strip()
                target_author["id"] = clean_id
                if clean_id.isdigit():
                    resolved_aid_int = int(clean_id)
                    if t.is_tupper(resolved_aid_int):
                        target_author["isBot"] = True
                        char_model = (
                            session.query(CharacterModel)
                            .options(selectinload(CharacterModel.names))
                            .filter_by(backup_id=str(backup_id), char_id=resolved_aid_int)
                            .first()
                        )
                        if char_model and char_model.names:
                            sorted_names = [n.name for n in sorted(char_model.names, key=lambda x: x.position)]
                            if sorted_names:
                                target_author["name"] = sorted_names[0]
                if target_author.get("name"):
                    target_author["nickname"] = target_author["name"]

            if override_content is not None:
                flagged.override_content = override_content
                flagged.override_flags = compute_skeleton_flags(
                    {
                        "type": "Default",
                        "content": override_content,
                        "author": target_author or {},
                    },
                    author_id=resolved_aid_int,
                )
            else:
                flagged.override_content = None
                flagged.override_flags = None
            flagged.override_author = target_author
        else:
            flagged.override_content = None
            flagged.override_author = None
            flagged.override_flags = None

        _sync_scene_after_message_resolution(session, backup_id, base_path, flagged)
        session.flush()

        return {
            "status": "success",
            "message_id": message_id,
            "resolution": resolution,
            "resolved_at": now_utc.isoformat(),
        }


def reopen_flagged_message(
    backup_id: str,
    base_path: str,
    message_id: str,
) -> Dict[str, Any]:
    """Reopens a previously resolved flagged message, restoring its original state in SQLite."""
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        flagged = (
            session.query(FlaggedMessageModel)
            .filter(
                FlaggedMessageModel.backup_id == str(backup_id),
                FlaggedMessageModel.message_id == str(message_id),
            )
            .first()
        )
        if not flagged:
            raise exc.NotFoundError(f"Flagged message #{message_id} not found.")

        old_res = flagged.resolution
        flagged.resolution = None
        flagged.resolved_at = None
        flagged.resolved_note = None
        flagged.override_content = None
        flagged.override_author = None
        flagged.override_flags = None

        msg_sf = snowflake_int(message_id)

        if old_res == FlaggedResolution.IGNORED.value and flagged.channel_pk:
            chan_model = session.query(ChannelModel).filter_by(pk=flagged.channel_pk).first()
            if chan_model:
                skels = _load_skeletons_or_json_fallback(
                    backup_id,
                    base_path,
                    chan_model,
                    start_message_id=message_id,
                    end_message_id=message_id,
                )
                target_sk = skels[0] if skels else None
                if target_sk is not None:
                    orig_author_id = str(target_sk.author_id or (flagged.author or {}).get("id") or "")
                    orig_timestamp = (
                        datetime.fromtimestamp(int(target_sk.timestamp_unix), tz=timezone.utc)
                        if target_sk.timestamp_unix
                        else None
                    )
                    cnt = str(flagged.content or "")
                    eff_excerpt = t.format_excerpt(cnt)

                    scenes = (
                        session.query(SceneModel)
                        .filter_by(backup_id=str(backup_id), channel_pk=flagged.channel_pk)
                        .order_by(cast(SceneModel.start_message_id, BigInteger).asc(), SceneModel.start_at.asc())
                        .all()
                    )
                    prev_scene = next(
                        (sc for sc in reversed(scenes) if snowflake_int(sc.end_message_id) <= msg_sf),
                        None,
                    )
                    next_scene = next(
                        (sc for sc in scenes if snowflake_int(sc.start_message_id) >= msg_sf),
                        None,
                    )

                    target_scene = None
                    target_role = None
                    if prev_scene and not next_scene:
                        target_scene = prev_scene
                        target_role = "end"
                    elif next_scene and not prev_scene:
                        target_scene = next_scene
                        target_role = "start"
                    elif prev_scene and next_scene:
                        if int(target_sk.flags) & SkeletonFlags.HAS_END_TAG:
                            target_scene = prev_scene
                            target_role = "end"
                        else:
                            target_scene = next_scene
                            target_role = "start"

                    if target_scene and target_role == "start":
                        old_start_mid = target_scene.start_message_id
                        target_scene.start_message_id = str(message_id)
                        target_scene.start_author_id = orig_author_id
                        if orig_timestamp:
                            target_scene.start_at = orig_timestamp
                        target_scene.start_excerpt = eff_excerpt
                        _recompute_scene_participants(session, backup_id, base_path, target_scene)

                        issues = session.query(SceneIssueModel).filter(
                            SceneIssueModel.backup_id == str(backup_id),
                            (SceneIssueModel.candidate_message_id == old_start_mid) | (SceneIssueModel.next_scene_pk == target_scene.pk),
                        ).all()
                        for iss in issues:
                            if iss.resolution == IssueResolution.SPLIT.value or iss.kind == IssueKind.AUTO_SPLIT.value:
                                iss.candidate_message_id = str(message_id)
                                iss.candidate_excerpt = eff_excerpt

                    elif target_scene and target_role == "end":
                        target_scene.end_message_id = str(message_id)
                        target_scene.end_author_id = orig_author_id
                        if orig_timestamp:
                            target_scene.end_at = orig_timestamp
                        target_scene.end_excerpt = eff_excerpt
                        _recompute_scene_participants(session, backup_id, base_path, target_scene)

        elif old_res == FlaggedResolution.OVERRIDE.value:
            orig_author_id = str((flagged.author or {}).get("id") or "")
            orig_content = str(flagged.content or "")
            orig_excerpt = t.format_excerpt(orig_content)
            start_scenes = session.query(SceneModel).filter_by(backup_id=str(backup_id), start_message_id=str(message_id)).all()
            for sc in start_scenes:
                sc.start_author_id = orig_author_id
                sc.start_excerpt = orig_excerpt
                _recompute_scene_participants(session, backup_id, base_path, sc)

            end_scenes = session.query(SceneModel).filter_by(backup_id=str(backup_id), end_message_id=str(message_id)).all()
            for sc in end_scenes:
                sc.end_author_id = orig_author_id
                sc.end_excerpt = orig_excerpt
                _recompute_scene_participants(session, backup_id, base_path, sc)

            if not start_scenes and not end_scenes and flagged.channel_pk and msg_sf > 0:
                mid_scenes = session.query(SceneModel).filter(
                    SceneModel.backup_id == str(backup_id),
                    SceneModel.channel_pk == flagged.channel_pk,
                    cast(SceneModel.start_message_id, BigInteger) <= msg_sf,
                    cast(SceneModel.end_message_id, BigInteger) >= msg_sf,
                ).all()
                for sc in mid_scenes:
                    _recompute_scene_participants(session, backup_id, base_path, sc)

        session.flush()
        try:
            from models import SceneManager
            SceneManager.clear_cache(backup_id)
        except Exception:
            pass

        return {
            "status": "success",
            "message_id": message_id,
            "reopened": True,
        }


def add_manual_flagged_message(
    backup_id: str,
    base_path: str,
    discord_link: str,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Adds a message manually into the flagged review queue using a Discord message link."""
    from utils.path_safety import DISCORD_MSG_LINK_RE
    match = DISCORD_MSG_LINK_RE.fullmatch(discord_link.strip()) if isinstance(discord_link, str) and len(discord_link) <= 500 else None
    if not match:
        raise exc.ValidationError(
            "Invalid Discord message link format. Expected: https://discord.com/channels/<guild_id>/<channel_id>/<message_id>"
        )

    guild_id = match.group("guild_id")
    channel_id = match.group("channel_id")
    message_id = match.group("message_id")

    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
        if not backup:
            raise exc.NotFoundError(f"Backup {backup_id} not found.")

        if backup.server_id and str(backup.server_id) != str(guild_id):
            raise exc.ValidationError(
                f"Discord link guild ID ({guild_id}) does not match backup server ID ({backup.server_id})."
            )

        channel = (
            session.query(ChannelModel)
            .filter(
                ChannelModel.backup_id == str(backup_id),
                ChannelModel.discord_id == str(channel_id),
            )
            .first()
        )
        if not channel:
            raise exc.ValidationError(f"Channel {channel_id} not found in this backup.")

        found_content = None
        found_author = None
        is_truncated = False

        c_path = Path(channel.path)
        f_path = Path(base_path) / c_path if (Path(base_path) / c_path).exists() else Path(base_path) / "Data" / c_path
        if f_path.exists():
            chan_data = t.load_from_json(f_path.as_posix())
            raw_msgs = chan_data.get("messages", [])
            found_msg = next((m for m in raw_msgs if str(m.get("id")) == str(message_id)), None)
            if found_msg:
                found_content = str(found_msg.get("content", ""))
                found_author = found_msg.get("author", {})

        if found_author is None:
            skels = load_channel_skeletons(
                backup_id, base_path, channel.discord_id, start_message_id=message_id, end_message_id=message_id
            )
            if skels:
                sk = skels[0]
                aid_str = str(sk.author_id)
                author_name = f"User #{aid_str}"
                is_bot = t.is_tupper(sk.author_id)
                if is_bot:
                    char_m = (
                        session.query(CharacterModel)
                        .options(selectinload(CharacterModel.names))
                        .filter_by(backup_id=str(backup_id), char_id=int(sk.author_id))
                        .first()
                    )
                    if char_m and char_m.names:
                        author_name = sorted(char_m.names, key=lambda n: n.position)[0].name
                else:
                    seen_u = (
                        session.query(SeenDiscordUserModel)
                        .filter_by(backup_id=str(backup_id), discord_user_id=aid_str)
                        .first()
                    )
                    if seen_u:
                        author_name = seen_u.nickname or seen_u.global_name or seen_u.username
                found_author = {"id": aid_str, "name": author_name, "isBot": is_bot}
                fetched = fetch_message_excerpt(backup_id, base_path, channel, str(message_id))
                found_content = fetched if fetched is not None else ""
                is_truncated = fetched is None

        if found_author is None:
            raise exc.ValidationError(f"Message {message_id} not found in channel #{channel.name}.")

        existing = (
            session.query(FlaggedMessageModel)
            .filter_by(backup_id=str(backup_id), message_id=str(message_id))
            .first()
        )
        now_utc = datetime.now(timezone.utc)
        if existing:
            if existing.resolved_at is not None:
                raise exc.ValidationError(
                    f"Message #{message_id} is already in flagged messages with resolution '{existing.resolution}'."
                )
            flagged = existing
        else:
            flagged = FlaggedMessageModel(
                backup_id=str(backup_id),
                message_id=str(message_id),
                channel_pk=channel.pk,
                kind=FlaggedKind.MANUAL.value,
                content=found_content or "",
                is_excerpt_truncated=is_truncated,
                author=found_author,
                flagged_at=now_utc,
                resolved_note=note.strip() if note and note.strip() else None,
            )
            session.add(flagged)
            session.flush()

        return {
            "id": flagged.pk,
            "message_id": flagged.message_id,
            "kind": flagged.kind,
            "channel_name": channel.name,
            "channel_discord_id": channel.discord_id,
            "content": flagged.content,
            "author": flagged.author,
            "discord_link": discord_link,
            "flagged_at": flagged.flagged_at.isoformat() if flagged.flagged_at else None,
            "resolution": flagged.resolution,
            "resolved_at": flagged.resolved_at.isoformat() if flagged.resolved_at else None,
            "resolved_note": flagged.resolved_note,
        }


def create_manual_scene_split(
    backup_id: str,
    base_path: str,
    discord_link: str,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Manually splits a scene at the message indicated by a Discord message link."""
    from utils.path_safety import DISCORD_MSG_LINK_RE
    match = DISCORD_MSG_LINK_RE.fullmatch(discord_link.strip()) if isinstance(discord_link, str) and len(discord_link) <= 500 else None
    if not match:
        raise exc.ValidationError(
            "Invalid Discord message link format. Expected: https://discord.com/channels/<guild_id>/<channel_id>/<message_id>"
        )

    guild_id = match.group("guild_id")
    channel_id = match.group("channel_id")
    message_id = match.group("message_id")

    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
        if not backup:
            raise exc.NotFoundError(f"Backup {backup_id} not found.")

        if backup.server_id and str(backup.server_id) != str(guild_id):
            raise exc.ValidationError(
                f"Discord link guild ID ({guild_id}) does not match backup server ID ({backup.server_id})."
            )

        channel = (
            session.query(ChannelModel)
            .filter(
                ChannelModel.backup_id == str(backup_id),
                ChannelModel.discord_id == str(channel_id),
            )
            .first()
        )
        if not channel:
            raise exc.ValidationError(f"Channel {channel_id} not found in this backup.")

        # Check if message is marked ignored
        flagged = (
            session.query(FlaggedMessageModel)
            .filter_by(backup_id=str(backup_id), message_id=str(message_id))
            .first()
        )
        if flagged and flagged.resolution == FlaggedResolution.IGNORED.value:
            raise exc.ValidationError(
                "This message is marked as Ignored (OOC). Reopen it in Flagged Messages or pick the next in-character message."
            )

        skels = _load_skeletons_or_json_fallback(
            backup_id, base_path, channel, start_message_id=message_id, end_message_id=message_id
        )
        if not skels:
            raise exc.ValidationError(f"Message {message_id} not found in channel #{channel.name}.")

        msg_sf = snowflake_int(message_id)

        # Locate containing scene via Snowflake bounds
        scenes = (
            session.query(SceneModel)
            .filter_by(backup_id=str(backup_id), channel_pk=channel.pk)
            .order_by(cast(SceneModel.start_message_id, BigInteger).asc(), SceneModel.start_at.asc())
            .all()
        )
        target_scene = next(
            (sc for sc in scenes if snowflake_int(sc.start_message_id) <= msg_sf <= snowflake_int(sc.end_message_id)),
            None,
        )
        if not target_scene:
            raise exc.ValidationError(f"Message {message_id} is not inside an indexed scene.")

        if str(target_scene.start_message_id) == str(message_id):
            raise exc.ValidationError(
                f"Message {message_id} is already the start message of Scene {target_scene.scene_key}."
            )

        flagged_map = {str(message_id): flagged.content} if flagged else None
        cand_excerpt = fetch_message_excerpt(backup_id, base_path, channel, str(message_id), flagged_content_map=flagged_map)

        now_utc = datetime.now(timezone.utc)
        issue = SceneIssueModel(
            backup_id=str(backup_id),
            scene_pk=target_scene.pk,
            next_scene_pk=None,
            kind=IssueKind.SOFT_BOUNDARY.value,
            reason=IssueReason.MANUAL.value,
            candidate_message_id=str(message_id),
            candidate_index=None,
            candidate_excerpt=cand_excerpt,
            created_at=now_utc,
            resolved_at=now_utc,
            resolution=IssueResolution.SPLIT.value,
            resolved_note=note.strip() if note and note.strip() else f"Manual split at {message_id}",
        )
        session.add(issue)
        session.flush()

        s1, s2 = _split_scene_at(
            session,
            backup_id,
            base_path,
            target_scene,
            candidate_message_id=str(message_id),
            exclude_issue_pk=issue.pk,
        )
        issue.next_scene_pk = s2.pk
        session.flush()

        return {
            "status": "success",
            "action": "split",
            "issue_id": issue.pk,
            "scene_pk": s1.pk,
            "scene_key": s1.scene_key,
            "next_scene_pk": s2.pk,
            "next_scene_key": s2.scene_key,
            "resolution": issue.resolution,
            "resolved_at": issue.resolved_at.isoformat(),
            "resolved_note": issue.resolved_note,
            "action_performed": True,
        }


# --- BACKWARD COMPATIBILITY OVERRIDE WRAPPERS ---


def promote_flagged_message(
    backup_id: str,
    base_path: str,
    message_id: str,
    content: Optional[str] = None,
    author: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Backward-compatible wrapper for promoting a flagged message to override."""
    res = resolve_flagged_message(
        backup_id=backup_id,
        base_path=base_path,
        message_id=message_id,
        resolution=FlaggedResolution.OVERRIDE.value,
        override_content=content,
        override_author=author,
    )
    return {
        "status": "success",
        "message_id": message_id,
        "promoted_at": res["resolved_at"],
    }


def get_message_overrides(
    backup_id: str, base_path: str, page: int = 1, per_page: int = 50
) -> Dict[str, Any]:
    """Backward-compatible retrieval of active message overrides."""
    res = get_flagged_messages(
        backup_id=backup_id,
        base_path=base_path,
        status="resolved",
        resolution=FlaggedResolution.OVERRIDE.value,
        page=page,
        per_page=per_page,
    )
    overrides = []
    for m in res.get("messages", []):
        item = dict(m)
        if item.get("override_content") is not None:
            item["content"] = item["override_content"]
        if item.get("override_author") is not None:
            item["author"] = item["override_author"]
        overrides.append(item)
    res["overrides"] = overrides
    return res


def delete_message_override(backup_id: str, base_path: str, message_id: str) -> Dict[str, Any]:
    """Backward-compatible deletion of an override (reopens the message)."""
    reopen_flagged_message(backup_id=backup_id, base_path=base_path, message_id=message_id)
    return {"status": "success", "deleted_override_message_id": message_id}


def get_overrides_map(backup_id: str, base_path: str) -> Dict[str, Dict[str, Any]]:
    """Returns a dictionary mapping message_id -> {"content": ..., "author": ...} for all active overrides."""
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        overrides = session.query(FlaggedMessageModel).filter(
            FlaggedMessageModel.backup_id == str(backup_id),
            FlaggedMessageModel.resolution == FlaggedResolution.OVERRIDE.value,
        ).all()
        return {
            str(o.message_id): {
                "content": o.override_content if o.override_content is not None else o.content,
                "author": o.override_author if o.override_author is not None else o.author,
            }
            for o in overrides
        }


def save_flagged_messages(
    backup_id: str,
    base_path: str,
    flagged_items: List[Dict[str, Any]],
    debug_files: bool = False
) -> None:
    """
    Saves newly discovered flagged messages to SQLite while strictly preserving
    all resolved messages (resolved_at IS NOT NULL) and all manual items (kind == 'manual').
    """
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    now_utc = datetime.now(timezone.utc)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        # Delete only auto-detected unresolved rows
        session.query(FlaggedMessageModel).filter(
            FlaggedMessageModel.backup_id == str(backup_id),
            FlaggedMessageModel.resolved_at.is_(None),
            FlaggedMessageModel.kind != FlaggedKind.MANUAL.value,
        ).delete()

        # Build discord_id -> channel_pk map (Schema v6: direct backup_id FK)
        channels = session.query(ChannelModel).filter(
            ChannelModel.backup_id == str(backup_id),
        ).all()
        chan_map = {ch.discord_id: ch.pk for ch in channels}

        # Query preserved message IDs to prevent duplicate inserts
        preserved = session.query(FlaggedMessageModel.message_id).filter(
            FlaggedMessageModel.backup_id == str(backup_id)
        ).all()
        existing_mids = {str(r[0]) for r in preserved}

        for item in flagged_items:
            mid = str(item["message_id"])
            if mid in existing_mids:
                continue

            chan_discord_id = str(item.get("channel_discord_id") or "")
            flagged = FlaggedMessageModel(
                backup_id=str(backup_id),
                message_id=mid,
                channel_pk=chan_map.get(chan_discord_id),
                kind=str(item.get("kind", FlaggedKind.OOC_MESSAGE.value)),
                content=str(item.get("content", "")),
                is_excerpt_truncated=bool(item.get("is_excerpt_truncated", False)),
                author=item.get("author", {}),
                flagged_at=item.get("flagged_at") or now_utc,
            )
            session.add(flagged)
            existing_mids.add(mid)

        session.flush()

        if debug_files:
            export_curation_snapshots(session, backup_id, base_path)


def save_channel_flagged_messages(
    backup_id: str,
    base_path: str,
    channel_pk: int,
    flagged_items: List[Dict[str, Any]],
    min_message_id: Optional[Any] = None,
    debug_files: bool = False,
) -> None:
    """
    Channel-scoped atomic upsert for auto-detected FlaggedMessageModel rows.
    Deletes only unresolved auto-detected rows in `channel_pk` (optionally bounded
    to `cast(message_id, BigInteger) > int(min_message_id)`), preserving all resolved
    rows, manual items, and older unresolved rows before the lookback window.
    """
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    now_utc = datetime.now(timezone.utc)
    min_sf = int(min_message_id) if (min_message_id is not None and str(min_message_id).isdigit() and int(min_message_id) > 0) else None

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        del_q = session.query(FlaggedMessageModel).filter(
            FlaggedMessageModel.backup_id == str(backup_id),
            FlaggedMessageModel.channel_pk == int(channel_pk),
            FlaggedMessageModel.resolved_at.is_(None),
            FlaggedMessageModel.kind != FlaggedKind.MANUAL.value,
        )
        if min_sf is not None:
            del_q = del_q.filter(cast(FlaggedMessageModel.message_id, BigInteger) > min_sf)
        del_q.delete(synchronize_session=False)

        existing_mids = {
            str(r[0])
            for r in session.query(FlaggedMessageModel.message_id).filter(
                FlaggedMessageModel.backup_id == str(backup_id)
            ).all()
        }

        for item in flagged_items:
            mid = str(item["message_id"])
            if mid in existing_mids:
                continue
            raw_content = str(item.get("content", "") or "")
            flagged = FlaggedMessageModel(
                backup_id=str(backup_id),
                message_id=mid,
                channel_pk=int(channel_pk),
                kind=str(item.get("kind", FlaggedKind.OOC_MESSAGE.value)),
                content=t.format_excerpt(raw_content),
                is_excerpt_truncated=bool(item.get("is_excerpt_truncated", len(raw_content) > 250)),
                author=item.get("author", {}),
                flagged_at=item.get("flagged_at") or now_utc,
            )
            session.add(flagged)
            existing_mids.add(mid)

        session.flush()
        if debug_files:
            export_curation_snapshots(session, backup_id, base_path)


# --- 'BY ME' USER LINKING ---


def get_my_writer(
    backup_id: str, base_path: str, discord_user_id: str
) -> Optional[Dict[str, Any]]:
    """Resolves the writer associated with the current user's Discord snowflake."""
    if not discord_user_id:
        return None
    require_db(base_path, backup_id=backup_id)

    try:
        init_db(engine_or_backup_id=backup_id, backup_path=base_path, check_version=False)
        with db_session(backup_id=backup_id, backup_path=base_path) as session:
            writer = (
                session.query(WriterModel)
                .filter(
                    WriterModel.backup_id == str(backup_id),
                    WriterModel.discord_user_id == str(discord_user_id),
                )
                .first()
            )
            if not writer:
                return None

            char_ids = [c.char_id for c in writer.characters]
            aliases = [a.alias for a in writer.aliases]
            return {
                "id": writer.pk,
                "display_name": writer.display_name,
                "discord_user_id": writer.discord_user_id,
                "aliases": aliases,
                "character_ids": char_ids,
            }
    except Exception as e:
        t.log("debug", f"Failed to resolve current user writer: {e}")
        return None


def get_curation_summary(backup_id: str, base_path: str) -> Dict[str, int]:
    """Returns real-time badge counts for curation review queues and unassigned data."""
    require_db(base_path, backup_id=backup_id)
    try:
        init_db(engine_or_backup_id=backup_id, backup_path=base_path, check_version=False)
    except Exception as e:
        t.log("debug", f"Failed schema inspect during curation summary for {backup_id}: {e}")

    try:
        suggestions = get_writer_link_suggestions(backup_id, base_path)
    except Exception:
        suggestions = []

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        try:
            return {
                "unresolved_issues": session.query(func.count(SceneIssueModel.pk)).filter(
                    SceneIssueModel.backup_id == str(backup_id),
                    SceneIssueModel.resolved_at.is_(None)
                ).scalar() or 0,
                "unassigned_characters": session.query(func.count(CharacterModel.pk)).filter(
                    CharacterModel.backup_id == str(backup_id),
                    CharacterModel.writer_pk.is_(None)
                ).scalar() or 0,
                "flagged_messages": session.query(func.count(FlaggedMessageModel.pk)).filter(
                    FlaggedMessageModel.backup_id == str(backup_id),
                    FlaggedMessageModel.resolved_at.is_(None)
                ).scalar() or 0,
                "unlinked_writers": session.query(func.count(WriterModel.pk)).filter(
                    WriterModel.backup_id == str(backup_id),
                    WriterModel.discord_user_id.is_(None)
                ).scalar() or 0,
                "link_suggestions": len(suggestions),
            }
        except Exception as e:
            session.rollback()
            t.log("debug", f"Failed to compute curation summary for {backup_id}: {e}")
            return {
                "unresolved_issues": 0,
                "unassigned_characters": 0,
                "flagged_messages": 0,
                "unlinked_writers": 0,
                "link_suggestions": len(suggestions),
            }


def update_scene_metadata(
    backup_id: str,
    base_path: str,
    scene_id: Any,
    custom_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Updates custom_name on a SceneModel record (supports scenes, sessions, or event channels)."""
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    clean_name = custom_name.strip() if isinstance(custom_name, str) and custom_name.strip() else None

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        query = session.query(SceneModel).filter(SceneModel.backup_id == str(backup_id))
        s_str = str(scene_id).strip()
        scene = None
        if s_str.isdigit():
            scene = query.filter((SceneModel.pk == int(s_str)) | (SceneModel.scene_key == s_str)).first()
        else:
            scene = query.filter(SceneModel.scene_key == s_str).first()

        if not scene:
            raise exc.NotFoundError(f"Scene '{scene_id}' not found in backup '{backup_id}'.")

        scene.custom_name = clean_name
        session.flush()

        # If scene is associated with an event, keep character_movements in sync
        if scene.event_pk:
            ev = session.query(EventModel).filter(EventModel.pk == scene.event_pk).first()
            if ev and ev.character_movements:
                custom_by_key = {sc.scene_key: sc.custom_name for sc in ev.scenes}
                custom_by_chan = {sc.channel.discord_id: sc.custom_name for sc in ev.scenes if sc.channel and sc.custom_name}
                updated_moves = {}
                for cid, hops in (ev.character_movements or {}).items():
                    hop_list = []
                    for h in hops:
                        h_copy = dict(h)
                        s_id = h_copy.get("scene_key") or h_copy.get("scene_id")
                        ch_id = h_copy.get("channel_id")
                        if s_id and s_id in custom_by_key:
                            h_copy["custom_name"] = custom_by_key[s_id]
                        elif ch_id and ch_id in custom_by_chan:
                            h_copy["custom_name"] = custom_by_chan[ch_id]
                        hop_list.append(h_copy)
                    updated_moves[cid] = hop_list
                ev.character_movements = updated_moves
                session.flush()

        return {
            "status": "success",
            "pk": scene.pk,
            "scene_pk": scene.pk,
            "scene_key": scene.scene_key,
            "custom_name": scene.custom_name,
        }
def _find_scene_by_id(session, backup_id: str, scene_id: Any) -> SceneModel:
    query = session.query(SceneModel).filter(SceneModel.backup_id == str(backup_id))
    s_str = str(scene_id).strip()
    scene = None
    if s_str.isdigit():
        scene = query.filter((SceneModel.pk == int(s_str)) | (SceneModel.scene_key == s_str)).first()
    else:
        scene = query.filter(SceneModel.scene_key == s_str).first()
    if not scene:
        raise exc.NotFoundError(f"Scene '{scene_id}' not found in backup '{backup_id}'.")
    return scene


def _find_issue_between_scenes(session, backup_id: str, s1: SceneModel, s2: SceneModel) -> Optional[SceneIssueModel]:
    """Finds an issue (auto_split, soft_boundary, manual split) separating adjacent s1 and s2."""
    return (
        session.query(SceneIssueModel)
        .filter(
            SceneIssueModel.backup_id == str(backup_id),
            or_(
                and_(SceneIssueModel.scene_pk == s1.pk, SceneIssueModel.next_scene_pk == s2.pk),
                and_(SceneIssueModel.scene_pk == s1.pk, SceneIssueModel.candidate_message_id == str(s2.start_message_id)),
                and_(SceneIssueModel.next_scene_pk == s2.pk, SceneIssueModel.candidate_message_id == str(s2.start_message_id)),
                and_(
                    SceneIssueModel.candidate_message_id == str(s2.start_message_id),
                    SceneIssueModel.candidate_index == s2.start_index,
                ),
                SceneIssueModel.candidate_message_id == str(s2.start_message_id),
            ),
        )
        .order_by(SceneIssueModel.pk.desc())
        .first()
    )


def _is_curator_split(issue: Optional[SceneIssueModel]) -> bool:
    if not issue:
        return False
    # Manual split created by curator
    if issue.reason in (IssueReason.MANUAL.value, "manual_split", "manual"):
        return True
    # Soft boundary explicitly set to split by curator
    if issue.kind == IssueKind.SOFT_BOUNDARY.value and issue.resolution == IssueResolution.SPLIT.value:
        return True
    return False


def _evaluate_scene_pair_merge(session, backup_id: str, s1: SceneModel, s2: SceneModel) -> Dict[str, Any]:
    """
    Evaluates whether earlier scene s1 and later scene s2 can be merged,
    and whether they are separated by an issue or curator split.
    """
    can_merge = True
    disabled_reason = None

    s1_end_sf = snowflake_int(s1.end_message_id)
    s2_start_sf = snowflake_int(s2.start_message_id)

    if s1.channel_pk != s2.channel_pk:
        can_merge = False
        disabled_reason = "Scenes belong to different channels."
    elif s2_start_sf <= s1_end_sf:
        can_merge = False
        disabled_reason = "Overlapping scenes cannot be merged."
    else:
        # Check for intervening scene
        intervening = (
            session.query(SceneModel)
            .filter(
                SceneModel.backup_id == str(backup_id),
                SceneModel.channel_pk == s1.channel_pk,
                cast(SceneModel.start_message_id, BigInteger) > s1_end_sf,
                cast(SceneModel.start_message_id, BigInteger) < s2_start_sf,
            )
            .first()
        )
        if intervening:
            can_merge = False
            disabled_reason = f"Scene #{intervening.pk} ({intervening.scene_key}) intervenes between these scenes."

    issue = _find_issue_between_scenes(session, backup_id, s1, s2)
    curator_split = _is_curator_split(issue)
    warning = None
    if curator_split:
        warning = (
            "These scenes were separated by a curator (manual split or soft boundary set to split). "
            "Merging them will combine the scenes and mark the issue as merged. Confirmation required."
        )

    return {
        "can_merge": can_merge,
        "disabled_reason": disabled_reason,
        "issue_id": issue.pk if issue else None,
        "is_curator_split": curator_split,
        "warning": warning,
    }


def get_scene_merge_neighbors(
    backup_id: str,
    base_path: str,
    scene_id: Any,
) -> Dict[str, Any]:
    """
    Returns immediate previous and next scenes in the same channel,
    along with merge eligibility and curator split status.
    """
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        scene = _find_scene_by_id(session, backup_id, scene_id)
        sc_start_sf = snowflake_int(scene.start_message_id)
        sc_end_sf = snowflake_int(scene.end_message_id)

        # Immediate previous scene in same channel
        prev_scene = (
            session.query(SceneModel)
            .filter(
                SceneModel.backup_id == str(backup_id),
                SceneModel.channel_pk == scene.channel_pk,
                SceneModel.kind == scene.kind,
                cast(SceneModel.end_message_id, BigInteger) < sc_start_sf,
            )
            .order_by(cast(SceneModel.start_message_id, BigInteger).desc())
            .first()
        )

        # Immediate next scene in same channel
        next_scene = (
            session.query(SceneModel)
            .filter(
                SceneModel.backup_id == str(backup_id),
                SceneModel.channel_pk == scene.channel_pk,
                SceneModel.kind == scene.kind,
                cast(SceneModel.start_message_id, BigInteger) > sc_end_sf,
            )
            .order_by(cast(SceneModel.start_message_id, BigInteger).asc())
            .first()
        )

        prev_info = {
            "exists": prev_scene is not None,
            "scene_pk": prev_scene.pk if prev_scene else None,
            "scene_key": prev_scene.scene_key if prev_scene else None,
            "custom_name": prev_scene.custom_name if prev_scene else None,
            "can_merge": False,
            "disabled_reason": "First scene in channel" if prev_scene is None else None,
            "is_curator_split": False,
            "issue_id": None,
            "warning": None,
        }
        if prev_scene:
            pair_eval = _evaluate_scene_pair_merge(session, backup_id, prev_scene, scene)
            prev_info.update(pair_eval)

        next_info = {
            "exists": next_scene is not None,
            "scene_pk": next_scene.pk if next_scene else None,
            "scene_key": next_scene.scene_key if next_scene else None,
            "custom_name": next_scene.custom_name if next_scene else None,
            "can_merge": False,
            "disabled_reason": "Last scene in channel" if next_scene is None else None,
            "is_curator_split": False,
            "issue_id": None,
            "warning": None,
        }
        if next_scene:
            pair_eval = _evaluate_scene_pair_merge(session, backup_id, scene, next_scene)
            next_info.update(pair_eval)

        return {
            "status": "success",
            "scene_pk": scene.pk,
            "scene_key": scene.scene_key,
            "kind": scene.kind,
            "prev": prev_info,
            "next": next_info,
        }


def merge_adjacent_scene(
    backup_id: str,
    base_path: str,
    scene_id: Any,
    direction: str,
    force: bool = False,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Merges scene with either its immediate previous or immediate next neighbor in the same channel.
    If separated by a curator split and not force, returns requires_confirmation.
    If no scene issue existed between them, creates a resolved issue so it can be undone easily.
    """
    if direction not in ("prev", "next"):
        raise exc.ValidationError(f"Invalid direction '{direction}'. Must be 'prev' or 'next'.")

    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        scene = _find_scene_by_id(session, backup_id, scene_id)
        sc_start_sf = snowflake_int(scene.start_message_id)
        sc_end_sf = snowflake_int(scene.end_message_id)

        if direction == "prev":
            prev_scene = (
                session.query(SceneModel)
                .filter(
                    SceneModel.backup_id == str(backup_id),
                    SceneModel.channel_pk == scene.channel_pk,
                    SceneModel.kind == scene.kind,
                    cast(SceneModel.end_message_id, BigInteger) < sc_start_sf,
                )
                .order_by(cast(SceneModel.start_message_id, BigInteger).desc())
                .first()
            )
            if not prev_scene:
                raise exc.ValidationError("Cannot merge with previous scene: this is the first scene in the channel.")
            s1 = prev_scene
            s2 = scene
        else:
            next_scene = (
                session.query(SceneModel)
                .filter(
                    SceneModel.backup_id == str(backup_id),
                    SceneModel.channel_pk == scene.channel_pk,
                    SceneModel.kind == scene.kind,
                    cast(SceneModel.start_message_id, BigInteger) > sc_end_sf,
                )
                .order_by(cast(SceneModel.start_message_id, BigInteger).asc())
                .first()
            )
            if not next_scene:
                raise exc.ValidationError("Cannot merge with next scene: this is the last scene in the channel.")
            s1 = scene
            s2 = next_scene

        # Adjacency and validity check
        pair_eval = _evaluate_scene_pair_merge(session, backup_id, s1, s2)
        if not pair_eval["can_merge"]:
            raise exc.ValidationError(pair_eval["disabled_reason"] or "Scenes cannot be merged.")

        issue = _find_issue_between_scenes(session, backup_id, s1, s2)
        curator_split = _is_curator_split(issue)

        if curator_split and not force:
            return {
                "status": "requires_confirmation",
                "warning": (
                    "These scenes were separated by a curator (manual split or soft boundary set to split). "
                    "Merging them will combine the scenes and mark the issue as merged. Please confirm to proceed."
                ),
                "direction": direction,
                "target_scene_key": (s1.scene_key if direction == "prev" else s2.scene_key),
                "target_pk": (s1.pk if direction == "prev" else s2.pk),
                "issue_id": issue.pk if issue else None,
            }

        s2_start_mid = str(s2.start_message_id)
        s2_start_idx = s2.start_index
        s2_start_excerpt = s2.start_excerpt
        s1_participants = list(s1.participants)
        s2_participants = list(s2.participants)
        s1_key = s1.scene_key
        s2_key = s2.scene_key
        s1_name = s1.custom_name
        s2_name = s2.custom_name

        # Resolve character char_id (Tupperbox/Discord ID) for participants, not internal SQLite character_pk
        all_char_pks = {p.character_pk for p in s1_participants} | {p.character_pk for p in s2_participants}
        char_pk_to_char_id = {}
        if all_char_pks:
            char_rows = (
                session.query(CharacterModel.pk, CharacterModel.char_id)
                .filter(CharacterModel.pk.in_(all_char_pks))
                .all()
            )
            char_pk_to_char_id = {row.pk: row.char_id for row in char_rows}

        previous_char_ids = sorted(list({
            char_pk_to_char_id[p.character_pk]
            for p in s1_participants
            if p.character_pk in char_pk_to_char_id
        }))
        next_char_ids = sorted(list({
            char_pk_to_char_id[p.character_pk]
            for p in s2_participants
            if p.character_pk in char_pk_to_char_id
        }))

        merged_s1 = _merge_scenes(session, backup_id, base_path, s1, s2)

        # Preserve custom_name: keep s1's if present, else adopt s2's if present
        if not merged_s1.custom_name and s2_name:
            merged_s1.custom_name = s2_name

        # Handle scene issue: update existing or create resolved one
        resolved_note = note.strip() if note and note.strip() else f"Merged {s1_key} and {s2_key} by curator"
        now_utc = datetime.now(timezone.utc)

        if issue:
            issue.resolution = IssueResolution.MERGED.value
            issue.resolved_at = now_utc
            issue.resolved_note = resolved_note
            issue.scene_pk = merged_s1.pk
            issue.next_scene_pk = None
            if not issue.previous_chars and previous_char_ids:
                issue.previous_chars = previous_char_ids
            if not issue.next_chars and next_char_ids:
                issue.next_chars = next_char_ids
        else:
            new_issue = SceneIssueModel(
                backup_id=str(backup_id),
                scene_pk=merged_s1.pk,
                next_scene_pk=None,
                kind=IssueKind.AUTO_SPLIT.value,
                reason=IssueReason.MANUAL.value,
                candidate_message_id=s2_start_mid,
                candidate_index=s2_start_idx,
                candidate_excerpt=s2_start_excerpt,
                previous_chars=previous_char_ids,
                next_chars=next_char_ids,
                created_at=merged_s1.start_at or now_utc,
                resolved_at=now_utc,
                resolved_note=resolved_note,
                resolution=IssueResolution.MERGED.value,
            )
            session.add(new_issue)

        session.flush()

        # If merged_s1 is associated with an event, keep character_movements in sync
        if merged_s1.event_pk:
            ev = session.query(EventModel).filter(EventModel.pk == merged_s1.event_pk).first()
            if ev and ev.character_movements:
                custom_by_key = {sc.scene_key: sc.custom_name for sc in ev.scenes}
                custom_by_chan = {sc.channel.discord_id: sc.custom_name for sc in ev.scenes if sc.channel and sc.custom_name}
                updated_moves = {}
                for cid, hops in (ev.character_movements or {}).items():
                    hop_list = []
                    for h in hops:
                        h_copy = dict(h)
                        s_id = h_copy.get("scene_key") or h_copy.get("scene_id")
                        ch_id = h_copy.get("channel_id")
                        if s_id and s_id in custom_by_key:
                            h_copy["custom_name"] = custom_by_key[s_id]
                        elif ch_id and ch_id in custom_by_chan:
                            h_copy["custom_name"] = custom_by_chan[ch_id]
                        hop_list.append(h_copy)
                    updated_moves[cid] = hop_list
                ev.character_movements = updated_moves
                session.flush()

        return {
            "status": "success",
            "merged_scene": {
                "pk": merged_s1.pk,
                "scene_key": merged_s1.scene_key,
                "custom_name": merged_s1.custom_name,
                "kind": merged_s1.kind,
            },
            "deleted_scene_key": s2_key,
        }


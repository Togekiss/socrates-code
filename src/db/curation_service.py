import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from sqlalchemy import func, or_

from db.models import (
    BackupModel,
    ChannelModel,
    CharacterGroupModel,
    CharacterModel,
    CharacterNameModel,
    ExportModel,
    FlaggedMessageModel,
    GroupNameModel,
    MessageOverrideModel,
    SceneIssueModel,
    SceneModel,
    Scope,
    WriterAliasModel,
    WriterModel,
)
from db.session import db_session, require_sqlite_db
from db.snapshots import export_character_list_snapshot, export_curation_snapshots


# --- WRITERS MANAGEMENT ---


def get_writers_detailed(backup_id: str, base_path: str) -> List[Dict[str, Any]]:
    """Retrieves all writers with their aliases, discord_user_id, and written characters."""
    require_sqlite_db(base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        writers = (
            session.query(WriterModel)
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
    try:
        from find_writer_links import find_writer_link_suggestions
        return find_writer_link_suggestions(backup_id, base_path)
    except ImportError:
        return []


# --- UNASSIGNED CHARACTERS QUEUE ---


def get_unassigned_characters(backup_id: str, base_path: str) -> List[Dict[str, Any]]:
    """Retrieves characters that currently have no writer assigned (writer_pk IS NULL)."""
    require_sqlite_db(base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        chars = (
            session.query(CharacterModel)
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
            result.append({
                "id": c.char_id,
                "names": c_names,
                "origin": c.origin,
                "activity": c.activity,
                "version_type": c.version_type,
                "group_id": c.group_pk,
                "parent_id": c.parent.char_id if c.parent else None,
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
    status: Optional[str] = "unresolved",
    channel_id: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> Dict[str, Any]:
    """Queries scene issues with filtering by kind, resolution status, and channel."""
    if not isinstance(kind, str):
        kind = None
    if not isinstance(status, str):
        status = "unresolved"
    if not isinstance(channel_id, str):
        channel_id = None
    if not isinstance(page, int):
        page = 1
    if not isinstance(per_page, int):
        per_page = 50

    require_sqlite_db(base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
        server_id = backup.server_id if backup else ""

        query = session.query(SceneIssueModel).join(SceneModel, SceneIssueModel.scene_pk == SceneModel.pk)
        query = query.filter(SceneIssueModel.backup_id == str(backup_id))

        if kind:
            query = query.filter(SceneIssueModel.kind == kind)

        if status == "unresolved":
            query = query.filter(SceneIssueModel.resolved_at.is_(None))
        elif status == "resolved":
            query = query.filter(SceneIssueModel.resolved_at.isnot(None))

        if channel_id:
            query = query.join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
            query = query.filter(ChannelModel.discord_id == str(channel_id))

        total_items = query.count()

        query = query.order_by(SceneIssueModel.created_at.desc(), SceneIssueModel.pk.desc())
        offset = (page - 1) * per_page
        issues_raw = query.offset(offset).limit(per_page).all()

        formatted = []
        for iss in issues_raw:
            scene = iss.scene
            channel = scene.channel if scene else None
            chan_id = channel.discord_id if channel else ""
            chan_name = channel.name if channel else ""
            start_msg_id = scene.start_message_id if scene else ""

            discord_link = ""
            if server_id and chan_id and start_msg_id:
                discord_link = f"https://discord.com/channels/{server_id}/{chan_id}/{start_msg_id}"

            formatted.append({
                "id": iss.pk,
                "kind": iss.kind,
                "scene_pk": scene.pk if scene else None,
                "scene_key": scene.scene_key if scene else "",
                "channel_name": chan_name,
                "channel_discord_id": chan_id,
                "discord_user_id": iss.discord_user_id,
                "details": iss.details,
                "discord_link": discord_link,
                "created_at": iss.created_at.isoformat() if iss.created_at else None,
                "resolved_at": iss.resolved_at.isoformat() if iss.resolved_at else None,
                "resolved_note": iss.resolved_note,
            })

        total_pages = math.ceil(total_items / per_page) if per_page > 0 else 1
        return {
            "total_items": total_items,
            "current_page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "issues": formatted,
        }


def resolve_scene_issue(
    backup_id: str, base_path: str, issue_id: int, note: Optional[str] = None
) -> Dict[str, Any]:
    """Marks a scene issue as resolved with an optional reviewer note."""
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
            raise ValueError(f"Scene issue #{issue_id} not found.")

        issue.resolved_at = datetime.now(timezone.utc)
        issue.resolved_note = note.strip() if note and note.strip() else "Resolved by reviewer"
        session.flush()

        return {
            "status": "success",
            "issue_id": issue.pk,
            "resolved_at": issue.resolved_at.isoformat(),
            "resolved_note": issue.resolved_note,
        }


def reopen_scene_issue(backup_id: str, base_path: str, issue_id: int) -> Dict[str, Any]:
    """Reopens a previously resolved scene issue."""
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
            raise ValueError(f"Scene issue #{issue_id} not found.")

        issue.resolved_at = None
        issue.resolved_note = None
        session.flush()

        return {
            "status": "success",
            "issue_id": issue.pk,
            "reopened": True,
        }


# --- FLAGGED MESSAGES & OVERRIDES ---


def get_flagged_messages(
    backup_id: str,
    base_path: str,
    kind: Optional[str] = None,
    channel_id: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> Dict[str, Any]:
    """Queries flagged messages awaiting curation review."""
    if not isinstance(kind, str):
        kind = None
    if not isinstance(channel_id, str):
        channel_id = None
    if not isinstance(page, int):
        page = 1
    if not isinstance(per_page, int):
        per_page = 50

    require_sqlite_db(base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
        server_id = backup.server_id if backup else ""

        query = session.query(FlaggedMessageModel).filter(FlaggedMessageModel.backup_id == str(backup_id))

        if kind:
            query = query.filter(FlaggedMessageModel.kind == kind)

        if channel_id:
            query = query.join(ChannelModel, FlaggedMessageModel.channel_pk == ChannelModel.pk)
            query = query.filter(ChannelModel.discord_id == str(channel_id))

        total_items = query.count()

        query = query.order_by(FlaggedMessageModel.flagged_at.desc(), FlaggedMessageModel.pk.desc())
        offset = (page - 1) * per_page
        msgs_raw = query.offset(offset).limit(per_page).all()

        formatted = []
        for f in msgs_raw:
            channel = f.channel
            chan_id = channel.discord_id if channel else ""
            chan_name = channel.name if channel else ""

            discord_link = ""
            if server_id and chan_id and f.message_id:
                discord_link = f"https://discord.com/channels/{server_id}/{chan_id}/{f.message_id}"

            formatted.append({
                "id": f.pk,
                "message_id": f.message_id,
                "kind": f.kind,
                "channel_name": chan_name,
                "channel_discord_id": chan_id,
                "content": f.content,
                "author": f.author,
                "discord_link": discord_link,
                "flagged_at": f.flagged_at.isoformat() if f.flagged_at else None,
            })

        total_pages = math.ceil(total_items / per_page) if per_page > 0 else 1
        return {
            "total_items": total_items,
            "current_page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "messages": formatted,
        }


def promote_flagged_message(
    backup_id: str,
    base_path: str,
    message_id: str,
    content: Optional[str] = None,
    author: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Promotes a flagged message into a permanent message override and removes it from the flagged queue."""
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
            raise ValueError(f"Flagged message #{message_id} not found.")

        # Check existing override or insert
        override = (
            session.query(MessageOverrideModel)
            .filter(
                MessageOverrideModel.backup_id == str(backup_id),
                MessageOverrideModel.message_id == str(message_id),
            )
            .first()
        )

        now_utc = datetime.now(timezone.utc)
        target_content = content if content is not None else flagged.content
        target_author = author if author is not None else flagged.author

        if override:
            override.content = target_content
            override.author = target_author
            override.channel_pk = flagged.channel_pk
        else:
            override = MessageOverrideModel(
                backup_id=str(backup_id),
                message_id=str(message_id),
                channel_pk=flagged.channel_pk,
                content=target_content,
                author=target_author,
                created_at=now_utc,
            )
            session.add(override)

        # Remove from flagged messages
        session.delete(flagged)
        session.flush()

        return {
            "status": "success",
            "message_id": message_id,
            "override_id": override.pk,
            "promoted_at": now_utc.isoformat(),
        }


def get_message_overrides(
    backup_id: str, base_path: str, page: int = 1, per_page: int = 50
) -> Dict[str, Any]:
    """Retrieves all active message overrides for the backup."""
    if not isinstance(page, int):
        page = 1
    if not isinstance(per_page, int):
        per_page = 50

    require_sqlite_db(base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
        server_id = backup.server_id if backup else ""

        query = session.query(MessageOverrideModel).filter(MessageOverrideModel.backup_id == str(backup_id))
        total_items = query.count()

        query = query.order_by(MessageOverrideModel.created_at.desc(), MessageOverrideModel.pk.desc())
        offset = (page - 1) * per_page
        overrides_raw = query.offset(offset).limit(per_page).all()

        formatted = []
        for o in overrides_raw:
            channel = o.channel
            chan_id = channel.discord_id if channel else ""
            chan_name = channel.name if channel else ""

            discord_link = ""
            if server_id and chan_id and o.message_id:
                discord_link = f"https://discord.com/channels/{server_id}/{chan_id}/{o.message_id}"

            formatted.append({
                "id": o.pk,
                "message_id": o.message_id,
                "channel_name": chan_name,
                "channel_discord_id": chan_id,
                "content": o.content,
                "author": o.author,
                "discord_link": discord_link,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            })

        total_pages = math.ceil(total_items / per_page) if per_page > 0 else 1
        return {
            "total_items": total_items,
            "current_page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "overrides": formatted,
        }


def delete_message_override(backup_id: str, base_path: str, message_id: str) -> Dict[str, Any]:
    """Deletes an active message override."""
    require_sqlite_db(base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        override = (
            session.query(MessageOverrideModel)
            .filter(
                MessageOverrideModel.backup_id == str(backup_id),
                MessageOverrideModel.message_id == str(message_id),
            )
            .first()
        )
        if not override:
            raise ValueError(f"Message override #{message_id} not found.")

        session.delete(override)
        session.flush()

        return {"status": "success", "deleted_override_message_id": message_id}


def get_overrides_map(backup_id: str, base_path: str) -> Dict[str, Dict[str, Any]]:
    """
    Returns a dictionary mapping message_id -> {"content": ..., "author": ...}
    for all active message overrides in SQLite.
    """
    require_sqlite_db(base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        overrides = session.query(MessageOverrideModel).filter(
            MessageOverrideModel.backup_id == str(backup_id)
        ).all()
        return {
            str(o.message_id): {
                "content": o.content,
                "author": o.author,
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
    Replaces FlaggedMessageModel rows in SQLite with newly discovered flagged messages from fix_bad_messages.
    Optionally exports debug JSON snapshots (bad_messages.json, bad_end_messages.json, fixed_messages.json).
    """
    require_sqlite_db(base_path)
    now_utc = datetime.now(timezone.utc)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        # Clear previous flagged messages
        session.query(FlaggedMessageModel).filter(
            FlaggedMessageModel.backup_id == str(backup_id)
        ).delete()

        # Build discord_id -> channel_pk map
        channels = session.query(ChannelModel).join(ExportModel).filter(
            ExportModel.backup_id == str(backup_id),
            ExportModel.scope == Scope.BASE.value
        ).all()
        chan_map = {ch.discord_id: ch.pk for ch in channels}

        for item in flagged_items:
            chan_discord_id = str(item.get("channel_discord_id") or "")
            flagged = FlaggedMessageModel(
                backup_id=str(backup_id),
                message_id=str(item["message_id"]),
                channel_pk=chan_map.get(chan_discord_id),
                kind=str(item.get("kind", "non_tupper")),
                content=str(item.get("content", "")),
                author=item.get("author", {}),
                flagged_at=item.get("flagged_at") or now_utc,
            )
            session.add(flagged)

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
    require_sqlite_db(base_path)

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


def get_curation_summary(backup_id: str, base_path: str) -> Dict[str, int]:
    """Returns real-time badge counts for curation review queues and unassigned data."""
    require_sqlite_db(base_path)
    suggestions = get_writer_link_suggestions(backup_id, base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
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
                FlaggedMessageModel.backup_id == str(backup_id)
            ).scalar() or 0,
            "unlinked_writers": session.query(func.count(WriterModel.pk)).filter(
                WriterModel.backup_id == str(backup_id),
                WriterModel.discord_user_id.is_(None)
            ).scalar() or 0,
            "link_suggestions": len(suggestions),
        }



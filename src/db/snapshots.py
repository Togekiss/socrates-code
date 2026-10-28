from fastapi import background
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from utils.tricks import save_json_atomic, get_backup_path, is_debug_files_enabled
from utils import exceptions as exc
from .models import (
    BackupModel,
    ExportModel,
    BackupStepModel,
    ChannelModel,
    WriterModel,
    CharacterGroupModel,
    CharacterModel,
    SceneModel,
    Scope,
    Step,
    Status,
    FlaggedMessageModel,
    FlaggedKind,
    FlaggedResolution,
)


def export_backup_info_snapshot(
    session: Session,
    backup_id: str,
    target_path: Optional[str] = None,
    scope: str = "base",
    write_to_disk: bool = True
) -> Dict[str, Any]:
    """
    Reconstructs and optionally atomically writes the human-readable backup_info.json snapshot
    from the database tables (backups, exports, backup_steps, channels, scenes).
    """
    if not is_debug_files_enabled(backup_id=backup_id):
        write_to_disk = False

    backup = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
    if not backup:
        raise exc.BackupError(f"Backup with id '{backup_id}' not found in database.")

    export = session.query(ExportModel).filter(
        ExportModel.backup_id == str(backup_id),
        ExportModel.scope == str(scope)
    ).first()
    if not export:
        raise exc.BackupError(f"Export scope '{scope}' for backup '{backup_id}' not found in database.")

    # Reconstruct steps dictionary
    steps = session.query(BackupStepModel).filter(BackupStepModel.export_pk == export.pk).all()
    steps_dict = {step.step: step.status for step in steps}

    # Determine overall status
    effective_steps = [s for s in steps if s.step != Step.UPDATE.value] if scope == Scope.BASE.value else steps
    if all(s.status == Status.SUCCESS.value for s in effective_steps) and effective_steps:
        overall_status = Status.SUCCESS.value
    elif any(s.status == Status.FAILED.value for s in effective_steps):
        overall_status = Status.FAILED.value
    elif any(s.status == Status.RUNNING.value for s in effective_steps):
        overall_status = Status.RUNNING.value
    else:
        overall_status = Status.PENDING.value

    # Scene counts indexed by channel_pk and category_pk
    scene_counts_by_channel = dict(
        session.query(SceneModel.channel_pk, func.count(SceneModel.pk))
        .filter(SceneModel.backup_id == str(backup_id))
        .group_by(SceneModel.channel_pk)
        .all()
    )
    scene_counts_by_category = dict(
        session.query(SceneModel.category_pk, func.count(SceneModel.pk))
        .filter(SceneModel.backup_id == str(backup_id))
        .group_by(SceneModel.category_pk)
        .all()
    )
    total_scenes = session.query(func.count(SceneModel.pk)).filter(
        SceneModel.backup_id == str(backup_id)
    ).scalar() or 0

    # Query all channels belonging to this export
    all_channels = session.query(ChannelModel).filter(
        ChannelModel.export_pk == export.pk
    ).all()

    categories = [c for c in all_channels if c.type == "GuildCategory"]
    categories.sort(key=lambda c: c.position)

    category_map = {c.pk: c for c in categories}
    channels_by_category: Dict[int, List[ChannelModel]] = {c.pk: [] for c in categories}
    threads_by_channel: Dict[int, List[ChannelModel]] = {}

    for ch in all_channels:
        if ch.type == "GuildCategory":
            continue
        if ch.parent_pk in category_map:
            channels_by_category[ch.parent_pk].append(ch)
            threads_by_channel[ch.pk] = []

    for ch in all_channels:
        if ch.parent_pk in threads_by_channel:
            threads_by_channel[ch.parent_pk].append(ch)

    total_category_count = len(categories)
    total_channel_count = 0
    total_thread_count = 0

    categories_json = []
    for cat in categories:
        cat_channels = channels_by_category.get(cat.pk, [])
        cat_channels.sort(key=lambda x: x.position)
        total_channel_count += len(cat_channels)

        cat_threads_count = 0
        channels_json = []

        for chan in cat_channels:
            chan_threads = threads_by_channel.get(chan.pk, [])
            chan_threads.sort(key=lambda x: x.position)
            cat_threads_count += len(chan_threads)
            total_thread_count += len(chan_threads)

            threads_json = []
            for thr in chan_threads:
                threads_json.append({
                    "id": thr.discord_id,
                    "name": thr.name,
                    "position": thr.position,
                    "path": thr.path,
                    "is_deleted": thr.is_deleted,
                    "number_of_messages": thr.message_count or 0,
                    "number_of_scenes": scene_counts_by_channel.get(thr.pk, 0),
                })

            chan_data: Dict[str, Any] = {
                "id": chan.discord_id,
                "name": chan.name,
                "position": chan.position,
                "path": chan.path,
                "is_deleted": chan.is_deleted,
                "number_of_messages": chan.message_count or 0,
                "number_of_scenes": scene_counts_by_channel.get(chan.pk, 0),
                "number_of_threads": len(chan_threads),
            }
            if chan_threads:
                chan_data["threads"] = threads_json

            channels_json.append(chan_data)

        cat_data: Dict[str, Any] = {
            "id": cat.discord_id,
            "name": cat.name,
            "position": cat.position,
            "path": cat.path,
            "is_deleted": cat.is_deleted,
            "number_of_scenes": scene_counts_by_category.get(cat.pk, 0),
            "number_of_channels": len(cat_channels),
            "number_of_threads": cat_threads_count,
            "channels": channels_json,
        }
        categories_json.append(cat_data)

    snapshot: Dict[str, Any] = {
        "id": backup.server_id or "",
        "name": backup.server_name or "",
        "updated_at": export.updated_at.isoformat() if export.updated_at else datetime.now(timezone.utc).isoformat(),
        "exported_from": export.exported_from.isoformat() if export.exported_from else "",
        "exported_at": export.exported_at.isoformat() if export.exported_at else "",
        "status": overall_status,
        "steps": steps_dict,
        "number_of_categories": total_category_count,
        "number_of_channels": total_channel_count,
        "number_of_threads": total_thread_count,
        "number_of_scenes": total_scenes,
        "categories": categories_json,
    }

    if write_to_disk:
        if not target_path:
            backup_path = get_backup_path(backup_id)
            filename = "backup_info.json" if scope == "base" else "backup_info_update.json"
            target_path = (Path(backup_path) / "Info" / filename).as_posix()
        save_json_atomic(snapshot, target_path)

    return snapshot


def export_character_list_snapshot(
    session: Session,
    backup_id: str,
    target_path: Optional[str] = None,
    write_to_disk: bool = True
) -> Dict[str, Any]:
    """
    Reconstructs and optionally atomically writes the human-readable character_list.json snapshot
    from the database tables (writers, character_groups, characters, character_names).
    """

    if not is_debug_files_enabled(backup_id=backup_id):
        write_to_disk = False

    # 1. Query writers
    writers = session.query(WriterModel).filter(
        WriterModel.backup_id == str(backup_id)
    ).order_by(WriterModel.pk).all()

    writers_json = []
    for w in writers:
        aliases = [a.alias for a in sorted(w.aliases, key=lambda a: a.pk)]
        writers_json.append({
            "id": w.pk,
            "display_name": w.display_name,
            "discord_user_id": w.discord_user_id,
            "aliases": aliases,
        })

    # 2. Query groups
    groups = session.query(CharacterGroupModel).filter(
        CharacterGroupModel.backup_id == str(backup_id)
    ).order_by(CharacterGroupModel.pk).all()

    groups_json = []
    for g in groups:
        group_names = [n.name for n in sorted(g.names, key=lambda n: n.position)]
        member_ids = [c.char_id for c in sorted(g.characters, key=lambda c: c.char_id)]
        groups_json.append({
            "id": g.pk,
            "names": group_names,
            "members": member_ids,
        })

    # 3. Query top-level characters (parent_pk IS NULL)
    top_characters = session.query(CharacterModel).filter(
        CharacterModel.backup_id == str(backup_id),
        CharacterModel.parent_pk.is_(None)
    ).order_by(CharacterModel.char_id).all()

    characters_json = []
    for c in top_characters:
        names = [n.name for n in sorted(c.names, key=lambda n: n.position)]
        
        # Nested tuppers
        tuppers_json = []
        for child in sorted(c.children, key=lambda ch: ch.char_id):
            child_names = [n.name for n in sorted(child.names, key=lambda n: n.position)]
            tuppers_json.append({
                "char_id": child.char_id,
                "names": child_names,
                "writer_id": child.writer_pk,
                "version_type": child.version_type,
                "origin": child.origin,
                "activity": child.activity,
            })

        char_entry: Dict[str, Any] = {
            "char_id": c.char_id,
            "names": names,
            "writer_id": c.writer_pk,
            "group_id": c.group_pk,
            "version_type": c.version_type,
            "origin": c.origin,
            "activity": c.activity,
            "tuppers": tuppers_json,
        }
        characters_json.append(char_entry)

    snapshot: Dict[str, Any] = {
        "backup_id": str(backup_id),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "writers": writers_json,
        "groups": groups_json,
        "characters": characters_json,
    }

    if write_to_disk:
        if not target_path:
            backup_path = get_backup_path(backup_id)
            target_path = (Path(backup_path) / "Info" / "character_list.json").as_posix()
        save_json_atomic(snapshot, target_path)

    return snapshot


def export_curation_snapshots(
    session: Session,
    backup_id: str,
    backup_path: Optional[str] = None
) -> None:
    """
    Exports auxiliary debug snapshots (fixed_messages.json, bad_messages.json, bad_end_messages.json)
    from SQLite tables into the Info/ folder.
    """

    if not is_debug_files_enabled(backup_id=backup_id):
        return
        
    if not backup_path:
        backup_path = get_backup_path(backup_id)

    info_dir = Path(backup_path) / "Info"
    info_dir.mkdir(parents=True, exist_ok=True)

    backup = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
    server_id = backup.server_id if backup and backup.server_id else ""

    # 1. Message overrides -> fixed_messages.json
    overrides = session.query(FlaggedMessageModel).filter(
        FlaggedMessageModel.backup_id == str(backup_id),
        FlaggedMessageModel.resolution == FlaggedResolution.OVERRIDE.value,
    ).all()
    fixed_messages_data = {
        str(o.message_id): {
            "content": o.override_content or o.content,
            "author": o.override_author or o.author,
        }
        for o in overrides
    }
    save_json_atomic(fixed_messages_data, (info_dir / "fixed_messages.json").as_posix())

    # 2. Flagged messages -> bad_messages.json & bad_end_messages.json
    flagged = session.query(FlaggedMessageModel).filter(
        FlaggedMessageModel.backup_id == str(backup_id),
        FlaggedMessageModel.resolved_at.is_(None),
    ).all()

    bad_messages_data = {}
    bad_end_messages_data = {}

    for f in flagged:
        channel_discord_id = f.channel.discord_id if f.channel else ""
        link = (
            f"https://discord.com/channels/{server_id}/{channel_discord_id}/{f.message_id}"
            if server_id and channel_discord_id and f.message_id
            else ""
        )
        entry = {
            "content": f.content,
            "author": f.author,
            "link": link,
        }
        if f.kind in (FlaggedKind.OOC_BOUNDARY.value, "non_tupper_end_tag"):
            bad_end_messages_data[str(f.message_id)] = entry
        else:
            bad_messages_data[str(f.message_id)] = entry

    save_json_atomic(bad_messages_data, (info_dir / "bad_messages.json").as_posix())
    save_json_atomic(bad_end_messages_data, (info_dir / "bad_end_messages.json").as_posix())



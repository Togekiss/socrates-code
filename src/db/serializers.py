from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import func, inspect
from sqlalchemy.orm import Session, selectinload

import utils.tricks as t
from utils import exceptions as exc
from .models import (
    BackupModel,
    ChannelModel,
    CharacterGroupModel,
    CharacterModel,
    EventModel,
    SceneKind,
    SceneModel,
    Scope,
    Status,
    Step,
    StorageMode,
    SyncStatus,
    WriterModel,
)

_STEP_CACHE_LOCK = threading.RLock()
_RUNTIME_STEP_OVERRIDES: Dict[Tuple[str, str], Dict[str, str]] = {}


def set_runtime_step_override(backup_id: str, scope: str, step: str, status: str) -> None:
    with _STEP_CACHE_LOCK:
        _RUNTIME_STEP_OVERRIDES.setdefault((str(backup_id), str(scope)), {})[str(step)] = str(status)


def clear_runtime_step_overrides(backup_id: str, scope: Optional[str] = None) -> None:
    with _STEP_CACHE_LOCK:
        if scope is None:
            keys = [k for k in _RUNTIME_STEP_OVERRIDES if k[0] == str(backup_id)]
            for k in keys:
                _RUNTIME_STEP_OVERRIDES.pop(k, None)
        else:
            _RUNTIME_STEP_OVERRIDES.pop((str(backup_id), str(scope)), None)


def synthesize_legacy_steps(
    backup: BackupModel,
    scope: str = "base",
    has_channels: bool = False,
) -> Tuple[str, Dict[str, str]]:
    """Synthesizes backward-compatible 'status' and 'steps' dict from Schema v6 BackupModel."""
    sync_status = getattr(backup, "sync_status", None) or SyncStatus.IDLE.value
    last_synced_at = getattr(backup, "last_synced_at", None)
    is_initialized = (last_synced_at is not None) or has_channels

    steps_dict: Dict[str, str] = {}
    for st in Step:
        if scope == Scope.BASE.value and st != Step.UPDATE and is_initialized:
            steps_dict[st.value] = Status.SUCCESS.value
        else:
            steps_dict[st.value] = Status.PENDING.value

    cache_key = (str(backup.backup_id), str(scope))
    with _STEP_CACHE_LOCK:
        bucket = _RUNTIME_STEP_OVERRIDES.get(cache_key)
        if bucket and sync_status == SyncStatus.IDLE.value:
            stale_keys = [
                k for k, v in bucket.items()
                if v in (Status.RUNNING.value, Status.FAILED.value)
            ]
            for k in stale_keys:
                bucket.pop(k, None)
            if not bucket:
                _RUNTIME_STEP_OVERRIDES.pop(cache_key, None)
        overrides = dict(_RUNTIME_STEP_OVERRIDES.get(cache_key, {}))

    for step_key, step_status in overrides.items():
        steps_dict[step_key] = step_status

    if sync_status == SyncStatus.SYNCING.value:
        if not any(v == Status.RUNNING.value for v in steps_dict.values()):
            fallback_step = Step.UPDATE.value if scope == Scope.UPDATE.value else Step.INDEX_SCENES.value
            steps_dict[fallback_step] = Status.RUNNING.value
    elif sync_status == SyncStatus.FAILED.value:
        if not any(v == Status.FAILED.value for v in steps_dict.values()):
            running_steps = [k for k, v in steps_dict.items() if v == Status.RUNNING.value]
            if running_steps:
                for k in running_steps:
                    steps_dict[k] = Status.FAILED.value
            else:
                fallback_step = Step.UPDATE.value if scope == Scope.UPDATE.value else Step.INDEX_SCENES.value
                steps_dict[fallback_step] = Status.FAILED.value
    elif sync_status == SyncStatus.IDLE.value:
        for k, v in list(steps_dict.items()):
            if v == Status.RUNNING.value:
                steps_dict[k] = Status.SUCCESS.value

    effective_steps = [v for k, v in steps_dict.items() if k != Step.UPDATE.value] if scope == Scope.BASE.value else list(steps_dict.values())
    if sync_status == SyncStatus.SYNCING.value or any(v == Status.RUNNING.value for v in effective_steps):
        overall_status = Status.RUNNING.value
    elif sync_status == SyncStatus.FAILED.value or any(v == Status.FAILED.value for v in effective_steps):
        overall_status = Status.FAILED.value
    elif effective_steps and all(v == Status.SUCCESS.value for v in effective_steps):
        overall_status = Status.SUCCESS.value
    else:
        overall_status = Status.PENDING.value

    return overall_status, steps_dict


def build_backup_info_dict(
    session: Session,
    backup_id: str,
    scope: str = "base",
    is_schema_outdated: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Pure in-memory ORM-to-dict serializer for backup_info state (Schema v6)
    (backups, channels, scenes, events). Never writes to disk or checks debugFiles.
    """
    backup = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
    if not backup:
        raise exc.BackupError(f"Backup with id '{backup_id}' not found in database.")

    # Query all channels belonging to this backup directly (Schema v6)
    all_channels = session.query(ChannelModel).filter(
        ChannelModel.backup_id == str(backup_id)
    ).all()

    overall_status, steps_dict = synthesize_legacy_steps(
        backup, scope=scope, has_channels=bool(all_channels)
    )

    # Scene & event counts indexed by channel_pk and category_pk
    scene_counts_by_channel: Dict[int, int] = {}
    scene_counts_by_category: Dict[int, int] = {}
    total_scenes = 0
    total_sessions = 0
    total_events = 0

    existing_tables: Optional[set] = None
    if is_schema_outdated:
        try:
            existing_tables = set(inspect(session.get_bind()).get_table_names())
        except Exception:
            existing_tables = None

    if existing_tables is None or "events" in existing_tables:
        try:
            total_events = session.query(func.count(EventModel.pk)).filter(
                EventModel.backup_id == str(backup_id),
            ).scalar() or 0
        except Exception as e:
            session.rollback()
            err_line = str(e).splitlines()[0] if str(e) else type(e).__name__
            t.log("debug", f"Failed to count events for backup {backup_id}: {err_line}")

    if existing_tables is None or "scenes" in existing_tables:
        try:
            scene_counts_by_channel = dict(
                session.query(SceneModel.channel_pk, func.count(SceneModel.pk))
                .filter(SceneModel.backup_id == str(backup_id), SceneModel.kind == SceneKind.SCENE.value)
                .group_by(SceneModel.channel_pk)
                .all()
            )
            scene_counts_by_category = dict(
                session.query(SceneModel.category_pk, func.count(SceneModel.pk))
                .filter(SceneModel.backup_id == str(backup_id), SceneModel.kind == SceneKind.SCENE.value)
                .group_by(SceneModel.category_pk)
                .all()
            )
            total_scenes = session.query(func.count(SceneModel.pk)).filter(
                SceneModel.backup_id == str(backup_id),
                SceneModel.kind == SceneKind.SCENE.value,
            ).scalar() or 0
            total_sessions = session.query(func.count(SceneModel.pk)).filter(
                SceneModel.backup_id == str(backup_id),
                SceneModel.kind == SceneKind.SESSION.value,
            ).scalar() or 0
        except Exception as e:
            session.rollback()
            # Fallback for legacy schemas lacking scenes.kind
            try:
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
                    SceneModel.backup_id == str(backup_id),
                ).scalar() or 0
                total_sessions = 0
            except Exception as fallback_e:
                session.rollback()
                err_line = str(e).splitlines()[0] if str(e) else type(e).__name__
                fb_line = str(fallback_e).splitlines()[0] if str(fallback_e) else type(fallback_e).__name__
                t.log("debug", f"Failed to calculate scene counts for backup {backup_id}: {err_line} (fallback: {fb_line})")

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

    last_synced_iso = backup.last_synced_at.isoformat() if backup.last_synced_at else None
    sync_started_iso = backup.sync_started_at.isoformat() if backup.sync_started_at else None
    created_iso = backup.created_at.isoformat() if backup.created_at else None

    return {
        "id": backup.server_id or "",
        "name": backup.server_name or "",
        "updated_at": last_synced_iso or created_iso or datetime.now(timezone.utc).isoformat(),
        "exported_from": "",
        "exported_at": created_iso or last_synced_iso or "",
        "storage_mode": getattr(backup, "storage_mode", StorageMode.BACKUPLESS.value),
        "sync_status": getattr(backup, "sync_status", SyncStatus.IDLE.value),
        "sync_started_at": sync_started_iso,
        "last_synced_at": last_synced_iso,
        "sync_error": getattr(backup, "sync_error", None),
        "channels_total": int(getattr(backup, "channels_total", 0) or 0),
        "channels_done": int(getattr(backup, "channels_done", 0) or 0),
        "status": overall_status,
        "steps": steps_dict,
        "number_of_categories": total_category_count,
        "number_of_channels": total_channel_count,
        "number_of_threads": total_thread_count,
        "number_of_scenes": total_scenes,
        "number_of_sessions": total_sessions,
        "number_of_events": total_events,
        "categories": categories_json,
    }


def build_character_list_dict(
    session: Session,
    backup_id: str,
) -> Dict[str, Any]:
    """
    Pure in-memory ORM-to-dict serializer for character_list
    (writers, character_groups, characters, character_names).
    Uses selectinload to avoid N+1 queries. Never writes to disk.
    """
    # 1. Query writers with eager-loaded aliases
    writers = (
        session.query(WriterModel)
        .options(selectinload(WriterModel.aliases))
        .filter(WriterModel.backup_id == str(backup_id))
        .order_by(WriterModel.pk)
        .all()
    )

    writers_json = []
    for w in writers:
        aliases = [a.alias for a in sorted(w.aliases, key=lambda a: a.pk)]
        writers_json.append({
            "id": w.pk,
            "display_name": w.display_name,
            "discord_user_id": w.discord_user_id,
            "aliases": aliases,
        })

    # 2. Query groups with eager-loaded names & characters
    groups = (
        session.query(CharacterGroupModel)
        .options(
            selectinload(CharacterGroupModel.names),
            selectinload(CharacterGroupModel.characters),
        )
        .filter(CharacterGroupModel.backup_id == str(backup_id))
        .order_by(CharacterGroupModel.pk)
        .all()
    )

    groups_json = []
    for g in groups:
        group_names = [n.name for n in sorted(g.names, key=lambda n: n.position)]
        member_ids = [c.char_id for c in sorted(g.characters, key=lambda c: c.char_id)]
        groups_json.append({
            "id": g.pk,
            "names": group_names,
            "members": member_ids,
        })

    # 3. Query top-level characters (parent_pk IS NULL) with eager-loaded names & children
    top_characters = (
        session.query(CharacterModel)
        .options(
            selectinload(CharacterModel.names),
            selectinload(CharacterModel.children).selectinload(CharacterModel.names),
        )
        .filter(
            CharacterModel.backup_id == str(backup_id),
            CharacterModel.parent_pk.is_(None),
        )
        .order_by(CharacterModel.char_id)
        .all()
    )

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

    return {
        "backup_id": str(backup_id),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "writers": writers_json,
        "groups": groups_json,
        "characters": characters_json,
    }

"""
Unified Resumable Per-Channel Atomic Sync Orchestrator.

Replaces the legacy 8-step DCE/JSON pipeline (`get_server_info` -> `download_channels` ->
`verify_download` -> `update_paths` -> `merge_exports` -> `fix_bad_messages` -> `index_scenes`)
with one streaming per-channel pipeline supporting both `storage_mode == "backupless"`
(zero Data/*.json files) and `storage_mode == "full"` (in-place DCE §7 JSON extension).
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import signal
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import httpx
from sqlalchemy import BigInteger, cast, func

import utils.exceptions as exc
import utils.tricks as t
from utils.path_safety import category_name_matches, expand_category_names
from assign_ids import assign_ids_in_memory
from db import curation_service
from db.event_service import save_indexed_events
from db.models import (
    BackupModel,
    ChannelModel,
    FlaggedMessageModel,
    SceneIssueModel,
    SceneKind,
    SceneModel,
    SeenDiscordUserModel,
    StorageMode,
    SyncStatus,
)
from db.scene_service import (
    load_channel_skeletons,
    save_channel_indexed_scenes,
    upsert_channel_skeletons,
)
from db.serializers import clear_runtime_step_overrides
from db.session import (
    close_all_engines,
    db_session,
    get_skeleton_engine,
    init_db,
    is_sqlite_tmp_cache_enabled,
    skeleton_db_session,
    sync_dirty_sqlite_dbs,
)
from db.skeleton_models import MessageSkeletonModel, SkeletonFlags, TUPPER_ID_MAX
from db.snapshots import (
    export_backup_info_snapshot,
    export_character_list_snapshot,
    export_curation_snapshots,
)
from discord_extractor import (
    ChannelAccessError,
    DiscordExtractor,
    ServerTopology,
    SyncableChannelItem,
    compute_effective_after_snowflake,
    extend_channel_json_atomic,
    should_skip_channel_sync,
    sync_full_mode_channel_paths,
)
from fix_bad_messages import (
    build_skeletons_from_messages,
    collect_channel_flagged_messages,
    prepare_channel_skeletons,
)
from index_events import index_event_categories
from index_scenes import find_all_scenes_in_channel, _load_db_excerpts_map
from index_sessions import find_all_sessions_in_channel
from models import CharacterList, ServerBackup

t.set_path()
from res import constants as c

_SYNC_LOCK_GUARD = threading.Lock()
_ACTIVE_SYNC_PATHS: Set[str] = set()


def _canonical_sync_key(backup_path: str) -> str:
    return Path(backup_path).resolve().as_posix()


def _sync_lock_file_path(backup_path: str) -> Path:
    return Path(backup_path).resolve() / ".sync.lock"


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    if os.name == "nt":
        try:
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return int(kernel32.GetLastError()) == 5
            try:
                exit_code = ctypes.c_ulong()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return exit_code.value == STILL_ACTIVE
                return True
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _read_lock_pid(lock_path: Path) -> Optional[int]:
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
        if raw.isdigit():
            return int(raw)
    except OSError:
        pass
    return None


def is_sync_lock_held(backup_path: Optional[str]) -> bool:
    """Returns True if an active in-process or external-process sync lock exists for backup_path."""
    if not backup_path:
        return False
    canon = _canonical_sync_key(backup_path)
    lock_path = _sync_lock_file_path(backup_path)
    with _SYNC_LOCK_GUARD:
        if canon in _ACTIVE_SYNC_PATHS:
            return True
        if lock_path.is_file():
            pid = _read_lock_pid(lock_path)
            if pid is not None and _is_pid_alive(pid):
                return True
    return False


def _acquire_sync_lock(backup_path: str) -> None:
    canon = _canonical_sync_key(backup_path)
    lock_path = _sync_lock_file_path(backup_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _SYNC_LOCK_GUARD:
        if canon in _ACTIVE_SYNC_PATHS:
            raise exc.AlreadyRunningError("The backup sync is already running in another process.")

        for _attempt in range(2):
            if lock_path.is_file():
                existing_pid = _read_lock_pid(lock_path)
                if existing_pid is not None and _is_pid_alive(existing_pid):
                    raise exc.AlreadyRunningError("The backup sync is already running in another process.")
                try:
                    lock_path.unlink(missing_ok=True)
                except OSError:
                    raise exc.AlreadyRunningError("The backup sync is already running in another process.")
            try:
                fd = os.open(lock_path.as_posix(), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, str(os.getpid()).encode("ascii"))
                finally:
                    os.close(fd)
                _ACTIVE_SYNC_PATHS.add(canon)
                return
            except FileExistsError:
                existing_pid = _read_lock_pid(lock_path)
                if existing_pid is not None and _is_pid_alive(existing_pid):
                    raise exc.AlreadyRunningError("The backup sync is already running in another process.")
        raise exc.AlreadyRunningError("The backup sync is already running in another process.")


def _release_sync_lock(backup_path: str) -> None:
    canon = _canonical_sync_key(backup_path)
    lock_path = _sync_lock_file_path(backup_path)
    with _SYNC_LOCK_GUARD:
        _ACTIVE_SYNC_PATHS.discard(canon)
        if lock_path.is_file():
            pid = _read_lock_pid(lock_path)
            if pid is None or pid == os.getpid() or not _is_pid_alive(pid):
                try:
                    lock_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _prune_orphan_data_jsons(data_dir: Path, active_rel_paths: Set[str]) -> int:
    """
    Removes stale/orphan *.json files under `data_dir` not present in `active_rel_paths`,
    then cleans up resulting empty subdirectories without touching `data_dir` itself.
    """
    if not data_dir.is_dir():
        return 0
    removed = 0
    for json_file in list(data_dir.rglob("*.json")):
        try:
            rel_posix = json_file.relative_to(data_dir).as_posix()
        except ValueError:
            continue
        if rel_posix not in active_rel_paths:
            try:
                json_file.unlink()
                removed += 1
            except OSError:
                pass
    for root, dirs, _files in os.walk(data_dir, topdown=False):
        root_path = Path(root)
        if root_path == data_dir:
            continue
        try:
            if not any(root_path.iterdir()):
                root_path.rmdir()
        except OSError:
            pass
    return removed


def _resolve_storage_mode(backup_path: str, existing_mode: Optional[str] = None) -> str:
    cfg_file = Path(backup_path) / "backup_config.json"
    if cfg_file.is_file():
        try:
            cfg = t.load_from_json(cfg_file.as_posix())
            mode = (cfg.get("admin") or {}).get("storageMode") or cfg.get("storageMode")
            if mode in (StorageMode.BACKUPLESS.value, StorageMode.FULL.value):
                return str(mode)
        except Exception:
            pass
    if existing_mode in (StorageMode.BACKUPLESS.value, StorageMode.FULL.value):
        return str(existing_mode)
    return StorageMode.BACKUPLESS.value


def _ensure_backup_bootstrap(
    backup_id: Optional[str],
    backup_path: Optional[str],
) -> Tuple[str, str]:
    b_id = str(backup_id or getattr(c, "BACKUP_ID", "") or "").strip()
    b_path = str(backup_path or getattr(c, "BACKUP_BASE", "") or "").strip()
    if not b_path and b_id:
        b_path = t.get_backup_path(b_id)
    if not b_path:
        raise exc.BackupError("Cannot run backup_server without backup_path or backup_id.")

    b_dir = Path(b_path)
    info_dir = b_dir / "Info"
    info_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = b_dir / "backup_config.json"
    if not cfg_path.is_file() and Path(c.GLOBAL_CONFIG).is_file():
        shutil.copyfile(c.GLOBAL_CONFIG, cfg_path.as_posix())

    if not b_id:
        rel_path = b_path
        try:
            rel_path = b_dir.relative_to(c.DATA_ROOT).as_posix()
        except ValueError:
            pass
        b_id = t.add_backup_to_index(
            getattr(c, "BACKUP_NAME", b_dir.name) or b_dir.name,
            getattr(c, "SERVER_ID", "") or "",
            getattr(c, "SERVER_NAME", "") or "",
            rel_path,
        )

    return b_id, b_path


def _sync_topology_to_db(
    session,
    backup_id: str,
    topology: ServerTopology,
    *,
    is_resume: bool,
    storage_mode: str,
) -> Tuple[Dict[str, ChannelModel], List[Tuple[str, str]]]:
    """
    Upserts categories, channels, and threads from `topology` into `channels` table.
    Preserves existing `ChannelModel.pk`, skeletons, scenes, and issues.
    Marks channels absent from `topology` as `is_deleted = True` (never cascade-deleting them).
    Returns `(chan_by_discord_id, path_renames)` where `path_renames` lists `(old_path, new_path)`.
    """
    existing = session.query(ChannelModel).filter(ChannelModel.backup_id == str(backup_id)).all()
    by_discord_id: Dict[str, ChannelModel] = {ch.discord_id: ch for ch in existing}
    seen_ids: Set[str] = set()
    path_renames: List[Tuple[str, str]] = []

    for cat in topology.categories:
        cat_did = str(cat.id)
        seen_ids.add(cat_did)
        cat_m = by_discord_id.get(cat_did)
        if cat_m is None:
            cat_m = ChannelModel(
                backup_id=str(backup_id),
                discord_id=cat_did,
                type="GuildCategory",
                parent_pk=None,
                name=str(cat.name)[:64],
                position=int(cat.position),
                path=str(cat.path)[:255],
                is_deleted=False,
                sync_status="synced",
            )
            session.add(cat_m)
            session.flush()
            by_discord_id[cat_did] = cat_m
        else:
            cat_m.name = str(cat.name)[:64]
            cat_m.position = int(cat.position)
            cat_m.path = str(cat.path)[:255]
            cat_m.is_deleted = False

        for ch in cat.channels:
            ch_did = str(ch.id)
            seen_ids.add(ch_did)
            raw_ch = topology.channels_by_id.get(ch_did) or {}
            ch_type_int = raw_ch.get("type", 0)
            ch_type_str = "GuildForum" if ch_type_int == 15 else "GuildTextChat"
            ch_m = by_discord_id.get(ch_did)
            if ch_m is None:
                ch_m = ChannelModel(
                    backup_id=str(backup_id),
                    discord_id=ch_did,
                    type=ch_type_str,
                    parent_pk=cat_m.pk,
                    name=str(ch.name)[:64],
                    position=int(ch.position),
                    path=str(ch.path)[:255],
                    is_deleted=False,
                    sync_status="pending",
                )
                session.add(ch_m)
                session.flush()
                by_discord_id[ch_did] = ch_m
            else:
                if ch_m.path and ch_m.path != str(ch.path)[:255]:
                    path_renames.append((ch_m.path, str(ch.path)[:255]))
                ch_m.parent_pk = cat_m.pk
                ch_m.type = ch_type_str
                ch_m.name = str(ch.name)[:64]
                ch_m.position = int(ch.position)
                ch_m.path = str(ch.path)[:255]
                ch_m.is_deleted = False
                if not is_resume:
                    ch_m.sync_status = "pending"
                    ch_m.sync_error = None

            for th in ch.threads:
                th_did = str(th.id)
                seen_ids.add(th_did)
                th_m = by_discord_id.get(th_did)
                if th_m is None:
                    th_m = ChannelModel(
                        backup_id=str(backup_id),
                        discord_id=th_did,
                        type="GuildPublicThread",
                        parent_pk=ch_m.pk,
                        name=str(th.name)[:64],
                        position=int(th.position),
                        path=str(th.path)[:255],
                        is_deleted=False,
                        sync_status="pending",
                    )
                    session.add(th_m)
                    session.flush()
                    by_discord_id[th_did] = th_m
                else:
                    if th_m.path and th_m.path != str(th.path)[:255]:
                        path_renames.append((th_m.path, str(th.path)[:255]))
                    th_m.parent_pk = ch_m.pk
                    th_m.type = "GuildPublicThread"
                    th_m.name = str(th.name)[:64]
                    th_m.position = int(th.position)
                    th_m.path = str(th.path)[:255]
                    th_m.is_deleted = False
                    if not is_resume:
                        th_m.sync_status = "pending"
                        th_m.sync_error = None

    for ch in existing:
        if ch.discord_id not in seen_ids:
            ch.is_deleted = True

    session.flush()
    return by_discord_id, path_renames


def _upsert_guild_members_to_seen_users(
    session,
    backup_id: str,
    members_by_id: Dict[str, Dict[str, Any]],
) -> None:
    if not members_by_id:
        return
    existing = {
        u.discord_user_id: u
        for u in session.query(SeenDiscordUserModel).filter(
            SeenDiscordUserModel.backup_id == str(backup_id)
        ).all()
    }
    member_uids: Set[str] = set()
    for uid, mem in members_by_id.items():
        usr = mem.get("user") or {}
        if usr.get("bot"):
            continue
        uid_str = str(uid).strip()
        if not uid_str.isdigit() or int(uid_str) < TUPPER_ID_MAX:
            continue
        member_uids.add(uid_str)
        username = str(usr.get("username") or f"User #{uid_str}")[:128]
        global_name = (str(usr.get("global_name") or "").strip()[:128]) or None
        nick = (str(mem.get("nick") or "").strip()[:128]) or None

        row = existing.get(uid_str)
        if row is None:
            session.add(
                SeenDiscordUserModel(
                    backup_id=str(backup_id),
                    discord_user_id=uid_str,
                    username=username,
                    global_name=global_name,
                    nickname=nick,
                    is_current_member=True,
                    message_count=0,
                    last_seen_at=None,
                )
            )
        else:
            row.username = username
            if global_name is not None:
                row.global_name = global_name
            if nick is not None:
                row.nickname = nick
            row.is_current_member = True

    for uid_str, row in existing.items():
        if uid_str not in member_uids:
            row.is_current_member = False
    session.flush()


def _upsert_channel_seen_users(
    session,
    backup_id: str,
    seen_users_delta: Dict[str, Dict[str, Any]],
) -> None:
    if not seen_users_delta:
        return
    existing = {
        u.discord_user_id: u
        for u in session.query(SeenDiscordUserModel).filter(
            SeenDiscordUserModel.backup_id == str(backup_id),
            SeenDiscordUserModel.discord_user_id.in_(list(seen_users_delta.keys())),
        ).all()
    }
    for uid_str, info in seen_users_delta.items():
        row = existing.get(uid_str)
        uname = str(info.get("username") or f"User #{uid_str}")[:128]
        gname = (str(info.get("global_name") or "").strip()[:128]) or None
        nick = (str(info.get("nickname") or "").strip()[:128]) or None
        delta_cnt = int(info.get("message_count") or 0)
        new_dt = info.get("last_seen_at")

        if row is None:
            row = SeenDiscordUserModel(
                backup_id=str(backup_id),
                discord_user_id=uid_str,
                username=uname,
                global_name=gname,
                nickname=nick,
                is_current_member=False,
                message_count=delta_cnt,
                last_seen_at=new_dt,
            )
            session.add(row)
            existing[uid_str] = row
        else:
            if uname and (not row.username or row.username.startswith("User #")):
                row.username = uname
            if gname:
                row.global_name = gname
            if nick:
                row.nickname = nick
            if delta_cnt > 0:
                row.message_count = int(row.message_count or 0) + delta_cnt
            if new_dt is not None:
                cur_dt = t.parse_datetime(row.last_seen_at)
                if cur_dt is None or new_dt > cur_dt:
                    row.last_seen_at = new_dt
    session.flush()


def _compute_affected_horizon(
    session,
    backup_id: str,
    base_path: str,
    chan_model: ChannelModel,
    *,
    is_chatroom: bool,
    earliest_touched_id: Optional[int],
    rescan_discord: bool,
) -> Optional[int]:
    """
    Computes `min_affected_message_id` for incremental tail segmentation.
    Returns `None` when the entire channel must be segmented (first sync, rescan, or no frozen closed scene).
    """
    if rescan_discord or earliest_touched_id is None:
        return None

    closed_scenes = (
        session.query(SceneModel)
        .filter(
            SceneModel.backup_id == str(backup_id),
            SceneModel.channel_pk == chan_model.pk,
            SceneModel.event_pk.is_(None),
            SceneModel.status == "closed",
            cast(SceneModel.end_message_id, BigInteger) < int(earliest_touched_id),
        )
        .order_by(cast(SceneModel.end_message_id, BigInteger).desc())
        .all()
    )
    if not closed_scenes:
        return None

    if is_chatroom:
        # Step back to a closed session at least 5 hours before earliest_touched_id so tempo & 1-msg merge match
        touched_dt = t.parse_datetime(
            datetime.fromtimestamp(((int(earliest_touched_id) >> 22) + 1420070400000) / 1000.0, tz=timezone.utc)
        )
        safe_closed = None
        for idx, sc in enumerate(closed_scenes):
            sc_end = t.parse_datetime(sc.end_at)
            if idx >= 1 and sc_end and touched_dt and (touched_dt - sc_end) >= timedelta(hours=5):
                safe_closed = sc
                break
        if safe_closed is None:
            return None
        return int(safe_closed.end_message_id) + 1

    # RP channel: check if earliest_touched skeleton is a short [END] tag that can attach to last_frozen
    last_frozen = closed_scenes[0]
    first_touched_skels = load_channel_skeletons(
        backup_id,
        base_path,
        chan_model.discord_id,
        start_message_id=int(last_frozen.end_message_id) + 1,
        end_message_id=int(earliest_touched_id),
    )
    if first_touched_skels and (int(first_touched_skels[0].flags) & SkeletonFlags.IS_SHORT_END_TAG):
        if len(closed_scenes) >= 2:
            last_frozen = closed_scenes[1]
        else:
            return None

    return int(last_frozen.end_message_id) + 1


def _build_synthetic_channel_dict(
    guild_meta: Dict[str, Any],
    item: SyncableChannelItem,
) -> Dict[str, Any]:
    return {
        "guild": {
            "id": str(guild_meta.get("id") or ""),
            "name": str(guild_meta.get("name") or ""),
            "iconUrl": guild_meta.get("iconUrl") or "",
        },
        "channel": {
            "id": str(item.discord_id),
            "type": str(item.type),
            "categoryId": item.parent_discord_id if item.is_thread else item.category_discord_id,
            "category": item.parent_name if item.is_thread else item.category_name,
            "name": str(item.name),
            "topic": item.topic,
        },
        "messages": [],
    }


def _count_channel_skeletons(backup_id: str, base_path: str, channel_discord_id: str) -> int:
    if not str(channel_discord_id).isdigit():
        return 0
    with skeleton_db_session(backup_id=backup_id, backup_path=base_path) as skel_session:
        return int(
            skel_session.query(func.count(MessageSkeletonModel.message_id))
            .filter(MessageSkeletonModel.channel_discord_id == int(channel_discord_id))
            .scalar()
            or 0
        )


async def _run_sync_async(
    backup_id: str,
    backup_path: str,
    *,
    token: Optional[str] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    resume: bool = False,
    rescan_discord: bool = False,
    stop_event: Optional[threading.Event] = None,
    on_channel_committed: Optional[Callable[[SyncableChannelItem, int, int], None]] = None,
) -> Dict[str, Any]:
    init_db(engine_or_backup_id=backup_id, backup_path=backup_path)
    get_skeleton_engine(backup_id=backup_id, backup_path=backup_path)

    _acquire_sync_lock(backup_path)
    try:
        stop_flag = stop_event or threading.Event()
        server_id = str(getattr(c, "SERVER_ID", "") or "")
        server_name = str(getattr(c, "SERVER_NAME", "") or "")
        backup_name = str(getattr(c, "BACKUP_NAME", "") or backup_id)
        categories_to_ignore = expand_category_names(getattr(c, "CATEGORIES_TO_IGNORE", set()))
        categories_to_keep = expand_category_names(getattr(c, "CATEGORIES_TO_KEEP", set()))
        keep_mode = bool(getattr(c, "KEEP_MODE", False))
        event_cat_names = expand_category_names(getattr(c, "EVENT_CATEGORIES", []))
        chatroom_cat_names = expand_category_names(getattr(c, "CHATROOM_CATEGORIES", []))
        debug_files = bool(getattr(c, "DEBUG_FILES", False))

        now_utc = datetime.now(timezone.utc)
        preexisting_sync_status = SyncStatus.IDLE.value
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            b_row = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
            existing_mode = b_row.storage_mode if b_row else None
            storage_mode = _resolve_storage_mode(backup_path, existing_mode=existing_mode)
            if b_row is None:
                b_row = BackupModel(
                    backup_id=str(backup_id),
                    backup_name=backup_name,
                    server_id=server_id or None,
                    server_name=server_name or None,
                    created_at=now_utc,
                    storage_mode=storage_mode,
                    sync_status=SyncStatus.IDLE.value,
                )
                session.add(b_row)
                session.flush()
            else:
                preexisting_sync_status = str(b_row.sync_status or SyncStatus.IDLE.value)
                b_row.storage_mode = storage_mode
                if server_id:
                    b_row.server_id = server_id
                if backup_name:
                    b_row.backup_name = backup_name

            if not server_id and b_row.server_id:
                server_id = b_row.server_id
            was_paused = (preexisting_sync_status == SyncStatus.PAUSED.value)
            is_resume = bool(resume or was_paused)

            existing_chans = session.query(ChannelModel).filter(
                ChannelModel.backup_id == str(backup_id)
            ).all()
            existing_channels_map: Dict[str, Dict[str, Any]] = {}
            for ch in existing_chans:
                existing_channels_map[str(ch.discord_id)] = {
                    "pk": ch.pk,
                    "name": ch.name,
                    "position": ch.position,
                    "path": ch.path,
                    "type": ch.type,
                    "last_message_id": ch.last_message_id,
                    "last_synced_at": ch.last_synced_at,
                    "sync_status": ch.sync_status,
                    "is_event_thread": "Events/Threads/" in str(ch.path or ""),
                }

        if not server_id:
            if preexisting_sync_status == SyncStatus.SYNCING.value:
                with db_session(backup_id=backup_id, backup_path=backup_path) as session:
                    b_row = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
                    if b_row is not None:
                        b_row.sync_status = SyncStatus.FAILED.value
                        b_row.sync_error = "Missing serverId in backup configuration/database."
            raise exc.BackupError("Missing serverId in backup configuration/database.")

        sync_wall_start = time.monotonic()
        extractor_ref: Optional[DiscordExtractor] = None
        t.log("info", "  Verifying Discord bot token...")
        try:
            async with DiscordExtractor(token=token, transport=transport) as extractor:
                extractor_ref = extractor
                # 1. Fail-fast Bot token check before starting topology sync
                await extractor.verify_bot_token()

                with db_session(backup_id=backup_id, backup_path=backup_path) as session:
                    b_row = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
                    b_row.sync_status = SyncStatus.SYNCING.value
                    b_row.sync_started_at = datetime.now(timezone.utc)
                    b_row.sync_error = None
                    clear_runtime_step_overrides(str(backup_id), scope="base")

                # 2. Topology + Member Discovery
                t.log("info", f"  Fetching server topology for guild {server_id}...")
                topology = await extractor.fetch_server_topology(
                    server_id,
                    categories_to_ignore=categories_to_ignore,
                    categories_to_keep=categories_to_keep,
                    keep_mode=keep_mode,
                    event_categories=event_cat_names,
                    existing_channels=existing_channels_map,
                )
                t.log(
                    "info",
                    f"  Topology ready: {len(topology.categories)} category(ies), "
                    f"{len(topology.syncable_items)} channel(s)/thread(s) ({storage_mode} mode).",
                )
                members_by_id = await extractor.fetch_guild_members(server_id)
                if members_by_id:
                    t.log("info", f"  Loaded {len(members_by_id)} server member(s).")

                with db_session(backup_id=backup_id, backup_path=backup_path) as session:
                    b_row = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
                    b_row.server_name = topology.guild_meta["name"]
                    chan_by_did, path_renames = _sync_topology_to_db(
                        session,
                        backup_id,
                        topology,
                        is_resume=is_resume,
                        storage_mode=storage_mode,
                    )
                    if members_by_id:
                        _upsert_guild_members_to_seen_users(session, backup_id, members_by_id)

                    if storage_mode == StorageMode.FULL.value and path_renames:
                        sync_full_mode_channel_paths(Path(backup_path) / "Data", path_renames)

                    # Snapshot channel state for worker tasks
                    channel_cursors: Dict[str, Dict[str, Any]] = {}
                    pending_items: List[SyncableChannelItem] = []
                    done_initial = 0
                    for item in topology.syncable_items:
                        cm = chan_by_did.get(item.discord_id)
                        if cm is None:
                            continue
                        channel_cursors[item.discord_id] = {
                            "pk": cm.pk,
                            "last_message_id": cm.last_message_id,
                            "last_synced_at": cm.last_synced_at,
                            "sync_status": cm.sync_status,
                        }
                        if is_resume and cm.sync_status == "synced":
                            done_initial += 1
                        else:
                            pending_items.append(item)

                    b_row.channels_total = len(topology.syncable_items)
                    b_row.channels_done = done_initial

                # Load shared curation & character state
                char_list = CharacterList.load(backup_id=backup_id, base_path=backup_path)
                resolved_decisions = curation_service.get_resolved_boundary_decisions(backup_id, backup_path)
                resolved_flags_map = curation_service.get_resolved_flags_map(backup_id, backup_path)
                preserved_flagged_mids = curation_service.get_preserved_flagged_message_ids(backup_id, backup_path)
                db_excerpts_all = _load_db_excerpts_map(backup_id, backup_path)

                db_write_lock = asyncio.Lock()
                sem = asyncio.Semaphore(extractor.max_concurrent_channels)
                progress = {"done": done_initial, "total": len(topology.syncable_items), "skipped": 0, "synced": 0, "errors": 0, "messages": 0}

                async def _process_item(item: SyncableChannelItem) -> None:
                    if stop_flag.is_set():
                        return

                    cursor = channel_cursors[item.discord_id]
                    stored_last_id = cursor["last_message_id"]
                    stored_last_synced_at = cursor["last_synced_at"]
                    chan_pk = int(cursor["pk"])

                    # 24h quiet-channel skip check
                    if not rescan_discord and should_skip_channel_sync(
                        item.discord_last_message_id, stored_last_id, stored_last_synced_at
                    ):
                        async with db_write_lock:
                            if stop_flag.is_set():
                                return
                            with db_session(backup_id=backup_id, backup_path=backup_path) as session:
                                cm = session.get(ChannelModel, chan_pk)
                                if cm is not None:
                                    cm.sync_status = "synced"
                                    cm.sync_error = None
                                    cm.last_synced_at = datetime.now(timezone.utc)
                                b_row = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
                                progress["done"] += 1
                                progress["skipped"] += 1
                                if b_row is not None:
                                    b_row.channels_done = progress["done"]
                            if progress["done"] % 25 == 0 and is_sqlite_tmp_cache_enabled():
                                sync_dirty_sqlite_dbs(force=True)
                            if on_channel_committed is not None:
                                on_channel_committed(item, progress["done"], progress["total"])
                            t.log("info", f"  [{progress['done']}/{progress['total']}] Unchanged (skipped): {item.path}")
                        return

                    effective_after = (
                        "0"
                        if rescan_discord
                        else compute_effective_after_snowflake(stored_last_id, stored_last_synced_at)
                    )

                    # Fetch channel messages from Discord under concurrency semaphore
                    fetched_msgs: List[Dict[str, Any]] = []
                    fetch_error: Optional[str] = None
                    async with sem:
                        if stop_flag.is_set():
                            return
                        try:
                            fetched_msgs = await extractor.fetch_channel_messages(
                                item.discord_id,
                                after_snowflake=effective_after,
                                guild_id=server_id,
                                channels_by_id=topology.channels_by_id,
                                roles_by_id=topology.roles_by_id,
                                members_by_id=members_by_id,
                                serialize=True,
                            )
                        except ChannelAccessError as ce:
                            fetch_error = str(ce)

                    if stop_flag.is_set():
                        return

                    async with db_write_lock:
                        if fetch_error is not None:
                            with db_session(backup_id=backup_id, backup_path=backup_path) as session:
                                cm = session.get(ChannelModel, chan_pk)
                                if cm is not None:
                                    cm.sync_status = "error"
                                    cm.sync_error = fetch_error
                                b_row = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
                                progress["done"] += 1
                                progress["errors"] += 1
                                if b_row is not None:
                                    b_row.channels_done = progress["done"]
                            if on_channel_committed is not None:
                                on_channel_committed(item, progress["done"], progress["total"])
                            t.log("error", f"  [{progress['done']}/{progress['total']}] Failed {item.path}: {fetch_error}")
                            return

                        # 1. In-memory Tupper ID assignment & seen-user collection
                        prev_last_int = int(stored_last_id) if (stored_last_id and str(stored_last_id).isdigit()) else 0
                        all_seen_acc: Dict[str, Dict[str, Any]] = {}
                        assign_ids_in_memory(fetched_msgs, char_list, seen_users_acc=all_seen_acc)
                        if char_list._new_characters:
                            char_list.save()

                        # Avoid double-counting message_count for lookback messages already <= prev_last_int
                        # while keeping new message counts accurate
                        seen_delta: Dict[str, Dict[str, Any]] = {}
                        if prev_last_int > 0 and not rescan_discord:
                            new_only = [m for m in fetched_msgs if int(m["id"]) > prev_last_int]
                            dummy_seen: Dict[str, Dict[str, Any]] = {}
                            for m in new_only:
                                # Count only newly arrived messages, preserving metadata from all_seen_acc
                                pass
                            # Recompute delta counts cleanly
                            for uid_k, u_info in all_seen_acc.items():
                                seen_delta[uid_k] = dict(u_info)
                                seen_delta[uid_k]["message_count"] = 0
                            for m in new_only:
                                auth = m.get("author") or {}
                                if not auth.get("isBot"):
                                    aid_s = str(auth.get("id") or "")
                                    if aid_s in seen_delta:
                                        seen_delta[aid_s]["message_count"] += 1
                        else:
                            seen_delta = all_seen_acc

                        # 2. Compute immutable 14-bit skeletons & upsert into skeletons.sqlite
                        skeletons = build_skeletons_from_messages(fetched_msgs, item.discord_id)
                        eff_after_for_del: Optional[int] = None
                        if stored_last_id is not None or rescan_discord:
                            eff_after_for_del = int(effective_after)

                        deleted_ids = upsert_channel_skeletons(
                            backup_id,
                            backup_path,
                            item.discord_id,
                            skeletons,
                            effective_after_id=eff_after_for_del,
                        )

                        # 3. Full mode: atomically write/extend Data/<item.path>
                        if storage_mode == StorageMode.FULL.value:
                            chan_meta = {
                                "id": item.discord_id,
                                "type": item.type,
                                "categoryId": item.parent_discord_id if item.is_thread else item.category_discord_id,
                                "category": item.parent_name if item.is_thread else item.category_name,
                                "name": item.name,
                                "topic": item.topic,
                                "icon": item.icon,
                            }
                            extend_channel_json_atomic(
                                Path(backup_path) / "Data" / item.path,
                                guild_meta=topology.guild_meta,
                                channel_meta=chan_meta,
                                new_or_updated_messages=fetched_msgs,
                                deleted_ids=deleted_ids,
                                exported_at=datetime.now(timezone.utc),
                                indent=4,
                                ensure_ascii=True,
                                overwrite=bool(rescan_discord),
                            )

                        # 4. Segment scenes / sessions & detect flagged messages
                        is_event = bool(
                            item.is_event
                            or category_name_matches(item.category_name, event_cat_names)
                            or item.category_name == "Events"
                        )
                        is_chatroom = (not is_event) and category_name_matches(item.category_name, chatroom_cat_names)

                        for m in fetched_msgs:
                            mid_s = str(m.get("id") or "")
                            if mid_s:
                                db_excerpts_all[mid_s] = str(m.get("content") or "")

                        if not is_event:
                            touched_ids = [int(m["id"]) for m in fetched_msgs if str(m.get("id", "")).isdigit()] + list(deleted_ids)
                            earliest_touched = min(touched_ids) if touched_ids else None

                            with db_session(backup_id=backup_id, backup_path=backup_path) as session:
                                cm = session.get(ChannelModel, chan_pk)
                                min_affected = _compute_affected_horizon(
                                    session,
                                    backup_id,
                                    backup_path,
                                    cm,
                                    is_chatroom=is_chatroom,
                                    earliest_touched_id=earliest_touched,
                                    rescan_discord=rescan_discord,
                                )

                            tail_skeletons = load_channel_skeletons(
                                backup_id,
                                backup_path,
                                item.discord_id,
                                start_message_id=min_affected,
                            )
                            prepared_tail = prepare_channel_skeletons(
                                tail_skeletons,
                                resolved_flags_map=resolved_flags_map,
                                excerpts_map=db_excerpts_all,
                            )

                            syn_chan = _build_synthetic_channel_dict(topology.guild_meta, item)
                            syn_chan["messages"] = prepared_tail

                            if is_chatroom:
                                id_b = f"{item.position}"
                                tail_scenes = find_all_sessions_in_channel(
                                    channel_data=syn_chan,
                                    messages=prepared_tail,
                                    id_builder=id_b,
                                    resolved_decisions=resolved_decisions,
                                )
                            else:
                                id_b = f"{item.position}"
                                tail_scenes = find_all_scenes_in_channel(
                                    syn_chan,
                                    id_builder=id_b,
                                    resolved_decisions=resolved_decisions,
                                )

                            save_channel_indexed_scenes(
                                backup_id,
                                backup_path,
                                chan_pk,
                                tail_scenes,
                                min_affected_message_id=min_affected,
                            )

                            if not is_chatroom:
                                # Combine all scenes in channel if needed, or tail_scenes covers the fetched window
                                flagged_items = collect_channel_flagged_messages(
                                    raw_messages=fetched_msgs,
                                    channel_id=item.discord_id,
                                    scenes=tail_scenes,
                                    preserved_msg_ids=preserved_flagged_mids,
                                )
                                curation_service.save_channel_flagged_messages(
                                    backup_id=backup_id,
                                    base_path=backup_path,
                                    channel_pk=chan_pk,
                                    flagged_items=flagged_items,
                                    min_message_id=int(effective_after) if (int(effective_after) > 0 and not rescan_discord) else None,
                                    debug_files=False,
                                )

                        # 5. Commit channel cursor, seen users, and BackupModel.channels_done atomically
                        max_fetched_id = max((int(m["id"]) for m in fetched_msgs), default=0)
                        new_last_id = max(
                            prev_last_int,
                            max_fetched_id,
                            int(item.discord_last_message_id) if (item.discord_last_message_id and str(item.discord_last_message_id).isdigit()) else 0,
                        )
                        total_skel_count = _count_channel_skeletons(backup_id, backup_path, item.discord_id)

                        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
                            _upsert_channel_seen_users(session, backup_id, seen_delta)
                            cm = session.get(ChannelModel, chan_pk)
                            if cm is not None:
                                if new_last_id > 0:
                                    cm.last_message_id = str(new_last_id)
                                cm.last_synced_at = datetime.now(timezone.utc)
                                cm.sync_status = "synced"
                                cm.sync_error = None
                                cm.message_count = total_skel_count
                            b_row = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
                            progress["done"] += 1
                            progress["synced"] += 1
                            progress["messages"] += len(fetched_msgs)
                            if b_row is not None:
                                b_row.channels_done = progress["done"]

                        if progress["done"] % 25 == 0 and is_sqlite_tmp_cache_enabled():
                            sync_dirty_sqlite_dbs(force=True)

                        if on_channel_committed is not None:
                            on_channel_committed(item, progress["done"], progress["total"])
                        t.log(
                            "info",
                            f"  [{progress['done']}/{progress['total']}] Synced {len(fetched_msgs)} msg(s): {item.path}",
                        )

                # Process pending channels concurrently
                tasks = [asyncio.create_task(_process_item(it)) for it in pending_items]
                if tasks:
                    await asyncio.gather(*tasks)

            if stop_flag.is_set():
                elapsed_s = max(0.0, time.monotonic() - sync_wall_start)
                with db_session(backup_id=backup_id, backup_path=backup_path) as session:
                    b_row = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
                    if b_row is not None:
                        b_row.sync_status = SyncStatus.PAUSED.value
                        if debug_files:
                            export_character_list_snapshot(session, backup_id, write_to_disk=True)
                            export_backup_info_snapshot(session, backup_id, scope="base", write_to_disk=True)
                if is_sqlite_tmp_cache_enabled():
                    sync_dirty_sqlite_dbs(force=True)
                t.log("info", f"  {extractor.format_wait_summary(elapsed_seconds=elapsed_s)}")
                close_all_engines()
                return {
                    "status": SyncStatus.PAUSED.value,
                    "channels_done": progress["done"],
                    "channels_total": progress["total"],
                    "synced": progress["synced"],
                    "skipped": progress["skipped"],
                }

            if rescan_discord and storage_mode == StorageMode.FULL.value and progress["errors"] == 0:
                active_rels = {Path(it.path).as_posix() for it in topology.syncable_items if it.path}
                pruned = _prune_orphan_data_jsons(Path(backup_path) / "Data", active_rels)
                if pruned > 0:
                    t.log("info", f"  Pruned {pruned} stale/orphan JSON file(s) from Data/.")

            # 3. Post-channel Events Stage 2 & 3 pass
            event_cats = [
                cat for cat in topology.categories
                if category_name_matches(cat.name, event_cat_names) or cat.id == "events_category" or cat.name == "Events"
            ]
            event_clusters = []
            if event_cats:
                t.log("info", f"  Indexing events across {len(event_cats)} event category(s)...")
                event_clusters = index_event_categories(
                    event_categories=event_cats,
                    data_folder=(Path(backup_path) / "Data").as_posix(),
                    resolved_flags_map=resolved_flags_map,
                    resolved_decisions=resolved_decisions,
                    backup_id=backup_id,
                    backup_path=backup_path,
                    rescan_json=False,
                    excerpts_map=db_excerpts_all,
                )
            save_indexed_events(backup_id, backup_path, event_clusters)
            elapsed_s = max(0.0, time.monotonic() - sync_wall_start)
            t.log(
                "info",
                f"  Sync complete: {progress['synced']} synced, {progress['skipped']} unchanged, "
                f"{progress['errors']} error(s), {len(event_clusters)} event(s) "
                f"({progress['messages']} msg(s) in {elapsed_s:.1f}s).",
            )
            t.log("info", f"  {extractor.format_wait_summary(elapsed_seconds=elapsed_s)}")

            # 4. Finalize BackupModel state & optional snapshots
            with db_session(backup_id=backup_id, backup_path=backup_path) as session:
                b_row = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
                if b_row is not None:
                    b_row.sync_status = SyncStatus.IDLE.value
                    b_row.last_synced_at = datetime.now(timezone.utc)
                    b_row.sync_error = None
                    b_row.channels_done = progress["total"]
                if debug_files:
                    export_character_list_snapshot(session, backup_id, write_to_disk=True)
                    export_backup_info_snapshot(session, backup_id, scope="base", write_to_disk=True)
                    export_curation_snapshots(session, backup_id, backup_path)

            if is_sqlite_tmp_cache_enabled():
                sync_dirty_sqlite_dbs(force=True)

            return {
                "status": SyncStatus.IDLE.value,
                "channels_done": progress["done"],
                "channels_total": progress["total"],
                "synced": progress["synced"],
                "skipped": progress["skipped"],
                "events": len(event_clusters),
            }

        except KeyboardInterrupt:
            with db_session(backup_id=backup_id, backup_path=backup_path) as session:
                b_row = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
                if b_row is not None:
                    b_row.sync_status = SyncStatus.PAUSED.value
            if is_sqlite_tmp_cache_enabled():
                sync_dirty_sqlite_dbs(force=True)
            t.log("info", "  Sync paused by user interruption.")
            if extractor_ref is not None:
                t.log("info", f"  {extractor_ref.format_wait_summary(elapsed_seconds=time.monotonic() - sync_wall_start)}")
            return {"status": SyncStatus.PAUSED.value}
        except exc.InvalidBotTokenError as e:
            if preexisting_sync_status == SyncStatus.SYNCING.value:
                with db_session(backup_id=backup_id, backup_path=backup_path) as session:
                    b_row = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
                    if b_row is not None:
                        b_row.sync_status = SyncStatus.FAILED.value
                        b_row.sync_error = str(e)
            if is_sqlite_tmp_cache_enabled():
                sync_dirty_sqlite_dbs(force=True)
            raise
        except Exception as e:
            with db_session(backup_id=backup_id, backup_path=backup_path) as session:
                b_row = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
                if b_row is not None:
                    b_row.sync_status = SyncStatus.FAILED.value
                    b_row.sync_error = str(e)
            if is_sqlite_tmp_cache_enabled():
                sync_dirty_sqlite_dbs(force=True)
            if extractor_ref is not None:
                t.log("info", f"  {extractor_ref.format_wait_summary(elapsed_seconds=time.monotonic() - sync_wall_start)}")
            raise
    finally:
        _release_sync_lock(backup_path)


def backup_server(
    *,
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
    token: Optional[str] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    resume: bool = False,
    rescan_discord: bool = False,
    stop_event: Optional[threading.Event] = None,
    on_channel_committed: Optional[Callable[[SyncableChannelItem, int, int], None]] = None,
) -> Dict[str, Any]:
    """
    Executes the resumable per-channel atomic sync pipeline for the active or specified backup.
    Supports both `"backupless"` and `"full"` storage modes.
    """
    start_time = time.time()
    b_id, b_path = _ensure_backup_bootstrap(backup_id, backup_path)
    t.log("base", f"\n# Syncing server backup '{b_id}'... #\n")

    local_stop = stop_event or threading.Event()
    prev_sigint = None
    prev_sigterm = None
    prev_sigbreak = None
    installed_signals = False

    if threading.current_thread() is threading.main_thread():
        def _handle_stop(signum, frame):
            local_stop.set()

        try:
            prev_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, _handle_stop)
            if hasattr(signal, "SIGTERM"):
                prev_sigterm = signal.getsignal(signal.SIGTERM)
                signal.signal(signal.SIGTERM, _handle_stop)
            if hasattr(signal, "SIGBREAK"):
                prev_sigbreak = signal.getsignal(signal.SIGBREAK)
                signal.signal(signal.SIGBREAK, _handle_stop)
            installed_signals = True
        except Exception:
            installed_signals = False

    try:
        result = asyncio.run(
            _run_sync_async(
                b_id,
                b_path,
                token=token,
                transport=transport,
                resume=resume,
                rescan_discord=rescan_discord,
                stop_event=local_stop,
                on_channel_committed=on_channel_committed,
            )
        )
        return result
    finally:
        if installed_signals:
            try:
                if prev_sigint is not None:
                    signal.signal(signal.SIGINT, prev_sigint)
                if prev_sigterm is not None and hasattr(signal, "SIGTERM"):
                    signal.signal(signal.SIGTERM, prev_sigterm)
                if prev_sigbreak is not None and hasattr(signal, "SIGBREAK"):
                    signal.signal(signal.SIGBREAK, prev_sigbreak)
            except Exception:
                pass
        if is_sqlite_tmp_cache_enabled():
            sync_dirty_sqlite_dbs(force=True)
        t.log("base", f"\n# Sync finished --- {time.time() - start_time:.2f} seconds --- #\n")


def _parse_cli_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Socrates unified Discord backup sync orchestrator")
    parser.add_argument("--backup-id", type=str, default=None, help="Backup ID to sync")
    parser.add_argument("--resume", action="store_true", help="Resume an interrupted/paused sync")
    parser.add_argument(
        "--rescan-discord",
        "--rescan",
        dest="rescan_discord",
        action="store_true",
        help="Full Discord history rescan",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_cli_args(sys.argv[1:])
    try:
        if args.backup_id:
            from models.backup_context import BackupContext
            with BackupContext.activate(backup_id=args.backup_id):
                res = backup_server(
                    backup_id=args.backup_id,
                    resume=args.resume,
                    rescan_discord=args.rescan_discord,
                )
        else:
            res = backup_server(resume=args.resume, rescan_discord=args.rescan_discord)
        if res.get("status") == SyncStatus.PAUSED.value:
            close_all_engines()
            sys.exit(0)
    except KeyboardInterrupt:
        t.log("error", "\nProcess interrupted by user.\n")
        close_all_engines()
        sys.exit(1)
    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
        close_all_engines()
        sys.exit(1)

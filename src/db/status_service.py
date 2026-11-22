from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from db.session import db_session, init_db, require_db, has_db, has_sqlite_db
from db.models import (
    BackupModel,
    ChannelModel,
    Status,
    Step,
    StorageMode,
    SyncStatus,
)
from db.serializers import (
    build_backup_info_dict,
    clear_runtime_step_overrides,
    set_runtime_step_override,
    synthesize_legacy_steps,
)
from db.snapshots import export_backup_info_snapshot
import utils.tricks as t

_RUNTIME_UPDATE_STATE: Dict[str, Dict[str, Any]] = {}


def _parse_dt(dt_val: Any) -> Optional[datetime]:
    if not dt_val:
        return None
    if isinstance(dt_val, datetime):
        return dt_val if dt_val.tzinfo else dt_val.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(dt_val))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _resolve_storage_mode_from_config(backup_path: Optional[str]) -> str:
    if not backup_path:
        return StorageMode.BACKUPLESS.value
    cfg_file = Path(backup_path) / "backup_config.json"
    if cfg_file.exists():
        try:
            cfg = t.load_from_json(cfg_file.as_posix())
            mode = (cfg.get("admin", {}) or {}).get("storageMode") or cfg.get("storageMode")
            if mode in (StorageMode.BACKUPLESS.value, StorageMode.FULL.value):
                return str(mode)
        except Exception:
            pass
    return StorageMode.BACKUPLESS.value


def init_backup_export(
    backup_id: str,
    backup_path: str,
    backup_name: str,
    server_id: Optional[str] = None,
    server_name: Optional[str] = None,
    scope: str = "base",
    updated_at: Optional[datetime] = None,
    storage_mode: Optional[str] = None,
) -> None:
    """
    Initializes backup.sqlite if not present and upserts BackupModel (Schema v6).
    """
    init_db(engine_or_backup_id=backup_id, backup_path=backup_path)
    now_utc = _parse_dt(updated_at) or datetime.now(timezone.utc)
    resolved_mode = storage_mode or _resolve_storage_mode_from_config(backup_path)

    if str(scope) == "update":
        _RUNTIME_UPDATE_STATE[str(backup_id)] = {
            "id": str(server_id) if server_id else "",
            "name": str(server_name) if server_name else str(backup_name),
            "updated_at": now_utc.isoformat(),
            "exported_from": now_utc.isoformat(),
            "exported_at": now_utc.isoformat(),
            "status": Status.PENDING.value,
            "steps": {s.value: Status.PENDING.value for s in Step},
            "categories": [],
        }
        clear_runtime_step_overrides(str(backup_id), scope="update")
        return

    with db_session(backup_id=backup_id, backup_path=backup_path) as session:
        backup = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
        if not backup:
            backup = BackupModel(
                backup_id=str(backup_id),
                backup_name=str(backup_name),
                server_id=str(server_id) if server_id else None,
                server_name=str(server_name) if server_name else None,
                created_at=now_utc,
                storage_mode=resolved_mode,
                sync_status=SyncStatus.IDLE.value,
                last_synced_at=_parse_dt(updated_at),
            )
            session.add(backup)
        else:
            if backup_name:
                backup.backup_name = str(backup_name)
            if server_id:
                backup.server_id = str(server_id)
            if server_name:
                backup.server_name = str(server_name)
            if storage_mode:
                backup.storage_mode = str(storage_mode)
            if updated_at is not None:
                backup.last_synced_at = _parse_dt(updated_at)
        session.commit()

    clear_runtime_step_overrides(str(backup_id), scope=str(scope))


def load_backup_state(
    backup_id: str,
    backup_path: str,
    scope: str = "base",
) -> Dict[str, Any]:
    """Reconstructs the backup state directly from SQLite without reading any JSON files."""
    require_db(backup_path, backup_id=backup_id)
    if str(scope) == "update" and str(backup_id) in _RUNTIME_UPDATE_STATE:
        import copy
        state = copy.deepcopy(_RUNTIME_UPDATE_STATE[str(backup_id)])
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            backup = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
            if backup:
                has_cats = bool(state.get("categories"))
                agg_status, steps_dict = synthesize_legacy_steps(backup, scope="update", has_channels=has_cats)
                state.setdefault("steps", {}).update(steps_dict)
                state["status"] = agg_status
        return state
    with db_session(backup_id=backup_id, backup_path=backup_path) as session:
        return build_backup_info_dict(
            session=session,
            backup_id=str(backup_id),
            scope=str(scope),
        )


def _sync_channels_internal(session: Any, backup_id: str, categories: list) -> None:
    existing_channels = session.query(ChannelModel).filter(
        ChannelModel.backup_id == str(backup_id)
    ).all()
    channel_by_discord_id = {ch.discord_id: ch for ch in existing_channels}
    seen_discord_ids = set()

    for cat in categories:
        cat_id_str = str(cat.id if hasattr(cat, "id") else cat.get("id"))
        cat_name = str(cat.name if hasattr(cat, "name") else cat.get("name", ""))
        cat_pos = int(cat.position if hasattr(cat, "position") else cat.get("position", 0))
        cat_path = str(cat.path if hasattr(cat, "path") else cat.get("path", ""))
        cat_is_deleted = bool(cat.is_deleted if hasattr(cat, "is_deleted") else cat.get("is_deleted", False))

        seen_discord_ids.add(cat_id_str)
        cat_model = channel_by_discord_id.get(cat_id_str)
        if cat_model:
            cat_model.name = cat_name
            cat_model.position = cat_pos
            cat_model.path = cat_path
            cat_model.is_deleted = cat_is_deleted
        else:
            cat_model = ChannelModel(
                backup_id=str(backup_id),
                discord_id=cat_id_str,
                type="GuildCategory",
                parent_pk=None,
                name=cat_name,
                position=cat_pos,
                path=cat_path,
                is_deleted=cat_is_deleted,
            )
            session.add(cat_model)
            session.flush()
            channel_by_discord_id[cat_id_str] = cat_model

        chan_list = cat.channels if hasattr(cat, "channels") else cat.get("channels", [])
        for chan in chan_list:
            chan_id_str = str(chan.id if hasattr(chan, "id") else chan.get("id"))
            chan_name = str(chan.name if hasattr(chan, "name") else chan.get("name", ""))
            chan_pos = int(chan.position if hasattr(chan, "position") else chan.get("position", 0))
            chan_path = str(chan.path if hasattr(chan, "path") else chan.get("path", ""))
            chan_is_deleted = bool(chan.is_deleted if hasattr(chan, "is_deleted") else chan.get("is_deleted", False))
            chan_type = str(getattr(chan, "type", None) or (chan.get("type") if isinstance(chan, dict) else None) or "GuildTextChat")
            msg_count = getattr(chan, "messages", getattr(chan, "number_of_messages", None)) if not isinstance(chan, dict) else chan.get("number_of_messages", chan.get("messages"))

            seen_discord_ids.add(chan_id_str)
            chan_model = channel_by_discord_id.get(chan_id_str)
            if chan_model:
                chan_model.parent_pk = cat_model.pk
                chan_model.name = chan_name
                chan_model.position = chan_pos
                chan_model.path = chan_path
                chan_model.is_deleted = chan_is_deleted
                if msg_count is not None:
                    chan_model.message_count = msg_count
            else:
                chan_model = ChannelModel(
                    backup_id=str(backup_id),
                    discord_id=chan_id_str,
                    type=chan_type,
                    parent_pk=cat_model.pk,
                    name=chan_name,
                    position=chan_pos,
                    path=chan_path,
                    is_deleted=chan_is_deleted,
                    message_count=msg_count,
                )
                session.add(chan_model)
                session.flush()
                channel_by_discord_id[chan_id_str] = chan_model

            thr_list = chan.threads if hasattr(chan, "threads") else (chan.get("threads", []) if isinstance(chan, dict) else [])
            for thr in thr_list:
                thr_id_str = str(thr.id if hasattr(thr, "id") else thr.get("id"))
                thr_name = str(thr.name if hasattr(thr, "name") else thr.get("name", ""))
                thr_pos = int(thr.position if hasattr(thr, "position") else thr.get("position", 0))
                thr_path = str(thr.path if hasattr(thr, "path") else thr.get("path", ""))
                thr_is_deleted = bool(thr.is_deleted if hasattr(thr, "is_deleted") else thr.get("is_deleted", False))
                thr_msg_count = getattr(thr, "messages", getattr(thr, "number_of_messages", None)) if not isinstance(thr, dict) else thr.get("number_of_messages", thr.get("messages"))

                seen_discord_ids.add(thr_id_str)
                thr_model = channel_by_discord_id.get(thr_id_str)
                if thr_model:
                    thr_model.parent_pk = chan_model.pk
                    thr_model.name = thr_name
                    thr_model.position = thr_pos
                    thr_model.path = thr_path
                    thr_model.is_deleted = thr_is_deleted
                    if thr_msg_count is not None:
                        thr_model.message_count = thr_msg_count
                else:
                    thr_model = ChannelModel(
                        backup_id=str(backup_id),
                        discord_id=thr_id_str,
                        type="GuildPublicThread",
                        parent_pk=chan_model.pk,
                        name=thr_name,
                        position=thr_pos,
                        path=thr_path,
                        is_deleted=thr_is_deleted,
                        message_count=thr_msg_count,
                    )
                    session.add(thr_model)
                    session.flush()
                    channel_by_discord_id[thr_id_str] = thr_model

    for ch in existing_channels:
        if ch.discord_id not in seen_discord_ids:
            if ch.type == "GuildCategory":
                session.flush()
                session.query(ChannelModel).filter(ChannelModel.pk == ch.pk).delete(synchronize_session="fetch")
            else:
                ch.is_deleted = True


def save_backup_state(
    backup_id: str,
    backup_path: str,
    backup_obj: Any,
    scope: str = "base",
    write_snapshot: bool = False,
) -> None:
    """
    Persists in-memory ServerBackup state into Schema v6 SQLite tables in a single transaction.
    """
    require_db(backup_path, backup_id=backup_id)

    with db_session(backup_id=backup_id, backup_path=backup_path) as session:
        backup = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
        if not backup:
            backup = BackupModel(
                backup_id=str(backup_id),
                backup_name=str(getattr(backup_obj, "backup_name", None) or getattr(backup_obj, "name", None) or backup_id),
                server_id=str(getattr(backup_obj, "id", "") or "") or None,
                server_name=str(getattr(backup_obj, "name", "") or "") or None,
                created_at=datetime.now(timezone.utc),
                storage_mode=_resolve_storage_mode_from_config(backup_path),
                sync_status=SyncStatus.IDLE.value,
            )
            session.add(backup)
            session.flush()

        if hasattr(backup_obj, "updated_at") and backup_obj.updated_at:
            dt = _parse_dt(backup_obj.updated_at)
            if dt:
                backup.last_synced_at = dt

        if hasattr(backup_obj, "steps") and backup_obj.steps:
            any_running = False
            any_failed = False
            for st_key, st_val in backup_obj.steps.items():
                step_str = st_key.value if hasattr(st_key, "value") else str(st_key)
                status_str = st_val.value if hasattr(st_val, "value") else str(st_val)
                set_runtime_step_override(str(backup_id), str(scope), step_str, status_str)
                if status_str == Status.RUNNING.value:
                    any_running = True
                elif status_str == Status.FAILED.value:
                    any_failed = True
            if any_running:
                backup.sync_status = SyncStatus.SYNCING.value
            elif any_failed:
                backup.sync_status = SyncStatus.FAILED.value
            else:
                backup.sync_status = SyncStatus.IDLE.value
                backup.sync_error = None
                if not backup.last_synced_at:
                    backup.last_synced_at = datetime.now(timezone.utc)

        if str(scope) == "update":
            if hasattr(backup_obj, "to_dict"):
                import copy
                _RUNTIME_UPDATE_STATE[str(backup_id)] = copy.deepcopy(backup_obj.to_dict())
            session.commit()
            if write_snapshot:
                snapshot_target_path = (Path(backup_path) / "Info" / "backup_info_update.json").as_posix()
                if hasattr(backup_obj, "to_dict"):
                    t.save_json_atomic(backup_obj.to_dict(), snapshot_target_path)
            return

        if hasattr(backup_obj, "categories") and backup_obj.categories:
            _sync_channels_internal(session, str(backup_id), backup_obj.categories)

        session.commit()

        if write_snapshot:
            filename = "backup_info.json" if str(scope) == "base" else "backup_info_update.json"
            snapshot_target_path = (Path(backup_path) / "Info" / filename).as_posix()
            export_backup_info_snapshot(
                session=session,
                backup_id=str(backup_id),
                target_path=snapshot_target_path,
                scope=str(scope),
                write_to_disk=True,
            )


def cleanup_update_export(backup_id: str, backup_path: str) -> None:
    """Clears legacy 'update' scope step tracking and runtime update state."""
    require_db(backup_path, backup_id=backup_id)
    _RUNTIME_UPDATE_STATE.pop(str(backup_id), None)
    clear_runtime_step_overrides(str(backup_id), scope="update")


def get_step_statuses(
    backup_id: str,
    backup_path: str,
    scope: str = "base",
) -> Dict[str, str]:
    """Returns backward-compatible step_name -> status map synthesized from Schema v6 BackupModel."""
    require_db(backup_path, backup_id=backup_id)
    try:
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            backup = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
            if not backup:
                return {}
            has_channels = session.query(ChannelModel.pk).filter(
                ChannelModel.backup_id == str(backup_id)
            ).first() is not None
            _, steps_dict = synthesize_legacy_steps(backup, scope=str(scope), has_channels=has_channels)
            return steps_dict
    except Exception as e:
        t.log("debug", f"Failed to read step statuses from SQLite: {e}")
        return {}


def update_step_status(
    backup_id: str,
    backup_path: str,
    step: str,
    status: str,
    scope: str = "base",
    error: Optional[str] = None,
    write_snapshot: bool = True,
    snapshot_target_path: Optional[str] = None,
) -> None:
    """
    Updates BackupModel.sync_status / sync_error / timestamps in SQLite and records
    backward-compatible step status in runtime overrides.
    """
    require_db(backup_path, backup_id=backup_id)
    step_val = step.value if hasattr(step, "value") else str(step)
    status_val = status.value if hasattr(status, "value") else str(status)

    try:
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            backup = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
            if not backup:
                backup = BackupModel(
                    backup_id=str(backup_id),
                    backup_name=str(backup_id),
                    created_at=datetime.now(timezone.utc),
                    storage_mode=_resolve_storage_mode_from_config(backup_path),
                    sync_status=SyncStatus.IDLE.value,
                )
                session.add(backup)
                session.flush()

            now_utc = datetime.now(timezone.utc)
            set_runtime_step_override(str(backup_id), str(scope), step_val, status_val)

            if status_val == Status.RUNNING.value:
                backup.sync_status = SyncStatus.SYNCING.value
                backup.sync_started_at = now_utc
                backup.sync_error = None
            elif status_val == Status.FAILED.value:
                backup.sync_status = SyncStatus.FAILED.value
                incoming_err = str(error) if error else "Process failed"
                if not (backup.sync_error and incoming_err.startswith("Process exited with code")):
                    backup.sync_error = incoming_err
            elif status_val == Status.SUCCESS.value:
                backup.sync_status = SyncStatus.IDLE.value
                backup.last_synced_at = now_utc
                backup.sync_error = None
            elif status_val == Status.PENDING.value:
                backup.sync_status = SyncStatus.IDLE.value
                backup.sync_error = None

            session.commit()

            if write_snapshot:
                export_backup_info_snapshot(
                    session,
                    str(backup_id),
                    target_path=snapshot_target_path,
                    scope=str(scope),
                    write_to_disk=True,
                )
    except Exception as e:
        t.log("debug", f"Failed to update step status in SQLite ({step_val} -> {status_val}): {e}")


def fail_running_steps(
    backup_id: str,
    backup_path: str,
    scope: str = "base",
    error: Optional[str] = None,
    write_snapshot: bool = True,
    snapshot_target_path: Optional[str] = None,
) -> None:
    """Marks BackupModel.sync_status as failed and updates any running synthetic steps."""
    require_db(backup_path, backup_id=backup_id)
    try:
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            backup = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
            if not backup:
                return

            has_channels = session.query(ChannelModel.pk).filter(
                ChannelModel.backup_id == str(backup_id)
            ).first() is not None
            _, current_steps = synthesize_legacy_steps(backup, scope=str(scope), has_channels=has_channels)
            running_keys = [k for k, v in current_steps.items() if v == Status.RUNNING.value]
            if running_keys:
                for k in running_keys:
                    set_runtime_step_override(str(backup_id), str(scope), k, Status.FAILED.value)
            else:
                first_incomplete = next((k for k, v in current_steps.items() if v != Status.SUCCESS.value), None)
                if first_incomplete:
                    set_runtime_step_override(str(backup_id), str(scope), first_incomplete, Status.FAILED.value)

            backup.sync_status = SyncStatus.FAILED.value
            incoming_err = str(error) if error else "Process failed"
            if not (backup.sync_error and incoming_err.startswith("Process exited with code")):
                backup.sync_error = incoming_err
            session.commit()

            if write_snapshot:
                export_backup_info_snapshot(
                    session,
                    str(backup_id),
                    target_path=snapshot_target_path,
                    scope=str(scope),
                    write_to_disk=True,
                )
    except Exception as e:
        t.log("debug", f"Failed to mark running steps as failed in SQLite: {e}")


def sync_channels_to_db(
    backup_id: str,
    backup_path: str,
    categories: list,
    scope: str = "base",
) -> None:
    """
    Synchronizes categories, channels, and threads into Schema v6 ChannelModel
    by (backup_id, discord_id).
    """
    require_db(backup_path, backup_id=backup_id)
    try:
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            backup = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
            if not backup:
                backup = BackupModel(
                    backup_id=str(backup_id),
                    backup_name=str(backup_id),
                    created_at=datetime.now(timezone.utc),
                    storage_mode=_resolve_storage_mode_from_config(backup_path),
                    sync_status=SyncStatus.IDLE.value,
                )
                session.add(backup)
                session.flush()

            _sync_channels_internal(session, str(backup_id), categories)
            session.commit()
    except Exception as e:
        t.log("debug", f"Failed to sync channels to SQLite: {e}")


def is_backup_syncing(backup_id: str, backup_path: str) -> bool:
    """Returns True if BackupModel.sync_status == 'syncing' in SQLite."""
    if not backup_path or not has_db(backup_path, backup_id=backup_id):
        return False
    try:
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            row = (
                session.query(BackupModel.sync_status)
                .filter(BackupModel.backup_id == str(backup_id))
                .first()
            )
            return bool(row and row[0] == SyncStatus.SYNCING.value)
    except Exception:
        return False


def is_backup_paused(backup_id: str, backup_path: str) -> bool:
    """Returns True if BackupModel.sync_status == 'paused' in SQLite."""
    if not backup_path or not has_db(backup_path, backup_id=backup_id):
        return False
    try:
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            row = (
                session.query(BackupModel.sync_status)
                .filter(BackupModel.backup_id == str(backup_id))
                .first()
            )
            return bool(row and row[0] == SyncStatus.PAUSED.value)
    except Exception:
        return False


def update_backup_storage_mode(
    backup_id: str,
    backup_path: str,
    storage_mode: str,
) -> None:
    """Updates BackupModel.storage_mode in SQLite when the database exists."""
    if storage_mode not in (StorageMode.BACKUPLESS.value, StorageMode.FULL.value):
        return
    if not backup_path or not has_db(backup_path, backup_id=backup_id):
        return
    try:
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            backup = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
            if backup and backup.storage_mode != storage_mode:
                backup.storage_mode = storage_mode
                session.commit()
    except Exception as e:
        t.log("debug", f"Failed to update storage_mode in SQLite: {e}")

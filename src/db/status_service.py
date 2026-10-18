from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from db.session import db_session, init_db, require_sqlite_db, has_sqlite_db
from db.models import BackupModel, ExportModel, BackupStepModel, ChannelModel, Step, Status, Scope
from db.snapshots import export_backup_info_snapshot
import utils.tricks as t
import utils.exceptions as exc


def _parse_dt(dt_val: Any) -> Optional[datetime]:
    if not dt_val:
        return None
    if isinstance(dt_val, datetime):
        return dt_val
    try:
        dt = datetime.fromisoformat(str(dt_val))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def init_backup_export(
    backup_id: str,
    backup_path: str,
    backup_name: str,
    server_id: Optional[str] = None,
    server_name: Optional[str] = None,
    scope: str = "base",
    updated_at: Optional[datetime] = None
) -> None:
    """
    Initializes the SQLite database (backup.sqlite) if not present,
    upserts BackupModel, and creates/resets the ExportModel for the given scope with all Step rows.
    """
    init_db(engine_or_backup_id=backup_id, backup_path=backup_path)
    now_utc = updated_at or datetime.now(timezone.utc)

    with db_session(backup_id=backup_id, backup_path=backup_path) as session:
        backup = session.query(BackupModel).filter(BackupModel.backup_id == str(backup_id)).first()
        if not backup:
            backup = BackupModel(
                backup_id=str(backup_id),
                backup_name=str(backup_name),
                server_id=str(server_id) if server_id else None,
                server_name=str(server_name) if server_name else None,
                created_at=now_utc,
            )
            session.add(backup)
        else:
            if backup_name:
                backup.backup_name = str(backup_name)
            if server_id:
                backup.server_id = str(server_id)
            if server_name:
                backup.server_name = str(server_name)
        session.flush()

        export = session.query(ExportModel).filter(
            ExportModel.backup_id == str(backup_id),
            ExportModel.scope == str(scope)
        ).first()

        if not export:
            export = ExportModel(
                backup_id=str(backup_id),
                scope=str(scope),
                updated_at=now_utc
            )
            session.add(export)
            session.flush()
        else:
            export.updated_at = now_utc

        # Ensure all steps exist
        existing_steps = {
            s.step: s for s in session.query(BackupStepModel).filter(BackupStepModel.export_pk == export.pk).all()
        }
        for st in Step:
            step_val = st.value
            if step_val not in existing_steps:
                session.add(BackupStepModel(
                    export_pk=export.pk,
                    step=step_val,
                    status=Status.PENDING.value
                ))
        session.commit()


def load_backup_state(
    backup_id: str,
    backup_path: str,
    scope: str = "base"
) -> Dict[str, Any]:
    """
    Reconstructs the backup state directly from SQLite without reading any JSON files.
    """
    require_sqlite_db(backup_path)
    with db_session(backup_id=backup_id, backup_path=backup_path) as session:
        return export_backup_info_snapshot(
            session=session,
            backup_id=str(backup_id),
            scope=str(scope),
            write_to_disk=False
        )


def _sync_channels_internal(session: Any, export_pk: int, categories: list) -> None:
    existing_channels = session.query(ChannelModel).filter(
        ChannelModel.export_pk == export_pk
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
                export_pk=export_pk,
                discord_id=cat_id_str,
                type="GuildCategory",
                parent_pk=None,
                name=cat_name,
                position=cat_pos,
                path=cat_path,
                is_deleted=cat_is_deleted
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
                    export_pk=export_pk,
                    discord_id=chan_id_str,
                    type=chan_type,
                    parent_pk=cat_model.pk,
                    name=chan_name,
                    position=chan_pos,
                    path=chan_path,
                    is_deleted=chan_is_deleted,
                    message_count=msg_count
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
                        export_pk=export_pk,
                        discord_id=thr_id_str,
                        type="GuildPublicThread",
                        parent_pk=chan_model.pk,
                        name=thr_name,
                        position=thr_pos,
                        path=thr_path,
                        is_deleted=thr_is_deleted,
                        message_count=thr_msg_count
                    )
                    session.add(thr_model)
                    session.flush()
                    channel_by_discord_id[thr_id_str] = thr_model

    for ch in existing_channels:
        if ch.discord_id not in seen_discord_ids:
            ch.is_deleted = True


def save_backup_state(
    backup_id: str,
    backup_path: str,
    backup_obj: Any,
    scope: str = "base",
    write_snapshot: bool = False
) -> None:
    """
    Persists the in-memory ServerBackup state into SQLite in a single transaction:
    syncs timestamps (updated_at, exported_from, exported_at), step statuses, and
    the channel/category/thread hierarchy. Optionally writes backup_info snapshot.
    """
    require_sqlite_db(backup_path)

    with db_session(backup_id=backup_id, backup_path=backup_path) as session:
        export = session.query(ExportModel).filter(
            ExportModel.backup_id == str(backup_id),
            ExportModel.scope == str(scope)
        ).first()

        if not export:
            export = ExportModel(
                backup_id=str(backup_id),
                scope=str(scope),
                updated_at=datetime.now(timezone.utc)
            )
            session.add(export)
            session.flush()

        # Update export timestamps
        if hasattr(backup_obj, "updated_at") and backup_obj.updated_at:
            dt = _parse_dt(backup_obj.updated_at)
            if dt:
                export.updated_at = dt
        if hasattr(backup_obj, "exported_from") and backup_obj.exported_from:
            export.exported_from = _parse_dt(backup_obj.exported_from)
        if hasattr(backup_obj, "exported_at") and backup_obj.exported_at:
            export.exported_at = _parse_dt(backup_obj.exported_at)

        # Sync step statuses
        if hasattr(backup_obj, "steps") and backup_obj.steps:
            existing_steps = {
                s.step: s for s in session.query(BackupStepModel).filter(BackupStepModel.export_pk == export.pk).all()
            }
            now_utc = datetime.now(timezone.utc)
            for st_key, st_val in backup_obj.steps.items():
                step_str = st_key.value if hasattr(st_key, "value") else str(st_key)
                status_str = st_val.value if hasattr(st_val, "value") else str(st_val)
                step_model = existing_steps.get(step_str)
                if step_model:
                    step_model.status = status_str
                    if status_str == Status.RUNNING.value and not step_model.started_at:
                        step_model.started_at = now_utc
                    elif status_str in (Status.SUCCESS.value, Status.FAILED.value) and not step_model.finished_at:
                        step_model.finished_at = now_utc
                else:
                    step_model = BackupStepModel(
                        export_pk=export.pk,
                        step=step_str,
                        status=status_str,
                        started_at=now_utc if status_str == Status.RUNNING.value else None,
                        finished_at=now_utc if status_str in (Status.SUCCESS.value, Status.FAILED.value) else None,
                    )
                    session.add(step_model)

        # Sync categories, channels, threads
        if hasattr(backup_obj, "categories") and backup_obj.categories:
            _sync_channels_internal(session, export.pk, backup_obj.categories)

        session.commit()

        if write_snapshot:
            filename = "backup_info.json" if str(scope) == "base" else "backup_info_update.json"
            snapshot_target_path = (Path(backup_path) / "Info" / filename).as_posix()
            export_backup_info_snapshot(
                session=session,
                backup_id=str(backup_id),
                target_path=snapshot_target_path,
                scope=str(scope),
                write_to_disk=True
            )


def cleanup_update_export(backup_id: str, backup_path: str) -> None:
    """Deletes the temporary scope='update' ExportModel after an update is merged and finished."""
    require_sqlite_db(backup_path)
    with db_session(backup_id=backup_id, backup_path=backup_path) as session:
        export = session.query(ExportModel).filter(
            ExportModel.backup_id == str(backup_id),
            ExportModel.scope == Scope.UPDATE.value
        ).first()
        if export:
            session.delete(export)
            session.commit()


def get_step_statuses(
    backup_id: str,
    backup_path: str,
    scope: str = "base"
) -> Dict[str, str]:
    """
    Returns a dictionary of step_name -> status directly from SQLite backup_steps.
    """
    require_sqlite_db(backup_path)
    try:
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            export = session.query(ExportModel).filter(
                ExportModel.backup_id == str(backup_id),
                ExportModel.scope == str(scope)
            ).first()
            if not export:
                return {}

            steps = session.query(BackupStepModel).filter(
                BackupStepModel.export_pk == export.pk
            ).all()
            return {s.step: s.status for s in steps}
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
    snapshot_target_path: Optional[str] = None
) -> None:
    """
    Synchronously updates the execution status of a pipeline step in SQLite.
    Optionally refreshes the backup_info.json snapshot on completion.
    """
    require_sqlite_db(backup_path)
    step_val = step.value if hasattr(step, "value") else str(step)
    status_val = status.value if hasattr(status, "value") else str(status)

    try:
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            export = session.query(ExportModel).filter(
                ExportModel.backup_id == str(backup_id),
                ExportModel.scope == str(scope)
            ).first()

            if not export:
                export = ExportModel(
                    backup_id=str(backup_id),
                    scope=str(scope),
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(export)
                session.flush()

            step_model = session.query(BackupStepModel).filter(
                BackupStepModel.export_pk == export.pk,
                BackupStepModel.step == step_val
            ).first()

            now_utc = datetime.now(timezone.utc)

            if not step_model:
                step_model = BackupStepModel(
                    export_pk=export.pk,
                    step=step_val,
                    status=status_val,
                    started_at=now_utc if status_val == Status.RUNNING.value else None,
                    finished_at=now_utc if status_val in (Status.SUCCESS.value, Status.FAILED.value) else None,
                    error=str(error) if error and status_val == Status.FAILED.value else None
                )
                session.add(step_model)
            else:
                step_model.status = status_val
                if status_val == Status.RUNNING.value:
                    step_model.started_at = now_utc
                    step_model.finished_at = None
                    step_model.error = None
                elif status_val == Status.SUCCESS.value:
                    step_model.finished_at = now_utc
                    step_model.error = None
                elif status_val == Status.FAILED.value:
                    step_model.finished_at = now_utc
                    step_model.error = str(error) if error else None
                elif status_val == Status.PENDING.value:
                    step_model.started_at = None
                    step_model.finished_at = None
                    step_model.error = None

            session.commit()

            if write_snapshot:
                export_backup_info_snapshot(
                    session,
                    str(backup_id),
                    target_path=snapshot_target_path,
                    scope=str(scope),
                    write_to_disk=True
                )
    except Exception as e:
        t.log("debug", f"Failed to update step status in SQLite ({step_val} -> {status_val}): {e}")


def fail_running_steps(
    backup_id: str,
    backup_path: str,
    scope: str = "base",
    error: Optional[str] = None,
    write_snapshot: bool = True,
    snapshot_target_path: Optional[str] = None
) -> None:
    """Marks any currently running steps as failed in SQLite."""
    require_sqlite_db(backup_path)
    try:
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            export = session.query(ExportModel).filter(
                ExportModel.backup_id == str(backup_id),
                ExportModel.scope == str(scope)
            ).first()
            if not export:
                return

            now_utc = datetime.now(timezone.utc)
            running_steps = session.query(BackupStepModel).filter(
                BackupStepModel.export_pk == export.pk,
                BackupStepModel.status == Status.RUNNING.value
            ).all()

            if not running_steps:
                first_incomplete = session.query(BackupStepModel).filter(
                    BackupStepModel.export_pk == export.pk,
                    BackupStepModel.status != Status.SUCCESS.value
                ).first()
                if first_incomplete:
                    first_incomplete.status = Status.FAILED.value
                    first_incomplete.finished_at = now_utc
                    first_incomplete.error = str(error) if error else "Process failed"
                else:
                    return
            else:
                for s in running_steps:
                    s.status = Status.FAILED.value
                    s.finished_at = now_utc
                    s.error = str(error) if error else None

            session.commit()

            if write_snapshot:
                export_backup_info_snapshot(
                    session,
                    str(backup_id),
                    target_path=snapshot_target_path,
                    scope=str(scope),
                    write_to_disk=True
                )
    except Exception as e:
        t.log("debug", f"Failed to mark running steps as failed in SQLite: {e}")


def sync_channels_to_db(
    backup_id: str,
    backup_path: str,
    categories: list,
    scope: str = "base"
) -> None:
    """
    Synchronizes the categories, channels, and threads hierarchy into SQLite ChannelModel.
    Upserts existing records by (export_pk, discord_id) to maintain referential integrity with scenes.
    Marks removed channels as is_deleted = True.
    """
    require_sqlite_db(backup_path)
    try:
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            export = session.query(ExportModel).filter(
                ExportModel.backup_id == str(backup_id),
                ExportModel.scope == str(scope)
            ).first()

            if not export:
                export = ExportModel(
                    backup_id=str(backup_id),
                    scope=str(scope),
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(export)
                session.flush()

            _sync_channels_internal(session, export.pk, categories)
            session.commit()
    except Exception as e:
        t.log("debug", f"Failed to sync channels to SQLite: {e}")

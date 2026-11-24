from pathlib import Path
from typing import Optional, Dict, Any
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from utils.tricks import (
    save_json_atomic,
    get_backup_path,
    is_debug_files_enabled,
    _get_active_context_debug_files,
)
from .models import (
    BackupModel,
    FlaggedMessageModel,
    FlaggedKind,
    FlaggedResolution,
)
from .serializers import build_backup_info_dict, build_character_list_dict


def _is_snapshot_debug_enabled(
    session: Session,
    backup_id: str,
    backup_path: Optional[str] = None,
) -> bool:
    """
    Determines if debug snapshots should be written, honoring an active matching
    BackupContext override first, then BackupModel.debug_files on `session`, and
    finally falling back to `is_debug_files_enabled`.
    """
    active_override = _get_active_context_debug_files(backup_id=backup_id, backup_path=backup_path)
    if active_override is not None:
        return active_override

    try:
        bind = session.get_bind()
        if bind is not None:
            inspector = inspect(bind)
            if inspector.has_table("backups"):
                cols = {col["name"] for col in inspector.get_columns("backups")}
                if "debug_files" in cols:
                    backup = (
                        session.query(BackupModel)
                        .filter(BackupModel.backup_id == str(backup_id))
                        .first()
                    )
                    if backup is not None:
                        return bool(backup.debug_files)
    except Exception:
        pass

    return is_debug_files_enabled(backup_id=backup_id, backup_path=backup_path)


def export_backup_info_snapshot(
    session: Session,
    backup_id: str,
    target_path: Optional[str] = None,
    scope: str = "base",
    write_to_disk: bool = True,
    backup_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Reconstructs and optionally atomically writes the human-readable backup_info.json snapshot
    from the database tables when debugFiles is enabled.
    """
    debug_enabled = _is_snapshot_debug_enabled(session, backup_id=backup_id, backup_path=backup_path)
    if write_to_disk and not debug_enabled:
        return {}

    snapshot = build_backup_info_dict(session, backup_id=backup_id, scope=scope)

    if write_to_disk and debug_enabled:
        if not target_path:
            resolved_path = backup_path or get_backup_path(backup_id)
            filename = "backup_info.json" if scope == "base" else "backup_info_update.json"
            target_path = (Path(resolved_path) / "Info" / filename).as_posix()
        save_json_atomic(snapshot, target_path)

    return snapshot


def export_character_list_snapshot(
    session: Session,
    backup_id: str,
    target_path: Optional[str] = None,
    write_to_disk: bool = True,
    backup_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Reconstructs and optionally atomically writes the human-readable character_list.json snapshot
    from the database tables when debugFiles is enabled.
    """
    debug_enabled = _is_snapshot_debug_enabled(session, backup_id=backup_id, backup_path=backup_path)
    if write_to_disk and not debug_enabled:
        return {}

    snapshot = build_character_list_dict(session, backup_id=backup_id)

    if write_to_disk and debug_enabled:
        if not target_path:
            resolved_path = backup_path or get_backup_path(backup_id)
            target_path = (Path(resolved_path) / "Info" / "character_list.json").as_posix()
        save_json_atomic(snapshot, target_path)

    return snapshot


def export_backup_config_snapshot(
    session: Session,
    backup_id: str,
    backup_path: Optional[str] = None,
    target_path: Optional[str] = None,
    force: bool = False,
) -> Optional[str]:
    """
    Serializes BackupModel, BackupCategoryConfigModel, and BackupRbacEntryModel into
    `<backup_dir>/Info/backup_config.json` when debugFiles is enabled.
    Returns the written path, or None when debugFiles is disabled.
    """
    if not force and not _is_snapshot_debug_enabled(session, backup_id=backup_id, backup_path=backup_path):
        return None

    from .config_service import _derive_fallback_rel_path, serialize_backup_config_from_session

    resolved_dir = backup_path
    if not resolved_dir and not target_path:
        resolved_dir = get_backup_path(backup_id)

    fallback_rel = _derive_fallback_rel_path(resolved_dir)
    serialized = serialize_backup_config_from_session(
        session,
        backup_id=str(backup_id),
        fallback_path=fallback_rel,
    )
    out_path = target_path or (Path(resolved_dir) / "Info" / "backup_config.json").as_posix()
    save_json_atomic(serialized, out_path)
    return out_path


def export_curation_snapshots(
    session: Session,
    backup_id: str,
    backup_path: Optional[str] = None
) -> None:
    """
    Exports auxiliary debug snapshots (fixed_messages.json, bad_messages.json, bad_end_messages.json)
    from SQLite tables into the Info/ folder.
    """

    if not _is_snapshot_debug_enabled(session, backup_id=backup_id, backup_path=backup_path):
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
            "content": o.override_content if o.override_content is not None else o.content,
            "author": o.override_author if o.override_author is not None else o.author,
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

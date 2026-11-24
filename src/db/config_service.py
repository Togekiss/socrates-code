"""
SQL-backed backup configuration and RBAC persistence service (Schema v7).

Centralizes reading, writing, serialization, and legacy-category-name promotion
for `BackupModel`, `BackupCategoryConfigModel`, and `BackupRbacEntryModel`, with
clean fallback to `<backup_path>/backup_config.json` for pre-v7 or uninitialized
backups.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from db.models import (
    BackupCategoryConfigModel,
    BackupModel,
    BackupRbacEntryModel,
    CategoryConfigKind,
    ChannelModel,
    RbacAccessLevel,
    RbacTargetType,
    StorageMode,
)
from db.session import db_session, get_engine, has_db, init_db
from utils import exceptions as exc
from utils import tricks as t
from utils.path_safety import SNOWFLAKE_RE, strip_category_prefix


DEFAULT_VERBOSITY: Dict[str, bool] = {
    "info": True,
    "debug": True,
    "console": True,
    "log": True,
    "debugFiles": False,
}

DEFAULT_ADMIN_CONFIG: Dict[str, Any] = {
    "serverName": "",
    "serverId": "",
    "storageMode": StorageMode.BACKUPLESS.value,
    "categoriesToKeep": [],
    "keepMode": False,
    "categoriesToIgnore": [],
    "chatroomCategories": [],
    "eventCategories": [],
    "backupName": "",
    "path": "",
    "verbosity": dict(DEFAULT_VERBOSITY),
}

_CATEGORY_KIND_KEYS: Tuple[Tuple[str, str], ...] = (
    ("categoriesToKeep", CategoryConfigKind.KEEP.value),
    ("categoriesToIgnore", CategoryConfigKind.IGNORE.value),
    ("chatroomCategories", CategoryConfigKind.CHATROOM.value),
    ("eventCategories", CategoryConfigKind.EVENT.value),
)

_RBAC_ROLE_KEYS: Tuple[Tuple[str, str, str], ...] = (
    ("adminRoleIds", RbacTargetType.ROLE.value, RbacAccessLevel.ADMIN.value),
    ("curatorRoleIds", RbacTargetType.ROLE.value, RbacAccessLevel.CURATOR.value),
    ("participantRoleIds", RbacTargetType.ROLE.value, RbacAccessLevel.PARTICIPANT.value),
    ("restrictedUserIds", RbacTargetType.USER.value, RbacAccessLevel.RESTRICTED.value),
    ("blockedUserIds", RbacTargetType.USER.value, RbacAccessLevel.BLOCKED.value),
)

_RBAC_EXTENDED_USER_KEYS: Tuple[Tuple[str, str, str], ...] = (
    ("adminUserIds", RbacTargetType.USER.value, RbacAccessLevel.ADMIN.value),
    ("curatorUserIds", RbacTargetType.USER.value, RbacAccessLevel.CURATOR.value),
    ("participantUserIds", RbacTargetType.USER.value, RbacAccessLevel.PARTICIPANT.value),
)


def get_default_global_config() -> Dict[str, Any]:
    """Returns a fresh copy of the default global/backup configuration dictionary."""
    return {
        "admin": copy.deepcopy(DEFAULT_ADMIN_CONFIG),
        "rbac": {
            "adminRoleIds": [],
            "curatorRoleIds": [],
            "participantRoleIds": [],
            "restrictedUserIds": [],
            "blockedUserIds": [],
        },
    }


def _dedupe_str_list(values: Any) -> List[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    seen: Set[str] = set()
    out: List[str] = []
    for item in values:
        if item is None:
            continue
        cleaned = str(item).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def _normalize_category_ref(raw_ref: Any, name_to_id_map: Optional[Dict[str, str]] = None) -> str:
    raw = str(raw_ref or "").strip()
    if not raw:
        return ""
    if SNOWFLAKE_RE.fullmatch(raw):
        return raw
    stripped = strip_category_prefix(raw)
    if not stripped:
        return ""
    if name_to_id_map:
        resolved = name_to_id_map.get(stripped.lower()) or name_to_id_map.get(raw.lower())
        if resolved:
            return str(resolved).strip()
    return stripped


def _build_normalized_name_map(name_to_id_map: Optional[Dict[str, str]]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    if not name_to_id_map:
        return normalized
    for raw_name, raw_id in name_to_id_map.items():
        cid = str(raw_id or "").strip()
        if not cid:
            continue
        raw_key = str(raw_name or "").strip().lower()
        stripped_key = strip_category_prefix(raw_name).lower()
        if stripped_key:
            normalized[stripped_key] = cid
        if raw_key:
            normalized[raw_key] = cid
    return normalized


def build_category_name_to_id_map(channels: Iterable[ChannelModel]) -> Dict[str, str]:
    """Builds a lowercase category name -> Discord Snowflake ID map from ChannelModel rows."""
    mapping: Dict[str, str] = {}
    for ch in channels:
        if getattr(ch, "type", None) != "GuildCategory":
            continue
        cid = str(getattr(ch, "discord_id", "") or "").strip()
        if not SNOWFLAKE_RE.fullmatch(cid):
            continue
        raw_name = str(getattr(ch, "name", "") or "").strip().lower()
        stripped = strip_category_prefix(getattr(ch, "name", "")).lower()
        if stripped:
            mapping[stripped] = cid
        if raw_name:
            mapping[raw_name] = cid
    return mapping


def _resolve_backup_dir(backup_id: Optional[str] = None, backup_path: Optional[str] = None) -> Optional[str]:
    if backup_path:
        return str(backup_path)
    if backup_id:
        try:
            return t.get_backup_path(str(backup_id))
        except Exception:
            return None
    return None


def _derive_fallback_rel_path(resolved_path: Optional[str]) -> str:
    if not resolved_path:
        return ""
    p = Path(resolved_path)
    if p.parent.name == "Backups":
        return f"Backups/{p.name}"
    return resolved_path.replace("\\", "/")


def _normalize_loaded_json_config(raw: Any, fallback_path: str = "") -> Dict[str, Any]:
    defaults = get_default_global_config()
    src = raw if isinstance(raw, dict) else {}
    admin_src = src.get("admin") if isinstance(src.get("admin"), dict) else {}
    verb_src = admin_src.get("verbosity") if isinstance(admin_src.get("verbosity"), dict) else {}

    merged_verb = dict(defaults["admin"]["verbosity"])
    for key in merged_verb:
        if key in verb_src:
            merged_verb[key] = bool(verb_src[key])

    merged_admin = dict(defaults["admin"])
    merged_admin["serverName"] = str(admin_src.get("serverName") or src.get("server_name") or "")
    merged_admin["serverId"] = str(admin_src.get("serverId") or src.get("server_id") or "")
    storage_mode = admin_src.get("storageMode") or src.get("storageMode") or StorageMode.BACKUPLESS.value
    merged_admin["storageMode"] = (
        str(storage_mode)
        if storage_mode in (StorageMode.BACKUPLESS.value, StorageMode.FULL.value)
        else StorageMode.BACKUPLESS.value
    )
    for json_key, _ in _CATEGORY_KIND_KEYS:
        normalized_refs = [_normalize_category_ref(x) for x in (admin_src.get(json_key) or [])]
        merged_admin[json_key] = _dedupe_str_list(normalized_refs)
    merged_admin["keepMode"] = bool(admin_src.get("keepMode", False))
    merged_admin["backupName"] = str(admin_src.get("backupName") or src.get("backup_name") or merged_admin["serverName"])
    merged_admin["path"] = str(admin_src.get("path") or fallback_path or "")
    merged_admin["verbosity"] = merged_verb

    rbac_src = src.get("rbac") if isinstance(src.get("rbac"), dict) else {}
    merged_rbac = {
        key: _dedupe_str_list(rbac_src.get(key))
        for key, _, _ in _RBAC_ROLE_KEYS
    }

    return {
        "admin": merged_admin,
        "rbac": merged_rbac,
    }


def _export_backup_config_debug_snapshot(
    session: Session,
    backup_id: str,
    backup_dir: Optional[str],
) -> None:
    if not backup_dir:
        return
    try:
        from db.snapshots import export_backup_config_snapshot

        export_backup_config_snapshot(
            session,
            backup_id=backup_id,
            backup_path=backup_dir,
            force=True,
        )
    except Exception as e:
        t.global_log("warning", f"Failed to write debug backup_config.json snapshot in '{backup_dir}': {e}")


def populate_rbac_models_from_dict(
    session: Session,
    backup_id: str,
    rbac_data: Optional[Dict[str, Any]],
) -> None:
    """Replaces BackupRbacEntryModel rows for backup_id from an RBAC config dictionary."""
    b_id = str(backup_id)
    src = rbac_data if isinstance(rbac_data, dict) else {}

    session.query(BackupRbacEntryModel).filter(
        BackupRbacEntryModel.backup_id == b_id
    ).delete(synchronize_session="fetch")
    session.flush()

    seen: Set[Tuple[str, str, str]] = set()
    for json_key, target_type, access_level in _RBAC_ROLE_KEYS + _RBAC_EXTENDED_USER_KEYS:
        for discord_id in _dedupe_str_list(src.get(json_key)):
            entry_key = (target_type, access_level, discord_id)
            if entry_key in seen:
                continue
            seen.add(entry_key)
            session.add(
                BackupRbacEntryModel(
                    backup_id=b_id,
                    target_type=target_type,
                    access_level=access_level,
                    discord_id=discord_id,
                )
            )

    backup_model = session.query(BackupModel).filter(BackupModel.backup_id == b_id).first()
    if backup_model is not None:
        session.expire(backup_model, ["rbac_entries"])


def populate_config_models_from_dict(
    session: Session,
    backup_model: BackupModel,
    config_data: Optional[Dict[str, Any]],
    name_to_id_map: Optional[Dict[str, str]] = None,
) -> None:
    """
    Populates BackupModel config columns, BackupCategoryConfigModel rows, and
    (if present) BackupRbacEntryModel rows from a config dictionary.
    """
    cfg = config_data if isinstance(config_data, dict) else {}
    admin = cfg.get("admin") if isinstance(cfg.get("admin"), dict) else {}
    verbosity = admin.get("verbosity") if isinstance(admin.get("verbosity"), dict) else {}

    backup_name = admin.get("backupName") or cfg.get("backup_name")
    if backup_name is not None and str(backup_name).strip():
        backup_model.backup_name = str(backup_name).strip()
    elif not backup_model.backup_name:
        backup_model.backup_name = str(admin.get("serverName") or cfg.get("server_name") or backup_model.backup_id)

    server_id = admin.get("serverId") if "serverId" in admin else cfg.get("server_id")
    if server_id is not None:
        cleaned_sid = str(server_id).strip()
        backup_model.server_id = cleaned_sid or None

    server_name = admin.get("serverName") if "serverName" in admin else cfg.get("server_name")
    if server_name is not None:
        cleaned_sname = str(server_name).strip()
        backup_model.server_name = cleaned_sname or None

    if "path" in admin:
        cleaned_path = str(admin.get("path") or "").strip()
        backup_model.path = cleaned_path or None

    storage_mode = admin.get("storageMode") or cfg.get("storageMode")
    if storage_mode in (StorageMode.BACKUPLESS.value, StorageMode.FULL.value):
        backup_model.storage_mode = str(storage_mode)

    if "keepMode" in admin:
        backup_model.keep_mode = bool(admin["keepMode"])
    if "info" in verbosity:
        backup_model.log_info = bool(verbosity["info"])
    if "debug" in verbosity:
        backup_model.log_debug = bool(verbosity["debug"])
    if "console" in verbosity:
        backup_model.log_console = bool(verbosity["console"])
    if "log" in verbosity:
        backup_model.log_file = bool(verbosity["log"])
    if "debugFiles" in verbosity:
        backup_model.debug_files = bool(verbosity["debugFiles"])

    session.flush()

    b_id = str(backup_model.backup_id)
    normalized_map = _build_normalized_name_map(name_to_id_map)

    if isinstance(cfg.get("admin"), dict):
        for json_key, kind_val in _CATEGORY_KIND_KEYS:
            if json_key not in admin:
                continue
            session.query(BackupCategoryConfigModel).filter(
                BackupCategoryConfigModel.backup_id == b_id,
                BackupCategoryConfigModel.kind == kind_val,
            ).delete(synchronize_session="fetch")
            raw_items = admin.get(json_key)
            if not isinstance(raw_items, (list, tuple, set)):
                continue
            seen_kind: Set[str] = set()
            for item in raw_items:
                ref = _normalize_category_ref(item, normalized_map)
                if not ref or ref in seen_kind:
                    continue
                seen_kind.add(ref)
                session.add(
                    BackupCategoryConfigModel(
                        backup_id=b_id,
                        kind=kind_val,
                        category_ref=ref,
                    )
                )
        session.flush()
        session.expire(backup_model, ["category_configs"])

    if isinstance(cfg.get("rbac"), dict):
        populate_rbac_models_from_dict(session, b_id, cfg["rbac"])


def serialize_rbac_from_session(
    session: Session,
    backup_id: str,
    include_user_roles: bool = False,
) -> Dict[str, List[str]]:
    """Serializes BackupRbacEntryModel rows for backup_id into the RBAC dictionary shape."""
    b_id = str(backup_id)
    key_lookup: Dict[Tuple[str, str], str] = {
        (target_type, access_level): json_key
        for json_key, target_type, access_level in _RBAC_ROLE_KEYS
    }
    result: Dict[str, List[str]] = {json_key: [] for json_key, _, _ in _RBAC_ROLE_KEYS}
    if include_user_roles:
        for json_key, target_type, access_level in _RBAC_EXTENDED_USER_KEYS:
            key_lookup[(target_type, access_level)] = json_key
            result[json_key] = []

    rows = (
        session.query(BackupRbacEntryModel)
        .filter(BackupRbacEntryModel.backup_id == b_id)
        .order_by(BackupRbacEntryModel.pk.asc())
        .all()
    )
    for row in rows:
        json_key = key_lookup.get((row.target_type, row.access_level))
        if json_key:
            result[json_key].append(str(row.discord_id))
    return result


def serialize_backup_config_from_session(
    session: Session,
    backup_id: str,
    fallback_path: str = "",
) -> Dict[str, Any]:
    """Serializes BackupModel, BackupCategoryConfigModel, and BackupRbacEntryModel into config JSON shape."""
    b_id = str(backup_id)
    backup = session.query(BackupModel).filter(BackupModel.backup_id == b_id).first()
    if backup is None:
        cfg = get_default_global_config()
        if fallback_path:
            cfg["admin"]["path"] = fallback_path
        return cfg

    cats_by_kind: Dict[str, List[str]] = {
        CategoryConfigKind.KEEP.value: [],
        CategoryConfigKind.IGNORE.value: [],
        CategoryConfigKind.CHATROOM.value: [],
        CategoryConfigKind.EVENT.value: [],
    }
    cat_rows = (
        session.query(BackupCategoryConfigModel)
        .filter(BackupCategoryConfigModel.backup_id == b_id)
        .order_by(BackupCategoryConfigModel.pk.asc())
        .all()
    )
    for row in cat_rows:
        if row.kind in cats_by_kind:
            cats_by_kind[row.kind].append(str(row.category_ref))

    return {
        "admin": {
            "serverName": backup.server_name or "",
            "serverId": backup.server_id or "",
            "storageMode": backup.storage_mode or StorageMode.BACKUPLESS.value,
            "categoriesToKeep": cats_by_kind[CategoryConfigKind.KEEP.value],
            "keepMode": bool(backup.keep_mode),
            "categoriesToIgnore": cats_by_kind[CategoryConfigKind.IGNORE.value],
            "chatroomCategories": cats_by_kind[CategoryConfigKind.CHATROOM.value],
            "eventCategories": cats_by_kind[CategoryConfigKind.EVENT.value],
            "backupName": backup.backup_name or "",
            "path": backup.path if backup.path else (fallback_path or ""),
            "verbosity": {
                "info": bool(backup.log_info),
                "debug": bool(backup.log_debug),
                "console": bool(backup.log_console),
                "log": bool(backup.log_file),
                "debugFiles": bool(backup.debug_files),
            },
        },
        "rbac": serialize_rbac_from_session(session, b_id, include_user_roles=False),
    }


def _maybe_import_json_if_tables_empty(
    session: Session,
    backup_model: BackupModel,
    resolved_dir: Optional[str],
) -> None:
    if not resolved_dir:
        return
    cfg_file = Path(resolved_dir) / "backup_config.json"
    if not cfg_file.is_file():
        return

    b_id = str(backup_model.backup_id)
    cat_count = (
        session.query(BackupCategoryConfigModel)
        .filter(BackupCategoryConfigModel.backup_id == b_id)
        .count()
    )
    rbac_count = (
        session.query(BackupRbacEntryModel)
        .filter(BackupRbacEntryModel.backup_id == b_id)
        .count()
    )
    if cat_count > 0 or rbac_count > 0:
        return

    try:
        raw_cfg = t.load_from_json(cfg_file.as_posix())
    except Exception as e:
        t.global_log("warning", f"Failed to read legacy backup_config.json at '{cfg_file}': {e}")
        return

    if not isinstance(raw_cfg, dict) or (not raw_cfg.get("admin") and not raw_cfg.get("rbac")):
        return

    channels = session.query(ChannelModel).filter(ChannelModel.backup_id == b_id).all()
    name_to_id_map = build_category_name_to_id_map(channels)
    populate_config_models_from_dict(session, backup_model, raw_cfg, name_to_id_map=name_to_id_map)
    session.flush()


def load_backup_config_dict(
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Loads the normalized configuration dictionary for a backup.
    Reads from SQLite/Postgres (Schema v7) when available, auto-importing an existing
    backup_config.json if both config tables are empty, and falls back to
    backup_config.json or defaults otherwise.
    """
    resolved_dir = _resolve_backup_dir(backup_id=backup_id, backup_path=backup_path)
    fallback_rel = _derive_fallback_rel_path(resolved_dir)

    if has_db(backup_id=backup_id, backup_path=resolved_dir):
        try:
            with db_session(backup_id=backup_id, backup_path=resolved_dir) as session:
                inspector = inspect(session.get_bind())
                has_v7_tables = (
                    inspector.has_table("backups")
                    and inspector.has_table("backup_category_configs")
                    and inspector.has_table("backup_rbac_entries")
                )
                if has_v7_tables:
                    backup_model = (
                        session.query(BackupModel)
                        .filter(BackupModel.backup_id == str(backup_id))
                        .first()
                        if backup_id is not None
                        else session.query(BackupModel).first()
                    )
                    if backup_model is not None:
                        _maybe_import_json_if_tables_empty(session, backup_model, resolved_dir)
                        return serialize_backup_config_from_session(
                            session,
                            backup_model.backup_id,
                            fallback_path=fallback_rel,
                        )
        except Exception as e:
            t.global_log("warning", f"load_backup_config_dict DB read failed, falling back: {e}")

    if resolved_dir:
        cfg_file = Path(resolved_dir) / "backup_config.json"
        if cfg_file.is_file():
            try:
                raw = t.load_from_json(cfg_file.as_posix())
                return _normalize_loaded_json_config(raw, fallback_path=fallback_rel)
            except Exception as e:
                raise exc.ConfigurationError(f"Failed to load backup_config.json at '{cfg_file}': {e}") from e

    cfg = get_default_global_config()
    if fallback_rel:
        cfg["admin"]["path"] = fallback_rel
    return cfg


def save_backup_config_dict(
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
    config_data: Optional[Dict[str, Any]] = None,
    create_db_if_missing: bool = False,
) -> Dict[str, Any]:
    """
    Persists a backup configuration dictionary into SQL (or backup_config.json if no DB exists
    and create_db_if_missing=False). Exports Info/backup_config.json when debug_files is True.
    """
    resolved_dir = _resolve_backup_dir(backup_id=backup_id, backup_path=backup_path)
    fallback_rel = _derive_fallback_rel_path(resolved_dir)
    cfg = config_data if isinstance(config_data, dict) else {}
    admin = cfg.get("admin") if isinstance(cfg.get("admin"), dict) else {}

    if create_db_if_missing:
        if not has_db(backup_id=backup_id, backup_path=resolved_dir):
            init_db(backup_id=backup_id, backup_path=resolved_dir)
        else:
            engine = get_engine(backup_id=backup_id, backup_path=resolved_dir)
            if not inspect(engine).get_table_names():
                init_db(engine)

    if has_db(backup_id=backup_id, backup_path=resolved_dir):
        with db_session(backup_id=backup_id, backup_path=resolved_dir) as session:
            inspector = inspect(session.get_bind())
            has_v7_tables = (
                inspector.has_table("backups")
                and inspector.has_table("backup_category_configs")
                and inspector.has_table("backup_rbac_entries")
            )
            if has_v7_tables:
                backup_model = (
                    session.query(BackupModel)
                    .filter(BackupModel.backup_id == str(backup_id))
                    .first()
                    if backup_id is not None
                    else session.query(BackupModel).first()
                )
                if backup_model is None:
                    resolved_bid = str(
                        backup_id
                        or cfg.get("backup_id")
                        or (Path(resolved_dir).name if resolved_dir else "default")
                    )
                    resolved_bname = str(
                        admin.get("backupName")
                        or cfg.get("backup_name")
                        or admin.get("serverName")
                        or resolved_bid
                    )
                    backup_model = BackupModel(
                        backup_id=resolved_bid,
                        backup_name=resolved_bname,
                        path=str(admin.get("path") or fallback_rel or "") or None,
                    )
                    session.add(backup_model)
                    session.flush()

                _maybe_import_json_if_tables_empty(session, backup_model, resolved_dir)
                channels = (
                    session.query(ChannelModel)
                    .filter(ChannelModel.backup_id == backup_model.backup_id)
                    .all()
                )
                name_to_id_map = build_category_name_to_id_map(channels)
                populate_config_models_from_dict(
                    session,
                    backup_model,
                    cfg,
                    name_to_id_map=name_to_id_map,
                )
                session.flush()
                serialized = serialize_backup_config_from_session(
                    session,
                    backup_model.backup_id,
                    fallback_path=fallback_rel,
                )
                if backup_model.debug_files:
                    _export_backup_config_debug_snapshot(session, backup_model.backup_id, resolved_dir)
                return serialized

    if resolved_dir:
        cfg_file = Path(resolved_dir) / "backup_config.json"
        existing: Dict[str, Any] = {}
        if cfg_file.is_file():
            try:
                loaded = t.load_from_json(cfg_file.as_posix())
                if isinstance(loaded, dict):
                    existing = loaded
            except Exception:
                existing = {}
        to_save = _normalize_loaded_json_config(cfg, fallback_path=fallback_rel)
        if "rbac" not in cfg and isinstance(existing.get("rbac"), dict):
            to_save["rbac"] = {
                key: _dedupe_str_list(existing["rbac"].get(key))
                for key, _, _ in _RBAC_ROLE_KEYS
            }
        t.save_json_atomic(to_save, cfg_file.as_posix())
        return to_save

    raise exc.ConfigurationError("Cannot save backup config without backup_id or backup_path.")


def load_rbac_config_dict(
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
    include_user_roles: bool = False,
) -> Dict[str, List[str]]:
    """Loads the 5-key RBAC dictionary (or 8-key with include_user_roles=True) from SQL or JSON fallback."""
    resolved_dir = _resolve_backup_dir(backup_id=backup_id, backup_path=backup_path)
    keys = _RBAC_ROLE_KEYS + (_RBAC_EXTENDED_USER_KEYS if include_user_roles else ())

    if has_db(backup_id=backup_id, backup_path=resolved_dir):
        try:
            with db_session(backup_id=backup_id, backup_path=resolved_dir) as session:
                inspector = inspect(session.get_bind())
                if inspector.has_table("backup_rbac_entries") and inspector.has_table("backups"):
                    backup_model = (
                        session.query(BackupModel)
                        .filter(BackupModel.backup_id == str(backup_id))
                        .first()
                        if backup_id is not None
                        else session.query(BackupModel).first()
                    )
                    if backup_model is not None:
                        _maybe_import_json_if_tables_empty(session, backup_model, resolved_dir)
                        return serialize_rbac_from_session(
                            session,
                            backup_model.backup_id,
                            include_user_roles=include_user_roles,
                        )
        except Exception as e:
            t.global_log("warning", f"load_rbac_config_dict DB read failed, falling back: {e}")

    if resolved_dir:
        cfg_file = Path(resolved_dir) / "backup_config.json"
        if cfg_file.is_file():
            try:
                raw = t.load_from_json(cfg_file.as_posix())
                rbac_src = raw.get("rbac") if isinstance(raw, dict) and isinstance(raw.get("rbac"), dict) else {}
                return {key: _dedupe_str_list(rbac_src.get(key)) for key, _, _ in keys}
            except Exception as e:
                t.global_log("warning", f"Failed to read RBAC from '{cfg_file}': {e}")

    return {key: [] for key, _, _ in keys}


def save_rbac_config_dict(
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
    rbac_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[str]]:
    """Persists RBAC configuration into SQL (or backup_config.json fallback) and returns the 5-key dict."""
    resolved_dir = _resolve_backup_dir(backup_id=backup_id, backup_path=backup_path)
    fallback_rel = _derive_fallback_rel_path(resolved_dir)
    src = rbac_data if isinstance(rbac_data, dict) else {}
    normalized = {key: _dedupe_str_list(src.get(key)) for key, _, _ in _RBAC_ROLE_KEYS}

    if has_db(backup_id=backup_id, backup_path=resolved_dir):
        with db_session(backup_id=backup_id, backup_path=resolved_dir) as session:
            inspector = inspect(session.get_bind())
            if inspector.has_table("backup_rbac_entries") and inspector.has_table("backups"):
                backup_model = (
                    session.query(BackupModel)
                    .filter(BackupModel.backup_id == str(backup_id))
                    .first()
                    if backup_id is not None
                    else session.query(BackupModel).first()
                )
                if backup_model is None:
                    resolved_bid = str(
                        backup_id
                        or (Path(resolved_dir).name if resolved_dir else "default")
                    )
                    backup_model = BackupModel(
                        backup_id=resolved_bid,
                        backup_name=resolved_bid,
                        path=fallback_rel or None,
                    )
                    session.add(backup_model)
                    session.flush()

                populate_rbac_models_from_dict(session, backup_model.backup_id, src)
                session.flush()
                saved = serialize_rbac_from_session(session, backup_model.backup_id)
                if backup_model.debug_files:
                    _export_backup_config_debug_snapshot(session, backup_model.backup_id, resolved_dir)
                return saved

    if resolved_dir:
        cfg_file = Path(resolved_dir) / "backup_config.json"
        existing: Dict[str, Any] = {}
        if cfg_file.is_file():
            try:
                loaded = t.load_from_json(cfg_file.as_posix())
                if isinstance(loaded, dict):
                    existing = loaded
            except Exception:
                existing = {}
        existing["rbac"] = normalized
        t.save_json_atomic(existing, cfg_file.as_posix())
        return normalized

    raise exc.ConfigurationError("Cannot save RBAC config without backup_id or backup_path.")


def upgrade_category_names_to_ids(
    session: Session,
    backup_id: str,
    name_to_id_map: Dict[str, str],
) -> int:
    """
    Promotes legacy non-Snowflake category_ref values in BackupCategoryConfigModel to
    Discord Snowflake IDs using name_to_id_map. Collapses duplicate (backup_id, kind, new_id)
    rows by deleting redundant legacy-named rows. Returns count of upgraded/collapsed rows.
    """
    b_id = str(backup_id)
    normalized_map = _build_normalized_name_map(name_to_id_map)
    if not normalized_map:
        return 0

    rows = (
        session.query(BackupCategoryConfigModel)
        .filter(BackupCategoryConfigModel.backup_id == b_id)
        .order_by(BackupCategoryConfigModel.pk.asc())
        .all()
    )
    if not rows:
        return 0

    existing_refs: Set[Tuple[str, str]] = {
        (row.kind, str(row.category_ref or "").strip())
        for row in rows
        if str(row.category_ref or "").strip()
    }

    upgraded_count = 0
    for row in rows:
        cur_ref = str(row.category_ref or "").strip()
        if SNOWFLAKE_RE.fullmatch(cur_ref):
            continue
        raw_lower = cur_ref.lower()
        stripped_lower = strip_category_prefix(cur_ref).lower()
        new_id = normalized_map.get(stripped_lower) or normalized_map.get(raw_lower)
        if not new_id or new_id == cur_ref:
            continue

        target_key = (row.kind, new_id)
        if target_key in existing_refs:
            session.delete(row)
        else:
            row.category_ref = new_id
            existing_refs.add(target_key)
        upgraded_count += 1

    if upgraded_count > 0:
        session.flush()
    return upgraded_count

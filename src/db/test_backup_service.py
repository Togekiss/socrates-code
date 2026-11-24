"""
Runtime helpers for resetting, seeding, and staging isolated test backups.

Kept in `src/db/` with zero imports from `tests/` or `unittest` so production
API endpoints (`/api/admin/test-backup/reset`, `/api/admin/test-backup/migrate`,
`/api/admin/tests/run`) never trigger test-harness isolation or inject `unittest`
into `sys.modules`.
"""

from __future__ import annotations

from datetime import datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from res import constants as c
from utils import exceptions as exc
from utils import tricks as t
from db.models import (
    Base,
    BackupModel,
    ChannelModel,
    WriterModel,
    WriterAliasModel,
    CharacterGroupModel,
    GroupNameModel,
    CharacterModel,
    CharacterNameModel,
    SceneModel,
    SceneIssueModel,
    SeenDiscordUserModel,
    FlaggedMessageModel,
    SchemaVersionModel,
    CURRENT_SCHEMA_VERSION,
    FlaggedKind,
    FlaggedResolution,
    SceneKind,
    StorageMode,
    SyncStatus,
)
from db.skeleton_models import TUPPER_ID_MAX, compute_skeleton_flags
from db.session import (
    close_all_engines,
    close_engine,
    db_session,
    get_engine,
    invalidate_sqlite_tmp_cache,
    is_sqlite_tmp_cache_enabled,
    sync_dirty_sqlite_dbs,
)
from db.snapshots import export_backup_info_snapshot, export_character_list_snapshot
from db.config_service import build_category_name_to_id_map, populate_config_models_from_dict
from db.upgrade import _populate_skeletons_and_collect_users, parse_datetime
from deprecated.migrate import (
    cluster_writers,
    extract_group_names,
    migrate_channels,
)

_TEST_FIXTURE_CACHE_LOCK = threading.Lock()


def _resolve_data_root(data_root: Optional[Union[str, Path]] = None) -> Path:
    if data_root is not None:
        return Path(data_root)
    env_root = os.environ.get("SOCRATES_DATA_DIR", "").strip()
    if env_root:
        return Path(env_root)
    return Path(c.DATA_ROOT)


def stage_tmp_test_data_root(
    source_data_root: Union[str, Path],
    target_data_root: Union[str, Path],
) -> Path:
    """
    Stages isolated `/tmp` test fixtures and `backups_index.json` from `source_data_root`
    into `target_data_root` so test suites never mutate live backups or hit GCS FUSE 429s.
    """
    import tempfile

    src_root = Path(source_data_root)
    dst_root = Path(target_data_root)
    backups_dir = dst_root / "Backups"
    out_dir = dst_root / "out"
    backups_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    src_clean = src_root / "Backups" / "Elysium-sql-tests-clean"
    if src_clean.exists():
        digest = hashlib.sha256(os.path.realpath(src_clean).encode("utf-8")).hexdigest()[:16]
        cache_dir = Path(tempfile.gettempdir()) / "socrates_test_fixture_cache" / f"clean_{digest}"
        with _TEST_FIXTURE_CACHE_LOCK:
            if not ((cache_dir / "backup_config.json").exists() or (cache_dir / "Info").exists()):
                shutil.rmtree(cache_dir, ignore_errors=True)
                cache_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src_clean, cache_dir)

        dst_clean = backups_dir / "Elysium-sql-tests-clean"
        dst_test = backups_dir / "Elysium-sql-tests"
        shutil.copytree(cache_dir, dst_clean, dirs_exist_ok=True)
        shutil.copytree(cache_dir, dst_test, dirs_exist_ok=True)
        update_dir = dst_test / "Update"
        if update_dir.exists():
            shutil.rmtree(update_dir, ignore_errors=True)

    for live_name in ("Elysium", "el_meu_server"):
        if (src_root / "Backups" / live_name).exists():
            (backups_dir / live_name).mkdir(parents=True, exist_ok=True)

    index_entries = [
        {
            "backup_id": "1",
            "backup_name": "Elysium",
            "server_id": "857848490683269161",
            "server_name": "(+18) Diabolik: Elysium",
            "path": "Backups/Elysium",
        },
        {
            "backup_id": "1789899843",
            "backup_name": "el meu server",
            "server_id": "442481942794076161",
            "server_name": "el meu server",
            "path": "Backups/el_meu_server",
        },
        {
            "backup_id": "1791895360",
            "backup_name": "Elysium-sql-tests",
            "server_id": "857848490683269161",
            "server_name": "(+18) Diabolik: Elysium",
            "path": "Backups/Elysium-sql-tests",
        },
    ]
    (backups_dir / "backups_index.json").write_text(
        json.dumps(index_entries, indent=4),
        encoding="utf-8",
    )
    return dst_root


def reset_test_backup_dir(data_root: Optional[Union[str, Path]] = None) -> bool:
    """
    Resets `<data_root>/Backups/Elysium-sql-tests` from `Backups/Elysium-sql-tests-clean`,
    releasing SQLite engines and invalidating any `/tmp` SQLite cache for the target.
    """
    resolved_root = _resolve_data_root(data_root)
    src_copy = resolved_root / "Backups" / "Elysium-sql-tests-clean"
    target = resolved_root / "Backups" / "Elysium-sql-tests"

    if not src_copy.exists():
        t.global_log("error", f"Error: Source copy does not exist at {src_copy}")
        return False

    try:
        from models import SceneManager

        SceneManager.clear_cache()
        close_engine(backup_path=target.as_posix(), sync=False, invalidate_cache=True)
        invalidate_sqlite_tmp_cache(backup_path=target.as_posix())
        close_all_engines()
        gc.collect()
    except Exception:
        pass

    target.mkdir(parents=True, exist_ok=True)

    # 1. Clean files in target that do not exist in src_copy (e.g. backup.sqlite, skeletons.sqlite, -wal/-shm, generated scenes)
    for root, dirs, files in os.walk(target, topdown=False):
        rel_root = Path(root).relative_to(target)
        src_root = src_copy / rel_root
        for f in files:
            target_file = Path(root) / f
            src_file = src_root / f
            if not src_file.exists():
                try:
                    target_file.unlink()
                except OSError:
                    pass
        for d in dirs:
            target_dir = Path(root) / d
            src_dir = src_root / d
            if not src_dir.exists():
                try:
                    target_dir.rmdir()
                except OSError:
                    pass

    # 2. Copy pristine files from src_copy to target
    for root, _dirs, files in os.walk(src_copy):
        rel_root = Path(root).relative_to(src_copy)
        dest_root = target / rel_root
        dest_root.mkdir(parents=True, exist_ok=True)
        for f in files:
            src_f = Path(root) / f
            dst_f = dest_root / f
            try:
                shutil.copyfile(src_f, dst_f)
            except OSError:
                time.sleep(0.05)
                try:
                    shutil.copyfile(src_f, dst_f)
                except OSError:
                    pass

    # 3. Remove Update/ folder
    update_dir = target / "Update"
    if update_dir.exists():
        try:
            shutil.rmtree(update_dir)
        except OSError:
            pass

    t.invalidate_backups_index_cache()
    t.global_log("info", "Successfully restored Backups/Elysium-sql-tests from pristine copy.")
    return True


def resolve_info_file(backup_path: Path, filename: str) -> Optional[Path]:
    for cand in (backup_path / "Info" / filename, backup_path / "Info" / "legacy" / filename):
        if cand.is_file():
            return cand
    return None


def _seed_writers_and_characters(
    session,
    backup_id: str,
    character_list: List[Dict[str, Any]],
) -> Tuple[Dict[int, int], Dict[str, int], Dict[str, int]]:
    """Seeds writers, aliases, groups, characters, and names into session."""
    counts = {
        "writers_count": 0,
        "writer_aliases_count": 0,
        "character_groups_count": 0,
        "characters_count": 0,
        "tuppers_count": 0,
    }
    writer_clusters = cluster_writers(character_list)
    alias_to_writer_pk: Dict[str, int] = {}

    for w_data in writer_clusters.values():
        wm = WriterModel(
            backup_id=backup_id,
            display_name=w_data["display_name"],
            discord_user_id=w_data["discord_user_id"],
        )
        session.add(wm)
        session.flush()
        counts["writers_count"] += 1
        for alias_str in w_data["aliases"]:
            session.add(WriterAliasModel(writer_pk=wm.pk, alias=alias_str))
            alias_to_writer_pk[alias_str.lower()] = wm.pk
            counts["writer_aliases_count"] += 1

    def resolve_writer_pk(raw_writer: Any) -> Optional[int]:
        if not raw_writer:
            return None
        if isinstance(raw_writer, str):
            raw_writer = [raw_writer]
        for w in raw_writer:
            if w and w.strip().lower() in alias_to_writer_pk:
                return alias_to_writer_pk[w.strip().lower()]
        return None

    char_id_to_pk: Dict[int, int] = {}
    char_name_to_id: Dict[str, int] = {}

    for item in character_list:
        char_id = int(item["id"])
        tags = item.get("tags", [])
        other_versions = item.get("other_versions", [])
        is_group_parent = "has_other_writers" in tags or any(
            "has_other_writers" in v.get("tags", []) for v in other_versions
        )
        group_pk = None
        if is_group_parent:
            gm = CharacterGroupModel(backup_id=backup_id)
            session.add(gm)
            session.flush()
            group_pk = gm.pk
            counts["character_groups_count"] += 1
            gnames = extract_group_names(item.get("names", [])) or [item["names"][0]]
            for pos, gname in enumerate(gnames):
                session.add(GroupNameModel(group_pk=group_pk, name=gname, position=pos))

        parent_writer_pk = resolve_writer_pk(item.get("writer"))
        top_vtype = (
            "npc" if "npc" in tags
            else "alter_ego" if "alter_ego" in tags
            else "familiar" if "familiar" in tags
            else None
        )
        cm = CharacterModel(
            backup_id=backup_id,
            char_id=char_id,
            writer_pk=parent_writer_pk,
            group_pk=group_pk,
            parent_pk=None,
            version_type=top_vtype,
            origin="canon" if "canon" in tags else "oc",
            activity="active" if "active" in tags else "inactive",
        )
        session.add(cm)
        session.flush()
        char_id_to_pk[char_id] = cm.pk
        counts["characters_count"] += 1

        for pos, name in enumerate(item.get("names", [])):
            session.add(CharacterNameModel(character_pk=cm.pk, name=name, position=pos))
            char_name_to_id.setdefault(str(name).strip().lower(), char_id)

        for v_item in other_versions:
            v_id = int(v_item["id"])
            v_tags = v_item.get("tags", [])
            v_writer_pk = resolve_writer_pk(v_item.get("writer"))
            is_sibling = "has_other_writers" in v_tags and is_group_parent
            v_vtype = (
                "alter_ego" if "alter_ego" in v_tags
                else "npc" if "npc" in v_tags
                else "familiar" if "familiar" in v_tags
                else (None if is_sibling else "alter_ego")
            )
            v_cm = CharacterModel(
                backup_id=backup_id,
                char_id=v_id,
                writer_pk=v_writer_pk,
                group_pk=group_pk if is_sibling else None,
                parent_pk=None if is_sibling else cm.pk,
                version_type=v_vtype,
                origin="canon" if "canon" in v_tags else "oc",
                activity="active" if "active" in v_tags else "inactive",
            )
            session.add(v_cm)
            session.flush()
            char_id_to_pk[v_id] = v_cm.pk
            counts["characters_count" if is_sibling else "tuppers_count"] += 1

            for pos, name in enumerate(v_item.get("names", [])):
                session.add(CharacterNameModel(character_pk=v_cm.pk, name=name, position=pos))
                char_name_to_id.setdefault(str(name).strip().lower(), v_id)

    return char_id_to_pk, char_name_to_id, counts


def seed_test_backup(
    backup_id: str = "1791895360",
    backup_path: Optional[str] = None,
    backup: Optional[Dict[str, Any]] = None,
    storage_mode: Optional[str] = None,
    include_scenes: bool = True,
    include_skeletons: bool = True,
    skip_snapshots: bool = True,
    data_root: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Directly seeds a Schema v7 backup.sqlite + skeletons.sqlite + seen_discord_users + scenes
    for the target backup directory from Info/*.json, Data/*.json, and backup_config.json fixtures.
    """
    resolved_root = _resolve_data_root(data_root)
    if backup is None:
        backup = next((b for b in t.get_backups_index() if str(b["backup_id"]) == str(backup_id)), None)
        if (
            not backup
            and str(backup_id) == "1791895360"
            and (resolved_root / "Backups" / "Elysium-sql-tests").exists()
        ):
            backup = {
                "backup_id": "1791895360",
                "backup_name": "Elysium-sql-tests",
                "server_id": "857848490683269161",
                "server_name": "(+18) Diabolik: Elysium",
                "path": "Backups/Elysium-sql-tests",
            }
        if not backup and not backup_path:
            raise exc.BackupError(f"Backup ID '{backup_id}' not found in index")

    b_id = str(backup_id)
    b_name = str((backup or {}).get("backup_name") or f"Backup {b_id}")
    if backup_path is None:
        backup_path = (resolved_root / backup["path"]).as_posix()
    b_path = Path(backup_path)

    info_file = resolve_info_file(b_path, "backup_info.json")
    if not info_file:
        raise exc.MigrationError(f"Missing backup_info.json in {b_path / 'Info'}")

    backup_info = t.load_from_json(info_file.as_posix())
    char_file = resolve_info_file(b_path, "character_list.json")
    character_list = t.load_from_json(char_file.as_posix()) if char_file else []

    fixed_file = resolve_info_file(b_path, "fixed_messages.json")
    fixed_messages = t.load_from_json(fixed_file.as_posix()) if fixed_file else {}

    bad_file = resolve_info_file(b_path, "bad_messages.json")
    bad_messages = t.load_from_json(bad_file.as_posix()) if bad_file else {}

    bad_end_file = resolve_info_file(b_path, "bad_end_messages.json")
    bad_end_messages = t.load_from_json(bad_end_file.as_posix()) if bad_end_file else {}

    cfg_file = (b_path / "backup_config.json") if (b_path / "backup_config.json").is_file() else resolve_info_file(b_path, "backup_config.json")
    raw_cfg = t.load_from_json(cfg_file.as_posix()) if cfg_file else {}
    if not isinstance(raw_cfg, dict):
        raw_cfg = {}

    resolved_mode = storage_mode or (
        StorageMode.FULL.value if (b_path / "Data").is_dir() else StorageMode.BACKUPLESS.value
    )

    close_engine(backup_id=b_id, backup_path=b_path.as_posix(), sync=False, invalidate_cache=True)
    close_all_engines()
    engine = get_engine(backup_id=b_id, backup_path=b_path.as_posix())
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    report_metrics: Dict[str, Any] = {
        "backup_id": b_id,
        "backup_name": b_name,
        "categories_count": 0,
        "channels_count": 0,
        "threads_count": 0,
        "writers_count": 0,
        "writer_aliases_count": 0,
        "character_groups_count": 0,
        "characters_count": 0,
        "tuppers_count": 0,
        "scenes_count": 0,
        "sessions_count": 0,
        "events_count": 0,
        "scene_issues_count": 0,
        "flagged_messages_count": 0,
        "seen_discord_users_count": 0,
    }

    with db_session(backup_id=b_id, backup_path=b_path.as_posix()) as session:
        session.add(SchemaVersionModel(
            version=CURRENT_SCHEMA_VERSION,
            applied_at=datetime.now(timezone.utc),
            description=f"Seeded Schema v{CURRENT_SCHEMA_VERSION} test backup",
        ))

        created_at = parse_datetime(backup_info.get("updated_at") or backup_info.get("exported_at")) or datetime.now(timezone.utc)
        server_id = str((backup or {}).get("server_id") or backup_info.get("id") or "")
        server_name = str((backup or {}).get("server_name") or backup_info.get("name") or "")

        backup_model = BackupModel(
            backup_id=b_id,
            backup_name=b_name,
            server_id=server_id,
            server_name=server_name,
            path=str((backup or {}).get("path") or "") or None,
            created_at=created_at,
            last_synced_at=created_at,
            storage_mode=resolved_mode,
            sync_status=SyncStatus.IDLE.value,
        )
        session.add(backup_model)
        session.flush()

        channel_map = migrate_channels(session, b_id, backup_info.get("categories", []))
        name_to_id_map = build_category_name_to_id_map(channel_map.values())
        populate_config_models_from_dict(
            session,
            backup_model,
            raw_cfg,
            name_to_id_map=name_to_id_map,
        )
        if storage_mode is not None:
            backup_model.storage_mode = resolved_mode
        if backup is not None and backup.get("backup_name"):
            backup_model.backup_name = b_name
        report_metrics["categories_count"] = sum(1 for ch in channel_map.values() if ch.type == "GuildCategory")
        report_metrics["channels_count"] = sum(
            1 for ch in channel_map.values() if ch.type not in ("GuildCategory", "GuildPublicThread")
        )
        report_metrics["threads_count"] = sum(1 for ch in channel_map.values() if ch.type == "GuildPublicThread")
        non_cat_channels = [ch for ch in channel_map.values() if ch.type != "GuildCategory"]
        backup_model.channels_total = len(non_cat_channels)
        backup_model.channels_done = len(non_cat_channels)

        _, char_name_to_id, char_counts = _seed_writers_and_characters(session, b_id, character_list)
        report_metrics.update(char_counts)

        # Curated overrides & flagged messages
        now_utc = datetime.now(timezone.utc)
        flagged_authors_for_seen: List[Dict[str, Any]] = []

        if isinstance(fixed_messages, dict):
            for msg_id, data in fixed_messages.items():
                content_val = data.get("content", "")
                author_val = data.get("author", {})
                o_flags = compute_skeleton_flags({"type": "Default", "content": content_val, "author": author_val})
                session.add(FlaggedMessageModel(
                    backup_id=b_id,
                    message_id=str(msg_id),
                    channel_pk=None,
                    kind=FlaggedKind.FAILED_TUPPER.value,
                    content=content_val,
                    is_excerpt_truncated=False,
                    author=author_val,
                    flagged_at=now_utc,
                    resolution=FlaggedResolution.OVERRIDE.value,
                    override_content=content_val,
                    override_author=author_val,
                    override_flags=o_flags,
                    resolved_at=now_utc,
                    resolved_note="Seeded from fixed_messages.json",
                ))
                report_metrics["flagged_messages_count"] += 1

        for src_dict, fkind in (
            (bad_messages, FlaggedKind.FAILED_TUPPER.value),
            (bad_end_messages, FlaggedKind.OOC_BOUNDARY.value),
        ):
            if isinstance(src_dict, dict):
                for msg_id, data in src_dict.items():
                    link = data.get("link", "")
                    resolved_chan_pk = None
                    if link and "/channels/" in link:
                        parts = link.split("/")
                        if len(parts) >= 2 and parts[-2] in channel_map:
                            resolved_chan_pk = channel_map[parts[-2]].pk
                    author_val = data.get("author", {})
                    if isinstance(author_val, dict):
                        flagged_authors_for_seen.append(author_val)
                    session.add(FlaggedMessageModel(
                        backup_id=b_id,
                        message_id=str(msg_id),
                        channel_pk=resolved_chan_pk,
                        kind=fkind,
                        content=data.get("content", ""),
                        is_excerpt_truncated=False,
                        author=author_val,
                        flagged_at=now_utc,
                    ))
                    report_metrics["flagged_messages_count"] += 1

        seen_users_from_json: Dict[str, Dict[str, Any]] = {}
        if include_skeletons:
            _, seen_users_from_json = _populate_skeletons_and_collect_users(
                backup_id=b_id,
                backup_path=b_path.as_posix(),
                channels=list(channel_map.values()),
                char_name_to_id=char_name_to_id,
                rebuild_skeletons=True,
            )

        # Populate SeenDiscordUserModel
        seen_merged: Dict[str, Dict[str, Any]] = dict(seen_users_from_json)
        for author_dict in flagged_authors_for_seen:
            raw_aid = str(author_dict.get("id") or "").strip()
            if not raw_aid.isdigit() or int(raw_aid) < TUPPER_ID_MAX or bool(author_dict.get("isBot")):
                continue
            if raw_aid not in seen_merged:
                seen_merged[raw_aid] = {
                    "discord_user_id": raw_aid,
                    "username": str(author_dict.get("name") or f"User #{raw_aid}"),
                    "global_name": None,
                    "nickname": str(author_dict["nickname"]) if author_dict.get("nickname") else None,
                    "message_count": 1,
                    "last_seen_at": now_utc,
                }
        for aid_key, u_info in seen_merged.items():
            session.add(SeenDiscordUserModel(
                backup_id=b_id,
                discord_user_id=aid_key,
                username=u_info["username"],
                global_name=u_info.get("global_name"),
                nickname=u_info.get("nickname"),
                is_current_member=False,
                message_count=int(u_info.get("message_count") or 0),
                last_seen_at=u_info.get("last_seen_at"),
            ))
            report_metrics["seen_discord_users_count"] += 1

    t.invalidate_backups_index_cache()

    if include_scenes and (b_path / "Data").is_dir():
        from models.backup_context import BackupContext
        from index_scenes import index_scenes

        ctx = BackupContext.create(backup_id=b_id, backup_path=b_path.as_posix())
        with BackupContext.activate(context=ctx):
            index_scenes(backup_id=b_id, backup_path=b_path.as_posix())

        with db_session(backup_id=b_id, backup_path=b_path.as_posix()) as session:
            report_metrics["scenes_count"] = session.query(SceneModel).filter(
                SceneModel.backup_id == b_id,
                SceneModel.kind == SceneKind.SCENE.value,
            ).count()
            report_metrics["sessions_count"] = session.query(SceneModel).filter(
                SceneModel.backup_id == b_id,
                SceneModel.kind == SceneKind.SESSION.value,
            ).count()
            report_metrics["scene_issues_count"] = session.query(SceneIssueModel).filter(
                SceneIssueModel.backup_id == b_id,
            ).count()

    if not skip_snapshots:
        with db_session(backup_id=b_id, backup_path=b_path.as_posix()) as session:
            export_backup_info_snapshot(session, b_id)
            export_character_list_snapshot(session, b_id)

    if is_sqlite_tmp_cache_enabled():
        sync_dirty_sqlite_dbs(force=True)

    t.invalidate_backups_index_cache()
    return report_metrics

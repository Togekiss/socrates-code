"""
Test database seeding utilities for Socrates Schema v6 and legacy Schema v5 upgrade tests.
Directly seeds Schema v6 backup.sqlite + skeletons.sqlite + seen_discord_users + indexed scenes
from Backups/Elysium-sql-tests-clean (or target backup_path) fixtures.
"""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
for p in (_SRC_DIR.as_posix(), _PROJECT_ROOT.as_posix()):
    if p not in sys.path:
        sys.path.insert(0, p)

import tests.test_env  # noqa: E402, F401
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
    get_engine,
    get_sqlite_path,
    get_skeleton_sqlite_path,
    db_session,
    close_all_engines,
)
from db.upgrade import _populate_skeletons_and_collect_users, parse_datetime
from db.snapshots import export_backup_info_snapshot, export_character_list_snapshot
from deprecated.migrate import (
    cluster_writers,
    extract_group_names,
    migrate_channels,
)


def _resolve_info_file(backup_path: Path, filename: str) -> Optional[Path]:
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
) -> Dict[str, Any]:
    """
    Directly seeds a Schema v6 backup.sqlite + skeletons.sqlite + seen_discord_users + scenes
    for the target backup directory from Info/*.json and Data/*.json fixtures.
    """
    if backup is None:
        backup = next((b for b in t.get_backups_index() if str(b["backup_id"]) == str(backup_id)), None)
        if not backup and not backup_path:
            raise exc.BackupError(f"Backup ID '{backup_id}' not found in index")

    b_id = str(backup_id)
    b_name = str((backup or {}).get("backup_name") or f"Backup {b_id}")
    if backup_path is None:
        backup_path = (Path(c.DATA_ROOT) / backup["path"]).as_posix()
    b_path = Path(backup_path)

    info_file = _resolve_info_file(b_path, "backup_info.json")
    if not info_file:
        raise exc.MigrationError(f"Missing backup_info.json in {b_path / 'Info'}")

    backup_info = t.load_from_json(info_file.as_posix())
    char_file = _resolve_info_file(b_path, "character_list.json")
    character_list = t.load_from_json(char_file.as_posix()) if char_file else []

    fixed_file = _resolve_info_file(b_path, "fixed_messages.json")
    fixed_messages = t.load_from_json(fixed_file.as_posix()) if fixed_file else {}

    bad_file = _resolve_info_file(b_path, "bad_messages.json")
    bad_messages = t.load_from_json(bad_file.as_posix()) if bad_file else {}

    bad_end_file = _resolve_info_file(b_path, "bad_end_messages.json")
    bad_end_messages = t.load_from_json(bad_end_file.as_posix()) if bad_end_file else {}

    resolved_mode = storage_mode or (
        StorageMode.FULL.value if (b_path / "Data").is_dir() else StorageMode.BACKUPLESS.value
    )

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
            description="Seeded Schema v6 test backup",
        ))

        created_at = parse_datetime(backup_info.get("updated_at") or backup_info.get("exported_at")) or datetime.now(timezone.utc)
        server_id = str((backup or {}).get("server_id") or backup_info.get("id") or "")
        server_name = str((backup or {}).get("server_name") or backup_info.get("name") or "")

        backup_model = BackupModel(
            backup_id=b_id,
            backup_name=b_name,
            server_id=server_id,
            server_name=server_name,
            created_at=created_at,
            last_synced_at=created_at,
            storage_mode=resolved_mode,
            sync_status=SyncStatus.IDLE.value,
        )
        session.add(backup_model)
        session.flush()

        channel_map = migrate_channels(session, b_id, backup_info.get("categories", []))
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

    return report_metrics


def seed_v5_test_backup(
    backup_id: str = "1791895360",
    backup_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates a genuine Schema v5 SQLite database (with exports & backup_steps, without
    seen_discord_users / SceneModel.message_count / skeletons.sqlite) for upgrade.py tests.
    """
    b_id = str(backup_id)
    if backup_path is None:
        backup_path = t.get_backup_path(b_id)
    b_path = Path(backup_path)

    info_file = _resolve_info_file(b_path, "backup_info.json")
    if not info_file:
        raise exc.MigrationError(f"Missing backup_info.json in {b_path / 'Info'}")

    backup_info = t.load_from_json(info_file.as_posix())
    char_file = _resolve_info_file(b_path, "character_list.json")
    character_list = t.load_from_json(char_file.as_posix()) if char_file else []
    fixed_file = _resolve_info_file(b_path, "fixed_messages.json")
    fixed_messages = t.load_from_json(fixed_file.as_posix()) if fixed_file else {}
    bad_file = _resolve_info_file(b_path, "bad_messages.json")
    bad_messages = t.load_from_json(bad_file.as_posix()) if bad_file else {}

    # Seed v6 first in-memory / temp? No, write genuine v5 DDL directly via sqlite3!
    close_all_engines()
    sqlite_file = Path(get_sqlite_path(b_path.as_posix()))
    sqlite_file.parent.mkdir(parents=True, exist_ok=True)
    for p in (sqlite_file, Path(f"{sqlite_file}-wal"), Path(f"{sqlite_file}-shm")):
        if p.exists():
            p.unlink()
    skel_file = Path(get_skeleton_sqlite_path(b_path.as_posix()))
    for p in (skel_file, Path(f"{skel_file}-wal"), Path(f"{skel_file}-shm")):
        if p.exists():
            p.unlink()

    conn = sqlite3.connect(sqlite_file.as_posix())
    try:
        conn.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE backups (
                backup_id VARCHAR(64) PRIMARY KEY,
                backup_name VARCHAR(128) NOT NULL,
                server_id VARCHAR(20),
                server_name VARCHAR(128),
                created_at DATETIME
            );
            CREATE TABLE exports (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_id VARCHAR(64) NOT NULL REFERENCES backups(backup_id) ON DELETE CASCADE,
                scope VARCHAR(16) NOT NULL,
                exported_from DATETIME,
                exported_at DATETIME,
                updated_at DATETIME,
                UNIQUE(backup_id, scope)
            );
            CREATE TABLE backup_steps (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                export_pk INTEGER NOT NULL REFERENCES exports(pk) ON DELETE CASCADE,
                step VARCHAR(32) NOT NULL,
                status VARCHAR(16) NOT NULL,
                started_at DATETIME,
                finished_at DATETIME,
                error TEXT,
                UNIQUE(export_pk, step)
            );
            CREATE TABLE channels (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                export_pk INTEGER NOT NULL REFERENCES exports(pk) ON DELETE CASCADE,
                discord_id VARCHAR(20) NOT NULL,
                type VARCHAR(32) NOT NULL,
                parent_pk INTEGER REFERENCES channels(pk) ON DELETE CASCADE,
                name VARCHAR(64) NOT NULL,
                position INTEGER NOT NULL,
                path VARCHAR(255) NOT NULL,
                is_deleted BOOLEAN NOT NULL DEFAULT 0,
                message_count INTEGER,
                UNIQUE(export_pk, discord_id)
            );
            CREATE TABLE writers (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_id VARCHAR(64) NOT NULL REFERENCES backups(backup_id) ON DELETE CASCADE,
                display_name VARCHAR(64) NOT NULL,
                discord_user_id VARCHAR(20),
                UNIQUE(backup_id, discord_user_id)
            );
            CREATE TABLE writer_aliases (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                writer_pk INTEGER NOT NULL REFERENCES writers(pk) ON DELETE CASCADE,
                alias VARCHAR(64) NOT NULL
            );
            CREATE TABLE character_groups (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_id VARCHAR(64) NOT NULL REFERENCES backups(backup_id) ON DELETE CASCADE
            );
            CREATE TABLE group_names (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                group_pk INTEGER NOT NULL REFERENCES character_groups(pk) ON DELETE CASCADE,
                name VARCHAR(64) NOT NULL,
                position INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE characters (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_id VARCHAR(64) NOT NULL REFERENCES backups(backup_id) ON DELETE CASCADE,
                char_id INTEGER NOT NULL,
                writer_pk INTEGER REFERENCES writers(pk) ON DELETE SET NULL,
                group_pk INTEGER REFERENCES character_groups(pk) ON DELETE SET NULL,
                parent_pk INTEGER REFERENCES characters(pk) ON DELETE CASCADE,
                version_type VARCHAR(32),
                origin VARCHAR(32),
                activity VARCHAR(32),
                UNIQUE(backup_id, char_id)
            );
            CREATE TABLE character_names (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                character_pk INTEGER NOT NULL REFERENCES characters(pk) ON DELETE CASCADE,
                name VARCHAR(64) NOT NULL,
                position INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE events (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_id VARCHAR(64) NOT NULL REFERENCES backups(backup_id) ON DELETE CASCADE,
                event_key VARCHAR(32) NOT NULL,
                name VARCHAR(128),
                status VARCHAR(32) NOT NULL DEFAULT 'open',
                start_at DATETIME NOT NULL,
                end_at DATETIME NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                is_curated BOOLEAN NOT NULL DEFAULT 0,
                character_movements JSON,
                UNIQUE(backup_id, event_key)
            );
            CREATE TABLE scenes (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_id VARCHAR(64) NOT NULL REFERENCES backups(backup_id) ON DELETE CASCADE,
                scene_key VARCHAR(32) NOT NULL,
                channel_pk INTEGER NOT NULL REFERENCES channels(pk) ON DELETE CASCADE,
                category_pk INTEGER NOT NULL REFERENCES channels(pk) ON DELETE CASCADE,
                event_pk INTEGER REFERENCES events(pk) ON DELETE SET NULL,
                custom_name VARCHAR(128),
                kind VARCHAR(16) NOT NULL DEFAULT 'scene',
                status VARCHAR(32) NOT NULL,
                start_message_id VARCHAR(20) NOT NULL,
                end_message_id VARCHAR(20) NOT NULL,
                start_index INTEGER NOT NULL,
                end_index INTEGER NOT NULL,
                start_at DATETIME NOT NULL,
                end_at DATETIME NOT NULL,
                start_author_id VARCHAR(20) NOT NULL,
                end_author_id VARCHAR(20) NOT NULL,
                start_excerpt VARCHAR(250),
                end_excerpt VARCHAR(250),
                UNIQUE(backup_id, scene_key)
            );
            CREATE TABLE scene_participants (
                scene_pk INTEGER NOT NULL REFERENCES scenes(pk) ON DELETE CASCADE,
                character_pk INTEGER NOT NULL REFERENCES characters(pk) ON DELETE CASCADE,
                position INTEGER NOT NULL DEFAULT 0,
                first_message_id VARCHAR(20),
                first_at DATETIME,
                last_message_id VARCHAR(20),
                last_at DATETIME,
                PRIMARY KEY (scene_pk, character_pk)
            );
            CREATE TABLE scene_issues (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_id VARCHAR(64) NOT NULL REFERENCES backups(backup_id) ON DELETE CASCADE,
                scene_pk INTEGER REFERENCES scenes(pk) ON DELETE SET NULL,
                next_scene_pk INTEGER REFERENCES scenes(pk) ON DELETE SET NULL,
                kind VARCHAR(32) NOT NULL,
                reason VARCHAR(32) NOT NULL,
                candidate_message_id VARCHAR(20),
                candidate_index INTEGER,
                candidate_excerpt VARCHAR(250),
                previous_chars JSON,
                next_chars JSON,
                created_at DATETIME NOT NULL,
                resolved_at DATETIME,
                resolved_note TEXT,
                resolution VARCHAR(32)
            );
            CREATE TABLE flagged_messages (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_id VARCHAR(64) NOT NULL REFERENCES backups(backup_id) ON DELETE CASCADE,
                message_id VARCHAR(20) NOT NULL,
                channel_pk INTEGER REFERENCES channels(pk) ON DELETE SET NULL,
                kind VARCHAR(32) NOT NULL,
                content TEXT NOT NULL,
                author JSON NOT NULL,
                flagged_at DATETIME NOT NULL,
                resolution VARCHAR(32),
                override_content TEXT,
                override_author JSON,
                resolved_at DATETIME,
                resolved_note TEXT,
                UNIQUE(backup_id, message_id)
            );
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY,
                applied_at DATETIME NOT NULL,
                description VARCHAR(255)
            );
            """
        )

        import json
        now_iso = datetime.now(timezone.utc).isoformat()
        updated_iso = str(backup_info.get("updated_at") or now_iso)
        exported_iso = str(backup_info.get("exported_at") or now_iso)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
            (5, now_iso, "Seeded Schema v5 fixture"),
        )
        conn.execute(
            "INSERT INTO backups (backup_id, backup_name, server_id, server_name, created_at) VALUES (?, ?, ?, ?, ?)",
            (b_id, "Elysium-sql-tests", str(backup_info.get("id") or "857848490683269161"), str(backup_info.get("name") or "Elysium-sql-tests"), updated_iso),
        )
        cur = conn.execute(
            "INSERT INTO exports (backup_id, scope, exported_from, exported_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (b_id, "base", None, exported_iso, updated_iso),
        )
        base_exp_pk = cur.lastrowid
        cur_upd = conn.execute(
            "INSERT INTO exports (backup_id, scope, exported_from, exported_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (b_id, "update", None, exported_iso, updated_iso),
        )
        upd_exp_pk = cur_upd.lastrowid

        for step_name, step_status in (backup_info.get("steps") or {}).items():
            conn.execute(
                "INSERT INTO backup_steps (export_pk, step, status) VALUES (?, ?, ?)",
                (base_exp_pk, str(step_name), str(step_status)),
            )

        chan_pk_by_discord: Dict[str, int] = {}
        cat_pk_by_discord: Dict[str, int] = {}
        for exp_pk_target in (base_exp_pk, upd_exp_pk):
            for cat in backup_info.get("categories", []):
                c_cur = conn.execute(
                    "INSERT INTO channels (export_pk, discord_id, type, parent_pk, name, position, path, is_deleted) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (exp_pk_target, str(cat["id"]), "GuildCategory", None, str(cat["name"]), int(cat["position"]), str(cat["path"]), 0),
                )
                cat_pk = c_cur.lastrowid
                if exp_pk_target == base_exp_pk:
                    cat_pk_by_discord[str(cat["id"])] = cat_pk
                    chan_pk_by_discord[str(cat["id"])] = cat_pk
                for ch in cat.get("channels", []):
                    ch_cur = conn.execute(
                        "INSERT INTO channels (export_pk, discord_id, type, parent_pk, name, position, path, is_deleted, message_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (exp_pk_target, str(ch["id"]), "GuildTextChat", cat_pk, str(ch["name"]), int(ch["position"]), str(ch["path"]), 0, ch.get("number_of_messages")),
                    )
                    ch_pk = ch_cur.lastrowid
                    if exp_pk_target == base_exp_pk:
                        chan_pk_by_discord[str(ch["id"])] = ch_pk
                    for th in ch.get("threads", []):
                        th_cur = conn.execute(
                            "INSERT INTO channels (export_pk, discord_id, type, parent_pk, name, position, path, is_deleted, message_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (exp_pk_target, str(th["id"]), "GuildPublicThread", ch_pk, str(th["name"]), int(th["position"]), str(th["path"]), 0, th.get("number_of_messages")),
                        )
                        if exp_pk_target == base_exp_pk:
                            chan_pk_by_discord[str(th["id"])] = th_cur.lastrowid

        # Writers & characters
        writer_clusters = cluster_writers(character_list)
        alias_to_writer_pk: Dict[str, int] = {}
        for w_data in writer_clusters.values():
            w_cur = conn.execute(
                "INSERT INTO writers (backup_id, display_name, discord_user_id) VALUES (?, ?, ?)",
                (b_id, w_data["display_name"], w_data["discord_user_id"]),
            )
            w_pk = w_cur.lastrowid
            for a_str in w_data["aliases"]:
                conn.execute("INSERT INTO writer_aliases (writer_pk, alias) VALUES (?, ?)", (w_pk, a_str))
                alias_to_writer_pk[a_str.lower()] = w_pk

        def _w_pk(raw_w: Any) -> Optional[int]:
            if isinstance(raw_w, str):
                raw_w = [raw_w]
            for w in (raw_w or []):
                if w and w.strip().lower() in alias_to_writer_pk:
                    return alias_to_writer_pk[w.strip().lower()]
            return None

        char_id_to_pk: Dict[int, int] = {}
        for item in character_list:
            cid = int(item["id"])
            tags = item.get("tags", [])
            w_pk = _w_pk(item.get("writer"))
            c_cur = conn.execute(
                "INSERT INTO characters (backup_id, char_id, writer_pk, group_pk, parent_pk, origin, activity) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (b_id, cid, w_pk, None, None, "canon" if "canon" in tags else "oc", "active" if "active" in tags else "inactive"),
            )
            c_pk = c_cur.lastrowid
            char_id_to_pk[cid] = c_pk
            for pos, nm in enumerate(item.get("names", [])):
                conn.execute("INSERT INTO character_names (character_pk, name, position) VALUES (?, ?, ?)", (c_pk, nm, pos))

        # Seed sample scenes from barside.json so v5->v6 upgrade tests scene + participant + resolved issue preservation
        barside_path = b_path / "Data" / "14# The Twisted Viper Bar" / "1# barside.json"
        if barside_path.is_file():
            barside_data = t.load_from_json(barside_path.as_posix())
            msgs = barside_data.get("messages", [])
            if len(msgs) >= 10:
                barside_pk = chan_pk_by_discord.get("1013915163423932496")
                bar_cat_pk = cat_pk_by_discord.get("1019770957172326470") or barside_pk
                sc_cur = conn.execute(
                    """
                    INSERT INTO scenes (
                        backup_id, scene_key, channel_pk, category_pk, kind, status,
                        start_message_id, end_message_id, start_index, end_index,
                        start_at, end_at, start_author_id, end_author_id, start_excerpt, end_excerpt
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        b_id, "14-1-1", barside_pk, bar_cat_pk, "scene", "closed",
                        str(msgs[0]["id"]), str(msgs[9]["id"]), 0, 9,
                        str(msgs[0]["timestamp"]), str(msgs[9]["timestamp"]),
                        str((msgs[0].get("author") or {}).get("id", "1")),
                        str((msgs[9].get("author") or {}).get("id", "1")),
                        str(msgs[0].get("content", ""))[:250],
                        str(msgs[9].get("content", ""))[:250],
                    ),
                )
                sc_pk = sc_cur.lastrowid
                first_char_pk = next(iter(char_id_to_pk.values()), None)
                if first_char_pk:
                    conn.execute(
                        "INSERT INTO scene_participants (scene_pk, character_pk, position, first_message_id, last_message_id) VALUES (?, ?, ?, ?, ?)",
                        (sc_pk, first_char_pk, 0, str(msgs[0]["id"]), str(msgs[9]["id"])),
                    )
                conn.execute(
                    "INSERT INTO scene_issues (backup_id, scene_pk, kind, reason, candidate_message_id, candidate_index, candidate_excerpt, created_at, resolved_at, resolved_note, resolution) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (b_id, sc_pk, "soft_boundary", "roster_change", str(msgs[4]["id"]), 4, str(msgs[4].get("content", ""))[:250], now_iso, now_iso, "v5 resolved issue", "merged"),
                )

        # Seed overrides & flagged messages
        if isinstance(fixed_messages, dict):
            for mid, fdata in list(fixed_messages.items())[:2]:
                conn.execute(
                    """
                    INSERT INTO flagged_messages (
                        backup_id, message_id, kind, content, author, flagged_at,
                        resolution, override_content, override_author, resolved_at, resolved_note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        b_id, str(mid), "failed_tupper", fdata.get("content", ""),
                        json.dumps(fdata.get("author", {})), now_iso,
                        "override", fdata.get("content", ""), json.dumps(fdata.get("author", {})),
                        now_iso, "v5 override",
                    ),
                )
        if isinstance(bad_messages, dict):
            for mid, bdata in list(bad_messages.items())[:2]:
                conn.execute(
                    "INSERT INTO flagged_messages (backup_id, message_id, kind, content, author, flagged_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (b_id, str(mid), "failed_tupper", bdata.get("content", ""), json.dumps(bdata.get("author", {})), now_iso),
                )

        conn.commit()
    finally:
        conn.close()

    return {"backup_id": b_id, "schema_version": 5, "sqlite_path": sqlite_file.as_posix()}

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
from db.test_backup_service import resolve_info_file as _resolve_info_file, seed_test_backup  # noqa: E402, F401
from utils import exceptions as exc  # noqa: E402
from utils import tricks as t  # noqa: E402
from db.session import (  # noqa: E402
    get_sqlite_path,
    get_skeleton_sqlite_path,
    close_all_engines,
)
from deprecated.migrate import cluster_writers  # noqa: E402


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

    t.invalidate_backups_index_cache()
    return {"backup_id": b_id, "schema_version": 5, "sqlite_path": sqlite_file.as_posix()}

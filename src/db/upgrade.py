"""
Database schema upgrade utility for Socrates SQLite databases.
Rebuilds the schema cleanly using Base.metadata and preserves curated data.
This is a development-iteration tool intended exclusively for SQLite databases.

# TODO: replace with Alembic migrations before release
"""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

# Ensure project root is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.as_posix()
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_SRC_DIR = (Path(_PROJECT_ROOT) / "src").as_posix()
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from sqlalchemy import create_engine, MetaData, Table, select, inspect
from sqlalchemy.orm import Session

from res import constants as c
from utils import exceptions as exc
from utils import tricks as t

from db.models import (
    Base,
    BackupModel,
    ExportModel,
    BackupStepModel,
    ChannelModel,
    WriterModel,
    WriterAliasModel,
    CharacterGroupModel,
    GroupNameModel,
    CharacterModel,
    CharacterNameModel,
    SceneModel,
    SceneParticipantModel,
    SceneIssueModel,
    FlaggedKind,
    FlaggedResolution,
    FlaggedMessageModel,
    SchemaVersionModel,
    CURRENT_SCHEMA_VERSION,
)
from db.session import get_engine, close_all_engines, get_sqlite_path, has_sqlite_db, get_db_schema_version, stamp_schema_version
from db.snapshots import export_backup_info_snapshot, export_character_list_snapshot


def parse_datetime(val: Any) -> Optional[datetime]:
    """Parses a datetime object or ISO-8601 string to a UTC datetime object."""
    if not val:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    if isinstance(val, str) and val.strip():
        try:
            dt = datetime.fromisoformat(val)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None
    return None


def extract_database_data(engine) -> Dict[str, List[Dict[str, Any]]]:
    """
    Introspects and extracts table rows from the database using SQLAlchemy Table reflection.
    Returns a dictionary of table_name -> list of row dictionaries.
    Missing tables return empty lists.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    meta = MetaData()

    data: Dict[str, List[Dict[str, Any]]] = {}
    target_tables = [
        "backups",
        "exports",
        "backup_steps",
        "channels",
        "writers",
        "writer_aliases",
        "character_groups",
        "group_names",
        "characters",
        "character_names",
        "scenes",
        "scene_participants",
        "scene_issues",
        "message_overrides",
        "flagged_messages",
    ]

    for t_name in target_tables:
        if t_name not in existing_tables:
            data[t_name] = []
            continue
        try:
            tbl = Table(t_name, meta, autoload_with=engine)
            with engine.connect() as conn:
                rows = conn.execute(select(tbl)).mappings().all()
                data[t_name] = [dict(r) for r in rows]
        except Exception as e:
            raise exc.DatabaseUpgradeError(f"Failed extracting table '{t_name}': {e}") from e

    return data


def populate_schema(
    target_engine,
    data: Dict[str, List[Dict[str, Any]]],
    backup_id: str,
    old_version: int,
    target_schema_version: int = CURRENT_SCHEMA_VERSION,
) -> Dict[str, int]:
    """
    Populates a fresh schema from extracted data, resolving all foreign key relationships.
    Returns metrics dictionary of entity counts.
    """
    metrics: Dict[str, int] = {
        "backups": 0,
        "exports": 0,
        "backup_steps": 0,
        "channels": 0,
        "writers": 0,
        "writer_aliases": 0,
        "character_groups": 0,
        "group_names": 0,
        "characters": 0,
        "character_names": 0,
        "scenes": 0,
        "scene_participants": 0,
        "scene_issues": 0,
        "message_overrides": 0,
        "flagged_messages": 0,
    }

    with Session(target_engine) as session:
        # 0. Schema Version
        stamp_schema_version(session, target_schema_version, description="Upgraded schema via export-and-reimport")

        # 1. Backups
        for b in data.get("backups", []):
            session.add(BackupModel(
                backup_id=str(b["backup_id"]),
                backup_name=str(b["backup_name"]),
                server_id=str(b.get("server_id")) if b.get("server_id") else None,
                server_name=str(b.get("server_name")) if b.get("server_name") else None,
                created_at=parse_datetime(b.get("created_at")),
            ))
            metrics["backups"] += 1
        session.flush()

        # 2. Exports
        export_pk_map: Dict[int, int] = {}
        for e in data.get("exports", []):
            old_pk = e["pk"]
            exp = ExportModel(
                backup_id=str(e["backup_id"]),
                scope=str(e["scope"]),
                exported_from=parse_datetime(e.get("exported_from")),
                exported_at=parse_datetime(e.get("exported_at")),
                updated_at=parse_datetime(e.get("updated_at")),
            )
            session.add(exp)
            session.flush()
            export_pk_map[old_pk] = exp.pk
            metrics["exports"] += 1

        # 3. Steps
        for s in data.get("backup_steps", []):
            new_exp_pk = export_pk_map.get(s["export_pk"])
            if not new_exp_pk:
                continue
            session.add(BackupStepModel(
                export_pk=new_exp_pk,
                step=str(s["step"]),
                status=str(s["status"]),
                started_at=parse_datetime(s.get("started_at")),
                finished_at=parse_datetime(s.get("finished_at")),
                error=s.get("error"),
            ))
            metrics["backup_steps"] += 1
        session.flush()

        # 4. Channels (ordered: categories first, then channels, then threads)
        chan_pk_map: Dict[int, int] = {}
        all_chans = data.get("channels", [])
        categories = [c for c in all_chans if c.get("parent_pk") is None or c.get("type") == "GuildCategory"]
        other_chans = [c for c in all_chans if c not in categories]
        text_chans = [c for c in other_chans if c.get("type") != "GuildPublicThread"]
        threads = [c for c in other_chans if c.get("type") == "GuildPublicThread"]

        for c_group in (categories, text_chans, threads):
            for c in c_group:
                old_pk = c["pk"]
                new_exp_pk = export_pk_map.get(c["export_pk"])
                if not new_exp_pk:
                    continue
                parent_pk = chan_pk_map.get(c.get("parent_pk")) if c.get("parent_pk") is not None else None
                chan = ChannelModel(
                    export_pk=new_exp_pk,
                    discord_id=str(c["discord_id"]),
                    type=str(c["type"]),
                    parent_pk=parent_pk,
                    name=str(c.get("name", "")),
                    position=int(c.get("position", 0)),
                    path=str(c.get("path", "")),
                    is_deleted=bool(c.get("is_deleted", False)),
                    message_count=c.get("message_count"),
                )
                session.add(chan)
                session.flush()
                chan_pk_map[old_pk] = chan.pk
                metrics["channels"] += 1

        # 5. Writers & Aliases
        writer_pk_map: Dict[int, int] = {}
        for w in data.get("writers", []):
            old_pk = w["pk"]
            writer = WriterModel(
                backup_id=str(w["backup_id"]),
                display_name=str(w["display_name"]),
                discord_user_id=str(w["discord_user_id"]) if w.get("discord_user_id") else None,
            )
            session.add(writer)
            session.flush()
            writer_pk_map[old_pk] = writer.pk
            metrics["writers"] += 1

        for a in data.get("writer_aliases", []):
            new_w_pk = writer_pk_map.get(a["writer_pk"])
            if not new_w_pk:
                continue
            session.add(WriterAliasModel(
                writer_pk=new_w_pk,
                alias=str(a["alias"]),
            ))
            metrics["writer_aliases"] += 1
        session.flush()

        # 6. Character Groups & Names
        group_pk_map: Dict[int, int] = {}
        for g in data.get("character_groups", []):
            old_pk = g["pk"]
            group = CharacterGroupModel(backup_id=str(g["backup_id"]))
            session.add(group)
            session.flush()
            group_pk_map[old_pk] = group.pk
            metrics["character_groups"] += 1

        for gn in data.get("group_names", []):
            new_g_pk = group_pk_map.get(gn["group_pk"])
            if not new_g_pk:
                continue
            session.add(GroupNameModel(
                group_pk=new_g_pk,
                name=str(gn["name"]),
                position=int(gn.get("position", 0)),
            ))
            metrics["group_names"] += 1
        session.flush()

        # 7. Characters (ordered: top-level first, then children)
        char_pk_map: Dict[int, int] = {}
        top_chars = [c for c in data.get("characters", []) if c.get("parent_pk") is None]
        child_chars = [c for c in data.get("characters", []) if c.get("parent_pk") is not None]

        for c in top_chars:
            old_pk = c["pk"]
            char = CharacterModel(
                backup_id=str(c["backup_id"]),
                char_id=int(c["char_id"]),
                writer_pk=writer_pk_map.get(c.get("writer_pk")),
                group_pk=group_pk_map.get(c.get("group_pk")),
                parent_pk=None,
                version_type=c.get("version_type"),
                origin=c.get("origin"),
                activity=c.get("activity"),
            )
            session.add(char)
            session.flush()
            char_pk_map[old_pk] = char.pk
            metrics["characters"] += 1

        for c in child_chars:
            old_pk = c["pk"]
            char = CharacterModel(
                backup_id=str(c["backup_id"]),
                char_id=int(c["char_id"]),
                writer_pk=writer_pk_map.get(c.get("writer_pk")),
                group_pk=group_pk_map.get(c.get("group_pk")),
                parent_pk=char_pk_map.get(c.get("parent_pk")),
                version_type=c.get("version_type"),
                origin=c.get("origin"),
                activity=c.get("activity"),
            )
            session.add(char)
            session.flush()
            char_pk_map[old_pk] = char.pk
            metrics["characters"] += 1

        for cn in data.get("character_names", []):
            new_c_pk = char_pk_map.get(cn["character_pk"])
            if not new_c_pk:
                continue
            session.add(CharacterNameModel(
                character_pk=new_c_pk,
                name=str(cn["name"]),
                position=int(cn.get("position", 0)),
            ))
            metrics["character_names"] += 1
        session.flush()

        # 8. Scenes
        scene_pk_map: Dict[int, int] = {}
        for s in data.get("scenes", []):
            old_pk = s["pk"]
            new_chan_pk = chan_pk_map.get(s["channel_pk"])
            new_cat_pk = chan_pk_map.get(s["category_pk"])
            if not new_chan_pk or not new_cat_pk:
                continue
            scene = SceneModel(
                backup_id=str(s["backup_id"]),
                scene_key=str(s["scene_key"]),
                channel_pk=new_chan_pk,
                category_pk=new_cat_pk,
                status=str(s["status"]),
                start_message_id=str(s["start_message_id"]),
                end_message_id=str(s["end_message_id"]),
                start_index=int(s["start_index"]),
                end_index=int(s["end_index"]),
                start_at=parse_datetime(s["start_at"]),
                end_at=parse_datetime(s["end_at"]),
                start_author_id=str(s["start_author_id"]),
                end_author_id=str(s["end_author_id"]),
                start_excerpt=str(s.get("start_excerpt") or "")[:250],
                end_excerpt=str(s.get("end_excerpt") or "")[:250],
            )
            session.add(scene)
            session.flush()
            scene_pk_map[old_pk] = scene.pk
            metrics["scenes"] += 1

        # 9. Scene Participants
        seen_parts: Set[Tuple[int, int]] = set()
        for p in data.get("scene_participants", []):
            new_s_pk = scene_pk_map.get(p["scene_pk"])
            new_c_pk = char_pk_map.get(p["character_pk"])
            if new_s_pk and new_c_pk and (new_s_pk, new_c_pk) not in seen_parts:
                seen_parts.add((new_s_pk, new_c_pk))
                session.add(SceneParticipantModel(
                    scene_pk=new_s_pk,
                    character_pk=new_c_pk,
                ))
                metrics["scene_participants"] += 1
        session.flush()

        # 10. Scene Issues
        for iss in data.get("scene_issues", []):
            new_s_pk = scene_pk_map.get(iss.get("scene_pk")) if iss.get("scene_pk") is not None else None
            new_next_s_pk = scene_pk_map.get(iss.get("next_scene_pk")) if iss.get("next_scene_pk") is not None else None
            raw_kind = str(iss["kind"])
            # SCHEMA_VERSION = 2
            # "possible_split" -> "soft_boundary"
            migrated_kind = "soft_boundary" if raw_kind == "possible_split" else raw_kind
            raw_res = iss.get("resolution")
            # SCHEMA_VERSION = 3
            # "accepted" -> "split" if migrated_kind == "auto_split" else "merged"
            if raw_res == "accepted":
                migrated_res = "split" if migrated_kind == "auto_split" else "merged"
            else:
                migrated_res = raw_res
            session.add(SceneIssueModel(
                backup_id=str(iss["backup_id"]),
                scene_pk=new_s_pk,
                next_scene_pk=new_next_s_pk,
                kind=migrated_kind,
                reason=str(iss.get("reason") or ""),
                candidate_message_id=str(iss["candidate_message_id"]) if iss.get("candidate_message_id") else None,
                candidate_index=iss.get("candidate_index"),
                candidate_excerpt=iss.get("candidate_excerpt"),
                previous_chars=iss.get("previous_chars"),
                next_chars=iss.get("next_chars"),
                created_at=parse_datetime(iss["created_at"]) or datetime.now(timezone.utc),
                resolved_at=parse_datetime(iss.get("resolved_at")),
                resolved_note=iss.get("resolved_note"),
                resolution=migrated_res,
            ))
            metrics["scene_issues"] += 1

        # 11. Overrides & Flagged Messages (Unified into FlaggedMessageModel)
        # SCHEMA_VERSION = 3
        # Remove message_overrides table, now it's integrated in flagged_messages
        overrides_by_mid = {str(o["message_id"]): o for o in data.get("message_overrides", [])}
        processed_mids = set()

        for f in data.get("flagged_messages", []):
            mid = str(f["message_id"])
            if mid in processed_mids:
                continue
            new_chan_pk = chan_pk_map.get(f.get("channel_pk")) if f.get("channel_pk") is not None else None
            raw_kind = str(f.get("kind", ""))
            if raw_kind == "non_tupper_end_tag":
                migrated_kind = FlaggedKind.OOC_BOUNDARY.value
            elif raw_kind == "non_tupper":
                migrated_kind = FlaggedKind.FAILED_TUPPER.value
            elif raw_kind in (e.value for e in FlaggedKind):
                migrated_kind = raw_kind
            else:
                migrated_kind = FlaggedKind.OOC_MESSAGE.value

            if mid in overrides_by_mid:
                o = overrides_by_mid[mid]
                o_chan_pk = chan_pk_map.get(o.get("channel_pk")) if o.get("channel_pk") is not None else new_chan_pk
                session.add(FlaggedMessageModel(
                    backup_id=str(f["backup_id"]),
                    message_id=mid,
                    channel_pk=o_chan_pk,
                    kind=migrated_kind,
                    content=str(f["content"]),
                    author=f.get("author", {}),
                    flagged_at=parse_datetime(f.get("flagged_at")) or datetime.now(timezone.utc),
                    resolution=FlaggedResolution.OVERRIDE.value,
                    override_content=str(o["content"]),
                    override_author=o.get("author", {}),
                    resolved_at=parse_datetime(o.get("created_at")) or datetime.now(timezone.utc),
                    resolved_note="Migrated from message_overrides",
                ))
            else:
                session.add(FlaggedMessageModel(
                    backup_id=str(f["backup_id"]),
                    message_id=mid,
                    channel_pk=new_chan_pk,
                    kind=migrated_kind,
                    content=str(f["content"]),
                    author=f.get("author", {}),
                    flagged_at=parse_datetime(f.get("flagged_at")) or datetime.now(timezone.utc),
                    resolution=f.get("resolution"),
                    override_content=f.get("override_content"),
                    override_author=f.get("override_author"),
                    resolved_at=parse_datetime(f.get("resolved_at")),
                    resolved_note=f.get("resolved_note"),
                ))
            processed_mids.add(mid)
            metrics["flagged_messages"] += 1

        for mid, o in overrides_by_mid.items():
            if mid in processed_mids:
                continue
            new_chan_pk = chan_pk_map.get(o.get("channel_pk")) if o.get("channel_pk") is not None else None
            session.add(FlaggedMessageModel(
                backup_id=str(o["backup_id"]),
                message_id=mid,
                channel_pk=new_chan_pk,
                kind=FlaggedKind.FAILED_TUPPER.value,
                content=str(o["content"]),
                author=o.get("author", {}),
                flagged_at=parse_datetime(o.get("created_at")) or datetime.now(timezone.utc),
                resolution=FlaggedResolution.OVERRIDE.value,
                override_content=str(o["content"]),
                override_author=o.get("author", {}),
                resolved_at=parse_datetime(o.get("created_at")) or datetime.now(timezone.utc),
                resolved_note="Migrated from message_overrides",
            ))
            processed_mids.add(mid)
            metrics["flagged_messages"] += 1

        session.commit()

    return metrics


def upgrade_single_backup(
    backup: dict,
    dry_run: bool = False,
    reindex_scenes: bool = False,
) -> Dict[str, Any]:
    """
    Upgrades a single backup database to CURRENT_SCHEMA_VERSION.
    Preserves all curated writers, characters, groups, overrides, and scene decisions.
    """
    backup_id = str(backup["backup_id"])
    backup_name = str(backup["backup_name"])
    backup_path = (Path(c.DATA_ROOT) / backup["path"]).as_posix()
    sqlite_path = get_sqlite_path(backup_path)

    t.log("info", f"\n=======================================================")
    t.log("info", f"Upgrading database for backup '{backup_name}' (ID: {backup_id})")
    t.log("info", f"Path: {sqlite_path}")
    t.log("info", f"Dry Run: {dry_run}")
    t.log("info", f"=======================================================\n")

    if not os.path.exists(sqlite_path):
        raise exc.DatabaseConnectionError(f"Database not found at '{sqlite_path}'. Run migration first.")

    # 1. Inspect source database and version
    source_engine = get_engine(backup_id=backup_id, backup_path=backup_path)
    if source_engine.dialect.name != "sqlite":
        raise exc.DatabaseUpgradeError("Schema upgrades are only supported for SQLite databases.")
    old_version = get_db_schema_version(source_engine)
    t.log("base", f"Current database schema version: {old_version} (Target: {CURRENT_SCHEMA_VERSION})")

    # 2. Extract data via SQLAlchemy Table reflection
    t.log("info", "Extracting existing data via SQLAlchemy reflection...")
    extracted_data = extract_database_data(source_engine)

    total_extracted = sum(len(rows) for rows in extracted_data.values())
    t.log(
        "info",
        f"Extracted {total_extracted} total rows across {len(extracted_data)} tables: "
        f"{len(extracted_data.get('characters', []))} characters, "
        f"{len(extracted_data.get('writers', []))} writers, "
        f"{len(extracted_data.get('scenes', []))} scenes."
    )

    if dry_run:
        # In-memory target validation
        t.log("info", "[DRY-RUN] Simulating schema upgrade in-memory...")
        mem_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=mem_engine)

        metrics = populate_schema(mem_engine, extracted_data, backup_id, old_version)
        new_version = get_db_schema_version(mem_engine)
        mem_engine.dispose()

        t.log("base", f"[DRY-RUN] Schema upgrade simulation successful! All {sum(metrics.values())} rows validated.")
        return {
            "backup_id": backup_id,
            "backup_name": backup_name,
            "old_version": old_version,
            "new_version": new_version,
            "dry_run": True,
            "metrics": metrics,
        }

    # 3. Create safety backup copy of the SQLite database
    bak_path = f"{sqlite_path}.bak"
    t.log("info", f"Creating safety database backup at: {bak_path}")
    try:
        with source_engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
    close_all_engines()
    shutil.copy2(sqlite_path, bak_path)

    try:
        # 4. Rebuild schema cleanly using Base.metadata
        t.log("info", "Rebuilding database schema...")
        engine = get_engine(backup_id=backup_id, backup_path=backup_path)
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys = OFF")
            existing_tables = [r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
            for t_name in existing_tables:
                conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{t_name}"')
            conn.exec_driver_sql("PRAGMA foreign_keys = ON")
            conn.commit()
        Base.metadata.create_all(bind=engine)

        # 5. Populate new schema with preserved data
        t.log("info", "Repopulating tables with preserved data...")
        metrics = populate_schema(engine, extracted_data, backup_id, old_version)
        new_version = get_db_schema_version(engine)
        t.log("base", f"Successfully upgraded schema to version {new_version}!")

        # 6. Optional Reindex
        if reindex_scenes:
            t.log("info", "Re-indexing scenes as requested...")
            try:
                from index_scenes import index_scenes
                index_scenes(backup_id=backup_id, backup_path=backup_path)
            except Exception:
                t.log("error", f"Scene re-indexing failed: {exc.unwrap(e)}")
                raise

        # 7. Post-upgrade Snapshots
        try:
            with Session(engine) as s:
                export_character_list_snapshot(s, backup_id)
                export_backup_info_snapshot(s, backup_id)
        except Exception as e:
            t.log("debug", f"Post-upgrade snapshot note: {e}")

        t.log(
            "base",
            f"Upgrade complete for '{backup_name}': {metrics['characters']} characters, "
            f"{metrics['writers']} writers, {metrics['scenes']} scenes preserved."
        )

        return {
            "backup_id": backup_id,
            "backup_name": backup_name,
            "old_version": old_version,
            "new_version": new_version,
            "dry_run": False,
            "metrics": metrics,
        }

    except Exception as e:
        t.log("error", f"Upgrade failed for '{backup_name}': {exc.unwrap(e)}")
        # Restore from safety copy
        close_all_engines()
        for p in (f"{sqlite_path}-wal", f"{sqlite_path}-shm"):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        if os.path.exists(bak_path):
            t.log("info", f"Restoring safety backup from {bak_path}...")
            shutil.copy2(bak_path, sqlite_path)
        raise exc.DatabaseUpgradeError(f"Upgrade failed and was rolled back from backup: {e}") from e


def run_all_upgrades(dry_run: bool = False, reindex_scenes: bool = False):
    """Discovers all backups in backups_index.json and upgrades them."""
    index = t.get_backups_index()
    if not index:
        t.log("error", "No backups found in backups_index.json")
        return

    t.log("base", f"Found {len(index)} backups in index. Starting upgrade scan...\n")
    results = []
    for b in index:
        backup_path = (Path(c.DATA_ROOT) / b["path"]).as_posix()
        if not has_sqlite_db(backup_path):
            t.log("info", f"Skipping '{b['backup_name']}': no backup.sqlite present.")
            continue
        try:
            res = upgrade_single_backup(b, dry_run=dry_run, reindex_scenes=reindex_scenes)
            results.append(res)
        except Exception as e:
            t.log("error", f"Failed upgrading backup '{b['backup_name']}': {exc.unwrap(e)}")
            raise

    t.log("base", f"\nAll {len(results)} active database(s) successfully processed!")


def main():
    parser = argparse.ArgumentParser(description="Socrates: Database Schema Upgrade & Sync Utility")
    parser.add_argument("--backup-id", help="Upgrade a single backup by ID")
    parser.add_argument("--all", action="store_true", help="Upgrade all backups with SQLite databases in backups_index.json")
    parser.add_argument("--dry-run", action="store_true", help="Perform simulation in-memory without modifying disk")
    parser.add_argument("--reindex", action="store_true", help="Re-index scenes from raw chatlogs after schema rebuild")

    args = parser.parse_args()

    try:
        if args.backup_id:
            index = t.get_backups_index()
            backup = next((b for b in index if str(b["backup_id"]) == str(args.backup_id)), None)
            if not backup:
                raise exc.BackupError(f"Backup ID '{args.backup_id}' not found in index")
            upgrade_single_backup(backup, dry_run=args.dry_run, reindex_scenes=args.reindex)
        elif args.all:
            run_all_upgrades(dry_run=args.dry_run, reindex_scenes=args.reindex)
        else:
            parser.print_help()
    except Exception as e:
        t.log("error", f"Upgrade utility halted with error: {exc.unwrap(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

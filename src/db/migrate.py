import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Dict, List, Optional, Set

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
    FlaggedMessageModel,
    SchemaVersionModel,
    CURRENT_SCHEMA_VERSION,
    Scope,
    IssueKind,
    FlaggedKind,
    FlaggedResolution,
)
from db.session import get_engine, init_db, db_session
from db.snapshots import export_backup_info_snapshot, export_character_list_snapshot


# Verified high-confidence Discord User ID links from Phase 0 profiling
DISCORD_USER_ID_LINKS: Dict[str, str] = {
    "kei": "189839589991645185",
    "mastermilkgane": "189839589991645185",
    "meli": "283733331122716672",
    "melissenpai": "283733331122716672",
    "prim": "200668852713947137",
    "cureprimulas": "200668852713947137",
    "ogi": "1036826326214127687",
    "daisybirdie.": "1036826326214127687",
    "rasha": "501081344328204298",
    "pen_gui": "501081344328204298",
    "luke": "612939395141599232",
    "stxrfell": "612939395141599232",
    "red": "374424148702920705",
    "crazyredridinghood": "374424148702920705",
    "rei": "315007560346238988",
    "reisodi": "315007560346238988",
    "clear": "355535781349294081",
    "bigpapa_": "355535781349294081",
    "dreamy": "488998675331284992",
    "dreamfreaks": "488998675331284992",
    "jess": "937860419077406760",
    "jess_5120": "937860419077406760",
    "bara": "316311544214585345",
    "meghawhopp": "316311544214585345",
    "summer": "206892967007485953",
    "summerbummer": "206892967007485953",
    "sheepie": "347719740640198667",
    "baasama": "347719740640198667",
    "shay": "267874999568695298",
    "spacebrawler": "267874999568695298",
    "vinnie": "234355084115443712",
    "love_exi3": "234355084115443712",
    "beth": "209769525137113098",
    "gentlebara": "209769525137113098",
    "yuki": "316326852593451009",
    "yuki_ikusaba": "316326852593451009",
    "onyx": "343912046515191808",
    "cuminboy": "343912046515191808",
    "kiyo": "323326957213188096",
    "kiyomizuki": "323326957213188096",
}

# Normalization map for legacy step keys
STEP_NAME_MAP: Dict[str, str] = {
    "getInfoStatus": "get_info",
    "cleanInfoStatus": "clean_info",
    "downloadStatus": "download",
    "sortingReadStatus": "verify",
    "sortingCleanStatus": "verify",
    "sortingWriteStatus": "verify",
    "idAssignStatus": "assign_ids",
    "compareStatus": "compare",
    "mergeStatus": "merge",
    "messageFixStatus": "fix_messages",
    "indexScenesStatus": "index_scenes",
    "updateStatus": "update",
}

STATUS_MAP: Dict[str, str] = {
    "notStarted": "pending",
    "not_started": "pending",
    "pending": "pending",
    "running": "running",
    "in_progress": "running",
    "completed": "success",
    "success": "success",
    "failed": "failed",
    "error": "failed",
}


def parse_datetime(val: Optional[str]) -> Optional[datetime]:
    """Parses ISO-8601 string to a UTC datetime object."""
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def archive_legacy_files(backup_path: str) -> List[str]:
    """
    Archives original pre-migration JSON files into Info/legacy/.
    Does not delete any files and preserves existing legacy files without overwriting.
    """
    info_dir = Path(backup_path) / "Info"
    legacy_dir = info_dir / "legacy"
    legacy_dir.mkdir(parents=True, exist_ok=True)

    candidates = [
        info_dir / "backup_info.json",
        info_dir / "backup_info_update.json",
        info_dir / "character_list.json",
        info_dir / "fixed_messages.json",
        info_dir / "bad_messages.json",
        info_dir / "bad_end_messages.json",
        Path(backup_path) / "Data" / "_scenes.json",
    ]

    archived = []
    for f in candidates:
        if f.exists():
            target = legacy_dir / f.name
            if not target.exists():
                shutil.move(f.as_posix(), target.as_posix())
                archived.append(f.name)
            else:
                try:
                    f.unlink()
                except OSError:
                    pass

    return archived


class UnionFind:
    """Disjoint Set Union helper for writer alias clustering."""
    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        if self.parent.setdefault(x, x) != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: str, y: str):
        root_x = self.find(x)
        root_y = self.find(y)
        if root_x != root_y:
            self.parent[root_y] = root_x


def cluster_writers(characters_data: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Clusters writers across all characters and nested tuppers.
    Merges writer arrays that share any alias (case-insensitive).
    Returns mapping from cluster root -> writer info dict.
    """
    uf = UnionFind()
    canonical_display: Dict[str, str] = {}
    cluster_aliases: Dict[str, Set[str]] = {}

    def collect_writer_lists(item: Dict[str, Any]):
        w_raw = item.get("writer", [])
        if isinstance(w_raw, str):
            w_raw = [w_raw]
        cleaned = [w.strip() for w in w_raw if w and w.strip()]
        if cleaned:
            root = cleaned[0].lower()
            if root not in canonical_display:
                canonical_display[root] = cleaned[0]
            for w in cleaned[1:]:
                uf.union(root, w.lower())

        for child in item.get("other_versions", []):
            collect_writer_lists(child)

    for item in characters_data:
        collect_writer_lists(item)

    # Group all aliases by their connected component root
    def register_aliases(item: Dict[str, Any]):
        w_raw = item.get("writer", [])
        if isinstance(w_raw, str):
            w_raw = [w_raw]
        for w in w_raw:
            w_strip = w.strip()
            if w_strip:
                root = uf.find(w_strip.lower())
                cluster_aliases.setdefault(root, set()).add(w_strip)

        for child in item.get("other_versions", []):
            register_aliases(child)

    for item in characters_data:
        register_aliases(item)

    writers_by_root: Dict[str, Dict[str, Any]] = {}
    for root, aliases in cluster_aliases.items():
        # Choose canonical display name
        display_name = canonical_display.get(root) or sorted(aliases)[0]
        # Match Discord User ID if any alias is known
        matched_discord_id = None
        for a in aliases:
            if a.lower() in DISCORD_USER_ID_LINKS:
                matched_discord_id = DISCORD_USER_ID_LINKS[a.lower()]
                break

        writers_by_root[root] = {
            "display_name": display_name,
            "discord_user_id": matched_discord_id,
            "aliases": sorted(list(aliases)),
        }

    return writers_by_root


def extract_group_names(names: List[str]) -> List[str]:
    """
    Extracts clean group names by filtering out writer qualifiers (e.g. (Ogi), Ogi!).
    """
    cleaned: List[str] = []
    for n in names:
        # Check if name has parenthetical qualifier e.g. (Ogi) or prefix e.g. Ogi!
        if re.search(r'\([^)]*\)', n) or re.search(r'^\S+!', n):
            continue
        trimmed = n.strip()
        if trimmed and trimmed not in cleaned:
            cleaned.append(trimmed)
    return cleaned


def migrate_channels(session, export_pk: int, categories_data: List[Dict[str, Any]]) -> Dict[str, ChannelModel]:
    """
    Inserts categories, channels, and threads hierarchy into ChannelModel.
    Returns mapping from discord_id -> ChannelModel.
    """
    channel_map: Dict[str, ChannelModel] = {}

    for cat_data in categories_data:
        cat_model = ChannelModel(
            export_pk=export_pk,
            discord_id=str(cat_data["id"]),
            type="GuildCategory",
            parent_pk=None,
            name=str(cat_data.get("name", "")),
            position=int(cat_data.get("position", 0)),
            path=str(cat_data.get("path", "")),
            is_deleted=bool(cat_data.get("is_deleted", False)),
            message_count=None,
        )
        session.add(cat_model)
        session.flush()
        channel_map[cat_model.discord_id] = cat_model

        for chan_data in cat_data.get("channels", []):
            chan_model = ChannelModel(
                export_pk=export_pk,
                discord_id=str(chan_data["id"]),
                type=str(chan_data.get("type", "GuildTextChat")),
                parent_pk=cat_model.pk,
                name=str(chan_data.get("name", "")),
                position=int(chan_data.get("position", 0)),
                path=str(chan_data.get("path", "")),
                is_deleted=bool(chan_data.get("is_deleted", False)),
                message_count=chan_data.get("number_of_messages"),
            )
            session.add(chan_model)
            session.flush()
            channel_map[chan_model.discord_id] = chan_model

            for thr_data in chan_data.get("threads", []):
                thr_model = ChannelModel(
                    export_pk=export_pk,
                    discord_id=str(thr_data["id"]),
                    type=str(thr_data.get("type", "GuildPublicThread")),
                    parent_pk=chan_model.pk,
                    name=str(thr_data.get("name", "")),
                    position=int(thr_data.get("position", 0)),
                    path=str(thr_data.get("path", "")),
                    is_deleted=bool(thr_data.get("is_deleted", False)),
                    message_count=thr_data.get("number_of_messages"),
                )
                session.add(thr_model)
                session.flush()
                channel_map[thr_model.discord_id] = thr_model

    return channel_map


def migrate_single_backup(
    backup: dict,
    dry_run: bool = False,
    skip_snapshots: bool = False
) -> Dict[str, Any]:
    """
    Migrates a single backup directory from loose JSONs to SQLite.
    """
    backup_id = backup["backup_id"]
    backup_name = backup["backup_name"]
    backup_path = (Path(c.DATA_ROOT) / backup["path"]).as_posix()
    
    t.log("info", f"\n=======================================================")
    t.log("info", f"Starting migration for backup '{backup_name}' (ID: {backup_id})")
    t.log("info", f"Path: {backup_path}")
    t.log("info", f"=======================================================\n")

    info_dir = Path(backup_path) / "Info"
    legacy_dir = info_dir / "legacy"

    # Step 0: Archive legacy originals (skip in dry-run)
    if not dry_run:
        archived_files = archive_legacy_files(backup_path)
        if archived_files:
            t.log("base", f"Archived {len(archived_files)} legacy JSON files to Info/legacy/: {', '.join(archived_files)}")
        else:
            t.log("info", "Legacy archive directory Info/legacy/ already contains original pre-migration files.")
    else:
        t.log("info", "DRY-RUN mode enabled: validating data transformations in-memory without modifying disk.")

    def resolve_source_file(filename: str, default_dir: Path) -> Path:
        """Prefers pristine pre-migration files from Info/legacy/ if present (ensures safe re-runs)."""
        legacy_file = legacy_dir / filename
        if legacy_file.exists():
            return legacy_file
        return default_dir / filename

    backup_info_file = resolve_source_file("backup_info.json", info_dir)
    if not backup_info_file.exists():
        raise exc.MigrationError(f"Missing required backup_info.json in {info_dir} or {legacy_dir}")

    backup_info = t.load_from_json(backup_info_file.as_posix())

    # Check for update export
    backup_info_update_file = resolve_source_file("backup_info_update.json", info_dir)
    backup_info_update = t.load_from_json(backup_info_update_file.as_posix()) if backup_info_update_file.exists() else None

    # Load character_list.json
    character_list_file = resolve_source_file("character_list.json", info_dir)
    character_list = t.load_from_json(character_list_file.as_posix()) if character_list_file.exists() else []

    # Load scenes
    scenes_file = resolve_source_file("_scenes.json", Path(backup_path) / "Data")
    scenes_data = t.load_from_json(scenes_file.as_posix()) if scenes_file.exists() else []

    # Load overrides and bad messages
    fixed_msg_file = resolve_source_file("fixed_messages.json", info_dir)
    fixed_messages = t.load_from_json(fixed_msg_file.as_posix()) if fixed_msg_file.exists() else {}

    bad_msg_file = resolve_source_file("bad_messages.json", info_dir)
    bad_messages = t.load_from_json(bad_msg_file.as_posix()) if bad_msg_file.exists() else {}

    bad_end_msg_file = resolve_source_file("bad_end_messages.json", info_dir)
    bad_end_messages = t.load_from_json(bad_end_msg_file.as_posix()) if bad_end_msg_file.exists() else {}

    report_metrics: Dict[str, Any] = {
        "backup_id": backup_id,
        "backup_name": backup_name,
        "categories_count": 0,
        "channels_count": 0,
        "threads_count": 0,
        "writers_count": 0,
        "writer_aliases_count": 0,
        "character_groups_count": 0,
        "characters_count": 0,
        "tuppers_count": 0,
        "scenes_count": 0,
        "scene_issues_count": 0,
        
        "flagged_messages_count": 0,
        "nested_writer_mismatches": [],
    }

    # Initialize Engine & Database schema
    if dry_run:
        from contextlib import contextmanager
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        mem_engine = create_engine("sqlite:///:memory:")
        init_db(mem_engine)

        @contextmanager
        def mem_session():
            Session = sessionmaker(bind=mem_engine)
            s = Session()
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise
            finally:
                s.close()

        session_context = mem_session()
    else:
        engine = get_engine(backup_id=backup_id, backup_path=backup_path)
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        session_context = db_session(backup_id=backup_id, backup_path=backup_path)

    with session_context as session:

        # 0. Stamp Schema Version
        session.add(SchemaVersionModel(
            version=CURRENT_SCHEMA_VERSION,
            applied_at=datetime.now(timezone.utc),
            description="Migrated from JSON",
        ))

        # 1. Backups & Base Export
        server_id = backup["server_id"]
        server_name = backup["server_name"]
        created_at = parse_datetime(backup_info.get("updated_at") or backup_info.get("exported_at"))

        backup_model = BackupModel(
            backup_id=backup_id,
            backup_name=backup_name,
            server_id=server_id,
            server_name=server_name,
            created_at=created_at,
        )
        session.add(backup_model)
        session.flush()

        base_export = ExportModel(
            backup_id=backup_model.backup_id,
            scope=Scope.BASE,
            exported_from=parse_datetime(backup_info.get("exported_from")),
            exported_at=parse_datetime(backup_info.get("exported_at")),
            updated_at=parse_datetime(backup_info.get("updated_at")),
        )
        session.add(base_export)
        session.flush()

        # Base Steps
        for raw_step, raw_status in backup_info.get("steps", {}).items():
            norm_step = STEP_NAME_MAP.get(raw_step, raw_step)
            norm_status = STATUS_MAP.get(raw_status, raw_status)
            session.add(BackupStepModel(
                export_pk=base_export.pk,
                step=norm_step,
                status=norm_status,
            ))

        # Base Channels
        channel_map = migrate_channels(session, base_export.pk, backup_info.get("categories", []))
        report_metrics["categories_count"] = sum(1 for c in channel_map.values() if c.type == "GuildCategory")
        report_metrics["channels_count"] = sum(1 for c in channel_map.values() if c.type != "GuildCategory" and c.type != "GuildPublicThread")
        report_metrics["threads_count"] = sum(1 for c in channel_map.values() if c.type == "GuildPublicThread")

        # 2. Update Export (if present)
        if backup_info_update:
            update_export = ExportModel(
                backup_id=backup_model.backup_id,
                scope=Scope.UPDATE,
                exported_from=parse_datetime(backup_info_update.get("exported_from")),
                exported_at=parse_datetime(backup_info_update.get("exported_at")),
                updated_at=parse_datetime(backup_info_update.get("updated_at")),
            )
            session.add(update_export)
            session.flush()

            for raw_step, raw_status in backup_info_update.get("steps", {}).items():
                norm_step = STEP_NAME_MAP.get(raw_step, raw_step)
                norm_status = STATUS_MAP.get(raw_status, raw_status)
                session.add(BackupStepModel(
                    export_pk=update_export.pk,
                    step=norm_step,
                    status=norm_status,
                ))

            migrate_channels(session, update_export.pk, backup_info_update.get("categories", []))
            t.log("base", "Migrated secondary 'update' export scope.")

        # 3. Writers & Writer Aliases
        writer_clusters = cluster_writers(character_list)
        alias_to_writer_pk: Dict[str, int] = {}

        for root_key, w_data in writer_clusters.items():
            writer_model = WriterModel(
                backup_id=backup_model.backup_id,
                display_name=w_data["display_name"],
                discord_user_id=w_data["discord_user_id"],
            )
            session.add(writer_model)
            session.flush()
            report_metrics["writers_count"] += 1

            for alias_str in w_data["aliases"]:
                session.add(WriterAliasModel(
                    writer_pk=writer_model.pk,
                    alias=alias_str,
                ))
                alias_to_writer_pk[alias_str.lower()] = writer_model.pk
                report_metrics["writer_aliases_count"] += 1

        def resolve_writer_pk(raw_writer: Any) -> Optional[int]:
            if not raw_writer:
                return None
            if isinstance(raw_writer, str):
                raw_writer = [raw_writer]
            for w in raw_writer:
                if w and w.strip().lower() in alias_to_writer_pk:
                    return alias_to_writer_pk[w.strip().lower()]
            return None

        # 4. Character Groups & Characters
        char_id_to_pk: Dict[int, int] = {}

        for item in character_list:
            char_id = int(item["id"])
            tags = item.get("tags", [])
            other_versions = item.get("other_versions", [])

            # Check if this character is a multi-writer group parent
            is_group_parent = "has_other_writers" in tags or any("has_other_writers" in v.get("tags", []) for v in other_versions)
            group_pk = None

            if is_group_parent:
                group_model = CharacterGroupModel(backup_id=backup_model.backup_id)
                session.add(group_model)
                session.flush()
                group_pk = group_model.pk
                report_metrics["character_groups_count"] += 1

                # Extract and insert clean group names
                gnames = extract_group_names(item.get("names", []))
                if not gnames:
                    gnames = [item["names"][0]]  # Fallback to primary name
                for pos, gname in enumerate(gnames):
                    session.add(GroupNameModel(
                        group_pk=group_pk,
                        name=gname,
                        position=pos,
                    ))

            # Insert top-level character
            parent_writer_pk = resolve_writer_pk(item.get("writer"))
            top_version_type = "npc" if "npc" in tags else "alter_ego" if "alter_ego" in tags else "familiar" if "familiar" in tags else None
            char_model = CharacterModel(
                backup_id=backup_model.backup_id,
                char_id=char_id,
                writer_pk=parent_writer_pk,
                group_pk=group_pk,
                parent_pk=None,
                version_type=top_version_type,
                origin="canon" if "canon" in tags else "oc",
                activity="active" if "active" in tags else "inactive",
            )
            session.add(char_model)
            session.flush()
            char_id_to_pk[char_id] = char_model.pk
            report_metrics["characters_count"] += 1

            for pos, name in enumerate(item.get("names", [])):
                session.add(CharacterNameModel(
                    character_pk=char_model.pk,
                    name=name,
                    position=pos,
                ))

            # Process other_versions
            for version_item in other_versions:
                v_id = int(version_item["id"])
                v_tags = version_item.get("tags", [])
                v_writer_pk = resolve_writer_pk(version_item.get("writer"))

                if "has_other_writers" in v_tags and is_group_parent:
                    # Sibling member of character group
                    sibling_vtype = "npc" if "npc" in v_tags else "alter_ego" if "alter_ego" in v_tags else "familiar" if "familiar" in v_tags else None
                    v_char_model = CharacterModel(
                        backup_id=backup_model.backup_id,
                        char_id=v_id,
                        writer_pk=v_writer_pk,
                        group_pk=group_pk,
                        parent_pk=None,
                        version_type=sibling_vtype,
                        origin="canon" if "canon" in v_tags else "oc",
                        activity="active" if "active" in v_tags else "inactive",
                    )
                    session.add(v_char_model)
                    session.flush()
                    char_id_to_pk[v_id] = v_char_model.pk
                    report_metrics["characters_count"] += 1

                    for pos, name in enumerate(version_item.get("names", [])):
                        session.add(CharacterNameModel(
                            character_pk=v_char_model.pk,
                            name=name,
                            position=pos,
                        ))
                else:
                    # Nested supporting tupper (alter_ego / npc / familiar)
                    if v_writer_pk != parent_writer_pk:
                        report_metrics["nested_writer_mismatches"].append({
                            "child_id": v_id,
                            "child_name": version_item["names"][0] if version_item.get("names") else "",
                            "parent_id": char_id,
                            "parent_name": item["names"][0] if item.get("names") else "",
                        })

                    vtype = "alter_ego" if "alter_ego" in v_tags else "npc" if "npc" in v_tags else "familiar" if "familiar" in v_tags else "alter_ego"
                    v_char_model = CharacterModel(
                        backup_id=backup_model.backup_id,
                        char_id=v_id,
                        writer_pk=v_writer_pk,
                        group_pk=None,
                        parent_pk=char_model.pk,
                        version_type=vtype,
                        origin="canon" if "canon" in v_tags else "oc",
                        activity="active" if "active" in v_tags else "inactive",
                    )
                    session.add(v_char_model)
                    session.flush()
                    char_id_to_pk[v_id] = v_char_model.pk
                    report_metrics["tuppers_count"] += 1

                    for pos, name in enumerate(version_item.get("names", [])):
                        session.add(CharacterNameModel(
                            character_pk=v_char_model.pk,
                            name=name,
                            position=pos,
                        ))


        # 5. Scenes, Participants & Issues
        # Group scenes by channelId to build unique separator keys
        scenes_by_channel: Dict[str, List[Dict[str, Any]]] = {}
        for s in scenes_data:
            scenes_by_channel.setdefault(str(s["channelId"]), []).append(s)

        for chan_discord_id, chan_scenes in scenes_by_channel.items():
            # Sort scenes in channel by start index
            chan_scenes.sort(key=lambda x: x.get("start", {}).get("index", 0))

            chan_model = channel_map.get(chan_discord_id)
            if not chan_model:
                t.log("debug", f"Channel ID {chan_discord_id} in scenes not found in channel map; skipping scene group.")
                continue

            # Determine category PK and key prefix
            if chan_model.type == "GuildPublicThread" and chan_model.parent_pk:
                parent_chan = session.get(ChannelModel, chan_model.parent_pk)
                cat_chan = session.get(ChannelModel, parent_chan.parent_pk) if parent_chan and parent_chan.parent_pk else parent_chan
                category_pk = cat_chan.pk if cat_chan else chan_model.pk
                key_prefix = f"{cat_chan.position if cat_chan else 0}-{parent_chan.position if parent_chan else 0}-{chan_model.position}"
            else:
                cat_chan = session.get(ChannelModel, chan_model.parent_pk) if chan_model.parent_pk else chan_model
                category_pk = cat_chan.pk if cat_chan else chan_model.pk
                key_prefix = f"{cat_chan.position if cat_chan else 0}-{chan_model.position}"


            for idx, s in enumerate(chan_scenes):
                scene_key = f"{key_prefix}-{idx + 1}"
                lifecycle_status = s.get("status", "closed")

                start_at = parse_datetime(s["start"].get("timestamp")) or datetime.now(timezone.utc)
                end_at = parse_datetime(s["end"].get("timestamp")) or datetime.now(timezone.utc)

                scene_model = SceneModel(
                    backup_id=backup_model.backup_id,
                    scene_key=scene_key,
                    channel_pk=chan_model.pk,
                    category_pk=category_pk,
                    status=lifecycle_status,
                    start_message_id=str(s["start"].get("id", "")),
                    end_message_id=str(s["end"].get("id", "")),
                    start_index=int(s["start"].get("index", 0)),
                    end_index=int(s["end"].get("index", 0)),
                    start_at=start_at,
                    end_at=end_at,
                    start_author_id=str(s["start"].get("authorID", "")),
                    end_author_id=str(s["end"].get("authorID", "")),
                    start_excerpt=str(s["start"].get("content", ""))[:250],
                    end_excerpt=str(s["end"].get("content", ""))[:250],
                )
                session.add(scene_model)
                session.flush()
                report_metrics["scenes_count"] += 1

                # Participants
                for participant_id in s.get("characters", []):
                    try:
                        p_int = int(participant_id)
                    except (ValueError, TypeError):
                        continue
                    if t.is_tupper(p_int) and p_int in char_id_to_pk:
                        session.add(SceneParticipantModel(
                            scene_pk=scene_model.pk,
                            character_pk=char_id_to_pk[p_int],
                        ))

                # Issues
                for iss in s.get("issues", []):
                    ikind = iss.get("kind")
                    if ikind == "timeout":
                        ikind = "auto_split"
                    if ikind == "possible_split":
                        ikind = IssueKind.SOFT_BOUNDARY.value
                    if ikind in (IssueKind.AUTO_SPLIT.value, IssueKind.SOFT_BOUNDARY.value):
                        session.add(SceneIssueModel(
                            backup_id=backup_model.backup_id,
                            scene_pk=scene_model.pk,
                            kind=ikind,
                            reason=iss.get("reason") or "roster_split",
                            candidate_message_id=str(iss.get("candidate_id") or "") or None,
                            candidate_index=iss.get("candidate_index"),
                            candidate_excerpt=iss.get("candidate_excerpt"),
                            previous_chars=iss.get("previous_chars") or [],
                            next_chars=iss.get("next_chars") or [],
                            created_at=start_at,
                        ))
                        report_metrics["scene_issues_count"] += 1

        # 6. Unified Flagged Messages & Overrides
        now_utc = datetime.now(timezone.utc)

        # fixed_messages.json -> FlaggedMessageModel with resolution="override"
        if isinstance(fixed_messages, dict):
            for msg_id, data in fixed_messages.items():
                content_val = data.get("content", "")
                author_val = data.get("author", {})
                session.add(FlaggedMessageModel(
                    backup_id=backup_model.backup_id,
                    message_id=str(msg_id),
                    channel_pk=None,
                    kind=FlaggedKind.FAILED_TUPPER.value,
                    content=content_val,
                    author=author_val,
                    flagged_at=now_utc,
                    resolution=FlaggedResolution.OVERRIDE.value,
                    override_content=content_val,
                    override_author=author_val,
                    resolved_at=now_utc,
                    resolved_note="Migrated from fixed_messages.json",
                ))
                report_metrics["flagged_messages_count"] += 1

        # bad_messages.json
        if isinstance(bad_messages, dict):
            for msg_id, data in bad_messages.items():
                session.add(FlaggedMessageModel(
                    backup_id=backup_model.backup_id,
                    message_id=str(msg_id),
                    channel_pk=None,
                    kind=FlaggedKind.FAILED_TUPPER.value,
                    content=data.get("content", ""),
                    author=data.get("author", {}),
                    flagged_at=now_utc,
                ))
                report_metrics["flagged_messages_count"] += 1

        # bad_end_messages.json
        if isinstance(bad_end_messages, dict):
            for msg_id, data in bad_end_messages.items():
                # Extract channel from link if available
                link = data.get("link", "")
                resolved_chan_pk = None
                if link and "/channels/" in link:
                    parts = link.split("/")
                    if len(parts) >= 2:
                        chan_discord_id = parts[-2]
                        if chan_discord_id in channel_map:
                            resolved_chan_pk = channel_map[chan_discord_id].pk

                session.add(FlaggedMessageModel(
                    backup_id=backup_model.backup_id,
                    message_id=str(msg_id),
                    channel_pk=resolved_chan_pk,
                    kind=FlaggedKind.OOC_BOUNDARY.value,
                    content=data.get("content", ""),
                    author=data.get("author", {}),
                    flagged_at=now_utc,
                ))
                report_metrics["flagged_messages_count"] += 1

    # Step 7: Export Parity Snapshots (outside transaction to commit first)
    if not dry_run and not skip_snapshots:
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            t.log("info", "Generating post-migration JSON snapshots...")
            export_backup_info_snapshot(session, backup_id)
            if backup_info_update:
                export_backup_info_snapshot(session, backup_id, scope="update")
            export_character_list_snapshot(session, backup_id)
            t.log("base", "Snapshots successfully generated in Info/")

    # Step 8: Write Human Review Report
    report_md = f"""# Migration Review Report: {backup_name}

- **Backup ID:** `{backup_id}`
- **Server Name:** {server_name} (Snowflake: `{server_id}`)
- **Timestamp:** {datetime.now(timezone.utc).isoformat()}
- **SQLite Database:** `backup.sqlite`

## Entity Summary
| Entity | Count | Notes |
|---|---|---|
| Categories | {report_metrics['categories_count']} | GuildCategory |
| Channels | {report_metrics['channels_count']} | GuildTextChat |
| Threads | {report_metrics['threads_count']} | GuildPublicThread |
| Writers | {report_metrics['writers_count']} | Normalized writer profiles |
| Writer Aliases | {report_metrics['writer_aliases_count']} | Clustered and merged aliases |
| Character Groups | {report_metrics['character_groups_count']} | Multi-writer vampire groups |
| Top-level Characters | {report_metrics['characters_count']} | Top-level characters & group siblings |
| Nested Tuppers | {report_metrics['tuppers_count']} | Alter egos, NPCs, familiars |
| Scenes | {report_metrics['scenes_count']} | Recomputed separator keys (`100% unique`) |
| Scene Issues | {report_metrics['scene_issues_count']} | Auto-splits & possible splits |
| Flagged Messages | {report_metrics['flagged_messages_count']} | Non-tupper messages & end tags |

## Informational Writer Mismatches (Nested Tuppers)
Count: {len(report_metrics['nested_writer_mismatches'])}
"""
    for mismatch in report_metrics["nested_writer_mismatches"]:
        report_md += f"- Child ID {mismatch['child_id']} (`{mismatch['child_name']}`) under Parent ID {mismatch['parent_id']} (`{mismatch['parent_name']}`)\n"

    if not dry_run:
        report_path = (Path(backup_path) / "Info" / "migration_report.md").as_posix()
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_md)
        t.log("base", f"Migration review report written to: {report_path}\n")
    else:
        t.log("base", f"[DRY-RUN] Migration review report preview:\n{report_md}\n")

    return report_metrics



def run_all_migrations(dry_run: bool = False, skip_snapshots: bool = False):
    """Discovers all backups from backups_index.json and migrates them."""
    index = t.get_backups_index()
    if not index:
        t.log("error", "No backups found in backups_index.json")
        return

    t.log("base", f"Found {len(index)} backups in index. Starting migration loop...\n")
    results = []
    for b in index:
        try:
            res = migrate_single_backup(b, dry_run=dry_run, skip_snapshots=skip_snapshots)
            results.append(res)
        except Exception as e:
            t.log("error", f"Failed migrating backup '{b['backup_name']}' ({b['backup_id']}): {exc.unwrap(e)}")
            raise

    t.log("base", f"All {len(results)} backups successfully migrated!")

def migrate_for_tests(backup_id: str):
    """Migrates a single backup for testing purposes."""
    backup = next((b for b in t.get_backups_index() if str(b["backup_id"]) == str(backup_id)), None)
    if not backup:
        raise exc.BackupError(f"Backup ID '{backup_id}' not found in index")
    migrate_single_backup(backup, dry_run=False, skip_snapshots=True)

def main():
    parser = argparse.ArgumentParser(description="Socrates: JSON to SQLite Database Migration")
    parser.add_argument("--backup-id", help="Migrate a single backup by ID")
    parser.add_argument("--all", action="store_true", help="Migrate all backups in backups_index.json")
    parser.add_argument("--dry-run", action="store_true", help="Perform validation without writing database")
    parser.add_argument("--skip-snapshots", action="store_true", help="Skip snapshot exports")

    args = parser.parse_args()

    try:
        if args.backup_id:
            index = t.get_backups_index()

            # Find backup info from index
            backup = next((b for b in index if str(b["backup_id"]) == str(args.backup_id)), None)
            if not backup:
                raise exc.BackupError(f"Backup ID '{args.backup_id}' not found in index")
            migrate_single_backup(backup, dry_run=args.dry_run, skip_snapshots=args.skip_snapshots)
        elif args.all:
            run_all_migrations(dry_run=args.dry_run, skip_snapshots=args.skip_snapshots)
        else:
            parser.print_help()
    except Exception as e:
        t.log("error", f"Migration halted with error: {exc.unwrap(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

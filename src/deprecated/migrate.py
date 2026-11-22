"""
Deprecated legacy JSON-to-SQLite migration script.
Retained for historical reference and shared writer/group clustering helpers.
For testing fixtures, use tests/seed_test_backup.py.
"""

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
    SceneParticipantModel,
    SceneIssueModel,
    FlaggedMessageModel,
    SchemaVersionModel,
    CURRENT_SCHEMA_VERSION,
    SceneKind,
    IssueKind,
    FlaggedKind,
    FlaggedResolution,
    StorageMode,
    SyncStatus,
)
from db.skeleton_models import compute_skeleton_flags
from db.session import get_engine, db_session
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


def parse_datetime(val: Optional[str]) -> Optional[datetime]:
    """Parses ISO-8601 string to a UTC datetime object."""
    return t.parse_datetime(val)


def archive_legacy_files(backup_path: str) -> List[str]:
    """Archives original pre-migration JSON files into Info/legacy/."""
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
    """Clusters writers across all characters and nested tuppers."""
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
        display_name = canonical_display.get(root) or sorted(aliases)[0]
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
    """Extracts clean group names by filtering out writer qualifiers (e.g. (Ogi), Ogi!)."""
    cleaned: List[str] = []
    for n in names:
        if re.search(r'\([^)]*\)', n) or re.search(r'^\S+!', n):
            continue
        trimmed = n.strip()
        if trimmed and trimmed not in cleaned:
            cleaned.append(trimmed)
    return cleaned


def migrate_channels(session, backup_id: str, categories_data: List[Dict[str, Any]]) -> Dict[str, ChannelModel]:
    """Inserts categories, channels, and threads hierarchy into Schema v6 ChannelModel."""
    channel_map: Dict[str, ChannelModel] = {}

    for cat_data in categories_data:
        cat_model = ChannelModel(
            backup_id=str(backup_id),
            discord_id=str(cat_data["id"]),
            type="GuildCategory",
            parent_pk=None,
            name=str(cat_data.get("name", "")),
            position=int(cat_data.get("position", 0)),
            path=str(cat_data.get("path", "")),
            is_deleted=bool(cat_data.get("is_deleted", False)),
            message_count=None,
            sync_status="synced",
        )
        session.add(cat_model)
        session.flush()
        channel_map[cat_model.discord_id] = cat_model

        for chan_data in cat_data.get("channels", []):
            chan_model = ChannelModel(
                backup_id=str(backup_id),
                discord_id=str(chan_data["id"]),
                type=str(chan_data.get("type", "GuildTextChat")),
                parent_pk=cat_model.pk,
                name=str(chan_data.get("name", "")),
                position=int(chan_data.get("position", 0)),
                path=str(chan_data.get("path", "")),
                is_deleted=bool(chan_data.get("is_deleted", False)),
                message_count=chan_data.get("number_of_messages"),
                sync_status="synced",
            )
            session.add(chan_model)
            session.flush()
            channel_map[chan_model.discord_id] = chan_model

            for thr_data in chan_data.get("threads", []):
                thr_model = ChannelModel(
                    backup_id=str(backup_id),
                    discord_id=str(thr_data["id"]),
                    type=str(thr_data.get("type", "GuildPublicThread")),
                    parent_pk=chan_model.pk,
                    name=str(thr_data.get("name", "")),
                    position=int(thr_data.get("position", 0)),
                    path=str(thr_data.get("path", "")),
                    is_deleted=bool(thr_data.get("is_deleted", False)),
                    message_count=thr_data.get("number_of_messages"),
                    sync_status="synced",
                )
                session.add(thr_model)
                session.flush()
                channel_map[thr_model.discord_id] = thr_model

    return channel_map


def migrate_single_backup(
    backup: dict,
    dry_run: bool = False,
    skip_snapshots: bool = False,
) -> Dict[str, Any]:
    """Legacy JSON-to-SQLite migration writing Schema v6 tables."""
    backup_id = str(backup["backup_id"])
    backup_name = str(backup["backup_name"])
    backup_path = (Path(c.DATA_ROOT) / backup["path"]).as_posix()

    info_dir = Path(backup_path) / "Info"
    legacy_dir = info_dir / "legacy"

    if not dry_run:
        archive_legacy_files(backup_path)

    def resolve_source_file(filename: str, default_dir: Path) -> Path:
        legacy_file = legacy_dir / filename
        if legacy_file.exists():
            return legacy_file
        return default_dir / filename

    backup_info_file = resolve_source_file("backup_info.json", info_dir)
    if not backup_info_file.exists():
        raise exc.MigrationError(f"Missing required backup_info.json in {info_dir} or {legacy_dir}")

    backup_info = t.load_from_json(backup_info_file.as_posix())
    character_list_file = resolve_source_file("character_list.json", info_dir)
    character_list = t.load_from_json(character_list_file.as_posix()) if character_list_file.exists() else []
    scenes_file = resolve_source_file("_scenes.json", Path(backup_path) / "Data")
    scenes_data = t.load_from_json(scenes_file.as_posix()) if scenes_file.exists() else []
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
    }

    if not dry_run:
        engine = get_engine(backup_id=backup_id, backup_path=backup_path)
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            session.add(SchemaVersionModel(
                version=CURRENT_SCHEMA_VERSION,
                applied_at=datetime.now(timezone.utc),
                description="Migrated from JSON (deprecated.migrate)",
            ))
            created_at = parse_datetime(backup_info.get("updated_at") or backup_info.get("exported_at"))
            backup_model = BackupModel(
                backup_id=backup_id,
                backup_name=backup_name,
                server_id=str(backup["server_id"]),
                server_name=str(backup["server_name"]),
                created_at=created_at,
                last_synced_at=created_at,
                storage_mode=StorageMode.FULL.value,
                sync_status=SyncStatus.IDLE.value,
            )
            session.add(backup_model)
            session.flush()

            channel_map = migrate_channels(session, backup_id, backup_info.get("categories", []))
            report_metrics["categories_count"] = sum(1 for ch in channel_map.values() if ch.type == "GuildCategory")
            report_metrics["channels_count"] = sum(1 for ch in channel_map.values() if ch.type not in ("GuildCategory", "GuildPublicThread"))
            report_metrics["threads_count"] = sum(1 for ch in channel_map.values() if ch.type == "GuildPublicThread")

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
                report_metrics["writers_count"] += 1
                for alias_str in w_data["aliases"]:
                    session.add(WriterAliasModel(writer_pk=wm.pk, alias=alias_str))
                    alias_to_writer_pk[alias_str.lower()] = wm.pk
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

            char_id_to_pk: Dict[int, int] = {}
            for item in character_list:
                char_id = int(item["id"])
                tags = item.get("tags", [])
                other_versions = item.get("other_versions", [])
                is_group_parent = "has_other_writers" in tags or any("has_other_writers" in v.get("tags", []) for v in other_versions)
                group_pk = None
                if is_group_parent:
                    gm = CharacterGroupModel(backup_id=backup_id)
                    session.add(gm)
                    session.flush()
                    group_pk = gm.pk
                    report_metrics["character_groups_count"] += 1
                    gnames = extract_group_names(item.get("names", [])) or [item["names"][0]]
                    for pos, gname in enumerate(gnames):
                        session.add(GroupNameModel(group_pk=group_pk, name=gname, position=pos))

                parent_writer_pk = resolve_writer_pk(item.get("writer"))
                top_vtype = "npc" if "npc" in tags else "alter_ego" if "alter_ego" in tags else "familiar" if "familiar" in tags else None
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
                report_metrics["characters_count"] += 1
                for pos, name in enumerate(item.get("names", [])):
                    session.add(CharacterNameModel(character_pk=cm.pk, name=name, position=pos))

                for v_item in other_versions:
                    v_id = int(v_item["id"])
                    v_tags = v_item.get("tags", [])
                    v_writer_pk = resolve_writer_pk(v_item.get("writer"))
                    is_sibling = "has_other_writers" in v_tags and is_group_parent
                    v_vtype = "alter_ego" if "alter_ego" in v_tags else "npc" if "npc" in v_tags else "familiar" if "familiar" in v_tags else (None if is_sibling else "alter_ego")
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
                    report_metrics["characters_count" if is_sibling else "tuppers_count"] += 1
                    for pos, name in enumerate(v_item.get("names", [])):
                        session.add(CharacterNameModel(character_pk=v_cm.pk, name=name, position=pos))

            now_utc = datetime.now(timezone.utc)
            if isinstance(fixed_messages, dict):
                for msg_id, data in fixed_messages.items():
                    content_val = data.get("content", "")
                    author_val = data.get("author", {})
                    o_flags = compute_skeleton_flags({"type": "Default", "content": content_val, "author": author_val})
                    session.add(FlaggedMessageModel(
                        backup_id=backup_id,
                        message_id=str(msg_id),
                        channel_pk=None,
                        kind=FlaggedKind.FAILED_TUPPER.value,
                        content=content_val,
                        author=author_val,
                        flagged_at=now_utc,
                        resolution=FlaggedResolution.OVERRIDE.value,
                        override_content=content_val,
                        override_author=author_val,
                        override_flags=o_flags,
                        resolved_at=now_utc,
                        resolved_note="Migrated from fixed_messages.json",
                    ))
                    report_metrics["flagged_messages_count"] += 1

            for src_dict, fkind in ((bad_messages, FlaggedKind.FAILED_TUPPER.value), (bad_end_messages, FlaggedKind.OOC_BOUNDARY.value)):
                if isinstance(src_dict, dict):
                    for msg_id, data in src_dict.items():
                        session.add(FlaggedMessageModel(
                            backup_id=backup_id,
                            message_id=str(msg_id),
                            channel_pk=None,
                            kind=fkind,
                            content=data.get("content", ""),
                            author=data.get("author", {}),
                            flagged_at=now_utc,
                        ))
                        report_metrics["flagged_messages_count"] += 1

    if not dry_run and not skip_snapshots:
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            export_backup_info_snapshot(session, backup_id)
            export_character_list_snapshot(session, backup_id)

    return report_metrics


def migrate_for_tests(backup_id: str):
    backup = next((b for b in t.get_backups_index() if str(b["backup_id"]) == str(backup_id)), None)
    if not backup:
        raise exc.BackupError(f"Backup ID '{backup_id}' not found in index")
    migrate_single_backup(backup, dry_run=False, skip_snapshots=True)

"""
Database schema upgrade utility for Socrates SQLite databases.
Rebuilds the schema cleanly using Base.metadata and preserves curated data.
Supports upgrading Schema v1-v5 -> Schema v6 + populating skeletons.sqlite.
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
    ChannelModel,
    WriterModel,
    WriterAliasModel,
    CharacterGroupModel,
    GroupNameModel,
    CharacterModel,
    CharacterNameModel,
    EventModel,
    SceneModel,
    SceneParticipantModel,
    SceneIssueModel,
    SeenDiscordUserModel,
    FlaggedKind,
    FlaggedResolution,
    FlaggedMessageModel,
    StorageMode,
    SyncStatus,
    CURRENT_SCHEMA_VERSION,
)
from db.skeleton_models import (
    MessageSkeletonModel,
    TUPPER_ID_MAX,
    compute_skeleton_flags,
)
from db.scene_service import compute_scene_counts_from_skeletons, snowflake_int
from db.session import (
    get_engine,
    close_engine,
    close_all_engines,
    get_sqlite_path,
    get_skeleton_sqlite_path,
    has_db,
    has_skeleton_db,
    skeleton_db_session,
    get_db_schema_version,
    stamp_schema_version,
    sync_sqlite_db,
    invalidate_sqlite_tmp_cache,
)
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


def _find_data_channel_json_files(backup_path: Optional[str]) -> List[Path]:
    if not backup_path:
        return []
    data_dir = Path(backup_path) / "Data"
    if not data_dir.is_dir():
        return []
    files: List[Path] = []
    for p in data_dir.rglob("*.json"):
        if p.name.startswith("_") or p.name.endswith("_scenes.json"):
            continue
        files.append(p)
    return files


def _resolve_channel_json_path(backup_path: str, channel_rel_path: str) -> Optional[Path]:
    if not backup_path or not channel_rel_path:
        return None
    c_path = Path(channel_rel_path)
    for cand in (Path(backup_path) / "Data" / c_path, Path(backup_path) / c_path):
        if cand.is_file():
            return cand
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
        "events",
        "scenes",
        "scene_participants",
        "scene_issues",
        "message_overrides",
        "flagged_messages",
        "seen_discord_users",
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


def _populate_skeletons_and_collect_users(
    backup_id: str,
    backup_path: str,
    channels: List[ChannelModel],
    char_name_to_id: Dict[str, int],
    rebuild_skeletons: bool = True,
) -> Tuple[Dict[str, List[MessageSkeletonModel]], Dict[str, Dict[str, Any]]]:
    """
    Populates skeletons.sqlite from Data/*.json files when present,
    collects non-bot Discord users for seen_discord_users backfill,
    and updates ChannelModel.last_message_id / sync_status.
    """
    skeletons_by_channel: Dict[str, List[MessageSkeletonModel]] = {}
    seen_users_agg: Dict[str, Dict[str, Any]] = {}

    if not backup_path:
        return skeletons_by_channel, seen_users_agg

    json_exists_any = False
    for ch in channels:
        if ch.type == "GuildCategory" or not ch.path:
            continue
        f_path = _resolve_channel_json_path(backup_path, ch.path)
        if not f_path:
            continue
        json_exists_any = True

        try:
            chan_data = t.load_from_json(f_path.as_posix())
        except Exception as e:
            t.log("debug", f"Skipping unreadable channel JSON '{f_path}': {e}")
            continue

        raw_msgs = chan_data.get("messages", [])
        chan_id_str = str(ch.discord_id)
        chan_id_int = int(chan_id_str) if chan_id_str.isdigit() else 0
        ch_skels: List[MessageSkeletonModel] = []
        max_msg_id = 0
        latest_msg_dt: Optional[datetime] = None

        for m in raw_msgs:
            mid_str = str(m.get("id", "")).strip()
            if not mid_str.isdigit():
                continue
            mid_int = int(mid_str)
            if mid_int > max_msg_id:
                max_msg_id = mid_int

            msg_dt = parse_datetime(m.get("timestamp"))
            if msg_dt and (latest_msg_dt is None or msg_dt > latest_msg_dt):
                latest_msg_dt = msg_dt

            author = m.get("author") or {}
            raw_aid = author.get("id")
            resolved_aid = 0
            if raw_aid is not None and str(raw_aid).strip().isdigit():
                resolved_aid = int(str(raw_aid).strip())

            # Resolve Tupper character ID if author is a webhook/bot whose ID wasn't mapped yet
            is_bot_flag = bool(author.get("isBot", False)) or str(author.get("discriminator", "")) == "0000"
            if resolved_aid >= TUPPER_ID_MAX and is_bot_flag:
                a_name = str(author.get("name") or "").strip().lower()
                if a_name and a_name in char_name_to_id:
                    resolved_aid = char_name_to_id[a_name]

            flags = compute_skeleton_flags(m, author_id=resolved_aid)
            ts_unix = int(msg_dt.timestamp()) if msg_dt else 0

            ch_skels.append(
                MessageSkeletonModel(
                    channel_discord_id=chan_id_int,
                    message_id=mid_int,
                    author_id=resolved_aid,
                    timestamp_unix=ts_unix,
                    flags=flags,
                )
            )

            # Collect non-bot human Discord authors for seen_discord_users
            if resolved_aid >= TUPPER_ID_MAX and not is_bot_flag:
                aid_key = str(resolved_aid)
                uname = str(author.get("name") or f"User #{aid_key}")
                nick = author.get("nickname")
                entry = seen_users_agg.get(aid_key)
                if entry is None:
                    seen_users_agg[aid_key] = {
                        "discord_user_id": aid_key,
                        "username": uname,
                        "global_name": None,
                        "nickname": str(nick) if nick else None,
                        "message_count": 1,
                        "last_seen_at": msg_dt,
                    }
                else:
                    entry["message_count"] += 1
                    if nick:
                        entry["nickname"] = str(nick)
                    if msg_dt and (entry["last_seen_at"] is None or msg_dt > entry["last_seen_at"]):
                        entry["last_seen_at"] = msg_dt

        ch_skels.sort(key=lambda s: int(s.message_id))
        skeletons_by_channel[chan_id_str] = ch_skels

        if max_msg_id > 0 and not ch.last_message_id:
            ch.last_message_id = str(max_msg_id)
        if latest_msg_dt and not ch.last_synced_at:
            ch.last_synced_at = latest_msg_dt
        if raw_msgs:
            ch.sync_status = "synced"
            if ch.message_count is None:
                ch.message_count = len(raw_msgs)

    if rebuild_skeletons and json_exists_any:
        with skeleton_db_session(backup_id=backup_id, backup_path=backup_path) as skel_session:
            for chan_id_str, ch_skels in skeletons_by_channel.items():
                if not chan_id_str.isdigit():
                    continue
                chan_id_int = int(chan_id_str)
                skel_session.query(MessageSkeletonModel).filter(
                    MessageSkeletonModel.channel_discord_id == chan_id_int
                ).delete(synchronize_session=False)
                if ch_skels:
                    skel_session.bulk_save_objects(ch_skels)

    return skeletons_by_channel, seen_users_agg


def populate_schema(
    target_engine,
    data: Dict[str, List[Dict[str, Any]]],
    backup_id: str = "",
    old_version: int = 5,
    target_schema_version: int = CURRENT_SCHEMA_VERSION,
    backup_path: Optional[str] = None,
    build_skeletons: bool = False,
) -> Dict[str, int]:
    """
    Populates a fresh Schema v6 database from extracted data, resolving all foreign keys,
    backfilling SceneModel/SceneParticipantModel message_count, SeenDiscordUserModel,
    and optionally building skeletons.sqlite from Data/*.json.
    """
    metrics: Dict[str, int] = {
        "backups": 0,
        "channels": 0,
        "writers": 0,
        "writer_aliases": 0,
        "character_groups": 0,
        "group_names": 0,
        "characters": 0,
        "character_names": 0,
        "events": 0,
        "scenes": 0,
        "scene_participants": 0,
        "scene_issues": 0,
        "flagged_messages": 0,
        "seen_discord_users": 0,
    }

    has_data_jsons = bool(_find_data_channel_json_files(backup_path))
    inferred_storage_mode = StorageMode.FULL.value if has_data_jsons else StorageMode.BACKUPLESS.value

    exports_list = data.get("exports", [])
    export_by_pk: Dict[int, Dict[str, Any]] = {e["pk"]: e for e in exports_list if "pk" in e}
    base_export_by_backup: Dict[str, Dict[str, Any]] = {}
    for e in exports_list:
        bid = str(e.get("backup_id", ""))
        if not bid:
            continue
        if bid not in base_export_by_backup or str(e.get("scope", "")) == "base":
            base_export_by_backup[bid] = e

    with Session(target_engine) as session:
        # 0. Schema Version
        stamp_schema_version(session, target_schema_version, description="Upgraded schema to v6")

        # 1. Backups
        for b in data.get("backups", []):
            b_id = str(b["backup_id"])
            base_exp = base_export_by_backup.get(b_id)
            last_synced = parse_datetime(b.get("last_synced_at"))
            if last_synced is None and base_exp:
                last_synced = parse_datetime(base_exp.get("updated_at") or base_exp.get("exported_at"))

            storage_mode = b.get("storage_mode") or inferred_storage_mode
            sync_status = b.get("sync_status") or SyncStatus.IDLE.value

            session.add(BackupModel(
                backup_id=b_id,
                backup_name=str(b["backup_name"]),
                server_id=str(b.get("server_id")) if b.get("server_id") else None,
                server_name=str(b.get("server_name")) if b.get("server_name") else None,
                created_at=parse_datetime(b.get("created_at")),
                storage_mode=str(storage_mode),
                sync_status=str(sync_status),
                sync_started_at=parse_datetime(b.get("sync_started_at")),
                last_synced_at=last_synced,
                sync_error=b.get("sync_error"),
                channels_total=int(b.get("channels_total") or 0),
                channels_done=int(b.get("channels_done") or 0),
            ))
            metrics["backups"] += 1
        session.flush()

        # 2. Channels (Schema v6: direct backup_id FK; migrate base scope channels from v1-v5)
        chan_pk_map: Dict[int, int] = {}
        created_channels: List[ChannelModel] = []
        seen_backup_discord: Set[Tuple[str, str]] = set()
        chan_by_backup_discord: Dict[Tuple[str, str], int] = {}

        all_chans = data.get("channels", [])
        categories = [c_row for c_row in all_chans if c_row.get("parent_pk") is None or c_row.get("type") == "GuildCategory"]
        other_chans = [c_row for c_row in all_chans if c_row not in categories]
        text_chans = [c_row for c_row in other_chans if c_row.get("type") != "GuildPublicThread"]
        threads = [c_row for c_row in other_chans if c_row.get("type") == "GuildPublicThread"]

        for c_group in (categories, text_chans, threads):
            for c_row in c_group:
                old_pk = c_row["pk"]
                c_backup_id = c_row.get("backup_id")
                if c_backup_id:
                    c_backup_id = str(c_backup_id)
                else:
                    exp = export_by_pk.get(c_row.get("export_pk"))
                    if not exp:
                        continue
                    c_backup_id = str(exp["backup_id"])
                    # Skip 'update' scope duplicate channel rows when upgrading from v1-v5
                    if str(exp.get("scope", "base")) != "base":
                        continue

                d_id = str(c_row["discord_id"])
                if (c_backup_id, d_id) in seen_backup_discord:
                    if (c_backup_id, d_id) in chan_by_backup_discord:
                        chan_pk_map[old_pk] = chan_by_backup_discord[(c_backup_id, d_id)]
                    continue
                seen_backup_discord.add((c_backup_id, d_id))

                parent_pk = chan_pk_map.get(c_row.get("parent_pk")) if c_row.get("parent_pk") is not None else None
                base_exp = base_export_by_backup.get(c_backup_id)
                inferred_sync_status = c_row.get("sync_status") or (
                    "synced" if (c_row.get("message_count") is not None or base_exp is not None) else "pending"
                )
                inferred_chan_synced = parse_datetime(c_row.get("last_synced_at")) or (
                    parse_datetime(base_exp.get("updated_at") or base_exp.get("exported_at")) if base_exp else None
                )

                chan = ChannelModel(
                    backup_id=c_backup_id,
                    discord_id=d_id,
                    type=str(c_row["type"]),
                    parent_pk=parent_pk,
                    name=str(c_row.get("name", "")),
                    position=int(c_row.get("position", 0)),
                    path=str(c_row.get("path", "")),
                    is_deleted=bool(c_row.get("is_deleted", False)),
                    message_count=c_row.get("message_count"),
                    last_message_id=str(c_row["last_message_id"]) if c_row.get("last_message_id") else None,
                    last_synced_at=inferred_chan_synced,
                    sync_status=str(inferred_sync_status),
                    sync_error=c_row.get("sync_error"),
                )
                session.add(chan)
                session.flush()
                chan_pk_map[old_pk] = chan.pk
                chan_by_backup_discord[(c_backup_id, d_id)] = chan.pk
                created_channels.append(chan)
                metrics["channels"] += 1

        # 3. Writers & Aliases
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

        # 4. Character Groups & Names
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

        # 5. Characters (ordered: top-level first, then children)
        char_pk_map: Dict[int, int] = {}
        char_pk_to_cid: Dict[int, int] = {}
        char_name_to_id: Dict[str, int] = {}

        top_chars = [c_row for c_row in data.get("characters", []) if c_row.get("parent_pk") is None]
        child_chars = [c_row for c_row in data.get("characters", []) if c_row.get("parent_pk") is not None]

        for c_row in top_chars:
            old_pk = c_row["pk"]
            char = CharacterModel(
                backup_id=str(c_row["backup_id"]),
                char_id=int(c_row["char_id"]),
                writer_pk=writer_pk_map.get(c_row.get("writer_pk")),
                group_pk=group_pk_map.get(c_row.get("group_pk")),
                parent_pk=None,
                version_type=c_row.get("version_type"),
                origin=c_row.get("origin"),
                activity=c_row.get("activity"),
            )
            session.add(char)
            session.flush()
            char_pk_map[old_pk] = char.pk
            char_pk_to_cid[char.pk] = char.char_id
            metrics["characters"] += 1

        for c_row in child_chars:
            old_pk = c_row["pk"]
            char = CharacterModel(
                backup_id=str(c_row["backup_id"]),
                char_id=int(c_row["char_id"]),
                writer_pk=writer_pk_map.get(c_row.get("writer_pk")),
                group_pk=group_pk_map.get(c_row.get("group_pk")),
                parent_pk=char_pk_map.get(c_row.get("parent_pk")),
                version_type=c_row.get("version_type"),
                origin=c_row.get("origin"),
                activity=c_row.get("activity"),
            )
            session.add(char)
            session.flush()
            char_pk_map[old_pk] = char.pk
            char_pk_to_cid[char.pk] = char.char_id
            metrics["characters"] += 1

        for cn in data.get("character_names", []):
            new_c_pk = char_pk_map.get(cn["character_pk"])
            if not new_c_pk:
                continue
            cname = str(cn["name"])
            session.add(CharacterNameModel(
                character_pk=new_c_pk,
                name=cname,
                position=int(cn.get("position", 0)),
            ))
            if new_c_pk in char_pk_to_cid:
                char_name_to_id.setdefault(cname.strip().lower(), char_pk_to_cid[new_c_pk])
            metrics["character_names"] += 1
        session.flush()

        char_id_to_pk = {cid: cpk for cpk, cid in char_pk_to_cid.items()}

        # 6. Flagged Messages & Overrides (unified into FlaggedMessageModel)
        overrides_by_mid = {str(o["message_id"]): o for o in data.get("message_overrides", [])}
        processed_mids: Set[str] = set()
        resolved_flags_map: Dict[str, Dict[str, Any]] = {}
        flagged_authors_for_seen: List[Tuple[str, Dict[str, Any], Optional[datetime]]] = []

        def _compute_override_flags_if_needed(
            o_content: Optional[str],
            o_author: Any,
            existing_flags: Optional[int],
        ) -> Optional[int]:
            if existing_flags is not None:
                return int(existing_flags)
            if o_content is None:
                return None
            aid_val = None
            if isinstance(o_author, dict) and str(o_author.get("id", "")).strip().isdigit():
                aid_val = int(str(o_author["id"]).strip())
            return compute_skeleton_flags(
                {"type": "Default", "content": o_content, "author": o_author or {}},
                author_id=aid_val,
            )

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

            flagged_at_dt = parse_datetime(f.get("flagged_at")) or datetime.now(timezone.utc)
            if isinstance(f.get("author"), dict):
                flagged_authors_for_seen.append((str(f["backup_id"]), f["author"], flagged_at_dt))

            if mid in overrides_by_mid:
                o = overrides_by_mid[mid]
                o_chan_pk = chan_pk_map.get(o.get("channel_pk")) if o.get("channel_pk") is not None else new_chan_pk
                o_content = str(o["content"])
                o_author = o.get("author", {})
                o_flags = _compute_override_flags_if_needed(o_content, o_author, None)
                fm = FlaggedMessageModel(
                    backup_id=str(f["backup_id"]),
                    message_id=mid,
                    channel_pk=o_chan_pk,
                    kind=migrated_kind,
                    content=str(f["content"]),
                    is_excerpt_truncated=bool(f.get("is_excerpt_truncated", False)),
                    author=f.get("author", {}),
                    flagged_at=flagged_at_dt,
                    resolution=FlaggedResolution.OVERRIDE.value,
                    override_content=o_content,
                    override_author=o_author,
                    override_flags=o_flags,
                    resolved_at=parse_datetime(o.get("created_at")) or datetime.now(timezone.utc),
                    resolved_note="Migrated from message_overrides",
                )
            else:
                res_val = f.get("resolution")
                o_content = f.get("override_content")
                o_author = f.get("override_author")
                o_flags = (
                    _compute_override_flags_if_needed(o_content, o_author, f.get("override_flags"))
                    if res_val == FlaggedResolution.OVERRIDE.value
                    else None
                )
                fm = FlaggedMessageModel(
                    backup_id=str(f["backup_id"]),
                    message_id=mid,
                    channel_pk=new_chan_pk,
                    kind=migrated_kind,
                    content=str(f["content"]),
                    is_excerpt_truncated=bool(f.get("is_excerpt_truncated", False)),
                    author=f.get("author", {}),
                    flagged_at=flagged_at_dt,
                    resolution=res_val,
                    override_content=o_content,
                    override_author=o_author,
                    override_flags=o_flags,
                    resolved_at=parse_datetime(f.get("resolved_at")),
                    resolved_note=f.get("resolved_note"),
                )

            session.add(fm)
            if fm.resolved_at is not None:
                resolved_flags_map[mid] = {
                    "resolution": fm.resolution,
                    "override_content": fm.override_content,
                    "override_author": fm.override_author,
                    "override_flags": fm.override_flags,
                }
            processed_mids.add(mid)
            metrics["flagged_messages"] += 1

        for mid, o in overrides_by_mid.items():
            if mid in processed_mids:
                continue
            new_chan_pk = chan_pk_map.get(o.get("channel_pk")) if o.get("channel_pk") is not None else None
            o_content = str(o["content"])
            o_author = o.get("author", {})
            o_flags = _compute_override_flags_if_needed(o_content, o_author, None)
            created_dt = parse_datetime(o.get("created_at")) or datetime.now(timezone.utc)
            fm = FlaggedMessageModel(
                backup_id=str(o["backup_id"]),
                message_id=mid,
                channel_pk=new_chan_pk,
                kind=FlaggedKind.FAILED_TUPPER.value,
                content=o_content,
                is_excerpt_truncated=False,
                author=o_author,
                flagged_at=created_dt,
                resolution=FlaggedResolution.OVERRIDE.value,
                override_content=o_content,
                override_author=o_author,
                override_flags=o_flags,
                resolved_at=created_dt,
                resolved_note="Migrated from message_overrides",
            )
            session.add(fm)
            resolved_flags_map[mid] = {
                "resolution": fm.resolution,
                "override_content": fm.override_content,
                "override_author": fm.override_author,
                "override_flags": fm.override_flags,
            }
            processed_mids.add(mid)
            metrics["flagged_messages"] += 1
        session.flush()

        # 7. Populate skeletons.sqlite from Data/*.json (when build_skeletons=True and Data/*.json exist)
        skeletons_by_channel: Dict[str, List[MessageSkeletonModel]] = {}
        seen_users_from_json: Dict[str, Dict[str, Any]] = {}
        if build_skeletons and backup_path:
            skeletons_by_channel, seen_users_from_json = _populate_skeletons_and_collect_users(
                backup_id=backup_id,
                backup_path=backup_path,
                channels=created_channels,
                char_name_to_id=char_name_to_id,
                rebuild_skeletons=(old_version < CURRENT_SCHEMA_VERSION or not has_skeleton_db(backup_path, backup_id=backup_id)),
            )
            if not skeletons_by_channel and has_skeleton_db(backup_path, backup_id=backup_id):
                # Load existing skeletons to recompute missing scene counts if needed
                with skeleton_db_session(backup_id=backup_id, backup_path=backup_path) as skel_session:
                    for ch in created_channels:
                        if ch.type == "GuildCategory" or not str(ch.discord_id).isdigit():
                            continue
                        rows = (
                            skel_session.query(MessageSkeletonModel)
                            .filter(MessageSkeletonModel.channel_discord_id == int(ch.discord_id))
                            .order_by(MessageSkeletonModel.message_id.asc())
                            .all()
                        )
                        skel_session.expunge_all()
                        if rows:
                            skeletons_by_channel[str(ch.discord_id)] = rows

        # 8. Events
        event_pk_map: Dict[int, int] = {}
        for ev in data.get("events", []):
            old_pk = ev["pk"]
            ev_model = EventModel(
                backup_id=str(ev["backup_id"]),
                event_key=str(ev["event_key"]),
                name=ev.get("name"),
                status=str(ev.get("status") or "open"),
                start_at=parse_datetime(ev["start_at"]) or datetime.now(timezone.utc),
                end_at=parse_datetime(ev["end_at"]) or datetime.now(timezone.utc),
                message_count=int(ev.get("message_count", 0)),
                is_curated=bool(ev.get("is_curated", False)),
                character_movements=ev.get("character_movements"),
            )
            session.add(ev_model)
            session.flush()
            event_pk_map[old_pk] = ev_model.pk
            metrics["events"] += 1

        # 9. Scenes & Participants (backfilling persisted message_count)
        chan_pk_to_discord = {ch.pk: ch.discord_id for ch in created_channels}
        scene_pk_map: Dict[int, int] = {}
        scene_part_counts_map: Dict[Tuple[int, int], int] = {}

        for s in data.get("scenes", []):
            old_pk = s["pk"]
            new_chan_pk = chan_pk_map.get(s["channel_pk"])
            new_cat_pk = chan_pk_map.get(s["category_pk"])
            if not new_chan_pk or not new_cat_pk:
                continue

            start_mid = str(s["start_message_id"])
            end_mid = str(s["end_message_id"])
            s_idx = s.get("start_index")
            e_idx = s.get("end_index")
            chan_discord = chan_pk_to_discord.get(new_chan_pk, "")
            ch_skels = skeletons_by_channel.get(chan_discord, [])

            scene_msg_count = s.get("message_count")
            if ch_skels and str(start_mid).isdigit() and str(end_mid).isdigit():
                s_sf = int(start_mid)
                e_sf = int(end_mid)
                slice_skels = [sk for sk in ch_skels if s_sf <= int(sk.message_id) <= e_sf]
                if slice_skels:
                    computed_count, computed_parts = compute_scene_counts_from_skeletons(
                        slice_skels, char_id_to_pk, resolved_flags_map=resolved_flags_map
                    )
                    if scene_msg_count is None or old_version < CURRENT_SCHEMA_VERSION:
                        scene_msg_count = computed_count
                    for cp in computed_parts:
                        scene_part_counts_map[(old_pk, cp["character_pk"])] = cp["message_count"]

            if scene_msg_count is None:
                if s_idx is not None and e_idx is not None:
                    scene_msg_count = max(0, int(e_idx) - int(s_idx) + 1)
                else:
                    scene_msg_count = 0

            scene = SceneModel(
                backup_id=str(s["backup_id"]),
                scene_key=str(s["scene_key"]),
                channel_pk=new_chan_pk,
                category_pk=new_cat_pk,
                event_pk=event_pk_map.get(s.get("event_pk")) if s.get("event_pk") is not None else None,
                custom_name=s.get("custom_name"),
                kind=str(s.get("kind") or "scene"),
                status=str(s["status"]),
                start_message_id=start_mid,
                end_message_id=end_mid,
                start_index=int(s_idx) if s_idx is not None else 0,
                end_index=int(e_idx) if e_idx is not None else 0,
                message_count=int(scene_msg_count),
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

        seen_parts: Set[Tuple[int, int]] = set()
        for p in data.get("scene_participants", []):
            old_s_pk = p["scene_pk"]
            new_s_pk = scene_pk_map.get(old_s_pk)
            new_c_pk = char_pk_map.get(p["character_pk"])
            if new_s_pk and new_c_pk and (new_s_pk, new_c_pk) not in seen_parts:
                seen_parts.add((new_s_pk, new_c_pk))
                p_msg_count = p.get("message_count")
                if p_msg_count is None or old_version < CURRENT_SCHEMA_VERSION:
                    p_msg_count = scene_part_counts_map.get((old_s_pk, new_c_pk), p_msg_count or 1)
                session.add(SceneParticipantModel(
                    scene_pk=new_s_pk,
                    character_pk=new_c_pk,
                    position=int(p.get("position", 0)),
                    message_count=int(p_msg_count or 1),
                    first_message_id=str(p["first_message_id"]) if p.get("first_message_id") else None,
                    first_at=parse_datetime(p.get("first_at")),
                    last_message_id=str(p["last_message_id"]) if p.get("last_message_id") else None,
                    last_at=parse_datetime(p.get("last_at")),
                ))
                metrics["scene_participants"] += 1
        session.flush()

        # 10. Scene Issues
        for iss in data.get("scene_issues", []):
            new_s_pk = scene_pk_map.get(iss.get("scene_pk")) if iss.get("scene_pk") is not None else None
            new_next_s_pk = scene_pk_map.get(iss.get("next_scene_pk")) if iss.get("next_scene_pk") is not None else None
            raw_kind = str(iss["kind"])
            migrated_kind = "soft_boundary" if raw_kind == "possible_split" else raw_kind
            raw_res = iss.get("resolution")
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

        # 11. Seen Discord Users backfill (existing + JSON harvest + FlaggedMessageModel.author)
        seen_users_merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for su in data.get("seen_discord_users", []):
            key = (str(su["backup_id"]), str(su["discord_user_id"]))
            seen_users_merged[key] = {
                "backup_id": key[0],
                "discord_user_id": key[1],
                "username": str(su["username"]),
                "global_name": su.get("global_name"),
                "nickname": su.get("nickname"),
                "is_current_member": bool(su.get("is_current_member", False)),
                "message_count": int(su.get("message_count") or 0),
                "last_seen_at": parse_datetime(su.get("last_seen_at")),
            }

        target_bid = backup_id or (str(data["backups"][0]["backup_id"]) if data.get("backups") else "")
        for aid_key, info in seen_users_from_json.items():
            key = (target_bid, aid_key)
            if key not in seen_users_merged:
                seen_users_merged[key] = {
                    "backup_id": target_bid,
                    "discord_user_id": aid_key,
                    "username": info["username"],
                    "global_name": info.get("global_name"),
                    "nickname": info.get("nickname"),
                    "is_current_member": False,
                    "message_count": info["message_count"],
                    "last_seen_at": info["last_seen_at"],
                }
            else:
                cur = seen_users_merged[key]
                cur["message_count"] = max(cur["message_count"], info["message_count"])
                if not cur.get("nickname") and info.get("nickname"):
                    cur["nickname"] = info["nickname"]

        for fb_id, author_dict, flagged_dt in flagged_authors_for_seen:
            raw_aid = str(author_dict.get("id") or "").strip()
            if not raw_aid.isdigit():
                continue
            if int(raw_aid) < TUPPER_ID_MAX or bool(author_dict.get("isBot")):
                continue
            key = (fb_id, raw_aid)
            uname = str(author_dict.get("name") or f"User #{raw_aid}")
            nick = author_dict.get("nickname")
            if key not in seen_users_merged:
                seen_users_merged[key] = {
                    "backup_id": fb_id,
                    "discord_user_id": raw_aid,
                    "username": uname,
                    "global_name": None,
                    "nickname": str(nick) if nick else None,
                    "is_current_member": False,
                    "message_count": 1,
                    "last_seen_at": flagged_dt,
                }
            else:
                cur = seen_users_merged[key]
                if not cur.get("username") and uname:
                    cur["username"] = uname
                if not cur.get("nickname") and nick:
                    cur["nickname"] = str(nick)
                if cur["message_count"] == 0:
                    cur["message_count"] = 1

        for item in seen_users_merged.values():
            if not item["backup_id"]:
                continue
            session.add(SeenDiscordUserModel(**item))
            metrics["seen_discord_users"] += 1

        session.commit()

    return metrics


_copy_all_data = populate_schema


def upgrade_single_backup(
    backup: dict,
    dry_run: bool = False,
    reindex_scenes: bool = False,
) -> Dict[str, Any]:
    """
    Upgrades a single backup database to CURRENT_SCHEMA_VERSION (v6).
    Preserves all curated writers, characters, groups, overrides, and scene decisions,
    populates skeletons.sqlite when Data/*.json exist, and rolls back both SQLite files on failure.
    """
    backup_id = str(backup["backup_id"])
    backup_name = str(backup["backup_name"])
    backup_path = (Path(c.DATA_ROOT) / backup["path"]).as_posix()
    sqlite_path = get_sqlite_path(backup_path)
    skel_path = get_skeleton_sqlite_path(backup_path)

    t.log("info", f"\n=======================================================")
    t.log("info", f"Upgrading database for backup '{backup_name}' (ID: {backup_id})")
    t.log("info", f"Path: {sqlite_path}")
    t.log("info", f"Dry Run: {dry_run}")
    t.log("info", f"=======================================================\n")

    if not has_db(backup_path, backup_id=backup_id):
        raise exc.DatabaseConnectionError(f"Database not found at '{sqlite_path}'. Run migration first.")

    # 1. Inspect source database and version
    source_engine = get_engine(backup_id=backup_id, backup_path=backup_path)
    is_sqlite = source_engine.dialect.name == "sqlite"
    if is_sqlite and not os.path.exists(sqlite_path) and not os.environ.get("DATABASE_URL"):
        raise exc.DatabaseConnectionError(f"Database not found at '{sqlite_path}'. Run migration first.")
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
        t.log("info", "[DRY-RUN] Simulating schema upgrade in-memory...")
        mem_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=mem_engine)

        metrics = populate_schema(
            mem_engine,
            extracted_data,
            backup_id,
            old_version,
            backup_path=backup_path,
            build_skeletons=False,
        )
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

    # 3. Create safety backup copies of backup.sqlite and skeletons.sqlite (if present)
    bak_path = f"{sqlite_path}.bak"
    skel_bak_path = f"{skel_path}.bak"
    skel_existed_before = is_sqlite and bool(skel_path) and os.path.exists(skel_path)
    close_all_engines()
    if is_sqlite and os.path.exists(sqlite_path):
        t.log("info", f"Creating safety database backup at: {bak_path}")
        shutil.copyfile(sqlite_path, bak_path)
    if skel_existed_before:
        shutil.copyfile(skel_path, skel_bak_path)

    try:
        # 4. Rebuild schema cleanly using SQLAlchemy reflection and Base.metadata
        t.log("info", "Rebuilding database schema...")
        engine = get_engine(backup_id=backup_id, backup_path=backup_path)
        existing_meta = MetaData()
        existing_meta.reflect(bind=engine)
        existing_meta.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        # 5. Populate new schema with preserved data + skeletons.sqlite
        t.log("info", "Repopulating tables with preserved data...")
        metrics = populate_schema(
            engine,
            extracted_data,
            backup_id,
            old_version,
            backup_path=backup_path,
            build_skeletons=True,
        )
        new_version = get_db_schema_version(engine)
        t.log("base", f"Successfully upgraded schema to version {new_version}!")

        # 6. Optional Reindex
        if reindex_scenes:
            t.log("info", "Re-indexing scenes as requested...")
            try:
                from index_scenes import index_scenes
                index_scenes(backup_id=backup_id, backup_path=backup_path)
            except Exception as e:
                t.log("error", f"Scene re-indexing failed: {exc.unwrap(e)}")
                raise

        # 7. Post-upgrade Snapshots
        try:
            with Session(engine) as s:
                export_character_list_snapshot(s, backup_id)
                export_backup_info_snapshot(s, backup_id)
        except Exception as e:
            t.log("debug", f"Post-upgrade snapshot note: {e}")

        # 8. Force sync upgraded DBs to GCS when /tmp cache is enabled, and clean up safety backups
        if is_sqlite:
            sync_sqlite_db(backup_id=backup_id, backup_path=backup_path, force=True)
            for bkup_file in (bak_path, skel_bak_path):
                if os.path.exists(bkup_file):
                    try:
                        os.remove(bkup_file)
                    except OSError:
                        pass

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
        close_engine(backup_id=backup_id, backup_path=backup_path, sync=False, invalidate_cache=True)
        close_all_engines()
        if is_sqlite:
            for p in (
                f"{sqlite_path}-wal",
                f"{sqlite_path}-shm",
                f"{skel_path}-wal",
                f"{skel_path}-shm",
            ):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            if os.path.exists(bak_path):
                t.log("info", f"Restoring safety backup from {bak_path}...")
                shutil.copyfile(bak_path, sqlite_path)
                try:
                    os.remove(bak_path)
                except OSError:
                    pass
            if skel_existed_before and os.path.exists(skel_bak_path):
                shutil.copyfile(skel_bak_path, skel_path)
                try:
                    os.remove(skel_bak_path)
                except OSError:
                    pass
            elif not skel_existed_before and skel_path and os.path.exists(skel_path):
                try:
                    os.remove(skel_path)
                except OSError:
                    pass
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
        if not has_db(backup_path, backup_id=str(b["backup_id"])):
            t.log("info", f"Skipping '{b['backup_name']}': no database present.")
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

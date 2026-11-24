from datetime import datetime, timezone
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import utils.tricks as t
import utils.exceptions as exc
from utils.path_safety import category_matches, expand_category_names
from find_character_scenes import (
    has_end_tag,
    has_start_tag,
    MENTION_ONLY_PAT,
)
from models import ServerBackup, Step
from db.models import FlaggedKind, FlaggedResolution, SceneStatus, IssueKind
from db.skeleton_models import (
    EXCERPT_MAX_LEN,
    MessageSkeletonModel,
    SkeletonFlags,
    compute_skeleton_flags,
)
from db.scene_service import resolve_effective_skeleton
from db import curation_service

t.set_path()
from res import constants as c

"""
Non-destructive preprocessing, skeleton flag computation, and flagging for Discord messages.
Raw JSON files and `skeletons.sqlite` rows are NEVER mutated by curation overrides:
  - Ignored messages are filtered out in memory.
  - Overridden messages have their author/flags/content overlaid in memory.
  - Unattributed non-tupper messages are flagged into `flagged_messages` with 250-char excerpts.
"""


def load_status() -> ServerBackup:
    """Loads backup information and checks if it's ready to work with."""
    try:
        backup = ServerBackup.load(scope="base")
        if backup.is_other_step_running(Step.FIX_MESSAGES):
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        if not backup.can_fix_messages():
            raise exc.DataNotReadyError(
                "The data may be corrupted or incomplete. Ensure the download is verified and IDs are assigned and try again."
            )
        t.log("debug", f"  The current status of the backup is '{backup.status}'\n")
        backup.start_fix_messages()
        t.log("debug", "  Backup info file is ready.\n")
    except (exc.DataNotReadyError, exc.AlreadyRunningError):
        raise
    except Exception as e:
        raise exc.FixMessagesError("The export status file could not be read") from e
    return backup


def prepare_channel_messages(
    messages: List[Dict[str, Any]],
    resolved_flags_map: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Prepares raw channel messages in memory for scene indexing without modifying disk:
    - Filters out non-Default messages (ThreadCreated, pins, joins).
    - Filters out messages matching MENTION_ONLY_PAT.
    - Filters out messages marked as 'ignored' in resolved_flags_map.
    - Overlays override_content and override_author in memory for messages marked as 'override'.
    - Preserves 'raw_index': i on each prepared message.
    """
    prepared: List[Dict[str, Any]] = []

    for i, msg in enumerate(messages):
        if msg.get("type") != "Default":
            continue

        content = str(msg.get("content", "") or "")
        if MENTION_ONLY_PAT.match(content.strip()):
            continue

        msg_id = str(msg.get("id", ""))
        flag_info = resolved_flags_map.get(msg_id)

        if flag_info:
            res = flag_info.get("resolution") if isinstance(flag_info, dict) else getattr(flag_info, "resolution", None)
            if res == FlaggedResolution.IGNORED.value:
                continue
            elif res == FlaggedResolution.OVERRIDE.value:
                m_copy = dict(msg)
                m_copy["raw_index"] = i
                o_content = flag_info.get("override_content") if isinstance(flag_info, dict) else getattr(flag_info, "override_content", None)
                o_author = flag_info.get("override_author") if isinstance(flag_info, dict) else getattr(flag_info, "override_author", None)
                if o_content is not None:
                    m_copy["content"] = o_content
                if o_author is not None:
                    m_copy["author"] = o_author
                prepared.append(m_copy)
                continue

        m_copy = dict(msg)
        m_copy["raw_index"] = i
        prepared.append(m_copy)

    return prepared


def prepare_channel_skeletons(
    skeletons: List[Any],
    resolved_flags_map: Optional[Dict[str, Any]] = None,
    excerpts_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """
    Prepares MessageSkeletonModel rows purely in memory for scene/session/event indexers
    by applying `resolve_effective_skeleton` overlays (`ignored` excluded, `override` patched)
    without mutating `skeletons.sqlite`.
    """
    flags_map = resolved_flags_map or {}
    exc_map = excerpts_map or {}
    prepared: List[Dict[str, Any]] = []

    for raw_idx, sk in enumerate(skeletons):
        eff = resolve_effective_skeleton(sk, resolved_flags_map=flags_map)
        if eff is None or not eff["is_valid"]:
            continue

        mid_str = eff["message_id_str"]
        flag_info = flags_map.get(mid_str)
        o_content = None
        if flag_info:
            res = flag_info.get("resolution") if isinstance(flag_info, dict) else getattr(flag_info, "resolution", None)
            if res == FlaggedResolution.OVERRIDE.value:
                o_content = (
                    flag_info.get("override_content")
                    if isinstance(flag_info, dict)
                    else getattr(flag_info, "override_content", None)
                )

        if o_content is not None:
            excerpt = str(o_content)
        else:
            excerpt = exc_map.get(mid_str, "")

        ts_dt = eff["timestamp_dt"]
        eff["raw_index"] = raw_idx
        eff["id"] = mid_str
        eff["timestamp"] = ts_dt.isoformat() if ts_dt else ""
        eff["author"] = {"id": str(eff["author_id"])}
        eff["content"] = excerpt
        eff["type"] = "Default"
        prepared.append(eff)

    return prepared


FAILED_TUPPER_PAT = re.compile(r"^\s*[\w\-]+:(?!//)")


def is_failed_tupper(content: str) -> bool:
    """Detects whether a message starts with a word (no spaces) followed by a colon."""
    if not content:
        return False
    return bool(FAILED_TUPPER_PAT.match(content))


def collect_channel_flagged_messages(
    raw_messages: List[Dict[str, Any]],
    channel_id: str,
    scenes: List[Dict[str, Any]],
    preserved_msg_ids: Set[str],
) -> List[Dict[str, Any]]:
    """
    Collects unattributed non-tupper messages from a channel into flagged review queue items.
    Always stores head+tail 250-char excerpt (`t.format_excerpt`) and `is_excerpt_truncated`.
    """
    scene_start_ids: Set[str] = set()
    scene_end_ids: Set[str] = set()
    auto_split_anchor_ids: Set[str] = set()
    closed_end_ids: Set[str] = set()
    start_header_ids: Set[str] = set()

    for sc in scenes:
        s_id = sc.get("start", {}).get("id")
        e_id = sc.get("end", {}).get("id")
        if s_id:
            s_id_str = str(s_id)
            scene_start_ids.add(s_id_str)
            if has_start_tag(sc.get("start", {}).get("content", "")):
                start_header_ids.add(s_id_str)
        if e_id:
            e_id_str = str(e_id)
            scene_end_ids.add(e_id_str)
            if sc.get("status") == SceneStatus.CLOSED.value and has_end_tag(sc.get("end", {}).get("content", "")):
                closed_end_ids.add(e_id_str)

        for iss in sc.get("issues", []):
            if iss.get("kind") == IssueKind.AUTO_SPLIT.value and iss.get("candidate_id"):
                auto_split_anchor_ids.add(str(iss["candidate_id"]))

    flagged_items: List[Dict[str, Any]] = []
    seen_first_tupper = False

    for msg in raw_messages:
        msg_id = str(msg.get("id", ""))
        aid = t.get_author_id(msg)

        if t.is_tupper(aid):
            seen_first_tupper = True
            continue

        if msg_id in preserved_msg_ids:
            continue

        if msg.get("type") != "Default":
            continue

        content = str(msg.get("content", "") or "")
        if MENTION_ONLY_PAT.match(content.strip()):
            continue

        if msg_id in closed_end_ids:
            continue

        if msg_id in start_header_ids:
            continue

        if not seen_first_tupper and len(msg.get("attachments", [])) > 0 and not has_start_tag(content) and not has_end_tag(content):
            continue

        if is_failed_tupper(content):
            kind = FlaggedKind.FAILED_TUPPER.value
        elif msg_id in scene_start_ids or msg_id in scene_end_ids or msg_id in auto_split_anchor_ids:
            kind = FlaggedKind.OOC_BOUNDARY.value
        else:
            kind = FlaggedKind.OOC_MESSAGE.value

        flagged_items.append({
            "message_id": msg_id,
            "channel_discord_id": str(channel_id),
            "kind": kind,
            "content": t.format_excerpt(content),
            "is_excerpt_truncated": len(content) > EXCERPT_MAX_LEN,
            "author": msg.get("author", {}),
        })

    return flagged_items


def build_skeletons_from_messages(
    messages: List[Dict[str, Any]],
    channel_discord_id: str,
) -> List[MessageSkeletonModel]:
    """
    Computes immutable 14-bit `MessageSkeletonModel` rows from raw/attributed messages.
    `flags` ALWAYS reflects the original message (never mutated by curation overrides).
    """
    if not str(channel_discord_id).isdigit():
        return []
    chan_id_int = int(channel_discord_id)
    rows: List[MessageSkeletonModel] = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        mid_str = str(msg.get("id", "")).strip()
        if not mid_str.isdigit():
            continue
        aid = t.get_author_id(msg)
        resolved_aid = int(aid) if aid is not None else 0
        dt = t.parse_datetime(msg.get("timestamp"))
        ts_unix = int(dt.timestamp()) if dt else 0
        flags = compute_skeleton_flags(msg, author_id=resolved_aid)

        rows.append(
            MessageSkeletonModel(
                channel_discord_id=chan_id_int,
                message_id=int(mid_str),
                author_id=resolved_aid,
                timestamp_unix=ts_unix,
                flags=flags,
            )
        )

    rows.sort(key=lambda r: int(r.message_id))
    return rows


def prepare_channel_messages_for_sync(
    messages: List[Dict[str, Any]],
    backup_id: str,
    channel_pk: Optional[int],
    is_full_mode: bool,
    existing_flagged_map: Optional[Dict[str, Any]] = None,
    *,
    channel_discord_id: str = "",
    scenes: Optional[List[Dict[str, Any]]] = None,
    preserved_msg_ids: Optional[Set[str]] = None,
    is_chatroom: bool = False,
    is_event: bool = False,
) -> Tuple[List[MessageSkeletonModel], List[Dict[str, Any]], Dict[str, int]]:
    """
    Sync-time message preparation:
      1. Computes original 14-bit `MessageSkeletonModel` rows (immutable to overrides).
      2. Detects unattributed non-tupper messages (`failed_tupper`, `ooc_boundary`, `ooc_message`)
         storing 250-char head+tail excerpts via `format_excerpt` and `is_excerpt_truncated`.
      3. Computes `override_flags` for any existing overridden messages lacking cached flags.
    """
    _ = (backup_id, channel_pk, is_full_mode)  # kept in signature for caller clarity
    skeletons = build_skeletons_from_messages(messages, channel_discord_id)

    flagged_items: List[Dict[str, Any]] = []
    if not is_chatroom and not is_event:
        flagged_items = collect_channel_flagged_messages(
            raw_messages=messages,
            channel_id=str(channel_discord_id),
            scenes=scenes or [],
            preserved_msg_ids=preserved_msg_ids or set(),
        )

    override_flags_updates: Dict[str, int] = {}
    if existing_flagged_map:
        for mid_str, flag_info in existing_flagged_map.items():
            res = flag_info.get("resolution") if isinstance(flag_info, dict) else getattr(flag_info, "resolution", None)
            if res != FlaggedResolution.OVERRIDE.value:
                continue
            o_content = flag_info.get("override_content") if isinstance(flag_info, dict) else getattr(flag_info, "override_content", None)
            o_flags = flag_info.get("override_flags") if isinstance(flag_info, dict) else getattr(flag_info, "override_flags", None)
            o_author = flag_info.get("override_author") if isinstance(flag_info, dict) else getattr(flag_info, "override_author", None)
            if o_content is not None and o_flags is None:
                o_aid = None
                if isinstance(o_author, dict) and str(o_author.get("id", "")).isdigit():
                    o_aid = int(o_author["id"])
                override_flags_updates[str(mid_str)] = compute_skeleton_flags(
                    {"type": "Default", "content": o_content, "author": o_author or {}},
                    author_id=o_aid,
                )

    return skeletons, flagged_items, override_flags_updates


def fix_bad_messages() -> None:
    """
    Non-destructive execution of message scanning and SQLite flagged message population.
    Reads channels without modifying files on disk.
    """
    backup = load_status()
    b_id = backup.backup_id or getattr(c, "BACKUP_ID", None)
    b_path = backup.path or getattr(c, "BACKUP_BASE", None)

    try:
        t.log("base", f"\n###  Scanning messages in {c.SERVER_NAME}...  ###\n")
        start_time = time.time()

        resolved_flags_map = curation_service.get_resolved_flags_map(b_id, b_path)
        preserved_msg_ids = curation_service.get_preserved_flagged_message_ids(b_id, b_path)

        t.log("info", f"    Loaded {len(resolved_flags_map)} active message resolutions\n")

        all_flagged: List[Dict[str, Any]] = []

        path_to_cat: Dict[str, Tuple[str, str]] = {}
        for cat in backup.categories:
            for p in cat.get_all_paths():
                path_to_cat[p] = (str(cat.id or ""), str(cat.name or ""))

        event_cat_targets = expand_category_names(getattr(c, "EVENT_CATEGORIES", []) or []) | {"events_category", "Events"}
        chatroom_cat_targets = expand_category_names(getattr(c, "CHATROOM_CATEGORIES", []) or [])

        for path in backup.get_all_paths():
            file_path = (Path(c.DATA_FOLDER) / path).as_posix()
            if not Path(file_path).is_file():
                continue
            t.log("log", f"\t    Analysing {file_path}...")
            raw_channel = t.load_from_json(file_path)
            cat_id, chan_cat = path_to_cat.get(path, ("", ""))
            raw_cat_id = str(raw_channel.get("channel", {}).get("categoryId") or "")
            raw_cat = str(raw_channel.get("channel", {}).get("category") or "")
            effective_cat_id = cat_id or raw_cat_id
            effective_cat_name = chan_cat or raw_cat
            if category_matches(effective_cat_id, effective_cat_name, chatroom_cat_targets):
                t.log("log", f"\t    Skipping chatroom category channel ({effective_cat_name}): {file_path}")
                continue
            if category_matches(effective_cat_id, effective_cat_name, event_cat_targets):
                t.log("log", f"\t    Skipping event category channel ({effective_cat_name}): {file_path}")
                continue
            raw_messages = raw_channel.get("messages", [])
            chan_id = raw_channel.get("channel", {}).get("id") or ""

            items = collect_channel_flagged_messages(
                raw_messages=raw_messages,
                channel_id=chan_id,
                scenes=[],
                preserved_msg_ids=preserved_msg_ids,
            )
            all_flagged.extend(items)

        curation_service.save_flagged_messages(
            backup_id=b_id,
            base_path=b_path,
            flagged_items=all_flagged,
            debug_files=c.DEBUG_FILES,
        )

        backup.save()
        backup.finish_fix_messages(success=True)

    except Exception as e:
        backup.finish_fix_messages(success=False)
        raise exc.FixMessagesError("Failed to fix bad messages in files") from e

    finally:
        t.log("base", f"### Finished scanning messages --- {time.time() - start_time:.2f} seconds --- ###\n")
        if "e" in locals() and e is not None:
            raise e


if __name__ == "__main__":
    try:
        fix_bad_messages()
    except KeyboardInterrupt:
        t.log("error", "\nProcess interrupted by user.\n")
        try:
            backup = ServerBackup.load(scope="base")
            if backup.is_updating():
                update = ServerBackup.load(scope="update")
                update.set_failed()
                backup.finish_update(success=False)
            else:
                backup.set_failed()
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
        sys.exit(1)

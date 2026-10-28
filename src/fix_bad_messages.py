import os
import sys
from pathlib import Path
import time
import re
from typing import Any, Dict, List, Optional, Set

import utils.tricks as t
import utils.exceptions as exc
from find_character_scenes import (
    has_end_tag,
    has_start_tag,
    MENTION_ONLY_PAT,
)
from models import ServerBackup, Step
from db.models import FlaggedKind, FlaggedResolution, SceneStatus, IssueKind
from db import curation_service

t.set_path()
from res import constants as c

################ File summary #################

"""
This module provides non-destructive preprocessing and flagging for Discord chatlog messages.
Raw JSON files on disk are NEVER mutated or deleted.
Messages are transformed in memory during pipeline processing according to SQLite curation decisions:
  - Ignored messages are filtered out.
  - Overridden messages have their author and content patched in memory.
  - Unattributed non-tupper messages are flagged and categorized into SQLite review queues.
"""

################ Functions #################

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
    Prepares channel messages in memory for scene indexing and processing without modifying disk.
    - Filters out non-Default messages (ThreadCreated, pins, joins).
    - Filters out messages matching MENTION_ONLY_PAT.
    - Filters out messages marked as 'ignored' in resolved_flags_map.
    - Overlays override_content and override_author in memory for messages marked as 'override'.
    """
    prepared: List[Dict[str, Any]] = []

    for msg in messages:
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
                o_content = flag_info.get("override_content") if isinstance(flag_info, dict) else getattr(flag_info, "override_content", None)
                o_author = flag_info.get("override_author") if isinstance(flag_info, dict) else getattr(flag_info, "override_author", None)
                if o_content is not None:
                    m_copy["content"] = o_content
                if o_author is not None:
                    m_copy["author"] = o_author
                prepared.append(m_copy)
                continue

        prepared.append(msg)

    return prepared


FAILED_TUPPER_PAT = re.compile(r"^\s*[\w\-]+:(?!//)")


def is_failed_tupper(content: str) -> bool:
    """Detects whether a message starts with a word (no spaces) followed by a colon, e.g. 'CharName:', 'AS:', 'eris:'."""
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
    Runs after scene segmentation to classify messages into failed_tupper, ooc_boundary, or ooc_message.
    Skips benign messages (valid scene end tags, start headers, setup attachments).
    Preserves existing resolved messages and manually added items.
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

        # Benign check 1: closed [END] tag that cleanly closed a scene
        if msg_id in closed_end_ids:
            continue

        # Benign check 2: start header tag at start of scene
        if msg_id in start_header_ids:
            continue

        # Benign check 3: OOC setup attachments before first scene
        if not seen_first_tupper and len(msg.get("attachments", [])) > 0 and not has_start_tag(content) and not has_end_tag(content):
            continue

        # Classify kind
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
            "content": content,
            "author": msg.get("author", {}),
        })

    return flagged_items


################# Main function #################

def fix_bad_messages():
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

        for path in backup.get_all_paths():
            file_path = (Path(c.DATA_FOLDER) / path).as_posix()
            t.log("log", f"\t    Analysing {file_path}...")
            raw_channel = t.load_from_json(file_path)
            raw_messages = raw_channel.get("messages", [])
            chan_id = raw_channel.get("channel", {}).get("id") or ""

            # In standalone fix_bad_messages, scenes haven't been indexed yet,
            # so scenes list is empty. Boundary classification happens during index_scenes.
            items = collect_channel_flagged_messages(
                raw_messages=raw_messages,
                channel_id=chan_id,
                scenes=[],
                preserved_msg_ids=preserved_msg_ids,
            )
            all_flagged.extend(items)

        # Save flagged messages to SQLite (and optionally snapshots if c.DEBUG_FILES)
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

        if 'e' in locals() and e is not None:
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

import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import utils.tricks as t
import utils.exceptions as exc
from find_character_scenes import (
    message_info,
    scene_info,
    extract_participants_from_messages,
    MENTION_ONLY_PAT,
)
from fix_bad_messages import prepare_channel_messages
from models import ServerBackup, Category, Channel, Step
from db.models import SceneStatus, SceneKind
from db.session import has_db
from models.scene_manager import SceneManager

t.set_path()
from res import constants as c

################ File summary #################

"""
This module provides detection, segmentation, and indexing of roleplayed chatroom sessions.
Unlike traditional narrative RP scenes, chatrooms lack explicit start and end markers.
Sessions are segmented using an activity-trend and composite heuristic model:
  - Hard upper ceiling (SESSION_HARD_CEILING_HOURS): Always splits on long inactivity gaps.
  - Status tag assist (SESSION_TAG_ASSIST_HOURS): Splits on shorter gaps if accompanied by [Online]/[Offline] tags.
  - Silence fallback (SESSION_SILENCE_HOURS): Splits on quiet pauses unless an apology/continuation is present.
  - Local activity spike (SESSION_SPIKE_FLOOR_HOURS & SESSION_SPIKE_RATIO): Splits when a pause is an extreme outlier
    relative to the local surrounding conversation pace.
  - 1-message session merge post-pass: Merges 1-message blocks into adjacent sessions if gap < SESSION_HARD_CEILING_HOURS
    (choosing the shorter gap if both qualify), while preserving manual curation split points.
  - Manual split curation decisions (status = "no_end_tag") take absolute precedence.
Chatroom channels are never auto-flagged or auto-split with scene issues.
"""

# ==============================================================================
# Chat Session Segmentation Thresholds & Activity-Trend Parameters
# ==============================================================================

# Hard upper ceiling: Any inactivity gap exceeding this duration always splits.
SESSION_HARD_CEILING_HOURS = 4.5
SESSION_GAP_HOURS = SESSION_HARD_CEILING_HOURS  # Backwards-compatible alias
SESSION_MAX_GAP_SECONDS = SESSION_HARD_CEILING_HOURS * 3600

# Status tag assist: Split on shorter gaps if message starts with an [Online]/[Joined] tag,
# or preceding message ended with an [Offline]/[Idle] tag.
SESSION_TAG_ASSIST_HOURS = 1

# Silence fallback: Split on inactivity when gap exceeds this duration,
# unless it's an explicit continuation or apology ("back, sorry", "fell asleep").
SESSION_SILENCE_HOURS = 2.8

# Local activity spike: Split if gap exceeds this floor AND exceeds local tempo by this ratio.
SESSION_SPIKE_FLOOR_HOURS = 2.0
SESSION_SPIKE_RATIO = 80.0

# Rolling window size for computing local tempo (number of messages before/after).
SESSION_TEMPO_WINDOW = 10

# Regex patterns for status tags and conversational apologies/continuations
ONLINE_TAG_PAT = re.compile(r"`{1,3}[^`]*?\b(?:online|joined)\b[^`]*?`{1,3}", re.IGNORECASE | re.DOTALL)
OFFLINE_TAG_PAT = re.compile(r"`{1,3}[^`]*?\b(?:offline|idle|left|leaving)\b[^`]*?`{1,3}", re.IGNORECASE | re.DOTALL)
# Matches conversational apologies, return announcements, and absence explanations
# (e.g., 'sorry'/'apolog*' and 'back' anywhere in the message, 'I'm back', 'fell asleep', 'sorry for the wait')
APOLOGY_CONTINUATION_PAT = re.compile(
    r"(?:"
    r"(?=.*\b(?:sorry|apolog\w*)\b)(?=.*\bback\b)"
    r"|\b(?:i(?:['’]| m)?\s*back|,\s*back|finally\s+back|got\s+back)\b"
    r"|\b(?:passed\s+out|asleep|dozed\s+off)\b"
    r"|\b(?:sorry|apolog\w*)\b.*?\b(?:delay|wait|late|busy|distracted)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)


def has_online_tag(msg: Dict[str, Any]) -> bool:
    """Returns True if the message contains an [Online] or [Joined] tag in backticks."""
    return bool(ONLINE_TAG_PAT.search(msg.get("content") or ""))


def has_offline_tag(msg: Dict[str, Any]) -> bool:
    """Returns True if the message contains an [Offline] or [Idle] tag in backticks."""
    return bool(OFFLINE_TAG_PAT.search(msg.get("content") or ""))


def has_apology_continuation(msg: Dict[str, Any]) -> bool:
    """Returns True if the message indicates an apology or direct return to an ongoing scene."""
    return bool(APOLOGY_CONTINUATION_PAT.search(msg.get("content") or ""))


def parse_msg_datetime(msg: Dict[str, Any]) -> Optional[datetime]:
    """Parses message timestamp into a timezone-aware UTC datetime."""
    ts_str = msg.get("timestamp")
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def merge_one_message_blocks(
    blocks: List[Tuple[List[Dict[str, Any]], str, Optional[str]]],
    ceiling_hours: float,
) -> List[Tuple[List[Dict[str, Any]], str, Optional[str]]]:
    """
    Post-pass: Merges 1-message session blocks with the adjacent session before or after it
    if either gap is less than ceiling_hours. If both gaps are under ceiling_hours,
    merges with whichever adjacent session has the shorter gap.
    Manual curation split boundaries (resolved_start or status=no_end_tag) are strictly preserved.
    """
    merged = list(blocks)
    changed = True

    while changed:
        changed = False
        i = 0
        while i < len(merged):
            blk_msgs, b_status, r_start = merged[i]
            if len(blk_msgs) == 1:
                cur_msg = blk_msgs[0]
                dt_cur = parse_msg_datetime(cur_msg)

                # Check gap before (and check manual split boundary before)
                gap_before = float("inf")
                can_merge_before = False
                if i > 0 and dt_cur:
                    prev_msgs, prev_status, prev_start = merged[i - 1]
                    is_manual_before = (r_start is not None) or (prev_status == SceneStatus.NO_END_TAG.value)
                    if not is_manual_before and prev_msgs:
                        dt_prev = parse_msg_datetime(prev_msgs[-1])
                        if dt_prev:
                            gap_before = (dt_cur - dt_prev).total_seconds() / 3600.0
                            can_merge_before = (gap_before < ceiling_hours)

                # Check gap after (and check manual split boundary after)
                gap_after = float("inf")
                can_merge_after = False
                if i < len(merged) - 1 and dt_cur:
                    next_msgs, next_status, next_start = merged[i + 1]
                    is_manual_after = (next_start is not None) or (b_status == SceneStatus.NO_END_TAG.value)
                    if not is_manual_after and next_msgs:
                        dt_next = parse_msg_datetime(next_msgs[0])
                        if dt_next:
                            gap_after = (dt_next - dt_cur).total_seconds() / 3600.0
                            can_merge_after = (gap_after < ceiling_hours)

                if can_merge_before and can_merge_after:
                    if gap_before <= gap_after:
                        merged[i - 1] = (merged[i - 1][0] + blk_msgs, b_status, merged[i - 1][2])
                        merged.pop(i)
                        changed = True
                        continue
                    else:
                        merged[i + 1] = (blk_msgs + merged[i + 1][0], merged[i + 1][1], r_start or merged[i + 1][2])
                        merged.pop(i)
                        changed = True
                        continue
                elif can_merge_before:
                    merged[i - 1] = (merged[i - 1][0] + blk_msgs, b_status, merged[i - 1][2])
                    merged.pop(i)
                    changed = True
                    continue
                elif can_merge_after:
                    merged[i + 1] = (blk_msgs + merged[i + 1][0], merged[i + 1][1], r_start or merged[i + 1][2])
                    merged.pop(i)
                    changed = True
                    continue

            i += 1

    return merged


def find_all_sessions_in_channel(
    channel_data: Dict[str, Any],
    messages: List[Dict[str, Any]],
    id_builder: str,
    resolved_decisions: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """
    Segments prepared messages into distinct chat sessions using a composite activity-trend model
    combining local relative pace spikes, status tag assists, silence floors, and manual curation splits.

    Args:
        channel_data (dict): Raw channel dictionary containing 'guild' and 'channel' metadata.
        messages (list): Prepared Default messages for the channel.
        id_builder (str): Unique prefix string for scene IDs.
        resolved_decisions (dict, optional): Map of candidate message ID -> resolution ("split" / "merged").

    Returns:
        List of session dictionaries formatted identically to scenes with kind="session".
    """
    if resolved_decisions is None:
        resolved_decisions = {}

    chan_info = channel_data.get("channel", {})
    chan_name = chan_info.get("name", "")
    t.log("info", f"Finding chat sessions in channel {repr(chan_name)}")

    if not messages:
        return []

    # 1. Precompute timestamps and consecutive gaps
    dts = [parse_msg_datetime(m) for m in messages]
    n_msgs = len(messages)

    gap_hours_list = [0.0] * n_msgs
    gap_min_list = [0.0] * n_msgs
    prev_valid_idx: Optional[int] = None

    for i in range(n_msgs):
        dt = dts[i]
        if dt and prev_valid_idx is not None and dts[prev_valid_idx]:
            gh = (dt - dts[prev_valid_idx]).total_seconds() / 3600.0
            gap_hours_list[i] = max(0.0, gh)
            gap_min_list[i] = max(0.0, gh * 60.0)
        if dt:
            prev_valid_idx = i

    # 2. Precompute local tempo (rolling median gap in minutes) around valid transitions
    valid_gaps_indices = [i for i in range(n_msgs) if gap_hours_list[i] > 0.0]
    valid_gaps_min = [gap_min_list[i] for i in valid_gaps_indices]

    pace_map: Dict[int, float] = {}
    for pos, orig_idx in enumerate(valid_gaps_indices):
        prev_w = valid_gaps_min[max(0, pos - SESSION_TEMPO_WINDOW) : pos]
        next_w = valid_gaps_min[pos + 1 : min(len(valid_gaps_min), pos + 1 + SESSION_TEMPO_WINDOW)]
        p_prev = statistics.median(prev_w) if prev_w else 0.5
        p_next = statistics.median(next_w) if next_w else 0.5
        # Floor local tempo at 15 seconds (0.25 min) to prevent micro-division noise
        pace_map[orig_idx] = max(min(p_prev, p_next), 0.25)

    # 3. Segment into blocks based on manual splits or composite trend thresholds
    blocks: List[Tuple[List[Dict[str, Any]], str, Optional[str]]] = []
    curr_block: List[Dict[str, Any]] = []
    curr_resolved_start: Optional[str] = None
    prev_msg: Optional[Dict[str, Any]] = None

    for i in range(n_msgs):
        msg = messages[i]
        m_id_str = str(msg.get("id", ""))
        dt = dts[i]
        gh = gap_hours_list[i]

        # Check manual split decision
        if resolved_decisions.get(m_id_str) == "split" and curr_block:
            blocks.append((curr_block, SceneStatus.NO_END_TAG.value, curr_resolved_start))
            curr_block = [msg]
            curr_resolved_start = m_id_str
            prev_msg = msg
            continue

        # Check composite activity-trend split conditions
        if curr_block and prev_msg and gh > 0.0:
            pace = pace_map.get(i, 0.5)
            spike_ratio = gap_min_list[i] / pace

            is_tag = has_online_tag(msg) or has_offline_tag(prev_msg)
            is_apology = has_apology_continuation(msg)
            cur_auth = msg.get("author", {}).get("name")
            prev_auth = prev_msg.get("author", {}).get("name")
            same_author = (cur_auth == prev_auth and cur_auth is not None)

            should_split = False
            # Condition 1: Inactivity exceeds hard ceiling
            if gh >= SESSION_HARD_CEILING_HOURS:
                should_split = True
            # Condition 2: Status tag assist on moderate gap
            elif gh >= SESSION_TAG_ASSIST_HOURS and is_tag:
                should_split = True
            # Condition 3: Extreme local pace spike after active chat
            elif (
                gh >= SESSION_SPIKE_FLOOR_HOURS
                and spike_ratio >= SESSION_SPIKE_RATIO
                and not is_apology
                and not (same_author and gh < 3.0)
            ):
                should_split = True
            # Condition 4: Cold silence fallback
            elif gh >= SESSION_SILENCE_HOURS and not is_apology and not same_author:
                should_split = True

            if should_split:
                blocks.append((curr_block, SceneStatus.CLOSED.value, curr_resolved_start))
                curr_block = [msg]
                curr_resolved_start = None
                prev_msg = msg
                continue

        curr_block.append(msg)
        if dt:
            prev_msg = msg

    if curr_block:
        blocks.append((curr_block, SceneStatus.CLOSED.value, curr_resolved_start))

    # 4. Post-pass: Merge 1-message sessions into adjacent sessions if gap < SESSION_HARD_CEILING_HOURS
    blocks = merge_one_message_blocks(blocks, SESSION_HARD_CEILING_HOURS)

    sessions: List[Dict[str, Any]] = []

    for block_msgs, block_status, resolved_start in blocks:
        # Extract participants (tupper characters only for sessions)
        characters, participant_details = extract_participants_from_messages(block_msgs, include_non_tuppers=False)

        # Skip sessions with zero tupper characters
        if not participant_details:
            continue

        first_msg = block_msgs[0]
        last_msg = block_msgs[-1]

        start_raw_idx = first_msg.get("raw_index", 0)
        end_raw_idx = last_msg.get("raw_index", len(block_msgs) - 1)

        start_msg_info = message_info(first_msg, channel_data, start_raw_idx)
        end_msg_info = message_info(last_msg, channel_data, end_raw_idx)

        session = scene_info(
            start_message=start_msg_info,
            end_message=end_msg_info,
            scene_id="",
            scene_index=0,
            channel=channel_data,
            status=block_status,
            characters=characters,
        )
        session["kind"] = SceneKind.SESSION.value
        session["participant_details"] = participant_details
        session["issues"] = []
        session["id_builder"] = id_builder
        if resolved_start:
            session["resolved_start"] = resolved_start

        sessions.append(session)

    # Sort sessions by start timestamp
    sessions.sort(key=lambda s: s["start"]["timestamp"] or "")

    for idx, s in enumerate(sessions):
        s["index"] = idx + 1
        s["id"] = f"{id_builder}{idx + 1}"

    return sessions

def process_chatroom_channel(
    channel: Channel,
    id_builder: str,
    resolved_decisions: Optional[Dict[str, str]] = None,
    resolved_flags_map: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Loads raw channel JSON, prepares messages with flags/overrides, and segments into sessions.
    Never auto-flags messages in chatroom channels.
    """
    file_path = (Path(c.DATA_FOLDER) / channel.path).as_posix()
    channel_data = t.load_from_json(file_path)

    raw_messages = channel_data.get("messages", [])
    prepared = prepare_channel_messages(raw_messages, resolved_flags_map or {})

    sessions = find_all_sessions_in_channel(
        channel_data=channel_data,
        messages=prepared,
        id_builder=id_builder,
        resolved_decisions=resolved_decisions,
    )

    channel.scenes = len(sessions)
    return sessions


def find_sessions_in_category(
    category: Category,
    resolved_decisions: Optional[Dict[str, str]] = None,
    resolved_flags_map: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Processes all channels and threads in a chatroom category to produce chat sessions.
    """
    start_time = time.time()
    all_sessions: List[Dict[str, Any]] = []

    t.log("info", f"\n    ## Finding chat sessions in {category.name}... ##")

    for channel in category.channels:
        chan_id_b = f"{category.position}{channel.position}"
        sessions = process_chatroom_channel(
            channel=channel,
            id_builder=chan_id_b,
            resolved_decisions=resolved_decisions,
            resolved_flags_map=resolved_flags_map,
        )
        all_sessions.extend(sessions)
        t.log("info", f"\t  Found {len(sessions)} sessions in '{channel.name}', adding up to {len(all_sessions)} total sessions\n")

        for thread in channel.threads:
            thread_id_b = f"{category.position}{channel.position}{thread.position}"
            thread_sessions = process_chatroom_channel(
                channel=thread,
                id_builder=thread_id_b,
                resolved_decisions=resolved_decisions,
                resolved_flags_map=resolved_flags_map,
            )
            all_sessions.extend(thread_sessions)
            t.log("info", f"\t  Found {len(thread_sessions)} sessions in '{thread.name}', adding up to {len(all_sessions)} total sessions\n")

    # Sort sessions by start timestamp
    all_sessions.sort(key=lambda s: s["start"]["timestamp"] or "")

    for idx, s in enumerate(all_sessions):
        s["index"] = idx + 1
        id_b = s.get("id_builder", "")
        s["id"] = f"{id_b}{idx + 1}"

    if c.DEBUG_FILES:
        folder_path = (Path(c.DATA_FOLDER) / category.path).as_posix()
        t.save_to_json(all_sessions, f"{folder_path}/_sessions.json")
        t.log("debug", f"\n    Saved {len(all_sessions)} sessions to {folder_path}/_sessions.json")

    t.log("info", f"\n    ## Finished finding sessions in {category.name} --- {time.time() - start_time:.2f} seconds --- ##\n")
    return all_sessions


def index_sessions(backup_id: Optional[str] = None, backup_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Standalone runner to index chat sessions across all configured chatroom categories.
    """
    backup = ServerBackup.load(scope="base", backup_id=backup_id, backup_path=backup_path)
    b_id = backup_id or backup.backup_id or getattr(c, "BACKUP_ID", None)
    b_path = backup_path or backup.path or getattr(c, "BACKUP_BASE", None)

    start_time = time.time()
    try:
        t.log("base", f"\n# Indexing chat sessions in {c.BACKUP_NAME}... #\n")

        resolved_decisions: Dict[str, str] = {}
        resolved_flags_map: Dict[str, Any] = {}

        if has_db(b_path, backup_id=b_id):
            from db.curation_service import (
                get_resolved_boundary_decisions,
                get_resolved_flags_map,
            )
            resolved_decisions = get_resolved_boundary_decisions(b_id, b_path)
            resolved_flags_map = get_resolved_flags_map(b_id, b_path)

        all_sessions: List[Dict[str, Any]] = []

        for category in backup.categories:
            if category.name in c.CHATROOM_CATEGORIES:
                sessions = find_sessions_in_category(
                    category=category,
                    resolved_decisions=resolved_decisions,
                    resolved_flags_map=resolved_flags_map,
                )
                all_sessions.extend(sessions)

        # Sort all sessions by start timestamp
        all_sessions.sort(key=lambda s: s["start"]["timestamp"] or "")

        for idx, s in enumerate(all_sessions):
            s["index"] = idx + 1
            id_b = s.get("id_builder", "")
            s["id"] = f"{id_b}{idx + 1}"

        # Delegate saving sessions to SQLite via SceneManager
        SceneManager.get_instance(backup_id=b_id, base_path=b_path).save_scenes(
            scenes=all_sessions,
            debug_files=c.DEBUG_FILES,
        )

        backup.save()
        t.log("base", f"### Finished indexing {len(all_sessions)} sessions --- {time.time() - start_time:.2f} seconds --- ###\n")
        return all_sessions

    except Exception as e:
        raise exc.IndexScenesError("Failed to index chat sessions") from e


if __name__ == "__main__":
    try:
        index_sessions()
    except KeyboardInterrupt:
        t.log("error", "\nProcess interrupted by user.\n")
        sys.exit(1)
    except Exception as e:
        t.log("error", f"Error indexing sessions: {e}\n")
        sys.exit(1)

import sys
from pathlib import Path
import time
from typing import Dict, List, Optional, Tuple, Any, Set
import utils.tricks as t
import utils.exceptions as exc
from fix_bad_messages import (
    prepare_channel_messages,
    prepare_channel_skeletons,
    collect_channel_flagged_messages,
    build_skeletons_from_messages,
)
from find_character_scenes import (
    has_end_tag,
    has_start_tag,
    message_info,
    scene_info,
    extract_participants_from_messages,
    MENTION_ONLY_PAT,
    END_TAG_SHORT_MSG_MAX_LEN,
    AUTO_SPLIT_MIN_TUPPERS,
    ROSTER_CHANGE_MIN_TUPPERS,
)
from models import ServerBackup, Category, Channel, Thread, SceneManager, Step, CharacterList
from db.models import SceneStatus, IssueKind, SceneKind, SceneModel, SceneIssueModel, FlaggedMessageModel, BackupModel, StorageMode
from db.session import has_db, has_skeleton_db, db_session
from db.scene_service import load_channel_skeletons, upsert_channel_skeletons, snowflake_int
from db.skeleton_models import SkeletonFlags
from utils.path_safety import category_matches, expand_category_names
t.set_path()
from res import constants as c

################ File summary #################

"""
This module indexes all the scenes of the server backup using a deterministic two-phase indexer:
  - Phase 1: Explicit Boundary Segmentation based on message types, start tags, and end tags.
  - Phase 2: Roster-Interval Sub-Segmentation and Issue Detection (recursive separate roster
             auto-splits, start tag flagging, and roster change detection).

Main function: index_scenes()
    Iterates through categories and channels, segments scenes, sessions, and events, and persists
    them to SQLite along with participants and detected curation issues (auto_split, soft_boundary).
"""

################# Functions #################


def load_status(backup_id: Optional[str] = None, backup_path: Optional[str] = None) -> ServerBackup:
    """Loads backup information and checks if it is ready to index."""
    try:
        backup = ServerBackup.load(scope="base", backup_id=backup_id, backup_path=backup_path)
        resolved_path = backup_path or backup.path or getattr(c, "BACKUP_BASE", None)

        from backup_server import is_sync_lock_held
        if is_sync_lock_held(resolved_path):
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")

        if not backup.can_index_scenes():
            raise exc.DataNotReadyError("The data may be corrupted or incomplete. Ensure the backup downloaded successfully and try again.")

        t.log("debug", f"  The current status of the backup is '{backup.status}'\n")
        backup.start_index_scenes()
        t.log("debug", "  Backup is ready.\n")

    except (exc.DataNotReadyError, exc.AlreadyRunningError):
        raise

    except Exception as e:
        raise exc.IndexScenesError("The export status file could not be read") from e

    return backup


def _compute_roster_window(blk: List[Dict[str, Any]]) -> Tuple[List[Set[int]], List[Set[int]], List[int]]:
    """
    Computes prefix/suffix character rosters and precomputed prefix tupper counts.
    Avoids O(n^2) repeated loops and sum() calls.
    """
    n = len(blk)

    # Arrays of sets of which tuppers have posted in that block
    # There will be two sets for each message in the block:
    # prefix_chars[i]: All tuppers who have posted from the start up to message i
    # suffix_chars[i]: All tuppers who will post from message i to the end
    prefix_chars = [set() for _ in range(n)]
    suffix_chars = [set() for _ in range(n)]
    prefix_tupper_counts = [0] * (n + 1)

    # Forward pass: For each index i, save a list of which characters have posted from the start until that message
    cur = set()
    t_count = 0
    for i in range(n):
        aid = blk[i]["author_id"]
        if t.is_tupper(aid):
            cur = cur | {aid}
            t_count += 1
        prefix_chars[i] = cur
        prefix_tupper_counts[i + 1] = t_count

    # Backward pass: For each index i, save a list of which characters have posted from that message to the end
    cur = set()
    for i in range(n - 1, -1, -1):
        aid = blk[i]["author_id"]
        if t.is_tupper(aid):
            cur = cur | {aid}
        suffix_chars[i] = cur

    return prefix_chars, suffix_chars, prefix_tupper_counts

"""
_recursive_split_block(blk, status, next_info=None):

    Recursively splits a candidate block of messages into smaller scenes.

    In Phase 1, blocks were created based only on explicit [END] tags. However,
    some [END] tags don't match the usual patterns and are not detected by Phase 1.
    This function analyzes the character rosters (tupper IDs < 10000) and start tags
    to determine if a block actually contains multiple distinct scenes.

    It evaluates every message k and checks two auto-split rules:
      - Rule 2A (Separate Roster Handoff): Characters before and after k have zero overlap.
      - Rule 2B (Start Tag + Roster Change): An explicit start tag occurs where the roster changes.

    When a split is found, the previous part is marked as 'auto_split' (since it ended without an
    explicit [END] tag) and both halves are recursively evaluated.

    Args:
        blk (list): List of message dictionaries in the block.
        status (str): Initial status of the block ('closed' or 'open').
        next_info (dict, optional): Information describing the reason and cut-point of a split
            passed forward from the parent recursion frame.

    Returns:
        list: A list of tuples (sub_block, sub_status, split_info) representing the resulting scenes.
"""
def _recursive_split_block(
    blk: List[Dict[str, Any]],
    status: str,
    next_info: Optional[Dict[str, Any]] = None,
    resolved_decisions: Optional[Dict[str, str]] = None,
) -> List[Tuple[List[Dict[str, Any]], str, Optional[Dict[str, Any]], List[str]]]:
    n = len(blk)
    # A block with 0 or 1 message cannot be split further
    if n <= 1:
        return [(blk, status, next_info, [])]

    prefix_chars, suffix_chars, prefix_tupper_counts = _compute_roster_window(blk)
    already_merged: List[str] = []

    # For each message of the block, check if it's a possible cut point
    for k in range(1, n):

        # Skip the message if it's not from a tupper and does not have a start tag
        if not t.is_tupper(blk[k]["author_id"]) and not blk[k]["has_start_tag"]:
            continue

        # Skip if reviewer resolved this boundary to be merged
        cand_mid = str(blk[k].get("id", ""))
        if resolved_decisions and resolved_decisions.get(cand_mid) == "merged":
            already_merged.append(cand_mid)
            continue

        # previous: characters that have posted from the start of the block to the previous message
        # next: characters that have posted from now until the end of the block
        previous_set = prefix_chars[k - 1]
        next_set = suffix_chars[k]

        # Skip the message if a side is empty (i.e. we're checking the first/last message)
        if not previous_set or not next_set:
            continue

        # Count how many tuppers appear in each half
        previous_tuppers = prefix_tupper_counts[k]
        next_tuppers = prefix_tupper_counts[n] - prefix_tupper_counts[k]

        # Check if the current message has a start tag
        has_start = blk[k]["has_start_tag"]

        split_reason = None

        # Rule 2A: Separate Roster Handoff
        # The list of characters in each half is completely different- no character appears in both
        # We auto-split if:
        # 1. Both sides have at least 2 tupper messages (two real scenes side by side), OR
        # 2. Message k has an explicit start tag (e.g. date/call header) and next side has at least 1 tupper post.
        if previous_set.isdisjoint(next_set):
            if (previous_tuppers >= AUTO_SPLIT_MIN_TUPPERS and next_tuppers >= AUTO_SPLIT_MIN_TUPPERS) or (has_start and next_tuppers >= 1):
                split_reason = "separate_roster"

        # Rule 2B: Start Tag + Roster Change
        # Message k has an explicit start tag, and the list of characters in each half is different.
        # Catches cases where one character has two scenes in a row with different characters,
        # but no [END] tag was detected between the two scenes.
        elif has_start and previous_set != next_set and previous_tuppers >= 1 and next_tuppers >= 1:
            split_reason = "start_tag_roster_change"

        # If a split condition was met, perform the split and recurse on both halves
        if split_reason:
            current_split_info = {
                "reason": split_reason,
                "candidate_index": blk[k]["index"],
                "candidate_id": blk[k].get("id", ""),
                "candidate_excerpt": blk[k].get("content", ""),
                "previous_chars": sorted(previous_set),
                "next_chars": sorted(next_set),
            }
            # previous block ended abruptly without an explicit [END] tag -> status is "no_end_tag"
            previous_parts = _recursive_split_block(
                blk[:k],
                SceneStatus.NO_END_TAG.value,
                current_split_info,
                resolved_decisions=resolved_decisions,
            )

            # next block inherits the parent block's original status (closed or open) and next_info
            next_parts = _recursive_split_block(
                blk[k:],
                status,
                next_info,
                resolved_decisions=resolved_decisions,
            )
            return previous_parts + next_parts

    # No split conditions matched across all candidate points; keep the block as a single scene
    return [(blk, status, next_info, already_merged)]

"""
_detect_soft_boundaries(sblk):

    Detects candidate split points within an already-segmented scene that should NOT be
    automatically split, but flagged as potential issues for manual curation review.

    This identifies cases where a scene might actually be two scenes, but the evidence
    is ambiguous enough that automatic splitting could cause false positives:
      1. Start Tag + Same Roster: An explicit scene header or date tag appears inside the scene,
         but the characters are the same on both sides (e.g., a time skip between the same characters).
      2. Roster Changes without a start tag: One character stays ("anchor"), one leaves permanently, and a new one
         arrives, with substantial dialogue on both sides. No start tag is present.

    Args:
        sblk (list): List of message dictionaries in the segmented scene block.

    Returns:
        list: A list of dicts describing candidate split issues found (if any).
"""
def _detect_soft_boundaries(
    sblk: List[Dict[str, Any]],
    resolved_decisions: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    sn = len(sblk)
    # A block with 0 or 1 message has no internal split points
    if sn <= 1:
        return [], []

    s_prefix, s_suffix, prefix_tupper_counts = _compute_roster_window(sblk)

    roster_change_found = False
    soft_boundaries = []
    already_merged: List[str] = []

    # For each message in the block, see if there's a possible soft boundary.
    # These are NOT auto-split because they might be legitimate transitions inside the same scene
    # (e.g. time jumps with same characters, or a character arriving/leaving mid-scene).
    for k in range(1, sn):

        # Skip if reviewer already resolved this boundary decision
        cand_mid = str(sblk[k].get("id", ""))
        if resolved_decisions and resolved_decisions.get(cand_mid) == "merged":
            already_merged.append(cand_mid)
            continue

        # previous: characters that have posted from the start of the block to the previous message
        # next: characters that have posted from now until the end of the block
        previous_set = s_prefix[k - 1]
        next_set = s_suffix[k]

        # Skip this split if a side is empty (i.e. we're checking the first/last message)
        if not previous_set or not next_set:
            continue

        # Count how many tupper messages appear in each half
        previous_tuppers = prefix_tupper_counts[k]
        next_tuppers = prefix_tupper_counts[sn] - prefix_tupper_counts[k]
        # author_id of the current message (the candidate split point)
        aid = sblk[k]["author_id"]

        # 1. Start Tag + Same Roster
        # Message k contains an explicit start tag (e.g. date header, call start, or markdown separator)
        # but was not auto-split by _recursive_split_block (typically because previous_set == next_set,
        # meaning the same characters continue after a time skip). We flag this for curation review.
        if sblk[k]["has_start_tag"]:
            soft_boundaries.append({
                "reason": "start_tag_same_roster",
                "candidate_index": sblk[k]["index"],
                "previous_chars": sorted(previous_set),
                "next_chars": sorted(next_set),
            })

        # 2. Roster Change
        # Detects partial roster handovers where an "anchor" character stays in the room while
        # their dialogue partner leaves and a new partner arrives.
        # We only flag at most one roster change per scene to prevent noisy duplicate alerts.
        elif not roster_change_found:
            # We flag a roster change when ALL of the following hold:
            # - Substantial dialogue: at least 4 tupper messages on each side
            # - Anchor character: at least one character is present on both sides (previous_set & next_set)
            # - Permanent departure: at least one character never speaks again after k (previous_set - next_set)
            # - New arrival: at least one character speaks for the first time at or after k (next_set - previous_set)
            # - Message k is authored by one of the arriving characters (marking the exact arrival point)
            if (
                previous_tuppers >= ROSTER_CHANGE_MIN_TUPPERS
                and next_tuppers >= ROSTER_CHANGE_MIN_TUPPERS
                and bool(previous_set & next_set)
                and bool(previous_set - next_set)
                and bool(next_set - previous_set)
                and aid in (next_set - previous_set)
            ):
                roster_change_found = True
                soft_boundaries.append({
                    "reason": "roster_change",
                    "candidate_index": sblk[k]["index"],
                    "previous_chars": sorted(previous_set),
                    "next_chars": sorted(next_set),
                })

    return soft_boundaries, already_merged


def _msg_is_default(m: Dict[str, Any]) -> bool:
    if "flags" in m:
        return bool(int(m["flags"]) & SkeletonFlags.IS_DEFAULT)
    return m.get("type") == "Default"


def _msg_is_mention_only(m: Dict[str, Any]) -> bool:
    if "flags" in m:
        return bool(int(m["flags"]) & SkeletonFlags.IS_MENTION_ONLY)
    return bool(MENTION_ONLY_PAT.match(str(m.get("content", "") or "").strip()))


def _msg_has_end_tag(m: Dict[str, Any]) -> bool:
    if "flags" in m:
        return bool(int(m["flags"]) & SkeletonFlags.HAS_END_TAG)
    return has_end_tag(m)


def _msg_is_short_end_tag(m: Dict[str, Any]) -> bool:
    if "flags" in m:
        return bool(int(m["flags"]) & SkeletonFlags.IS_SHORT_END_TAG)
    content = str(m.get("content", "") or "")
    return len(content.strip()) <= END_TAG_SHORT_MSG_MAX_LEN


def _msg_has_start_tag(m: Dict[str, Any]) -> bool:
    if "flags" in m:
        return bool(int(m["flags"]) & SkeletonFlags.HAS_START_TAG)
    return has_start_tag(m)


def _msg_has_attachment(m: Dict[str, Any]) -> bool:
    if "flags" in m:
        return bool(int(m["flags"]) & SkeletonFlags.HAS_ATTACHMENT)
    return len(m.get("attachments", []) or []) > 0


def _segment_explicit_boundaries(
    messages: List[Dict[str, Any]],
    resolved_decisions: Optional[Dict[str, str]] = None,
) -> List[Tuple[List[Dict[str, Any]], str, Optional[str]]]:
    """
    Phase 1: Segments channel messages into raw blocks based on explicit start/end tags
    and applied reviewer 'split' decisions.
    """
    raw_blocks = []
    curr_block = []
    curr_resolved_start = None

    for i, m in enumerate(messages):

        # Skip non-text messages (pins, invites, etc)
        if not _msg_is_default(m):
            continue

        # Skip messages with only a mention
        if _msg_is_mention_only(m):
            continue

        m_content = m.get("content", "") or ""
        # Check the author and if the message has start or end tags
        aid = t.get_author_id(m)
        is_end = _msg_has_end_tag(m)
        is_start = _msg_has_start_tag(m)

        # Skip OOC setup posts, like images that describe the channel location
        if (
            (not curr_block or all(not t.is_tupper(msg["author_id"]) for msg in curr_block))
            and not t.is_tupper(aid) and _msg_has_attachment(m)
            and not is_start and not is_end
        ):
            continue

        # If a "new" scene's first message is an end tag, append to previous block
        if len(curr_block) == 0 and len(raw_blocks) > 0 and is_end and _msg_is_short_end_tag(m):
            prev_blk, prev_status, prev_res_start = raw_blocks[-1]
            prev_blk.append({
                "index": i,
                "author_id": aid,
                "has_end_tag": is_end,
                "has_start_tag": is_start,
                "id": str(m.get("id", "")),
                "content": m_content,
            })
            raw_blocks[-1] = (prev_blk, SceneStatus.CLOSED.value, prev_res_start)
            continue

        m_id_str = str(m.get("id", ""))
        # If this message was manually marked as split by reviewer, close current block before this message
        if resolved_decisions and resolved_decisions.get(m_id_str) == "split":
            if curr_block:
                raw_blocks.append((curr_block, SceneStatus.NO_END_TAG.value, curr_resolved_start))
                curr_block = []
            curr_resolved_start = m_id_str

        curr_block.append({
            "index": i,
            "author_id": aid,
            "has_end_tag": is_end,
            "has_start_tag": is_start,
            "id": m_id_str,
            "content": m_content,
        })

        # If we encounter an end tag, close the current block and start a new one
        if is_end:
            raw_blocks.append((curr_block, SceneStatus.CLOSED.value, curr_resolved_start))
            curr_block = []
            curr_resolved_start = None

    # Add any remaining messages as an open block
    if curr_block:
        raw_blocks.append((curr_block, SceneStatus.OPEN.value, curr_resolved_start))

    return raw_blocks


def _build_scene(
    messages: List[Dict[str, Any]],
    channel: Dict[str, Any],
    id_builder: str,
    sblk: List[Dict[str, Any]],
    s_status: str,
    characters: List[int],
    issues: List[Dict[str, Any]],
    resolved_start: Optional[str] = None,
    resolved_inside: Optional[List[str]] = None,
    participant_details: Optional[List[Dict[str, Any]]] = None,
    kind: str = SceneKind.SCENE.value,
) -> Dict[str, Any]:
    start_idx = sblk[0]["index"]
    end_idx = sblk[-1]["index"]
    start_msg_info = message_info(messages[start_idx], channel, start_idx)
    end_msg_info = message_info(messages[end_idx], channel, end_idx)

    scene = scene_info(
        start_message=start_msg_info,
        end_message=end_msg_info,
        scene_id="",
        scene_index=0,
        channel=channel,
        status=s_status,
        characters=characters,
    )
    scene["kind"] = kind
    scene["participant_details"] = participant_details or []
    scene["message_count"] = len(sblk)
    scene["issues"] = issues
    scene["id_builder"] = id_builder
    if resolved_start:
        scene["resolved_start"] = resolved_start
    if resolved_inside:
        scene["resolved_inside"] = resolved_inside
    return scene


def find_all_scenes_in_channel(
    channel: Dict[str, Any],
    id_builder: str,
    resolved_decisions: Optional[dict] = None,
) -> List[Dict[str, Any]]:
    messages = channel.get("messages", [])
    if not messages:
        return []

    ctype = channel.get("channel", {}).get("type")
    chan_name = channel.get("channel", {}).get("name", "")
    t.log("info", "Finding scenes in channel " + repr(chan_name))

    # If it's a thread, it only has one scene.
    if ctype != "GuildTextChat":

        # Get all text messages (no Discord status messages like only mentions, pins, invites, etc.)
        # Might not be needed if fix_bad_messages already filtered messages like these out
        default_msgs = [(i, m) for i, m in enumerate(messages) if _msg_is_default(m) and not _msg_is_mention_only(m)]
        if not default_msgs:
            return []

        # Find all the participants of the thread
        thread_msgs = [m for _, m in default_msgs]
        characters, participant_details = extract_participants_from_messages(thread_msgs, include_non_tuppers=True)

        # If there are no tuppers, it isn't a scene
        if not participant_details:
            return []

        first_idx, first_msg = default_msgs[0]
        last_idx, last_msg = default_msgs[-1]
        status = SceneStatus.CLOSED.value if _msg_has_end_tag(last_msg) else SceneStatus.OPEN.value

        start_msg = message_info(first_msg, channel, first_idx)
        end_msg = message_info(last_msg, channel, last_idx)
        scene = scene_info(start_msg, end_msg, f"{id_builder}1", 1, channel, status, characters)
        scene["kind"] = SceneKind.SCENE.value
        scene["participant_details"] = participant_details
        scene["message_count"] = len(thread_msgs)
        scene["issues"] = []
        scene["id_builder"] = id_builder
        return [scene]

    # If it's a channel we have to find all the scenes there

    # Phase 1: Split channel into blocks based on explicit start/end tags
    raw_blocks = _segment_explicit_boundaries(messages, resolved_decisions=resolved_decisions)


    # Phase 2: Verify that each block only contains one scene, and split them if they don't
    total_scenes = []

    for blk, status, block_resolved_start in raw_blocks:
        # If a block has no tuppers, ignore it
        if not any(t.is_tupper(m["author_id"]) for m in blk):
            continue

        # Recursively split the block if it contains more than one scene
        sub_blocks = _recursive_split_block(blk, status, resolved_decisions=resolved_decisions)

        # Save each valid sub-block as a scene
        for sub_idx, (sblk, s_status, split_info, sub_resolved_inside) in enumerate(sub_blocks):
            
            # Find all the participants of the scene
            sblk_msgs = [messages[m_dict["index"]] for m_dict in sblk]
            characters, participant_details = extract_participants_from_messages(sblk_msgs, include_non_tuppers=True)

            # If a block has no tuppers, ignore it
            # Should already be false since we filtered it before, but doesn't hurt
            if not participant_details:
                continue

            # Check if a scene didn't close cleanly and save details of the problem
            issues = []
            if s_status == SceneStatus.NO_END_TAG.value and split_info and split_info.get("candidate_id"):
                issues.append({
                    "kind": IssueKind.AUTO_SPLIT.value,
                    "reason": split_info.get("reason", "separate_roster"),
                    "candidate_index": split_info.get("candidate_index"),
                    "candidate_id": split_info.get("candidate_id"),
                    "candidate_excerpt": split_info.get("candidate_excerpt"),
                    "previous_chars": split_info.get("previous_chars", []),
                    "next_chars": split_info.get("next_chars", []),
                })

            # Check if there are any other possible issues
            soft_boundaries, already_merged = _detect_soft_boundaries(sblk, resolved_decisions=resolved_decisions)
            for ps in soft_boundaries:
                cand_idx = ps["candidate_index"]
                cand_msg = messages[cand_idx]
                cand_id = str(cand_msg.get("id", ""))
                issues.append({
                    "kind": IssueKind.SOFT_BOUNDARY.value,
                    "reason": ps["reason"],
                    "candidate_index": cand_idx,
                    "candidate_id": cand_id,
                    "candidate_excerpt": str(cand_msg.get("content", "")),
                    "previous_chars": ps["previous_chars"],
                    "next_chars": ps["next_chars"],
                })

            resolved_start = block_resolved_start if (sub_idx == 0 and block_resolved_start) else None
            resolved_inside = list(dict.fromkeys(sub_resolved_inside + already_merged))

            scene = _build_scene(
                messages=messages,
                channel=channel,
                id_builder=id_builder,
                sblk=sblk,
                s_status=s_status,
                characters=characters,
                issues=issues,
                resolved_start=resolved_start,
                resolved_inside=resolved_inside,
                participant_details=participant_details,
                kind=SceneKind.SCENE.value,
            )
            total_scenes.append(scene)

    # Sort all the scenes we found in this channel by Snowflake ID / start index
    total_scenes.sort(key=lambda x: (snowflake_int(x["start"].get("id")), x["start"]["index"]))

    # Assign each scene an index and an ID
    for i, scene in enumerate(total_scenes):
        scene["index"] = i + 1
        scene["id"] = f"{id_builder}{scene['index']}"

    return total_scenes



def _load_db_excerpts_map(backup_id: str, backup_path: str) -> Dict[str, str]:
    """Loads preserved message boundary excerpts from SceneModel, SceneIssueModel, and FlaggedMessageModel."""
    excerpts: Dict[str, str] = {}
    if not has_db(backup_path, backup_id=backup_id):
        return excerpts
    try:
        with db_session(backup_id=backup_id, backup_path=backup_path) as session:
            for s_mid, s_exc, e_mid, e_exc in session.query(
                SceneModel.start_message_id,
                SceneModel.start_excerpt,
                SceneModel.end_message_id,
                SceneModel.end_excerpt,
            ).filter(SceneModel.backup_id == str(backup_id)).all():
                if s_mid and s_exc:
                    excerpts[str(s_mid)] = str(s_exc)
                if e_mid and e_exc:
                    excerpts[str(e_mid)] = str(e_exc)
            for c_mid, c_exc in session.query(
                SceneIssueModel.candidate_message_id,
                SceneIssueModel.candidate_excerpt,
            ).filter(SceneIssueModel.backup_id == str(backup_id)).all():
                if c_mid and c_exc and str(c_mid) not in excerpts:
                    excerpts[str(c_mid)] = str(c_exc)
            for f_mid, f_cnt, f_ov in session.query(
                FlaggedMessageModel.message_id,
                FlaggedMessageModel.content,
                FlaggedMessageModel.override_content,
            ).filter(FlaggedMessageModel.backup_id == str(backup_id)).all():
                if f_mid:
                    val = f_ov if f_ov is not None else f_cnt
                    if val:
                        excerpts[str(f_mid)] = str(val)
    except Exception:
        pass
    return excerpts


def _synthetic_channel_dict(
    channel: Channel | Thread,
    category_name: str,
    server_id: str = "",
) -> Dict[str, Any]:
    is_thread = isinstance(channel, Thread) or not hasattr(channel, "threads")
    return {
        "guild": {"id": str(server_id or getattr(c, "SERVER_ID", "") or "")},
        "channel": {
            "id": str(channel.id),
            "name": str(channel.name),
            "category": str(category_name),
            "type": "GuildPublicThread" if is_thread else "GuildTextChat",
        },
        "messages": [],
    }


def _rescan_json_channel_skeletons(
    channel: Channel | Thread,
    file_path: str,
    backup_id: str,
    backup_path: str,
    char_list: Optional[CharacterList] = None,
    excerpts_map: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Reads a Data/<channel.path> JSON, runs assign_ids_in_memory, and rebuilds skeletons.sqlite rows."""
    if not file_path or not Path(file_path).is_file():
        return None
    json_data = t.load_from_json(file_path)
    raw_messages = json_data.get("messages", [])
    if char_list is not None:
        from assign_ids import assign_ids_in_memory
        assign_ids_in_memory(raw_messages, char_list)
    if excerpts_map is not None:
        for m in raw_messages:
            mid_s = str(m.get("id") or "")
            if mid_s:
                excerpts_map[mid_s] = str(m.get("content") or "")
    chan_did = str(getattr(channel, "id", None) or (json_data.get("channel") or {}).get("id") or "")
    if chan_did and backup_id and backup_path:
        skels = build_skeletons_from_messages(raw_messages, chan_did)
        upsert_channel_skeletons(backup_id, backup_path, chan_did, skels, effective_after_id=0)
    return json_data


def process_channel(
    channel: Channel | Thread,
    id_builder: str,
    resolved_decisions: Optional[dict] = None,
    resolved_flags_map: Optional[dict] = None,
    preserved_flagged_mids: Optional[set] = None,
    *,
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
    category_name: str = "",
    server_id: str = "",
    rescan_json: bool = False,
    excerpts_map: Optional[Dict[str, str]] = None,
    char_list: Optional[CharacterList] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    b_id = backup_id or getattr(c, "BACKUP_ID", None)
    b_path = backup_path or getattr(c, "BACKUP_BASE", None)
    data_folder = (Path(b_path) / "Data").as_posix() if b_path else c.DATA_FOLDER
    file_path = (Path(data_folder) / channel.path).as_posix() if channel.path else ""
    t.log("log", f"  Analysing {channel.name}...")

    if not rescan_json and b_id and b_path and has_skeleton_db(b_path, backup_id=b_id):
        skeletons = load_channel_skeletons(b_id, b_path, channel.id)
        if skeletons:
            prepared_messages = prepare_channel_skeletons(
                skeletons,
                resolved_flags_map or {},
                excerpts_map=excerpts_map,
            )
            channel_for_scenes = _synthetic_channel_dict(channel, category_name, server_id=server_id)
            channel_for_scenes["messages"] = prepared_messages
            scenes = find_all_scenes_in_channel(channel_for_scenes, id_builder, resolved_decisions=resolved_decisions)
            channel.scenes = len(scenes)
            return scenes, []
        if not (file_path and Path(file_path).is_file()):
            channel.scenes = 0
            return [], []

    if not file_path or not Path(file_path).is_file():
        channel.scenes = 0
        return [], []

    if rescan_json and b_id and b_path:
        json_data = _rescan_json_channel_skeletons(
            channel, file_path, b_id, b_path, char_list=char_list, excerpts_map=excerpts_map
        ) or {}
    else:
        json_data = t.load_from_json(file_path)

    raw_messages = json_data.get("messages", [])

    # Prepare messages in-memory with resolved overrides and exclusions
    prepared_messages = prepare_channel_messages(raw_messages, resolved_flags_map or {})
    channel_for_scenes = dict(json_data)
    channel_for_scenes["messages"] = prepared_messages

    # Find scene starts and ends for all characters
    scenes = find_all_scenes_in_channel(channel_for_scenes, id_builder, resolved_decisions=resolved_decisions)

    # Collect flagged messages for review
    chan_discord_id = getattr(channel, "id", None) or json_data.get("channel", {}).get("id") or ""
    flagged_items = collect_channel_flagged_messages(
        raw_messages=raw_messages,
        channel_id=str(chan_discord_id),
        scenes=scenes,
        preserved_msg_ids=preserved_flagged_mids or set(),
    )

    if c.DEBUG_FILES:
        scenes_file = file_path.replace(".json", "_scenes.json")
        scenes_path = scenes_file.replace("/Threads/", "/Scenes/") if "/Threads/" in scenes_file else (Path(scenes_file).parent / "Scenes" / Path(scenes_file).name).as_posix()
        Path(scenes_path).parent.mkdir(parents=True, exist_ok=True)
        t.save_to_json(scenes, scenes_path)
        t.log("log", f"\tSaved {len(scenes)} scenes to {scenes_file}")

    # Update the model with the scene count
    channel.scenes = len(scenes)

    return scenes, flagged_items


def find_scenes_in_category(
    category: Category,
    resolved_decisions: Optional[dict] = None,
    resolved_flags_map: Optional[dict] = None,
    preserved_flagged_mids: Optional[set] = None,
    *,
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
    server_id: str = "",
    rescan_json: bool = False,
    excerpts_map: Optional[Dict[str, str]] = None,
    char_list: Optional[CharacterList] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    start_time = time.time()

    all_scenes = []
    all_flagged = []

    t.log("info", f"\n    ## Finding scenes in {category.name}... ##")

    for channel in category.channels:
        scenes, flagged = process_channel(
            channel,
            f"{category.position}{channel.position}",
            resolved_decisions=resolved_decisions,
            resolved_flags_map=resolved_flags_map,
            preserved_flagged_mids=preserved_flagged_mids,
            backup_id=backup_id,
            backup_path=backup_path,
            category_name=category.name,
            server_id=server_id,
            rescan_json=rescan_json,
            excerpts_map=excerpts_map,
            char_list=char_list,
        )
        all_scenes.extend(scenes)
        all_flagged.extend(flagged)
        t.log("info", f"\t  Found {len(scenes)} scenes in '{scenes[0]['channel'] if len(scenes) > 0 else 'this channel'}', adding up to {len(all_scenes)} total scenes\n")

        for thread in channel.threads:
            scenes, flagged = process_channel(
                thread,
                f"{category.position}{channel.position}{thread.position}",
                resolved_decisions=resolved_decisions,
                resolved_flags_map=resolved_flags_map,
                preserved_flagged_mids=preserved_flagged_mids,
                backup_id=backup_id,
                backup_path=backup_path,
                category_name=category.name,
                server_id=server_id,
                rescan_json=rescan_json,
                excerpts_map=excerpts_map,
                char_list=char_list,
            )
            all_scenes.extend(scenes)
            all_flagged.extend(flagged)
            t.log("info", f"\t  Found {len(scenes)} scenes in '{scenes[0]['channel'] if len(scenes) > 0 else 'this thread'}', adding up to {len(all_scenes)} total scenes\n")

    # sort the scenes by start time
    all_scenes.sort(key=lambda x: x["start"]["timestamp"])

    # give the scenes new indexes and keep id in sync
    for i, scene in enumerate(all_scenes):
        scene["index"] = i + 1
        id_b = scene.get("id_builder", "")
        scene["id"] = f"{id_b}{scene['index']}"

    if c.DEBUG_FILES:
        folder_path = (Path(c.DATA_FOLDER) / category.path).as_posix()
        t.save_to_json(all_scenes, f"{folder_path}/_scenes.json")
        t.log("debug", f"\n    Saved {len(all_scenes)} scenes to {folder_path}/_scenes.json")

    t.log("info", f"\n    ## Finished finding scenes in {category.name} --- {time.time() - start_time:.2f} seconds --- ##\n")

    return all_scenes, all_flagged

################ Main function #################

def index_scenes(
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
    rescan_json: bool = False,
):
    backup = load_status(backup_id=backup_id, backup_path=backup_path)
    b_id = backup_id or backup.backup_id or getattr(c, "BACKUP_ID", None)
    b_path = backup_path or backup.path or getattr(c, "BACKUP_BASE", None)
    data_folder = (Path(b_path) / "Data").as_posix() if b_path else c.DATA_FOLDER

    start_time = time.time()
    try:
        t.log("base", f"\n# Indexing all the scenes in {c.BACKUP_NAME}... #\n")

        if rescan_json and (not data_folder or not Path(data_folder).is_dir()):
            raise exc.IndexScenesError(
                f"Cannot rescan local JSONs: Data folder not found at '{data_folder}' (full storage_mode required)."
            )

        # Load existing resolved boundary decisions, flags, and preserved DB excerpts from SQLite
        resolved_decisions = {}
        resolved_flags_map = {}
        preserved_flagged_mids = set()
        excerpts_map: Dict[str, str] = {}
        use_skeletons_mode = (not rescan_json) and bool(b_id and b_path and has_skeleton_db(b_path, backup_id=b_id))

        if has_db(b_path, backup_id=b_id):
            from db.curation_service import (
                get_resolved_boundary_decisions,
                get_resolved_flags_map,
                get_preserved_flagged_message_ids,
            )
            resolved_decisions = get_resolved_boundary_decisions(b_id, b_path)
            if resolved_decisions:
                t.log("info", f"  Loaded {len(resolved_decisions)} resolved curation decisions.\n")
            resolved_flags_map = get_resolved_flags_map(b_id, b_path)
            preserved_flagged_mids = get_preserved_flagged_message_ids(b_id, b_path)
            if use_skeletons_mode:
                excerpts_map = _load_db_excerpts_map(b_id, b_path)

        char_list = CharacterList.load(backup_id=b_id, base_path=b_path) if rescan_json else None

        full_scenes = []
        full_sessions = []
        full_flagged = []
        event_cats = []

        event_cat_names = expand_category_names(getattr(c, "EVENT_CATEGORIES", []))
        chatroom_cat_names = expand_category_names(getattr(c, "CHATROOM_CATEGORIES", []))

        for category in backup.categories:
            if (
                category_matches(category.id, category.name, event_cat_names)
                or category.id == "events_category"
                or category.name == "Events"
            ):
                event_cats.append(category)
                continue

            if category_matches(category.id, category.name, chatroom_cat_names):
                if rescan_json:
                    for ch in category.channels:
                        _rescan_json_channel_skeletons(
                            ch,
                            (Path(data_folder) / ch.path).as_posix(),
                            b_id,
                            b_path,
                            char_list=char_list,
                            excerpts_map=excerpts_map,
                        )
                        for th in ch.threads:
                            _rescan_json_channel_skeletons(
                                th,
                                (Path(data_folder) / th.path).as_posix(),
                                b_id,
                                b_path,
                                char_list=char_list,
                                excerpts_map=excerpts_map,
                            )
                from index_sessions import find_sessions_in_category
                use_rebuilt_skeletons = rescan_json and bool(b_id and b_path and has_skeleton_db(b_path, backup_id=b_id))
                sessions = find_sessions_in_category(
                    category=category,
                    resolved_decisions=resolved_decisions,
                    resolved_flags_map=resolved_flags_map,
                    backup_id=b_id,
                    backup_path=b_path,
                    server_id=str(backup.id or ""),
                    rescan_json=False if use_rebuilt_skeletons else rescan_json,
                    excerpts_map=excerpts_map,
                )
                full_sessions.extend(sessions)
                t.log("info", f"  Found {len(sessions)} chat sessions in chatroom category {category.name}\n")
                continue

            if c.DEBUG_FILES:
                scenes_dir = Path(data_folder) / category.path / "Scenes"
                if not scenes_dir.exists():
                    scenes_dir.mkdir(parents=True, exist_ok=True)

            scenes, flagged = find_scenes_in_category(
                category,
                resolved_decisions=resolved_decisions,
                resolved_flags_map=resolved_flags_map,
                preserved_flagged_mids=preserved_flagged_mids,
                backup_id=b_id,
                backup_path=b_path,
                server_id=str(backup.id or ""),
                rescan_json=rescan_json,
                excerpts_map=excerpts_map,
                char_list=char_list,
            )
            full_scenes.extend(scenes)
            full_flagged.extend(flagged)
            t.log("info", f"  Found {len(scenes)} scenes in {category.path}, adding up to {len(full_scenes)} total scenes\n")

        if rescan_json and char_list is not None:
            char_list.save()

        event_clusters = []
        if event_cats:
            if rescan_json:
                for cat in event_cats:
                    for ch in cat.channels:
                        _rescan_json_channel_skeletons(
                            ch,
                            (Path(data_folder) / ch.path).as_posix(),
                            b_id,
                            b_path,
                            char_list=char_list,
                            excerpts_map=excerpts_map,
                        )
                        for th in ch.threads:
                            _rescan_json_channel_skeletons(
                                th,
                                (Path(data_folder) / th.path).as_posix(),
                                b_id,
                                b_path,
                                char_list=char_list,
                                excerpts_map=excerpts_map,
                            )
                if char_list is not None:
                    char_list.save()
            from index_events import index_event_categories
            use_rebuilt_ev_skeletons = rescan_json and bool(b_id and b_path and has_skeleton_db(b_path, backup_id=b_id))
            event_clusters = index_event_categories(
                event_categories=event_cats,
                data_folder=data_folder,
                resolved_flags_map=resolved_flags_map,
                resolved_decisions=resolved_decisions,
                backup_id=b_id,
                backup_path=b_path,
                rescan_json=False if use_rebuilt_ev_skeletons else rescan_json,
                excerpts_map=excerpts_map,
            )
            t.log("info", f"  Found {len(event_clusters)} events across {len(event_cats)} event category(s)\n")

        # sort the scenes by start time
        full_scenes.sort(key=lambda x: x["start"]["timestamp"])

        # update scene indexes and keep id in sync
        for i, scene in enumerate(full_scenes):
            scene["index"] = i + 1
            id_b = scene.get("id_builder", "")
            scene["id"] = f"{id_b}{scene['index']}"

        # Delegate saving to SQLite via SceneManager
        SceneManager.get_instance(backup_id=b_id, base_path=b_path).save_scenes(
            scenes=full_scenes + full_sessions,
            debug_files=c.DEBUG_FILES,
        )

        if has_db(b_path, backup_id=b_id):
            from db.curation_service import save_flagged_messages
            from db.event_service import save_indexed_events
            save_indexed_events(
                b_id,
                b_path,
                event_clusters,
            )
            if not use_skeletons_mode:
                save_flagged_messages(
                    backup_id=b_id,
                    base_path=b_path,
                    flagged_items=full_flagged,
                    debug_files=c.DEBUG_FILES,
                )

        # Update the overall backup model and save to the status file
        backup.save()
        backup.finish_index_scenes(success=True)

    except Exception as e:
        backup.finish_index_scenes(success=False, error=str(e))
        raise exc.IndexScenesError("Failed to index all scenes") from e

    finally:
        t.log("base", f"\n# Scene indexing finished --- {time.time() - start_time:.2f} seconds --- #\n")

        # if there was an exception, raise it again
        if 'e' in locals() and e is not None:
            raise e

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Socrates scene/session/event indexer")
    parser.add_argument("--backup-id", type=str, default=None, help="Backup ID to index")
    parser.add_argument("--rescan-json", action="store_true", help="Rescan local Data/*.json files into skeletons.sqlite")
    cli_args = parser.parse_args(sys.argv[1:])

    try:
        if cli_args.backup_id:
            from models.backup_context import BackupContext
            with BackupContext.activate(backup_id=cli_args.backup_id):
                index_scenes(backup_id=cli_args.backup_id, rescan_json=cli_args.rescan_json)
        else:
            index_scenes(rescan_json=cli_args.rescan_json)
    except KeyboardInterrupt:
        t.log("error", "\nProcess interrupted by user.\n")
        try:
            backup = load_status(backup_id=cli_args.backup_id)
            backup.set_failed()
        except Exception:
            pass
        sys.exit(1)

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
        sys.exit(1)

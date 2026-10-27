import sys
from pathlib import Path
import time
from typing import Dict, List, Optional, Tuple, Any, Set
import utils.tricks as t
import utils.exceptions as exc
from find_character_scenes import (
    has_end_tag,
    has_start_tag,
    message_info,
    scene_info,
    MENTION_ONLY_PAT,
    END_TAG_SHORT_MSG_MAX_LEN,
    AUTO_SPLIT_MIN_TUPPERS,
    ROSTER_CHANGE_MIN_TUPPERS,
)
from models import ServerBackup, Category, Channel, Thread, SceneManager, Step
from db.models import SceneStatus, IssueKind
from db.session import has_sqlite_db
t.set_path()
from res import constants as c

################ File summary #################

"""
This module indexes all the scenes of the server backup using a deterministic two-phase indexer:
  - Phase 1: Explicit Boundary Segmentation based on message types, start tags, and end tags.
  - Phase 2: Roster-Interval Sub-Segmentation and Issue Detection (recursive separate roster
             auto-splits, start tag flagging, and roster change detection).

Main function: index_scenes()
    Iterates through categories and channels, segments scenes, and persists them to SQLite
    along with participants and detected curation issues (auto_split, soft_boundary).
"""

################# Functions #################


def load_status(backup_id: Optional[str] = None, backup_path: Optional[str] = None) -> ServerBackup:
    """Loads backup information and checks if it is ready to index."""
    try:
        backup = ServerBackup.load(scope="base", backup_id=backup_id, backup_path=backup_path)

        if backup.is_other_step_running(Step.INDEX_SCENES):
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
        if m.get("type") != "Default":
            continue

        # Skip messages with only a mention
        m_content = m.get("content", "") or ""
        if MENTION_ONLY_PAT.match(m_content.strip()):
            continue
        
        # Check the author and if the message has start or end tags
        aid = t.get_author_id(m)
        is_end = has_end_tag(m_content)
        is_start = has_start_tag(m_content)

        # Skip OOC setup posts, like images that describe the channel location:
        # If there's no "current block" (we're at the start), AND
        # The message has no start or end tags (it's not a scene message), AND
        # The message is from an OOC user (id >= 10000), AND
        # The message has attachments (it's likely an image)
        if (
            (not curr_block or all(not t.is_tupper(msg["author_id"]) for msg in curr_block))
            and not t.is_tupper(aid) and len(m.get("attachments", [])) > 0
            and not is_start and not is_end
        ):
            continue

        # If a "new" scene's first message is an end tag,
        # it means the previous scene had two messages with an end tag,
        # so we add this message to the previous block instead of this one
        if len(curr_block) == 0 and len(raw_blocks) > 0 and is_end and len(m_content.strip()) <= END_TAG_SHORT_MSG_MAX_LEN:
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

        # Get all text messages (no Discord status messages like pins, invites, etc.)
        default_msgs = [(i, m) for i, m in enumerate(messages) if m.get("type") == "Default"]
        if not default_msgs:
            return []

        # Find all the participants of the thread
        tupper_ids = set()
        non_tupper_ids = set()
        for _, m in default_msgs:
            aid = t.get_author_id(m)
            if aid is not None:
                if t.is_tupper(aid):
                    tupper_ids.add(aid)
                else:
                    non_tupper_ids.add(aid)

        # If there are no tuppers, it isn't a scene
        if not tupper_ids:
            return []

        characters = sorted(tupper_ids) + sorted(non_tupper_ids)
        first_idx, first_msg = default_msgs[0]
        last_idx, last_msg = default_msgs[-1]
        status = SceneStatus.CLOSED.value if has_end_tag(last_msg) else SceneStatus.OPEN.value

        start_msg = message_info(first_msg, channel, first_idx)
        end_msg = message_info(last_msg, channel, last_idx)
        scene = scene_info(start_msg, end_msg, f"{id_builder}1", 1, channel, status, characters)
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
            tupper_chars = set()
            non_tupper_chars = set()
            for m in sblk:
                aid = m["author_id"]
                if t.is_tupper(aid):
                    tupper_chars.add(aid)
                elif aid is not None:
                    non_tupper_chars.add(aid)

            # If a block has no tuppers, ignore it
            # Should already be false since we filtered it before, but doesn't hurt
            if not tupper_chars:
                continue

            characters = sorted(tupper_chars) + sorted(non_tupper_chars)

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
            )
            total_scenes.append(scene)

    # Sort all the scenes we found in this channel by their start index
    total_scenes.sort(key=lambda x: x["start"]["index"])

    # Assign each scene an index and an ID
    for i, scene in enumerate(total_scenes):
        scene["index"] = i + 1
        scene["id"] = f"{id_builder}{scene['index']}"

    return total_scenes



def process_channel(
    channel: Channel | Thread,
    id_builder: str,
    resolved_decisions: Optional[dict] = None,
) -> List[Dict[str, Any]]:
    file_path = (Path(c.DATA_FOLDER) / channel.path).as_posix()
    t.log("log", f"  Analysing {channel.name}...")

    # Load JSON channel from file
    json_data = t.load_from_json(file_path)

    # Find scene starts and ends for all characters
    scenes = find_all_scenes_in_channel(json_data, id_builder, resolved_decisions=resolved_decisions)

    if c.DEBUG_FILES:
        scenes_file = file_path.replace(".json", "_scenes.json")
        scenes_path = scenes_file.replace("/Threads/", "/Scenes/") if "/Threads/" in scenes_file else (Path(scenes_file).parent / "Scenes" / Path(scenes_file).name).as_posix()
        Path(scenes_path).parent.mkdir(parents=True, exist_ok=True)
        t.save_to_json(scenes, scenes_path)
        t.log("log", f"\tSaved {len(scenes)} scenes to {scenes_file}")

    # Update the model with the scene count
    channel.scenes = len(scenes)

    return scenes


def find_scenes_in_category(
    category: Category,
    resolved_decisions: Optional[dict] = None,
) -> List[Dict[str, Any]]:
    start_time = time.time()

    # Create an empty list to store scene starts and ends
    all_scenes = []

    t.log("info", f"\n    ## Finding scenes in {category.name}... ##")

    for channel in category.channels:
        scenes = process_channel(channel, f"{category.position}{channel.position}", resolved_decisions=resolved_decisions)
        all_scenes.extend(scenes)
        t.log("info", f"\t  Found {len(scenes)} scenes in '{scenes[0]['channel'] if len(scenes) > 0 else 'this channel'}', adding up to {len(all_scenes)} total scenes\n")

        for thread in channel.threads:
            scenes = process_channel(thread, f"{category.position}{channel.position}{thread.position}", resolved_decisions=resolved_decisions)
            all_scenes.extend(scenes)
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

    return all_scenes

################ Main function #################

def index_scenes(backup_id: Optional[str] = None, backup_path: Optional[str] = None):
    backup = load_status(backup_id=backup_id, backup_path=backup_path)
    b_id = backup_id or backup.backup_id or getattr(c, "BACKUP_ID", None)
    b_path = backup_path or backup.path or getattr(c, "BACKUP_BASE", None)

    start_time = time.time()
    try:
        t.log("base", f"\n# Indexing all the scenes in {c.BACKUP_NAME}... #\n")

        # Load existing resolved boundary decisions from SQLite so curation persists
        resolved_decisions = {}
        if has_sqlite_db(b_path):
            from db.curation_service import get_resolved_boundary_decisions
            resolved_decisions = get_resolved_boundary_decisions(b_id, b_path)
            if resolved_decisions:
                t.log("info", f"  Loaded {len(resolved_decisions)} resolved curation decisions.\n")

        full_scenes = []

        for category in backup.categories:
            if c.DEBUG_FILES:
                scenes_dir = Path(c.DATA_FOLDER) / category.path / "Scenes"
                if not scenes_dir.exists():
                    scenes_dir.mkdir(parents=True, exist_ok=True)

            scenes = find_scenes_in_category(category, resolved_decisions=resolved_decisions)
            full_scenes.extend(scenes)
            t.log("info", f"  Found {len(scenes)} scenes in {category.path}, adding up to {len(full_scenes)} total scenes\n")

        # sort the scenes by start time
        full_scenes.sort(key=lambda x: x["start"]["timestamp"])

        # update scene indexes and keep id in sync
        for i, scene in enumerate(full_scenes):
            scene["index"] = i + 1
            id_b = scene.get("id_builder", "")
            scene["id"] = f"{id_b}{scene['index']}"

        # Delegate saving to SQLite via SceneManager
        SceneManager.get_instance(backup_id=b_id, base_path=b_path).save_scenes(
            scenes=full_scenes,
            debug_files=c.DEBUG_FILES,
        )

        # Update the overall backup model and save to the status file
        backup.save()
        backup.finish_index_scenes(success=True)

    except Exception as e:
        backup.finish_index_scenes(success=False)
        raise exc.IndexScenesError("Failed to index all scenes") from e

    finally:
        t.log("base", f"\n# Scene indexing finished --- {time.time() - start_time:.2f} seconds --- #\n")

        # if there was an exception, raise it again
        if 'e' in locals() and e is not None:
            raise e

if __name__ == "__main__":
    
    try:
        index_scenes()
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
    
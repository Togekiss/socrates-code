from typing import Any, Dict, List, Optional, Tuple
import utils.tricks as t
from db.skeleton_models import (
    END_PAT1,
    END_PAT2,
    END_TAG_SHORT_MSG_MAX_LEN,
    EXCERPT_MAX_LEN,
    SEARCH_CONTENT_PREFIX_LEN,
    MONTHS,
    DAYS,
    TIMES,
    START_HEADER_PAT,
    MENTION_ONLY_PAT,
    has_end_tag,
    has_start_tag,
)

################ File summary #################

"""
This module provides boundary regex patterns, tag detection utilities, and scene/message
data constructors used across the scene indexing pipeline.

Note:
    Legacy standalone per-character scan functions (find_character_scenes) and backwards
    channel traversing algorithms have been deprecated and removed. All scene indexing is
    performed deterministically via index_scenes.py into SQLite.
"""

# Threshold constants for scene detection and heuristics
AUTO_SPLIT_MIN_TUPPERS = 2
ROSTER_CHANGE_MIN_TUPPERS = 4


"""
message_info(message, channel, i):
    Creates a JSON object with information about a message.

    Args:
        message (dict): Message info in JSON format
        channel (dict): Channel info in JSON format
        i (int): Index of the message in the channel
    Returns:
        dict: Message info in JSON format
"""
def message_info(message, channel, i):
    guild_id = channel.get("guild", {}).get("id", "")
    chan_id = channel.get("channel", {}).get("id", "")
    msg_id = message.get("id", "")

    return {
        "index": i,
        "id": msg_id,
        "timestamp": message.get("timestamp"),
        "authorID": message.get("author", {}).get("id"),
        "content": message.get("content"),
        "link": f"https://discord.com/channels/{guild_id}/{chan_id}/{msg_id}" if guild_id and chan_id and msg_id else "",
    }


"""
scene_info(start_message, end_message, scene_id, scene_index, channel, status, characters=[]):
    Creates a JSON object with information about a scene.

    Args:
        start_message (dict): Start message info in JSON format
        end_message (dict): End message info in JSON format
        scene_id (str): Scene ID
        scene_index (int): Scene sequential index
        channel (dict): Channel info in JSON format
        status (str): Scene status
        characters (list): List of character IDs in the scene
    Returns:
        dict: Scene info in JSON format
"""
def scene_info(start_message, end_message, scene_id, scene_index, channel, status, characters=None):
    if characters is None:
        characters = []

    chan_info = channel.get("channel", {})
    return {
        "index": scene_index,
        "id": scene_id,
        "category": chan_info.get("category", ""),
        "channel": chan_info.get("name", ""),
        "type": "channel" if chan_info.get("type") == "GuildTextChat" else "thread",
        "channelId": chan_info.get("id", ""),
        "status": status,
        "characters": characters,
        "start": start_message,
        "end": end_message,
    }


def extract_participants_from_messages(
    messages: List[Dict[str, Any]],
    include_non_tuppers: bool = True
) -> Tuple[List[int], List[Dict[str, Any]]]:
    """
    Extracts ordered characters and participant details from a chronological sequence of messages.
    Returns:
        (characters, participant_details)
        characters: List[int] (tupper IDs in order of first appearance, followed by non-tupper IDs if include_non_tuppers)
        participant_details: List[Dict[str, Any]] in apparition order:
            [{
                "char_id": int,
                "position": int,  # 0-indexed apparition position
                "first_message_id": str,
                "first_at": str,
                "last_message_id": str,
                "last_at": str,
            }]
    """
    tupper_order: List[int] = []
    tupper_details: Dict[int, Dict[str, Any]] = {}
    non_tupper_order: List[int] = []

    for msg in messages:
        aid = t.get_author_id(msg)
        if aid is None:
            continue
        try:
            aid_int = int(aid)
        except (ValueError, TypeError):
            continue

        msg_id = str(msg.get("id", ""))
        ts = msg.get("timestamp")

        if t.is_tupper(aid_int):
            if aid_int not in tupper_details:
                pos = len(tupper_order)
                tupper_order.append(aid_int)
                tupper_details[aid_int] = {
                    "char_id": aid_int,
                    "position": pos,
                    "first_message_id": msg_id,
                    "first_at": ts,
                    "last_message_id": msg_id,
                    "last_at": ts,
                    "message_count": 1,
                }
            else:
                tupper_details[aid_int]["last_message_id"] = msg_id
                tupper_details[aid_int]["last_at"] = ts
                tupper_details[aid_int]["message_count"] += 1
        else:
            if aid_int not in non_tupper_order:
                non_tupper_order.append(aid_int)

    characters = list(tupper_order)
    if include_non_tuppers:
        characters.extend(non_tupper_order)

    participant_details = [tupper_details[cid] for cid in tupper_order]
    return characters, participant_details

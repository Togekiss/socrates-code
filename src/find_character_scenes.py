import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple
import utils.tricks as t

################ File summary #################

"""
This module provides boundary regex patterns, tag detection utilities, and scene/message
data constructors used across the scene indexing pipeline.

Note:
    Legacy standalone per-character scan functions (find_character_scenes) and backwards
    channel traversing algorithms have been deprecated and removed. All scene indexing is
    performed deterministically via index_scenes.py into SQLite.
"""

# Strict pattern at the end of the message
END_PAT1 = re.compile(
    r"(?:`|```)[^\n]*(?:\n+[^\n]*)?\b(?:end|hold|close|dropped|offline|moved|moving|continu)\w*.{0,10}\n*(?:`|```)\n*(?:$|@[^\n]*|\W*)$",
    re.I
)
# Pattern that looks through the entire message for more flexible closing tags
END_PAT2 = re.compile(
    r"(?:moved to #|moving to #|continued in #|DM END|END DM|\[end\]|\[read\])",
    re.I
)

# Threshold constants for scene detection and heuristics
END_TAG_SHORT_MSG_MAX_LEN = 35
EXCERPT_MAX_LEN = 250
SEARCH_CONTENT_PREFIX_LEN = 300
AUTO_SPLIT_MIN_TUPPERS = 2
ROSTER_CHANGE_MIN_TUPPERS = 4

# Patterns to detect dates and times for the start of a scene
MONTHS = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|dezember)"
DAYS = r"(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
TIMES = r"(?:morning|afternoon|evening|night|midnight|noon|lunchtime|midday|\d{1,2}(?::\d{2})?\s*(?:am|pm))"

# Pattern for the start of a scene (only at the beginning of the message)
# Includes DM/Call openers and dates with times/days
START_HEADER_PAT = re.compile(
    r"^\s*(?:[x—\-=_*]{4,}\s*\n\s*)?(?:@\S+\s*)*(?:`+|\[|\*\*)\s*(?:"
    r"dm|direct\s+message|private\s+message|incoming\s+call|outgoing\s+call|video\s+call|call\s+(?:to|from|with)|continu(?:ed|ing)\s+from"
    rf"|(?:{DAYS}[,.\s]+)?(?:{MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?|\d{{1,2}}(?:st|nd|rd|th|\.)?\s+(?:of\s+)?{MONTHS}|(?:\d{{1,2}}[./-]\d{{1,2}})[,.\s]+{TIMES}|{TIMES}[,.\s]+\d{{1,2}}[./-]\d{{1,2}})"
    r")\b",
    re.I
)

# Pattern to detect messages that contain only tag mentions (single or multiple)
MENTION_ONLY_PAT = re.compile(r"^(?:\s*(?:<@&?[0-9]+>|@(?:deleted-role|unknown-role|[\w\.\-]+(?:\s+[\w\.\-]+)*))\s*)+$")


"""
has_end_tag(message):
    Checks if a message has an end of scene tag

    Args:
        message (dict | str): Message info in JSON format or raw string
    Returns:
        bool: True if the message has an end of scene tag, False otherwise
"""
def has_end_tag(message):
    # Convert the message content to normalized form
    content = message.get("content", "") if isinstance(message, dict) else (message or "")
    message_content = unicodedata.normalize("NFKD", str(content))

    return bool(END_PAT1.search(message_content) or END_PAT2.search(message_content))


"""
has_start_tag(message):
    Checks if a message has a start of scene tag

    Args:
        message (dict | str): Message info in JSON format or raw string
    Returns:
        bool: True if the message has a start of scene tag, False otherwise
"""
def has_start_tag(message):
    # Convert the first SEARCH_CONTENT_PREFIX_LEN characters of the message to normalized form
    content = message.get("content", "") if isinstance(message, dict) else (message or "")
    message_content = unicodedata.normalize("NFKD", str(content)[:SEARCH_CONTENT_PREFIX_LEN])

    return bool(START_HEADER_PAT.search(message_content))


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
                }
            else:
                tupper_details[aid_int]["last_message_id"] = msg_id
                tupper_details[aid_int]["last_at"] = ts
        else:
            if aid_int not in non_tupper_order:
                non_tupper_order.append(aid_int)

    characters = list(tupper_order)
    if include_non_tuppers:
        characters.extend(non_tupper_order)

    participant_details = [tupper_details[cid] for cid in tupper_order]
    return characters, participant_details

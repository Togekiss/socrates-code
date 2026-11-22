"""
Lightweight skeleton index models and 14-bit message flag bitmask for Backupless & Full modes.
Zero dependencies on other src/db/ or pipeline modules to avoid circular imports.
"""

from enum import IntFlag
import re
import unicodedata
from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, Column, DateTime, Integer, String
from sqlalchemy.orm import declarative_base

SkeletonBase = declarative_base()
CURRENT_SKELETON_SCHEMA_VERSION = 1
TUPPER_ID_MAX = 10000

# Threshold constants for scene boundary & tag detection
END_TAG_SHORT_MSG_MAX_LEN = 35
EXCERPT_MAX_LEN = 250
SEARCH_CONTENT_PREFIX_LEN = 300

# Scene end tag patterns
END_PAT1 = re.compile(
    r"(?:```|`)[^`\n]*(?:\n+[^`\n]*)?\b(?:end|hold|close|dropped|offline|moved|moving|continu)[A-Za-z0-9_]{0,20}[^\n`]{0,10}\n*(?:```|`)\s*(?:@[^\n]*|[^\w\n]*)?$",
    re.I,
)
END_PAT2 = re.compile(
    r"(?:moved to #|moving to #|continued in #|DM END|END DM|\[end\]|\[read\])",
    re.I,
)

# Scene start tag patterns
MONTHS = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|dezember)"
DAYS = r"(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
TIMES = r"(?:morning|afternoon|evening|night|midnight|noon|lunchtime|midday|\d{1,2}(?::\d{2})?\s*(?:am|pm))"

START_HEADER_PAT = re.compile(
    r"^\s*(?:[x—\-=_*]{4,}\s*\n\s*)?(?:@[^`\n\[\*\s]+\s+){0,10}(?:`+|\[|\*\*)\s*(?:"
    r"dm|direct\s+message|private\s+message|incoming\s+call|outgoing\s+call|video\s+call|call\s+(?:to|from|with)|continu(?:ed|ing)\s+from"
    rf"|(?:{DAYS}[,.\s]+)?(?:{MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?|\d{{1,2}}(?:st|nd|rd|th|\.)?\s+(?:of\s+)?{MONTHS}|(?:\d{{1,2}}[./-]\d{{1,2}})[,.\s]+{TIMES}|{TIMES}[,.\s]+\d{{1,2}}[./-]\d{{1,2}})"
    r")\b",
    re.I,
)

# Mention-only message pattern (linear O(n), no nested quantifiers)
MENTION_ONLY_PAT = re.compile(
    r"^\s*(?:<@&?[0-9]+>|@(?:deleted-role|unknown-role|[\w.-]+))"
    r"(?:\s+(?:<@&?[0-9]+>|@?(?:deleted-role|unknown-role|[\w.-]+)))*\s*$"
)

# Event end tag patterns
STRICT_EVENT_END_PAT = re.compile(r"(?:`{1,3}\s*EVENT\s+END\b|\[\s*EVENT\s+END\b)", re.IGNORECASE)
MOD_END_PAT = re.compile(r"(?:`{1,3}\s*(?:EVENT\s+END|END)\b|\[\s*(?:EVENT\s+END|END)\b)", re.IGNORECASE)

# Session status & continuation patterns
ONLINE_TAG_PAT = re.compile(r"`{1,3}[^`]*?\b(?:online|joined)\b[^`]*?`{1,3}", re.IGNORECASE | re.DOTALL)
OFFLINE_TAG_PAT = re.compile(r"`{1,3}[^`]*?\b(?:offline|idle|left|leaving)\b[^`]*?`{1,3}", re.IGNORECASE | re.DOTALL)
_APOLOGY_WORD_PAT = re.compile(r"\b(?:sorry|apolog\w*)\b", re.IGNORECASE)
_BACK_WORD_PAT = re.compile(r"\bback\b", re.IGNORECASE)
_DELAY_WORD_PAT = re.compile(r"\b(?:delay|wait|late|busy|distracted)\b", re.IGNORECASE)
_RETURN_PHRASE_PAT = re.compile(
    r"\b(?:i(?:['’]| m)?\s*back|,\s*back|finally\s+back|got\s+back|passed\s+out|asleep|dozed\s+off)\b",
    re.IGNORECASE,
)


def _extract_content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content", "") or "")
    return str(message or "")


def has_end_tag(message: Any) -> bool:
    """Checks if a message has an end-of-scene tag."""
    content = _extract_content(message)
    normalized = unicodedata.normalize("NFKD", content)
    tail = normalized[-SEARCH_CONTENT_PREFIX_LEN:]
    return bool(END_PAT1.search(tail) or END_PAT2.search(normalized))


def has_start_tag(message: Any) -> bool:
    """Checks if a message has a start-of-scene tag."""
    content = _extract_content(message)
    normalized = unicodedata.normalize("NFKD", content[:SEARCH_CONTENT_PREFIX_LEN])
    return bool(START_HEADER_PAT.search(normalized))


def has_online_tag(message: Any) -> bool:
    """Returns True if the message contains an [Online] or [Joined] tag in backticks."""
    return bool(ONLINE_TAG_PAT.search(_extract_content(message)))


def has_offline_tag(message: Any) -> bool:
    """Returns True if the message contains an [Offline] or [Idle] tag in backticks."""
    return bool(OFFLINE_TAG_PAT.search(_extract_content(message)))


def has_apology_continuation(message: Any) -> bool:
    """Returns True if the message indicates an apology or direct return to an ongoing scene."""
    content = _extract_content(message)
    if _RETURN_PHRASE_PAT.search(content):
        return True
    m_apology = _APOLOGY_WORD_PAT.search(content)
    if not m_apology:
        return False
    if _BACK_WORD_PAT.search(content):
        return True
    return bool(_DELAY_WORD_PAT.search(content, m_apology.end()))


def is_event_end_tag(msg: Dict[str, Any], author_id_override: Optional[int] = None) -> bool:
    """
    Detects whether a message is a moderator/Janitor event end marker.
    Ignores standard [END] tags posted by Tupperbox characters.
    """
    if not isinstance(msg, dict):
        return False
    content = str(msg.get("content", "") or "").strip()
    if not content:
        return False

    if len(content) <= 120 and STRICT_EVENT_END_PAT.search(content):
        return True

    author = msg.get("author") or {}
    raw_aid = author_id_override if author_id_override is not None else author.get("id")
    is_tupper_author = False
    if raw_aid is not None:
        try:
            is_tupper_author = int(raw_aid) < TUPPER_ID_MAX
        except (ValueError, TypeError):
            is_tupper_author = False

    author_name = str(author.get("name", "") or "").strip()
    if (not is_tupper_author or author_name == "Janitor") and len(content) <= 80:
        if MOD_END_PAT.search(content):
            return True

    return False


class SkeletonFlags(IntFlag):
    """14-bit bitmask stored in MessageSkeletonModel.flags (uint16)."""

    IS_DEFAULT = 1 << 0
    IS_TUPPER = 1 << 1
    IS_MENTION_ONLY = 1 << 2
    HAS_ATTACHMENT = 1 << 3
    IS_BANNER = 1 << 4
    HAS_START_TAG = 1 << 5
    HAS_END_TAG = 1 << 6
    IS_SHORT_END_TAG = 1 << 7
    IS_EVENT_END = 1 << 8
    IS_MOD_END = 1 << 9
    HAS_ONLINE_TAG = 1 << 10
    HAS_OFFLINE_TAG = 1 << 11
    HAS_APOLOGY = 1 << 12
    IS_DELETED = 1 << 13


def _resolve_author_id(msg: Dict[str, Any], author_id: Optional[int] = None) -> Optional[int]:
    if author_id is not None:
        try:
            return int(author_id)
        except (ValueError, TypeError):
            return None
    author = msg.get("author")
    if isinstance(author, dict) and author.get("id") is not None:
        try:
            return int(author["id"])
        except (ValueError, TypeError):
            return None
    return None


def compute_skeleton_flags(msg: Dict[str, Any], author_id: Optional[int] = None) -> int:
    """Computes the 14-bit SkeletonFlags integer bitmask from a message dictionary."""
    if not isinstance(msg, dict):
        return 0

    resolved_aid = _resolve_author_id(msg, author_id=author_id)
    is_tupper_val = resolved_aid is not None and resolved_aid < TUPPER_ID_MAX
    content = str(msg.get("content", "") or "")
    stripped = content.strip()
    attachments = msg.get("attachments") or []
    embeds = msg.get("embeds") or []

    flags = 0
    if msg.get("type") == "Default":
        flags |= SkeletonFlags.IS_DEFAULT
    if is_tupper_val:
        flags |= SkeletonFlags.IS_TUPPER
    if MENTION_ONLY_PAT.match(stripped):
        flags |= SkeletonFlags.IS_MENTION_ONLY
    if len(attachments) > 0:
        flags |= SkeletonFlags.HAS_ATTACHMENT

    end_tag = has_end_tag(content)
    event_end = is_event_end_tag(msg, author_id_override=resolved_aid)

    if (len(attachments) > 0 or len(embeds) > 0) and not is_tupper_val and not event_end:
        flags |= SkeletonFlags.IS_BANNER
    if has_start_tag(content):
        flags |= SkeletonFlags.HAS_START_TAG
    if end_tag:
        flags |= SkeletonFlags.HAS_END_TAG
        if len(stripped) <= END_TAG_SHORT_MSG_MAX_LEN:
            flags |= SkeletonFlags.IS_SHORT_END_TAG
    if event_end:
        flags |= SkeletonFlags.IS_EVENT_END
    if stripped and len(stripped) <= 80 and MOD_END_PAT.search(stripped):
        flags |= SkeletonFlags.IS_MOD_END
    if has_online_tag(content):
        flags |= SkeletonFlags.HAS_ONLINE_TAG
    if has_offline_tag(content):
        flags |= SkeletonFlags.HAS_OFFLINE_TAG
    if has_apology_continuation(content):
        flags |= SkeletonFlags.HAS_APOLOGY
    if msg.get("is_deleted"):
        flags |= SkeletonFlags.IS_DELETED

    return int(flags)


class MessageSkeletonModel(SkeletonBase):
    """Compact structural index of Discord messages stored in skeletons.sqlite (WITHOUT ROWID)."""

    __tablename__ = "message_skeletons"
    __table_args__ = {"sqlite_with_rowid": False}

    channel_discord_id = Column(BigInteger, primary_key=True)
    message_id = Column(BigInteger, primary_key=True)
    author_id = Column(BigInteger, nullable=False)
    timestamp_unix = Column(Integer, nullable=False)
    flags = Column(Integer, nullable=False)


class SkeletonSchemaVersionModel(SkeletonBase):
    """Schema version tracking table inside skeletons.sqlite."""

    __tablename__ = "skeleton_schema_version"

    version = Column(Integer, primary_key=True)
    applied_at = Column(DateTime(timezone=True), nullable=False)
    description = Column(String(255), nullable=True)

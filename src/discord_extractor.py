"""
Native Python Discord REST API v10 Extractor & DCE §7 Compatible Serializer.

Replaces external .NET / DiscordChatExporter CLI subprocesses for:
  - Fail-fast Bot token verification (`GET /users/@me`, `bot: True`)
  - Adaptive rate-limited HTTP client (40 req/s global token bucket + per-route buckets + 429/5xx retries)
  - Server topology, thread, and guild member discovery (`--relative-positions` & event-slot consolidation)
  - 24-hour Snowflake edit lookback & `IS_DELETED` detection
  - Single-pass markdown formatting, codeblock-aware `inlineEmojis`, Twitter embed merge & DCE §7 JSON parity
  - Dual storage mode support (`"backupless"` zero-JSON vs `"full"` atomic in-place JSON extension)
  - Targeted curation hydration (`fetch_message` & `fetch_message_range`)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

import httpx

import utils.exceptions as exc
import utils.tricks as t
from utils.path_safety import (
    category_matches,
    expand_category_names,
    strip_category_prefix,
    validate_snowflake,
)
from db.skeleton_models import MessageSkeletonModel, SkeletonFlags
from db.session import has_skeleton_db, skeleton_db_session

DISCORD_API_BASE = "https://discord.com/api/v10/"
DISCORD_EPOCH_MS = 1420070400000
MAX_HTTP_RETRIES = 8
GLOBAL_RATE_LIMIT_RPS = 40.0

CHANNEL_TYPE_NAMES: Dict[int, str] = {
    0: "GuildTextChat",
    1: "DirectTextChat",
    2: "GuildVoiceChat",
    3: "DirectGroupTextChat",
    4: "GuildCategory",
    5: "GuildNews",
    10: "GuildNewsThread",
    11: "GuildPublicThread",
    12: "GuildPrivateThread",
    13: "GuildStageVoice",
    14: "GuildDirectory",
    15: "GuildForum",
}

MESSAGE_TYPE_NAMES: Dict[int, str] = {
    0: "Default",
    1: "RecipientAdd",
    2: "RecipientRemove",
    3: "Call",
    4: "ChannelNameChange",
    5: "ChannelIconChange",
    6: "ChannelPinnedMessage",
    7: "GuildMemberJoin",
    18: "ThreadCreated",
    19: "Reply",
    21: "ThreadStarterMessage",
    46: "PollResult",
}

SYSTEM_NOTIFICATION_TYPES: Set[int] = {1, 2, 3, 4, 5, 6, 7, 18, 46}

STICKER_FORMATS: Dict[int, Tuple[str, str]] = {
    1: ("Png", "png"),
    2: ("Apng", "png"),
    3: ("Lottie", "json"),
    4: ("Gif", "gif"),
}

_IGNORED_EMOJI_CHARS = frozenset("\u26a7\u2640\u2642\u2695\u267e\u00a9\u00ae\u2122")

# Single-pass markdown formatter token regex (first-earliest-match-wins)
_MARKDOWN_TOKEN_RE = re.compile(
    r"<@!?(\d+)>|<#!?(\d+)>|<@&(\d+)>|<(a)?:([^:\n]+?):(\d+?)>|<t:(-?\d+)(?::(\w))?>"
)

# Inline emoji extraction helpers
_CODEBLOCK_OR_ESCAPE_RE = re.compile(r"```[\s\S]*?```|`[^`\n]+`|\\.", re.MULTILINE)
_CUSTOM_EMOJI_RE = re.compile(r"<(a)?:([^:\n]+?):(\d+?)>")
_SHORTCODE_EMOJI_RE = re.compile(r":([\w_]+):")
_INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_EMOJI_INDEX_LOCK = threading.Lock()
_EMOJI_INDEX_CACHE: Optional[Tuple[Dict[str, str], Dict[str, str], Optional[re.Pattern]]] = None


class ChannelAccessError(exc.DownloadExportError):
    """Non-fatal channel-level access error (HTTP 403/404)."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _load_emoji_index() -> Tuple[Dict[str, str], Dict[str, str], Optional[re.Pattern]]:
    """Loads bundled res/emoji_index.json once and compiles longest-first Unicode matcher."""
    global _EMOJI_INDEX_CACHE
    with _EMOJI_INDEX_LOCK:
        if _EMOJI_INDEX_CACHE is not None:
            return _EMOJI_INDEX_CACHE

        root_dir = Path(__file__).resolve().parent.parent
        candidates = [
            root_dir / "res" / "emoji_index.json",
            root_dir / "src" / "res" / "emoji_index.json",
        ]
        unicode_to_code: Dict[str, str] = {}
        for cand in candidates:
            if cand.is_file():
                try:
                    raw = json.loads(cand.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        unicode_to_code = {str(k): str(v) for k, v in raw.items() if k and v}
                except Exception:
                    unicode_to_code = {}
                break

        code_to_unicode: Dict[str, str] = {}
        for u_str, code in unicode_to_code.items():
            code_to_unicode.setdefault(code, u_str)

        if unicode_to_code:
            ordered_keys = sorted(unicode_to_code.keys(), key=len, reverse=True)
            unicode_re = re.compile("|".join(re.escape(k) for k in ordered_keys))
        else:
            unicode_re = None

        _EMOJI_INDEX_CACHE = (unicode_to_code, code_to_unicode, unicode_re)
        return _EMOJI_INDEX_CACHE


def escape_dce_filename(name: str) -> str:
    """Escapes OS-invalid filename characters matching DCE's escape_file_name."""
    cleaned = _INVALID_FILENAME_RE.sub("_", str(name or "")).rstrip(". ")
    if not cleaned or cleaned in {".", ".."}:
        return "unnamed"
    return cleaned


def resolve_bot_token(token: Optional[str] = None) -> str:
    """Resolves Discord Bot token, stripping an accidental 'Bot ' prefix."""
    if (
        token is None
        and "DISCORD_TOKEN" not in os.environ
        and "unittest" not in sys.modules
        and os.environ.get("SOCRATES_TEST_SUITE", "").strip() != "1"
    ):
        try:
            from dotenv import load_dotenv
            load_dotenv(override=False)
        except Exception:
            pass
    raw = token if token is not None else os.environ.get("DISCORD_TOKEN", "")
    cleaned = str(raw or "").strip()
    if cleaned.lower().startswith("bot "):
        cleaned = cleaned[4:].strip()
    if not cleaned:
        raise exc.InvalidBotTokenError("DISCORD_TOKEN is missing or empty; a valid Bot token is required.")
    return cleaned


def snowflake_to_datetime(snowflake: Any) -> datetime:
    """Converts a Discord Snowflake ID to a timezone-aware UTC datetime."""
    unix_ms = (int(snowflake) >> 22) + DISCORD_EPOCH_MS
    return datetime.fromtimestamp(unix_ms / 1000.0, tz=timezone.utc)


def datetime_to_snowflake(dt: datetime) -> int:
    """Converts a datetime to a Discord Snowflake ID."""
    dt_utc = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    unix_ms = int(dt_utc.timestamp() * 1000)
    return max(0, (unix_ms - DISCORD_EPOCH_MS) << 22)


def compute_24h_lookback_snowflake(last_synced_at: Optional[datetime]) -> int:
    """Computes ((last_sync_ms - 86_400_000) - 1420070400000) << 22 clamped >= 0."""
    if last_synced_at is None:
        return 0
    dt_utc = (
        last_synced_at.replace(tzinfo=timezone.utc)
        if last_synced_at.tzinfo is None
        else last_synced_at.astimezone(timezone.utc)
    )
    last_sync_ms = int(dt_utc.timestamp() * 1000)
    return max(0, ((last_sync_ms - 86_400_000) - DISCORD_EPOCH_MS) << 22)


def should_skip_channel_sync(
    discord_last_message_id: Optional[str],
    stored_last_message_id: Optional[str],
    last_synced_at: Optional[datetime],
) -> bool:
    """
    Determines whether HTTP history fetch can be skipped for a quiet channel:
    True when stored_last_message_id exists, discord_last_message_id <= stored_last_message_id
    (or channel is empty and was already synced), and stored_last_message_id < cutoff_24h_snowflake.
    """
    if last_synced_at is None:
        return False
    if not stored_last_message_id:
        return discord_last_message_id is None
    if not str(stored_last_message_id).isdigit():
        return False
    stored_int = int(stored_last_message_id)
    if discord_last_message_id is not None and str(discord_last_message_id).isdigit():
        if int(discord_last_message_id) > stored_int:
            return False
    cutoff = compute_24h_lookback_snowflake(last_synced_at)
    return stored_int < cutoff


def compute_effective_after_snowflake(
    stored_last_message_id: Optional[str],
    last_synced_at: Optional[datetime],
) -> str:
    """Computes effective_after = min(stored_last_id, cutoff_24h_snowflake), or '0' on first sync."""
    if not stored_last_message_id or not str(stored_last_message_id).isdigit():
        return "0"
    stored_int = int(stored_last_message_id)
    if last_synced_at is None:
        return str(stored_int)
    cutoff = compute_24h_lookback_snowflake(last_synced_at)
    return str(min(stored_int, cutoff))


def format_dotnet_utc_iso(value: Any) -> Optional[str]:
    """
    Formats a datetime or ISO-8601 string in UTC extended format matching .NET Utf8JsonWriter:
    e.g. '2021-07-14T21:00:00+00:00' or '2021-07-14T21:00:00.123+00:00'.
    """
    if value is None or value == "":
        return None
    dt = t.parse_datetime(value)
    if dt is None:
        return None
    dt_utc = dt.astimezone(timezone.utc)
    base = dt_utc.strftime("%Y-%m-%dT%H:%M:%S")
    if dt_utc.microsecond == 0:
        return f"{base}+00:00"
    frac = f"{dt_utc.microsecond:06d}".rstrip("0")
    return f"{base}.{frac}+00:00"


def unicode_to_twemoji_url(emoji_str: str) -> str:
    """Computes Twemoji SVG URL following DCE's ZWJ/FE0F rules."""
    cps = [ord(ch) for ch in emoji_str]
    if 0x200D not in cps:
        cps = [cp for cp in cps if cp != 0xFE0F]
    hex_parts = [f"{cp:x}" for cp in cps]
    return f"https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/svg/{'-'.join(hex_parts)}.svg"


def _cdn_ext(hash_val: str) -> str:
    return "gif" if str(hash_val).startswith("a_") else "png"


def _guild_icon_url(guild_id: str, icon_hash: Optional[str]) -> str:
    if icon_hash and str(icon_hash).strip():
        h = str(icon_hash).strip()
        return f"https://cdn.discordapp.com/icons/{guild_id}/{h}.{_cdn_ext(h)}?size=512"
    return "https://cdn.discordapp.com/embed/avatars/0.png"


def _channel_icon_url(channel_id: str, icon_hash: Optional[str]) -> Optional[str]:
    if icon_hash and str(icon_hash).strip():
        h = str(icon_hash).strip()
        return f"https://cdn.discordapp.com/channel-icons/{channel_id}/{h}.{_cdn_ext(h)}?size=512"
    return None


def _color_hex(color_val: Any) -> Optional[str]:
    if color_val is None:
        return None
    try:
        c_int = int(color_val)
    except (ValueError, TypeError):
        return None
    if c_int <= 0:
        return None
    return f"#{c_int & 0xFFFFFF:06X}"


def _format_discord_timestamp(ts_str: str, style: Optional[str]) -> str:
    try:
        ts_val = int(ts_str)
        dt = datetime.fromtimestamp(ts_val, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return "Invalid date"

    eff_style = style or "f"
    if style in (None, "r", "R"):
        return dt.strftime("%d/%m/%Y %H:%M")
    if eff_style == "t":
        return dt.strftime("%H:%M")
    if eff_style == "T":
        return dt.strftime("%H:%M:%S")
    if eff_style == "d":
        return dt.strftime("%d/%m/%Y")
    if eff_style == "D":
        return dt.strftime("%d %B %Y")
    if eff_style == "f":
        return dt.strftime("%d %B %Y %H:%M")
    if eff_style == "F":
        return dt.strftime("%d %B %Y %H:%M:%S")
    return "Invalid date"


def _resolve_mention_username(
    user_id: str,
    members_by_id: Dict[str, Dict[str, Any]],
    inline_users_by_id: Dict[str, Dict[str, Any]],
) -> str:
    """
    Resolves a space-free username / display-name fallback for <@id> mentions so
    START_HEADER_PAT and MENTION_ONLY_PAT never break on spaces in server nicknames.
    """
    member = members_by_id.get(user_id)
    user = (member.get("user") if isinstance(member, dict) else None) or inline_users_by_id.get(user_id)

    if isinstance(user, dict):
        uname = str(user.get("username") or user.get("name") or "").strip()
        if uname:
            no_ws = re.sub(r"\s+", "", uname)
            if no_ws:
                return no_ws
        gname = str(user.get("global_name") or "").strip()
        if gname:
            no_ws = re.sub(r"\s+", "", gname)
            if no_ws:
                return no_ws

    if isinstance(member, dict):
        nick = str(member.get("nick") or "").strip()
        if nick:
            no_ws = re.sub(r"\s+", "", nick)
            if no_ws:
                return no_ws

    return "Unknown"


def format_content(
    text: Optional[str],
    *,
    channels_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    roles_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    members_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    inline_users_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """Single-pass regex formatter converting Discord mention/emoji/timestamp tokens."""
    if not text:
        return ""
    ch_map = channels_by_id or {}
    role_map = roles_by_id or {}
    mem_map = members_by_id or {}
    usr_map = inline_users_by_id or {}

    def _replace(match: re.Match) -> str:
        uid, cid, rid, _anim, ename, _eid, ts_val, ts_style = match.groups()
        if uid is not None:
            return f"@{_resolve_mention_username(uid, mem_map, usr_map)}"
        if cid is not None:
            ch = ch_map.get(cid)
            if not ch:
                return "#deleted-channel"
            ch_name = str(ch.get("name") or cid)
            ch_type = int(ch.get("type", 0)) if ch.get("type") is not None else 0
            suffix = " [voice]" if ch_type in (2, 13) else ""
            return f"#{ch_name}{suffix}"
        if rid is not None:
            role = role_map.get(rid)
            if not role:
                return "@deleted-role"
            return f"@{role.get('name') or 'deleted-role'}"
        if ename is not None:
            return f":{ename}:"
        if ts_val is not None:
            return _format_discord_timestamp(ts_val, ts_style)
        return match.group(0)

    return _MARKDOWN_TOKEN_RE.sub(_replace, str(text))


def extract_inline_emojis(raw_text: Optional[str]) -> List[Dict[str, Any]]:
    """
    Extracts custom, Unicode, and shortcode emojis from raw markdown text,
    ignoring code blocks (```...``` / `...`), backslash escapes, and ignored symbols.
    Deduplicates by emoji.name preserving first occurrence.
    """
    if not raw_text:
        return []

    unicode_to_code, code_to_unicode, unicode_re = _load_emoji_index()
    stripped = _CODEBLOCK_OR_ESCAPE_RE.sub(" ", str(raw_text))

    # Build combined match stream in left-to-right order
    found: List[Tuple[int, Dict[str, Any]]] = []
    occupied: List[Tuple[int, int]] = []

    for m in _CUSTOM_EMOJI_RE.finditer(stripped):
        occupied.append((m.start(), m.end()))
        is_anim = bool(m.group(1))
        e_name = m.group(2)
        e_id = m.group(3)
        found.append((
            m.start(),
            {
                "id": e_id,
                "name": e_name,
                "code": e_name,
                "isAnimated": is_anim,
                "imageUrl": f"https://cdn.discordapp.com/emojis/{e_id}.{'gif' if is_anim else 'png'}",
            },
        ))

    def _overlaps(start: int, end: int) -> bool:
        return any(not (end <= o_s or start >= o_e) for o_s, o_e in occupied)

    for m in _SHORTCODE_EMOJI_RE.finditer(stripped):
        if _overlaps(m.start(), m.end()):
            continue
        code = m.group(1)
        u_str = code_to_unicode.get(code)
        if u_str:
            occupied.append((m.start(), m.end()))
            found.append((
                m.start(),
                {
                    "id": None,
                    "name": u_str,
                    "code": code,
                    "isAnimated": False,
                    "imageUrl": unicode_to_twemoji_url(u_str),
                },
            ))

    if unicode_re is not None:
        for m in unicode_re.finditer(stripped):
            if _overlaps(m.start(), m.end()):
                continue
            u_str = m.group(0)
            if u_str in _IGNORED_EMOJI_CHARS:
                continue
            code = unicode_to_code.get(u_str, u_str)
            found.append((
                m.start(),
                {
                    "id": None,
                    "name": u_str,
                    "code": code,
                    "isAnimated": False,
                    "imageUrl": unicode_to_twemoji_url(u_str),
                },
            ))

    found.sort(key=lambda item: item[0])
    deduped: List[Dict[str, Any]] = []
    seen_names: Set[str] = set()
    for _, emoji_obj in found:
        name_key = str(emoji_obj["name"])
        if name_key not in seen_names:
            seen_names.add(name_key)
            deduped.append(emoji_obj)
    return deduped


def _serialize_embed_image_obj(img: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(img, dict):
        return None
    raw_url = img.get("url")
    proxy_url = img.get("proxy_url")
    out: Dict[str, Any] = {}
    effective_url = proxy_url or raw_url
    if effective_url and str(effective_url).strip():
        out["url"] = str(effective_url)
    if raw_url and str(raw_url).strip():
        out["canonicalUrl"] = str(raw_url)
    out["width"] = img.get("width")
    out["height"] = img.get("height")
    return out


def merge_twitter_embeds(raw_embeds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Implements DCE's Twitter multi-image embed merging workaround.
    Returns serialized-ready intermediate embed dicts with `_images` lists.
    """
    if not raw_embeds:
        return []

    grouped: List[Dict[str, Any]] = []
    for raw in raw_embeds:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        img_obj = item.get("image")
        item["_images"] = [img_obj] if isinstance(img_obj, dict) and img_obj else []
        grouped.append(item)

    merged: List[Dict[str, Any]] = []
    for emb in grouped:
        if merged:
            prev = merged[-1]
            prev_url = str(prev.get("url") or "")
            cur_url = str(emb.get("url") or "")
            if (
                "://twitter.com/" in prev_url.lower()
                and cur_url == prev_url
                and not emb.get("timestamp")
                and not emb.get("author")
                and emb.get("color") is None
                and not str(emb.get("description") or "").strip()
                and not emb.get("fields")
                and len(emb["_images"]) == 1
                and not emb.get("footer")
            ):
                prev["_images"].extend(emb["_images"])
                continue
        merged.append(emb)

    return merged


def serialize_user(
    user: Optional[Dict[str, Any]],
    member: Optional[Dict[str, Any]] = None,
    roles_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    guild_id: str = "",
    include_roles: bool = True,
) -> Dict[str, Any]:
    """Serializes a Discord user + optional guild member into a DCE §7 User object."""
    u = user or {}
    uid = str(u.get("id") or "0")
    username = str(u.get("username") or u.get("name") or uid)
    raw_disc = str(u.get("discriminator") or "").strip()
    disc_num: Optional[int] = None
    if raw_disc.isdigit() and int(raw_disc) != 0:
        disc_num = int(raw_disc)
    disc_str = f"{disc_num:04d}" if disc_num is not None else "0000"

    g_name = str(u.get("global_name") or "").strip()
    display_name = g_name if g_name else username
    m_nick = str(member.get("nick") or "").strip() if isinstance(member, dict) else ""
    nickname = m_nick if m_nick else display_name

    # Role sorting & color resolution
    role_map = roles_by_id or {}
    sorted_roles: List[Dict[str, Any]] = []
    if isinstance(member, dict):
        for rid in member.get("roles") or []:
            r_obj = role_map.get(str(rid))
            if r_obj:
                sorted_roles.append(r_obj)
    sorted_roles.sort(key=lambda r: int(r.get("position", 0)), reverse=True)

    user_color: Optional[str] = None
    for r in sorted_roles:
        c_hex = _color_hex(r.get("color"))
        if c_hex is not None:
            user_color = c_hex
            break

    # Avatar URL resolution
    m_avatar = str(member.get("avatar") or "").strip() if isinstance(member, dict) else ""
    u_avatar = str(u.get("avatar") or "").strip()
    if m_avatar and guild_id:
        avatar_url = f"https://cdn.discordapp.com/guilds/{guild_id}/users/{uid}/avatars/{m_avatar}.{_cdn_ext(m_avatar)}?size=512"
    elif u_avatar:
        avatar_url = f"https://cdn.discordapp.com/avatars/{uid}/{u_avatar}.{_cdn_ext(u_avatar)}?size=512"
    else:
        if disc_num is not None:
            idx = disc_num % 5
        else:
            idx = ((int(uid) >> 22) % 6) if uid.isdigit() else 0
        avatar_url = f"https://cdn.discordapp.com/embed/avatars/{idx}.png"

    result: Dict[str, Any] = {
        "id": uid,
        "name": username,
        "discriminator": disc_str,
        "nickname": nickname,
        "color": user_color,
        "isBot": bool(u.get("bot", u.get("isBot", False))),
    }
    if include_roles:
        result["roles"] = [
            {
                "id": str(r.get("id", "")),
                "name": str(r.get("name", "")),
                "color": _color_hex(r.get("color")),
                "position": int(r.get("position", 0)),
            }
            for r in sorted_roles
        ]
    result["avatarUrl"] = avatar_url
    return result


def serialize_embed(
    raw_embed: Dict[str, Any],
    *,
    channels_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    roles_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    members_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    inline_users_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Serializes a Discord API embed into a DCE §7 Embed object with exact conditional omissions."""
    fmt = lambda txt: format_content(  # noqa: E731
        txt,
        channels_by_id=channels_by_id,
        roles_by_id=roles_by_id,
        members_by_id=members_by_id,
        inline_users_by_id=inline_users_by_id,
    )
    raw_desc = str(raw_embed.get("description") or "")
    out: Dict[str, Any] = {
        "title": fmt(raw_embed.get("title") or ""),
        "url": raw_embed.get("url"),
        "timestamp": format_dotnet_utc_iso(raw_embed.get("timestamp")),
        "description": fmt(raw_desc),
    }

    c_hex = _color_hex(raw_embed.get("color"))
    if c_hex is not None:
        out["color"] = c_hex

    author = raw_embed.get("author")
    if isinstance(author, dict):
        a_out: Dict[str, Any] = {
            "name": str(author.get("name") or ""),
            "url": author.get("url"),
        }
        icon_raw = author.get("icon_url")
        icon_proxy = author.get("proxy_icon_url")
        if icon_raw and str(icon_raw).strip():
            eff_icon = icon_proxy if (icon_proxy and str(icon_proxy).strip()) else icon_raw
            a_out["iconUrl"] = str(eff_icon)
            a_out["iconCanonicalUrl"] = str(icon_raw)
        out["author"] = a_out

    thumb = _serialize_embed_image_obj(raw_embed.get("thumbnail"))
    if thumb is not None:
        out["thumbnail"] = thumb

    raw_images = raw_embed.get("_images")
    if raw_images is None:
        img = raw_embed.get("image")
        raw_images = [img] if isinstance(img, dict) and img else []
    ser_images = [s for s in (_serialize_embed_image_obj(im) for im in raw_images) if s is not None]

    if ser_images:
        out["image"] = ser_images[0]

    vid = _serialize_embed_image_obj(raw_embed.get("video"))
    if vid is not None:
        out["video"] = vid

    footer = raw_embed.get("footer")
    if isinstance(footer, dict):
        f_out: Dict[str, Any] = {
            "text": str(footer.get("text") or ""),
        }
        f_icon_raw = footer.get("icon_url")
        f_icon_proxy = footer.get("proxy_icon_url")
        if f_icon_raw and str(f_icon_raw).strip():
            eff_f = f_icon_proxy if (f_icon_proxy and str(f_icon_proxy).strip()) else f_icon_raw
            f_out["iconUrl"] = str(eff_f)
            f_out["iconCanonicalUrl"] = str(f_icon_raw)
        out["footer"] = f_out

    out["images"] = ser_images
    out["fields"] = [
        {
            "name": fmt(fld.get("name") or ""),
            "value": fmt(fld.get("value") or ""),
            "isInline": bool(fld.get("inline", False)),
        }
        for fld in (raw_embed.get("fields") or [])
        if isinstance(fld, dict)
    ]
    out["inlineEmojis"] = extract_inline_emojis(raw_desc) if raw_desc.strip() else []
    return out


def _format_system_notification(
    raw_msg: Dict[str, Any],
    msg_type_int: int,
    author_serialized: Dict[str, Any],
    mentions_serialized: List[Dict[str, Any]],
) -> str:
    """Formats literal fallback content for DCE system notification message types."""
    first_mention_nick = mentions_serialized[0]["nickname"] if mentions_serialized else None
    first_mention_id = mentions_serialized[0]["id"] if mentions_serialized else None
    author_id = str((raw_msg.get("author") or {}).get("id") or "")
    author_display = author_serialized.get("nickname") or author_serialized.get("name") or "Unknown"

    if msg_type_int == 1:  # RecipientAdd
        return f"Added {first_mention_nick} to the group." if first_mention_nick else "Added a recipient."
    if msg_type_int == 2:  # RecipientRemove
        if first_mention_id and first_mention_id == author_id:
            return "Left the group."
        return f"Removed {first_mention_nick} from the group." if first_mention_nick else "Removed a recipient."
    if msg_type_int == 3:  # Call
        call_obj = raw_msg.get("call") or {}
        ended_dt = t.parse_datetime(call_obj.get("ended_timestamp"))
        start_dt = t.parse_datetime(raw_msg.get("timestamp"))
        if ended_dt and start_dt:
            mins = max(0, round((ended_dt - start_dt).total_seconds() / 60.0))
            return f"Started a call that lasted {mins:,} minutes."
        return "Started a call that lasted 0 minutes."
    if msg_type_int == 4:  # ChannelNameChange
        raw_c = str(raw_msg.get("content") or "")
        return f"Changed the channel name: {raw_c}" if raw_c.strip() else "Changed the channel name."
    if msg_type_int == 5:  # ChannelIconChange
        return "Changed the channel icon."
    if msg_type_int == 6:  # ChannelPinnedMessage
        return "Pinned a message."
    if msg_type_int == 7:  # GuildMemberJoin
        return "Joined the server."
    if msg_type_int == 18:  # ThreadCreated
        return "Started a thread."
    if msg_type_int == 46:  # PollResult
        for emb in raw_msg.get("embeds") or []:
            if isinstance(emb, dict) and emb.get("type") == "poll_result":
                q_text = ""
                for fld in emb.get("fields") or []:
                    if isinstance(fld, dict) and fld.get("name") == "poll_question_text":
                        q_text = str(fld.get("value") or "").strip()
                        break
                if q_text:
                    return f"{author_display}'s poll {q_text} has closed."
                return f"{author_display}'s poll has closed."
        return "A poll has closed."
    return str(raw_msg.get("content") or "")


def serialize_message(
    raw_msg: Dict[str, Any],
    *,
    guild_id: str = "",
    channels_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    roles_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    members_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Serializes a raw Discord REST API v10 message into DCE §7 JSON format."""
    mem_map = members_by_id or {}
    role_map = roles_by_id or {}
    ch_map = channels_by_id or {}

    inline_users_by_id: Dict[str, Dict[str, Any]] = {}
    raw_author = raw_msg.get("author") or {}
    if isinstance(raw_author, dict) and raw_author.get("id"):
        inline_users_by_id[str(raw_author["id"])] = raw_author
    for m_usr in raw_msg.get("mentions") or []:
        if isinstance(m_usr, dict) and m_usr.get("id"):
            inline_users_by_id[str(m_usr["id"])] = m_usr
    ref_msg = raw_msg.get("referenced_message")
    if isinstance(ref_msg, dict) and isinstance(ref_msg.get("author"), dict) and ref_msg["author"].get("id"):
        inline_users_by_id[str(ref_msg["author"]["id"])] = ref_msg["author"]
    raw_inter = raw_msg.get("interaction") or raw_msg.get("interaction_metadata")
    if isinstance(raw_inter, dict) and isinstance(raw_inter.get("user"), dict) and raw_inter["user"].get("id"):
        inline_users_by_id[str(raw_inter["user"]["id"])] = raw_inter["user"]

    author_id = str(raw_author.get("id") or "0")
    author_serialized = serialize_user(
        raw_author,
        member=mem_map.get(author_id),
        roles_by_id=role_map,
        guild_id=guild_id,
        include_roles=True,
    )

    mentions_serialized: List[Dict[str, Any]] = []
    for m_usr in raw_msg.get("mentions") or []:
        if not isinstance(m_usr, dict):
            continue
        m_uid = str(m_usr.get("id") or "0")
        mentions_serialized.append(
            serialize_user(
                m_usr,
                member=mem_map.get(m_uid),
                roles_by_id=role_map,
                guild_id=guild_id,
                include_roles=True,
            )
        )

    raw_type = raw_msg.get("type", 0)
    try:
        msg_type_int = int(raw_type)
    except (ValueError, TypeError):
        msg_type_int = 0
    msg_type_str = MESSAGE_TYPE_NAMES.get(msg_type_int, str(raw_type))

    raw_content = str(raw_msg.get("content") or "")
    if msg_type_int in SYSTEM_NOTIFICATION_TYPES:
        formatted_content = _format_system_notification(
            raw_msg, msg_type_int, author_serialized, mentions_serialized
        )
        inline_emojis: List[Dict[str, Any]] = []
    else:
        formatted_content = format_content(
            raw_content,
            channels_by_id=ch_map,
            roles_by_id=role_map,
            members_by_id=mem_map,
            inline_users_by_id=inline_users_by_id,
        )
        inline_emojis = extract_inline_emojis(raw_content)

    call_obj = raw_msg.get("call") if isinstance(raw_msg.get("call"), dict) else {}
    call_ended_iso = format_dotnet_utc_iso(call_obj.get("ended_timestamp"))

    attachments_ser = [
        {
            "id": str(att.get("id") or ""),
            "url": str(att.get("url") or ""),
            "fileName": str(att.get("filename") or att.get("fileName") or ""),
            "fileSizeBytes": int(att.get("size", att.get("fileSizeBytes", 0)) or 0),
        }
        for att in (raw_msg.get("attachments") or [])
        if isinstance(att, dict)
    ]

    merged_embeds = merge_twitter_embeds(raw_msg.get("embeds") or [])
    embeds_ser = [
        serialize_embed(
            emb,
            channels_by_id=ch_map,
            roles_by_id=role_map,
            members_by_id=mem_map,
            inline_users_by_id=inline_users_by_id,
        )
        for emb in merged_embeds
    ]

    stickers_ser: List[Dict[str, Any]] = []
    for st in raw_msg.get("sticker_items") or raw_msg.get("stickers") or []:
        if not isinstance(st, dict):
            continue
        st_id = str(st.get("id") or "")
        fmt_type = int(st.get("format_type", 1) or 1)
        fmt_name, fmt_ext = STICKER_FORMATS.get(fmt_type, ("Png", "png"))
        stickers_ser.append({
            "id": st_id,
            "name": str(st.get("name") or ""),
            "format": fmt_name,
            "sourceUrl": f"https://cdn.discordapp.com/stickers/{st_id}.{fmt_ext}",
        })

    unicode_to_code, _, _ = _load_emoji_index()
    reactions_ser: List[Dict[str, Any]] = []
    for react in raw_msg.get("reactions") or []:
        if not isinstance(react, dict):
            continue
        em = react.get("emoji") or {}
        em_id = str(em["id"]) if em.get("id") else None
        em_name = str(em.get("name") or "").strip() or "Unknown Emoji"
        em_anim = bool(em.get("animated", False))
        if em_id:
            em_code = em_name
            em_url = f"https://cdn.discordapp.com/emojis/{em_id}.{'gif' if em_anim else 'png'}"
        else:
            em_code = unicode_to_code.get(em_name, em_name)
            em_url = unicode_to_twemoji_url(em_name)
        reactions_ser.append({
            "emoji": {
                "id": em_id,
                "name": em_name,
                "code": em_code,
                "isAnimated": em_anim,
                "imageUrl": em_url,
            },
            "count": int(react.get("count", 0) or 0),
            "users": [],
        })

    out: Dict[str, Any] = {
        "id": str(raw_msg.get("id") or ""),
        "type": msg_type_str,
        "timestamp": format_dotnet_utc_iso(raw_msg.get("timestamp")),
        "timestampEdited": format_dotnet_utc_iso(raw_msg.get("edited_timestamp")),
        "callEndedTimestamp": call_ended_iso,
        "isPinned": bool(raw_msg.get("pinned", False)),
        "content": formatted_content,
        "author": author_serialized,
        "attachments": attachments_ser,
        "embeds": embeds_ser,
        "stickers": stickers_ser,
        "reactions": reactions_ser,
        "mentions": mentions_serialized,
    }

    msg_ref = raw_msg.get("message_reference")
    if isinstance(msg_ref, dict) and msg_ref:
        ref_type_int = int(msg_ref.get("type", 0) or 0)
        ref_type_str = "Forward" if ref_type_int == 1 else "Default"
        out["reference"] = {
            "type": ref_type_str,
            "messageId": str(msg_ref["message_id"]) if msg_ref.get("message_id") else None,
            "channelId": str(msg_ref["channel_id"]) if msg_ref.get("channel_id") else None,
            "guildId": str(msg_ref["guild_id"]) if msg_ref.get("guild_id") else None,
        }

    snapshots = raw_msg.get("message_snapshots")
    if isinstance(snapshots, list) and snapshots:
        snap_msg = snapshots[0].get("message") if isinstance(snapshots[0], dict) else None
        if isinstance(snap_msg, dict):
            snap_content = format_content(
                str(snap_msg.get("content") or ""),
                channels_by_id=ch_map,
                roles_by_id=role_map,
                members_by_id=mem_map,
                inline_users_by_id=inline_users_by_id,
            )
            snap_atts = [
                {
                    "id": str(att.get("id") or ""),
                    "url": str(att.get("url") or ""),
                    "fileName": str(att.get("filename") or att.get("fileName") or ""),
                    "fileSizeBytes": int(att.get("size", att.get("fileSizeBytes", 0)) or 0),
                }
                for att in (snap_msg.get("attachments") or [])
                if isinstance(att, dict)
            ]
            snap_embeds = [
                serialize_embed(
                    emb,
                    channels_by_id=ch_map,
                    roles_by_id=role_map,
                    members_by_id=mem_map,
                    inline_users_by_id=inline_users_by_id,
                )
                for emb in merge_twitter_embeds(snap_msg.get("embeds") or [])
            ]
            snap_stickers = []
            for st in snap_msg.get("sticker_items") or snap_msg.get("stickers") or []:
                if not isinstance(st, dict):
                    continue
                st_id = str(st.get("id") or "")
                fmt_type = int(st.get("format_type", 1) or 1)
                fmt_name, fmt_ext = STICKER_FORMATS.get(fmt_type, ("Png", "png"))
                snap_stickers.append({
                    "id": st_id,
                    "name": str(st.get("name") or ""),
                    "format": fmt_name,
                    "sourceUrl": f"https://cdn.discordapp.com/stickers/{st_id}.{fmt_ext}",
                })
            out["forwardedMessage"] = {
                "timestamp": format_dotnet_utc_iso(snap_msg.get("timestamp")),
                "timestampEdited": format_dotnet_utc_iso(snap_msg.get("edited_timestamp")),
                "content": snap_content,
                "attachments": snap_atts,
                "embeds": snap_embeds,
                "stickers": snap_stickers,
            }

    if isinstance(raw_inter, dict) and raw_inter:
        i_user = raw_inter.get("user") or {}
        i_uid = str(i_user.get("id") or "0")
        out["interaction"] = {
            "id": str(raw_inter.get("id") or ""),
            "name": str(raw_inter.get("name") or ""),
            "user": serialize_user(
                i_user,
                member=mem_map.get(i_uid),
                roles_by_id=role_map,
                guild_id=guild_id,
                include_roles=True,
            ),
        }

    out["inlineEmojis"] = inline_emojis
    return out


def build_channel_export_payload(
    guild_meta: Dict[str, Any],
    channel_meta: Dict[str, Any],
    messages: List[Dict[str, Any]],
    *,
    after_dt: Optional[datetime] = None,
    before_dt: Optional[datetime] = None,
    exported_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Builds the DCE §7 root channel export dictionary."""
    g_id = str(guild_meta.get("id") or "")
    g_name = str(guild_meta.get("name") or "")
    g_icon = guild_meta.get("iconUrl") or _guild_icon_url(g_id, guild_meta.get("icon"))

    ch_id = str(channel_meta.get("id") or "")
    raw_type = channel_meta.get("type", 0)
    if isinstance(raw_type, int) or str(raw_type).isdigit():
        ch_type = CHANNEL_TYPE_NAMES.get(int(raw_type), str(raw_type))
    else:
        ch_type = str(raw_type)

    ch_obj: Dict[str, Any] = {
        "id": ch_id,
        "type": ch_type,
        "categoryId": channel_meta.get("categoryId"),
        "category": channel_meta.get("category"),
        "name": str(channel_meta.get("name") or ch_id),
        "topic": channel_meta.get("topic"),
    }
    ch_icon = channel_meta.get("iconUrl") or _channel_icon_url(ch_id, channel_meta.get("icon"))
    if ch_icon and str(ch_icon).strip():
        ch_obj["iconUrl"] = str(ch_icon)

    exp_dt = exported_at or datetime.now(timezone.utc)
    return {
        "guild": {
            "id": g_id,
            "name": g_name,
            "iconUrl": g_icon,
        },
        "channel": ch_obj,
        "dateRange": {
            "after": format_dotnet_utc_iso(after_dt),
            "before": format_dotnet_utc_iso(before_dt),
        },
        "exportedAt": format_dotnet_utc_iso(exp_dt),
        "messages": messages,
        "messageCount": len(messages),
    }


def extend_channel_json_atomic(
    file_path: str | Path,
    guild_meta: Dict[str, Any],
    channel_meta: Dict[str, Any],
    new_or_updated_messages: List[Dict[str, Any]],
    *,
    deleted_ids: Optional[Set[int]] = None,
    exported_at: Optional[datetime] = None,
    indent: int = 4,
    ensure_ascii: bool = True,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """
    Atomically creates or extends an existing Data/<channel.path> JSON in place:
    - When `overwrite=False` (default), merges edited/new messages into existing file content
    - When `overwrite=True`, ignores any pre-existing file and writes fresh messages atomically
    - Marks deleted_ids with `"is_deleted": True` while keeping historical message objects
    - Saves via `t.save_json_atomic(..., indent=4, ensure_ascii=True)`.
    """
    target = Path(file_path)
    existing_payload: Optional[Dict[str, Any]] = None
    if not overwrite and target.is_file():
        try:
            existing_payload = t.load_from_json(target.as_posix())
        except Exception:
            existing_payload = None

    msg_by_id: Dict[int, Dict[str, Any]] = {}
    if isinstance(existing_payload, dict):
        for m in existing_payload.get("messages") or []:
            if isinstance(m, dict) and str(m.get("id", "")).isdigit():
                msg_by_id[int(m["id"])] = m

    for m in new_or_updated_messages:
        if isinstance(m, dict) and str(m.get("id", "")).isdigit():
            msg_by_id[int(m["id"])] = m

    if deleted_ids:
        for del_id in deleted_ids:
            if del_id in msg_by_id:
                msg_by_id[del_id] = dict(msg_by_id[del_id])
                msg_by_id[del_id]["is_deleted"] = True

    merged_messages = [msg_by_id[mid] for mid in sorted(msg_by_id.keys())]
    payload = build_channel_export_payload(
        guild_meta=guild_meta,
        channel_meta=channel_meta,
        messages=merged_messages,
        exported_at=exported_at,
    )
    t.save_json_atomic(payload, target.as_posix(), indent=indent, ensure_ascii=ensure_ascii)
    return payload


def sync_full_mode_channel_paths(
    data_folder: str | Path,
    path_renames: List[Tuple[str, str]],
) -> None:
    """
    Safely renames/moves channel JSON files inside Data/ when ChannelModel.path changes
    (e.g. channel/category renames or position shifts), using two-phase `.moving_tmp` swaps
    to avoid collisions on cycles/swaps.
    """
    base = Path(data_folder)
    moves: List[Tuple[Path, Path]] = []
    for old_rel, new_rel in path_renames:
        if not old_rel or not new_rel or old_rel == new_rel:
            continue
        src = base / old_rel
        dst = base / new_rel
        if src.resolve() == dst.resolve():
            continue
        if src.is_file():
            moves.append((src, dst))

    if not moves:
        return

    src_set = {s.resolve() for s, _ in moves}
    dst_set = {d.resolve() for _, d in moves}

    staged: List[Tuple[Path, Path]] = []
    for src, dst in moves:
        if dst.resolve() in src_set or src.resolve() in dst_set:
            tmp = src.with_name(f"{src.name}.moving_tmp")
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(src.as_posix(), tmp.as_posix())
            staged.append((tmp, dst))
        else:
            staged.append((src, dst))

    old_parents: Set[Path] = set()
    for src_or_tmp, dst in staged:
        old_parents.add(src_or_tmp.parent)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst.unlink()
        shutil.move(src_or_tmp.as_posix(), dst.as_posix())

    for old_dir in sorted(old_parents, key=lambda p: len(p.parts), reverse=True):
        try:
            if old_dir.exists() and not any(old_dir.iterdir()):
                old_dir.rmdir()
        except OSError:
            pass


@dataclass
class SyncableChannelItem:
    discord_id: str
    name: str
    type: str
    position: int
    path: str
    category_discord_id: str
    category_name: str
    parent_discord_id: Optional[str] = None
    parent_name: Optional[str] = None
    discord_last_message_id: Optional[str] = None
    topic: Optional[str] = None
    icon: Optional[str] = None
    is_thread: bool = False
    is_event: bool = False
    is_forum: bool = False
    is_archived: bool = False


@dataclass
class ServerTopology:
    guild_meta: Dict[str, Any]
    roles_by_id: Dict[str, Dict[str, Any]]
    channels_by_id: Dict[str, Dict[str, Any]]
    categories: List[Any] = field(default_factory=list)
    syncable_items: List[SyncableChannelItem] = field(default_factory=list)


class AsyncTokenBucket:
    """Async leaky/token bucket rate limiter enforcing <= rate requests/sec."""

    def __init__(self, rate: float = GLOBAL_RATE_LIMIT_RPS, capacity: float = GLOBAL_RATE_LIMIT_RPS):
        self.rate = float(rate)
        self.capacity = float(capacity)
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self.wait_count: int = 0
        self.wait_seconds: float = 0.0

    async def acquire(self, sleep_fn: Callable[[float], Any] = asyncio.sleep) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = max(0.0, now - self._last_refill)
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_seconds = (1.0 - self._tokens) / self.rate
                self.wait_count += 1
                self.wait_seconds += wait_seconds
            await sleep_fn(wait_seconds)


def _route_key(method: str, path: str) -> str:
    clean = path.lstrip("/").split("?", 1)[0]
    parts = clean.split("/")
    if len(parts) >= 2 and parts[0] in ("channels", "guilds") and parts[1].isdigit():
        major = f"{parts[0]}/{parts[1]}"
        rest = "/".join(
            "{id}" if (p.isdigit() and i > 1) else p
            for i, p in enumerate(parts[2:], start=2)
        )
        return f"{method.upper()} {major}/{rest}" if rest else f"{method.upper()} {major}"
    return f"{method.upper()} {clean}"


class DiscordExtractor:
    """
    Native async Discord REST API v10 extractor with fail-fast Bot verification,
    adaptive rate-limiting, topology/thread/member discovery, 24h edit lookback,
    and DCE §7 JSON serialization.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 30.0,
        max_concurrent_channels: int = 4,
        sleep_fn: Optional[Callable[[float], Any]] = None,
        throttle_notice_single_s: float = 5.0,
        throttle_notice_delta_s: float = 15.0,
        throttle_notice_cooldown_s: float = 15.0,
    ):
        self.token = resolve_bot_token(token)
        self._transport = transport
        self._external_client = client
        self._client: Optional[httpx.AsyncClient] = client
        self._timeout = timeout
        self.max_concurrent_channels = max(1, int(max_concurrent_channels))
        self._sleep_fn = sleep_fn or asyncio.sleep

        self._global_bucket = AsyncTokenBucket(rate=GLOBAL_RATE_LIMIT_RPS, capacity=GLOBAL_RATE_LIMIT_RPS)
        self._global_pause_until: float = 0.0
        self._rate_lock = asyncio.Lock()
        self._route_to_bucket: Dict[str, str] = {}
        self._bucket_state: Dict[str, Tuple[int, float]] = {}

        self._started_monotonic: float = time.monotonic()
        self._requests_total: int = 0
        self._rate_limit_waits: int = 0
        self._rate_limit_wait_seconds: float = 0.0
        self._http_429_count: int = 0
        self._global_429_count: int = 0
        self._http_429_wait_seconds: float = 0.0
        self._retry_count: int = 0
        self._retry_wait_seconds: float = 0.0
        self._throttle_notice_single_s: float = max(0.0, float(throttle_notice_single_s))
        self._throttle_notice_delta_s: float = max(0.0, float(throttle_notice_delta_s))
        self._throttle_notice_cooldown_s: float = max(0.0, float(throttle_notice_cooldown_s))
        self._last_throttle_notice_at: float = 0.0
        self._last_notice_wait_seconds: float = 0.0

        self._bot_verified = False
        self._bot_user: Optional[Dict[str, Any]] = None
        self._app_intent_checked = False
        self._owns_client = client is None

    async def __aenter__(self) -> "DiscordExtractor":
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.aclose()

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            kwargs: Dict[str, Any] = {
                "base_url": DISCORD_API_BASE,
                "timeout": self._timeout,
                "headers": {
                    "Authorization": f"Bot {self.token}",
                    "User-Agent": "SocratesBot (https://github.com/socrates, 2.0)",
                },
            }
            if self._transport is not None:
                kwargs["transport"] = self._transport
            self._client = httpx.AsyncClient(**kwargs)
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def _snapshot_telemetry_unlocked(self, elapsed_seconds: Optional[float] = None) -> Dict[str, Any]:
        elapsed = (
            max(0.0, float(elapsed_seconds))
            if elapsed_seconds is not None
            else max(0.0, time.monotonic() - self._started_monotonic)
        )
        bucket_waits = self._rate_limit_waits + int(self._global_bucket.wait_count)
        bucket_wait_s = self._rate_limit_wait_seconds + float(self._global_bucket.wait_seconds)
        rate_limit_wait_s = bucket_wait_s + self._http_429_wait_seconds
        total_wait_s = rate_limit_wait_s + self._retry_wait_seconds
        return {
            "elapsed_seconds": elapsed,
            "requests_total": self._requests_total,
            "bucket_waits": bucket_waits,
            "bucket_wait_seconds": bucket_wait_s,
            "http_429_count": self._http_429_count,
            "global_429_count": self._global_429_count,
            "http_429_wait_seconds": self._http_429_wait_seconds,
            "rate_limit_wait_seconds": rate_limit_wait_s,
            "retry_count": self._retry_count,
            "retry_wait_seconds": self._retry_wait_seconds,
            "total_wait_seconds": total_wait_s,
        }

    def get_telemetry(self, *, elapsed_seconds: Optional[float] = None) -> Dict[str, Any]:
        """Returns accumulated Discord API request, rate-limit, and retry telemetry."""
        return self._snapshot_telemetry_unlocked(elapsed_seconds=elapsed_seconds)

    def format_wait_summary(self, *, elapsed_seconds: Optional[float] = None) -> str:
        """Formats a single compact summary line explaining rate-limit and retry time vs. total elapsed."""
        stats = self.get_telemetry(elapsed_seconds=elapsed_seconds)
        elapsed = stats["elapsed_seconds"]
        total_wait = stats["total_wait_seconds"]
        reqs = stats["requests_total"]
        rate_s = stats["rate_limit_wait_seconds"]
        b_waits = stats["bucket_waits"]
        c_429 = stats["http_429_count"]
        g_429 = stats["global_429_count"]
        retries = stats["retry_count"]
        retry_s = stats["retry_wait_seconds"]

        if elapsed >= 0.05 and total_wait <= elapsed * 1.05:
            pct = min(100, int(round((total_wait / elapsed) * 100)))
            span_part = f"{total_wait:.1f}s ({pct}% of {elapsed:.1f}s)"
        elif elapsed >= 0.05:
            span_part = f"{total_wait:.1f}s worker-wait across {elapsed:.1f}s elapsed"
        else:
            span_part = f"{total_wait:.1f}s waited"

        global_note = f" [{g_429} global]" if g_429 > 0 else ""
        return (
            f"API wait summary: {span_part} across {reqs} request(s) — "
            f"rate limits: {rate_s:.1f}s ({b_waits} bucket wait(s), {c_429}x 429{global_note}); "
            f"retries: {retry_s:.1f}s ({retries} retry/ies)."
        )

    async def _record_wait_and_sleep(
        self,
        kind: str,
        wait_s: float,
        *,
        is_global: bool = False,
    ) -> None:
        clean_wait = max(0.0, float(wait_s))
        notice_msg: Optional[str] = None

        async with self._rate_lock:
            if kind == "proactive":
                self._rate_limit_waits += 1
                self._rate_limit_wait_seconds += clean_wait
            elif kind == "429":
                self._http_429_count += 1
                if is_global:
                    self._global_429_count += 1
                self._http_429_wait_seconds += clean_wait
            elif kind == "retry":
                self._retry_count += 1
                self._retry_wait_seconds += clean_wait

            stats = self._snapshot_telemetry_unlocked()
            total_wait = stats["total_wait_seconds"]
            now = time.monotonic()
            delta_wait = total_wait - self._last_notice_wait_seconds
            since_last_notice = now - self._last_throttle_notice_at if self._last_throttle_notice_at > 0 else float("inf")

            should_notify = (
                clean_wait >= self._throttle_notice_single_s
                and since_last_notice >= min(10.0, self._throttle_notice_cooldown_s)
            ) or (
                delta_wait >= self._throttle_notice_delta_s
                and since_last_notice >= self._throttle_notice_cooldown_s
            )
            if should_notify and total_wait > 0:
                self._last_throttle_notice_at = now
                self._last_notice_wait_seconds = total_wait
                notice_msg = (
                    f"  [Throttle notice] Paused on Discord rate limits/retries "
                    f"({total_wait:.1f}s waited so far across {stats['requests_total']} reqs: "
                    f"{stats['http_429_count']}x 429, {stats['retry_count']} retry/ies) — continuing..."
                )

        if notice_msg:
            t.log("warning", notice_msg)

        if clean_wait > 0:
            await self._sleep_fn(clean_wait)

    async def _wait_for_rate_limit(self, r_key: str) -> None:
        while True:
            wait_for = 0.0
            async with self._rate_lock:
                now = time.monotonic()
                if self._global_pause_until > now:
                    wait_for = max(wait_for, self._global_pause_until - now)
                bucket_id = self._route_to_bucket.get(r_key)
                if bucket_id and bucket_id in self._bucket_state:
                    rem, reset_at = self._bucket_state[bucket_id]
                    if rem <= 0 and reset_at > now:
                        wait_for = max(wait_for, reset_at - now)
            if wait_for > 0:
                await self._record_wait_and_sleep("proactive", wait_for)
            else:
                break
        await self._global_bucket.acquire(sleep_fn=self._sleep_fn)

    async def _update_rate_headers(self, r_key: str, response: httpx.Response) -> None:
        headers = response.headers
        bucket_id = headers.get("X-RateLimit-Bucket")
        rem_raw = headers.get("X-RateLimit-Remaining")
        reset_after_raw = headers.get("X-RateLimit-Reset-After")
        is_global = str(headers.get("X-RateLimit-Global", "")).lower() == "true"

        async with self._rate_lock:
            now = time.monotonic()
            if bucket_id:
                self._route_to_bucket[r_key] = bucket_id
            target_bucket = bucket_id or self._route_to_bucket.get(r_key)
            if target_bucket and rem_raw is not None and reset_after_raw is not None:
                try:
                    rem = int(rem_raw)
                    reset_after = max(0.0, float(reset_after_raw))
                    self._bucket_state[target_bucket] = (rem, now + min(reset_after, 60.0))
                except ValueError:
                    pass
            if is_global and reset_after_raw is not None:
                try:
                    self._global_pause_until = max(
                        self._global_pause_until,
                        now + min(max(0.0, float(reset_after_raw)), 60.0),
                    )
                except ValueError:
                    pass

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        optional: bool = False,
        channel_scoped: bool = False,
    ) -> Any:
        client = await self._ensure_client()
        rel_path = path.lstrip("/")
        r_key = _route_key(method, rel_path)
        headers = {"Authorization": f"Bot {self.token}"}

        for attempt in range(MAX_HTTP_RETRIES + 1):
            await self._wait_for_rate_limit(r_key)
            async with self._rate_lock:
                self._requests_total += 1
            try:
                resp = await client.request(method, rel_path, params=params, headers=headers)
            except httpx.RequestError as req_err:
                if attempt >= MAX_HTTP_RETRIES:
                    if optional:
                        return None
                    raise exc.ExportError(f"Discord HTTP request error on {rel_path}: {req_err}") from req_err
                await self._record_wait_and_sleep("retry", min(60.0, 0.5 * (2 ** attempt)))
                continue

            await self._update_rate_headers(r_key, resp)
            status = resp.status_code

            if 200 <= status < 300:
                if status == 204 or not resp.content:
                    return {}
                return resp.json()

            if status == 401:
                raise exc.InvalidBotTokenError(
                    f"Discord API rejected bot token with 401 Unauthorized on {rel_path}."
                )

            if status in (403, 404):
                # Never retry 403/404 (prevents Cloudflare 10k/10m invalid-request ban)
                if optional:
                    return None
                if channel_scoped:
                    raise ChannelAccessError(status, f"Discord API returned HTTP {status} for {rel_path}")
                raise exc.GetChannelListError(f"Discord API returned HTTP {status} for {rel_path}")

            if status == 429:
                retry_after = None
                is_global_429 = str(resp.headers.get("X-RateLimit-Global", "")).lower() == "true"
                try:
                    body = resp.json()
                    if isinstance(body, dict):
                        if body.get("retry_after") is not None:
                            retry_after = float(body["retry_after"])
                        if body.get("global"):
                            is_global_429 = True
                except Exception:
                    body = None
                if retry_after is None:
                    ra_hdr = resp.headers.get("Retry-After")
                    if ra_hdr:
                        try:
                            retry_after = float(ra_hdr)
                        except ValueError:
                            retry_after = None
                wait_s = max(0.0, min(retry_after if retry_after is not None else (0.5 * (2 ** attempt)), 60.0))
                if is_global_429:
                    async with self._rate_lock:
                        self._global_pause_until = max(self._global_pause_until, time.monotonic() + wait_s)
                if attempt >= MAX_HTTP_RETRIES:
                    async with self._rate_lock:
                        self._http_429_count += 1
                        if is_global_429:
                            self._global_429_count += 1
                    if optional:
                        return None
                    raise exc.ExportError(f"Discord API 429 rate-limit exhausted retries on {rel_path}")
                await self._record_wait_and_sleep("429", wait_s, is_global=is_global_429)
                continue

            if status == 408 or status >= 500:
                if attempt >= MAX_HTTP_RETRIES:
                    async with self._rate_lock:
                        self._retry_count += 1
                    if optional:
                        return None
                    raise exc.ExportError(f"Discord API HTTP {status} on {rel_path} after retries")
                ra_hdr = resp.headers.get("Retry-After")
                try:
                    wait_s = float(ra_hdr) if ra_hdr else (0.5 * (2 ** attempt))
                except ValueError:
                    wait_s = 0.5 * (2 ** attempt)
                await self._record_wait_and_sleep("retry", min(60.0, max(0.0, wait_s)))
                continue

            if optional:
                return None
            raise exc.ExportError(f"Unexpected Discord API HTTP {status} on {rel_path}")

        return None

    async def verify_bot_token(self) -> Dict[str, Any]:
        """
        Fail-fast verification via `GET /users/@me`.
        Raises `InvalidBotTokenError` if HTTP 401, non-200, or `payload.get("bot") is not True`.
        """
        if self._bot_verified and self._bot_user is not None:
            return self._bot_user
        try:
            payload = await self._request_json("GET", "users/@me", optional=False)
        except exc.InvalidBotTokenError:
            raise
        except Exception as e:
            raise exc.InvalidBotTokenError(f"Bot token verification failed: {e}") from e

        if not isinstance(payload, dict) or payload.get("bot") is not True:
            raise exc.InvalidBotTokenError(
                "Provided DISCORD_TOKEN is not a Bot token (payload['bot'] is not True)."
            )
        self._bot_user = payload
        self._bot_verified = True
        return payload

    async def _check_message_content_intent(self, batch: List[Dict[str, Any]]) -> None:
        if self._app_intent_checked or not batch:
            return
        all_empty = all(
            not str(m.get("content") or "").strip()
            and not m.get("attachments")
            and not m.get("embeds")
            and not m.get("sticker_items")
            and not m.get("stickers")
            and not m.get("poll")
            for m in batch
        )
        if not all_empty:
            self._app_intent_checked = True
            return
        app_info = await self._request_json("GET", "applications/@me", optional=True)
        self._app_intent_checked = True
        if isinstance(app_info, dict) and "flags" in app_info:
            flags_int = int(app_info.get("flags") or 0)
            if not (flags_int & (262144 | 524288)):
                raise exc.ExportError(
                    "Bot application lacks GATEWAY_MESSAGE_CONTENT privileged intent (flags missing 262144/524288)."
                )

    async def fetch_categories(self, server_id: str) -> Dict[str, str]:
        """Fetches sorted guild categories mapping `{category_id: '<pos># <name>'}`."""
        try:
            safe_guild_id = validate_snowflake(server_id, "server_id")
        except ValueError as ve:
            raise exc.GetChannelListError(f"Invalid server_id: {ve}") from ve

        try:
            await self.verify_bot_token()
            raw_channels = await self._request_json("GET", f"guilds/{safe_guild_id}/channels")
            if not isinstance(raw_channels, list):
                raise exc.GetChannelListError("Unexpected response format for guild channels")

            sorted_raw = sorted(
                raw_channels,
                key=lambda ch: (
                    int(ch["parent_id"]) if ch.get("parent_id") else 0,
                    int(ch.get("type", 0)),
                    int(ch.get("position", 0)),
                ),
            )
            categories: Dict[str, str] = {}
            cat_pos = 0
            for ch in sorted_raw:
                if int(ch.get("type", 0)) == 4:
                    cat_pos += 1
                    categories[str(ch["id"])] = f"{cat_pos}# {ch.get('name', '')}"
            return categories
        except exc.GetChannelListError:
            raise
        except Exception as e:
            raise exc.GetChannelListError(f"Failed to get categories for server {safe_guild_id}") from e

    async def fetch_guild_members(self, guild_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Paginates `GET /guilds/{guild_id}/members?limit=1000&after=...`.
        Degrades gracefully to `{}` with a warning log on HTTP 403 (missing GUILD_MEMBERS intent).
        """
        safe_guild_id = validate_snowflake(guild_id, "guild_id")
        await self.verify_bot_token()

        members_by_id: Dict[str, Dict[str, Any]] = {}
        after = "0"
        while True:
            try:
                batch = await self._request_json(
                    "GET",
                    f"guilds/{safe_guild_id}/members",
                    params={"limit": 1000, "after": after},
                    channel_scoped=True,
                )
            except ChannelAccessError as ce:
                if ce.status_code == 403:
                    t.log(
                        "info",
                        f"\tWarning: GUILD_MEMBERS intent unavailable (HTTP 403) for guild {safe_guild_id}; "
                        "falling back to channel-harvested users.",
                    )
                    return {}
                return members_by_id

            if not isinstance(batch, list) or not batch:
                break

            for mem in batch:
                if not isinstance(mem, dict):
                    continue
                usr = mem.get("user") or {}
                uid = str(usr.get("id") or "")
                if uid:
                    members_by_id[uid] = mem

            if len(batch) < 1000:
                break
            last_uid = str((batch[-1].get("user") or {}).get("id") or "")
            if not last_uid or last_uid == after:
                break
            after = last_uid

        return members_by_id

    async def _fetch_archived_threads_for_channel(
        self,
        channel_id: str,
        archive_type: str,
    ) -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        current_before: Optional[str] = None
        while True:
            params: Dict[str, Any] = {}
            if current_before is not None:
                params["before"] = current_before
            data = await self._request_json(
                "GET",
                f"channels/{channel_id}/threads/archived/{archive_type}",
                params=params or None,
                optional=True,
            )
            if not isinstance(data, dict):
                break
            threads = data.get("threads") or []
            if not threads:
                break
            for th in threads:
                if isinstance(th, dict):
                    collected.append(th)
                    meta = th.get("thread_metadata") or {}
                    if meta.get("archive_timestamp"):
                        current_before = str(meta["archive_timestamp"])
            if not data.get("has_more"):
                break
        return collected

    async def fetch_server_topology(
        self,
        guild_id: str,
        *,
        categories_to_ignore: Optional[Set[str]] = None,
        categories_to_keep: Optional[Set[str]] = None,
        keep_mode: bool = False,
        event_categories: Optional[Iterable[str]] = None,
        existing_channels: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> ServerTopology:
        """
        Fetches guild metadata, roles, channels, active threads, and archived threads
        for relevant non-ignored channels, applying `--relative-positions` sorting,
        category filtering, and virtual `'Events'` slot normalization.
        """
        from models.category import Category
        from models.channel import Channel
        from models.thread import Thread

        safe_guild_id = validate_snowflake(guild_id, "guild_id")
        await self.verify_bot_token()

        guild_raw = await self._request_json("GET", f"guilds/{safe_guild_id}")
        raw_channels = await self._request_json("GET", f"guilds/{safe_guild_id}/channels")
        if not isinstance(guild_raw, dict) or not isinstance(raw_channels, list):
            raise exc.GetChannelListError(f"Invalid guild/channels payload for {safe_guild_id}")

        roles_by_id: Dict[str, Dict[str, Any]] = {
            str(r["id"]): r for r in (guild_raw.get("roles") or []) if isinstance(r, dict) and r.get("id")
        }
        guild_meta = {
            "id": str(guild_raw.get("id") or safe_guild_id),
            "name": str(guild_raw.get("name") or ""),
            "icon": guild_raw.get("icon"),
            "iconUrl": _guild_icon_url(safe_guild_id, guild_raw.get("icon")),
        }

        # `--relative-positions` sorting per DCE_specification.md §3
        sorted_raw = sorted(
            raw_channels,
            key=lambda ch: (
                int(ch["parent_id"]) if ch.get("parent_id") else 0,
                int(ch.get("type", 0)),
                int(ch.get("position", 0)),
            ),
        )

        channels_by_id: Dict[str, Dict[str, Any]] = {}
        raw_categories: List[Dict[str, Any]] = []
        cat_pos_by_id: Dict[str, int] = {}
        cat_by_id: Dict[str, Dict[str, Any]] = {}
        cat_counter = 0
        for ch in sorted_raw:
            cid = str(ch.get("id") or "")
            if cid:
                channels_by_id[cid] = ch
            if int(ch.get("type", 0)) == 4:
                cat_counter += 1
                ch_copy = dict(ch)
                ch_copy["_rel_pos"] = cat_counter
                raw_categories.append(ch_copy)
                cat_pos_by_id[cid] = cat_counter
                cat_by_id[cid] = ch_copy

        # Relative position assignment across all non-category items
        rel_pos = 0
        prev_parent: Optional[str] = None
        parented_channels: Dict[str, List[Dict[str, Any]]] = {cid: [] for cid in cat_by_id}
        for ch in sorted_raw:
            p_id = str(ch["parent_id"]) if ch.get("parent_id") else None
            if p_id != prev_parent:
                prev_parent = p_id
                rel_pos = 1
            else:
                rel_pos += 1
            if int(ch.get("type", 0)) == 4:
                continue
            ch_copy = dict(ch)
            ch_copy["_rel_pos"] = rel_pos
            if p_id and p_id in parented_channels:
                parented_channels[p_id].append(ch_copy)

        ignore_set = expand_category_names(categories_to_ignore)
        keep_set = expand_category_names(categories_to_keep)
        event_cat_names = expand_category_names(event_categories)

        def _is_cat_selected(cat_id: str, cat_name: str) -> bool:
            if keep_mode:
                return category_matches(cat_id, cat_name, keep_set)
            return not category_matches(cat_id, cat_name, ignore_set)

        selected_cats = [
            c_obj
            for c_obj in raw_categories
            if _is_cat_selected(str(c_obj.get("id") or ""), str(c_obj.get("name") or ""))
        ]
        selected_cat_ids = {str(c_obj["id"]) for c_obj in selected_cats}

        # Eligible parent channels for thread discovery (selected categories, non-voice, non-empty)
        eligible_parents: List[Dict[str, Any]] = []
        eligible_parent_ids: Set[str] = set()
        for cid in selected_cat_ids:
            for ch in parented_channels.get(cid, []):
                ch_type = int(ch.get("type", 0))
                if ch_type in (4, 2, 13):
                    continue
                if ch.get("last_message_id") is None:
                    continue
                eligible_parents.append(ch)
                eligible_parent_ids.add(str(ch["id"]))

        # Fetch active threads once + archived threads concurrently for eligible parents
        active_data = await self._request_json("GET", f"guilds/{safe_guild_id}/threads/active", optional=True)
        raw_threads: List[Dict[str, Any]] = []
        if isinstance(active_data, dict):
            for th in active_data.get("threads") or []:
                if isinstance(th, dict):
                    raw_threads.append(th)

        sem = asyncio.Semaphore(self.max_concurrent_channels)

        async def _fetch_parent_archived(p_id: str) -> List[Dict[str, Any]]:
            async with sem:
                pub = await self._fetch_archived_threads_for_channel(p_id, "public")
                priv = await self._fetch_archived_threads_for_channel(p_id, "private")
                return pub + priv

        if eligible_parents:
            archived_batches = await asyncio.gather(
                *[_fetch_parent_archived(str(p["id"])) for p in eligible_parents]
            )
            for b in archived_batches:
                raw_threads.extend(b)

        # Deduplicate, filter to eligible parents, and sort threads by (int(parent_id), int(id))
        dedup_threads: Dict[str, Dict[str, Any]] = {}
        for th in raw_threads:
            tid = str(th.get("id") or "")
            pid = str(th.get("parent_id") or "")
            if not tid or pid not in eligible_parent_ids:
                continue
            dedup_threads[tid] = th
            channels_by_id[tid] = th

        sorted_threads = sorted(
            dedup_threads.values(),
            key=lambda th: (int(th["parent_id"]), int(th["id"])),
        )
        threads_by_parent: Dict[str, List[Dict[str, Any]]] = {}
        th_pos = 0
        prev_th_parent: Optional[str] = None
        for th in sorted_threads:
            pid = str(th["parent_id"])
            if pid != prev_th_parent:
                prev_th_parent = pid
                th_pos = 1
            else:
                th_pos += 1
            th_copy = dict(th)
            th_copy["_rel_pos"] = th_pos
            threads_by_parent.setdefault(pid, []).append(th_copy)

        # Partition selected categories into regular categories vs event categories
        existing_map = existing_channels or {}
        faux_cat_id = "events_category"
        faux_cat_name = "Events"

        matched_event_cats = [
            c_obj for c_obj in selected_cats
            if category_matches(str(c_obj.get("id") or ""), str(c_obj.get("name") or ""), event_cat_names)
            or str(c_obj.get("id") or "") == faux_cat_id
            or str(c_obj.get("name") or "") == faux_cat_name
        ]
        matched_event_cat_ids = {str(c_obj["id"]) for c_obj in matched_event_cats}
        regular_cats = [c_obj for c_obj in selected_cats if str(c_obj["id"]) not in matched_event_cat_ids]

        model_categories: List[Category] = []
        syncable_items: List[SyncableChannelItem] = []

        # Build regular categories
        for c_obj in regular_cats:
            cat_id = str(c_obj["id"])
            cat_name = str(c_obj.get("name") or cat_id)
            cat_pos = int(c_obj["_rel_pos"])
            cat_path = f"{cat_pos}# {escape_dce_filename(cat_name)}"
            cat_model = Category(id=cat_id, name=cat_name, position=cat_pos, path=cat_path)

            for ch in parented_channels.get(cat_id, []):
                ch_type_int = int(ch.get("type", 0))
                if ch_type_int in (4, 2, 13):
                    continue
                ch_id = str(ch["id"])
                ch_name = str(ch.get("name") or ch_id)
                ch_pos = int(ch["_rel_pos"])
                ch_type_name = CHANNEL_TYPE_NAMES.get(ch_type_int, str(ch_type_int))
                is_forum = (ch_type_int == 15)
                ch_path = f"{cat_path}/{ch_pos}# {escape_dce_filename(ch_name)}.json"

                ch_model = Channel(id=ch_id, name=ch_name, position=ch_pos, path=ch_path)
                if not is_forum:
                    syncable_items.append(
                        SyncableChannelItem(
                            discord_id=ch_id,
                            name=ch_name,
                            type=ch_type_name,
                            position=ch_pos,
                            path=ch_path,
                            category_discord_id=cat_id,
                            category_name=cat_name,
                            parent_discord_id=cat_id,
                            parent_name=cat_name,
                            discord_last_message_id=str(ch["last_message_id"]) if ch.get("last_message_id") else None,
                            topic=ch.get("topic"),
                            icon=ch.get("icon"),
                            is_thread=False,
                            is_event=False,
                            is_forum=False,
                        )
                    )
                else:
                    # Forum containers are kept as parent Channel objects (non-exportable directly)
                    ch_model.path = f"{cat_path}/{ch_pos}# {escape_dce_filename(ch_name)}"

                for th in threads_by_parent.get(ch_id, []):
                    th_id = str(th["id"])
                    th_name = str(th.get("name") or th_id)
                    th_pos = int(th["_rel_pos"])
                    th_type_int = int(th.get("type", 11))
                    th_type_name = CHANNEL_TYPE_NAMES.get(th_type_int, "GuildPublicThread")
                    th_path = f"{cat_path}/Threads/{ch_pos}-{th_pos}# {escape_dce_filename(th_name)}.json"
                    th_model = Thread(id=th_id, name=th_name, position=th_pos, path=th_path)
                    ch_model.add_thread(th_model)
                    syncable_items.append(
                        SyncableChannelItem(
                            discord_id=th_id,
                            name=th_name,
                            type=th_type_name,
                            position=th_pos,
                            path=th_path,
                            category_discord_id=cat_id,
                            category_name=cat_name,
                            parent_discord_id=ch_id,
                            parent_name=ch_name,
                            discord_last_message_id=str(th["last_message_id"]) if th.get("last_message_id") else None,
                            topic=th.get("topic"),
                            icon=th.get("icon"),
                            is_thread=True,
                            is_event=False,
                            is_archived=bool((th.get("thread_metadata") or {}).get("archived", False)),
                        )
                    )

                cat_model.add_channel(ch_model)

            model_categories.append(cat_model)

        # Build virtual consolidated 'Events' category with preserved event-1..N slot positions
        if matched_event_cats:
            existing_events_cat_pos = None
            existing_event_slots: Dict[str, int] = {}
            existing_event_thread_slots: Dict[str, int] = {}
            event_ch_pat = re.compile(r"^event-(\d+)$")

            for did, info in existing_map.items():
                if did == faux_cat_id or info.get("name") == faux_cat_name:
                    existing_events_cat_pos = info.get("position")
                elif info.get("type") != "GuildPublicThread":
                    m_ev = event_ch_pat.match(str(info.get("name") or ""))
                    if m_ev:
                        existing_event_slots[did] = int(m_ev.group(1))
                else:
                    if info.get("is_event_thread") or "Events/Threads/" in str(info.get("path") or ""):
                        existing_event_thread_slots[did] = int(info.get("position") or 0)

            faux_cat_pos = (
                int(existing_events_cat_pos)
                if existing_events_cat_pos is not None
                else min(int(c_obj["_rel_pos"]) for c_obj in matched_event_cats)
            )
            faux_cat_path = f"{faux_cat_pos}# {faux_cat_name}"

            raw_event_channels: List[Dict[str, Any]] = []
            seen_ev_ids: Set[str] = set()
            for c_obj in matched_event_cats:
                for ch in parented_channels.get(str(c_obj["id"]), []):
                    ch_type_int = int(ch.get("type", 0))
                    if ch_type_int in (4, 2, 13):
                        continue
                    ch_id = str(ch["id"])
                    if ch_id not in seen_ev_ids:
                        seen_ev_ids.add(ch_id)
                        raw_event_channels.append(ch)

            assigned_ev: List[Tuple[int, Dict[str, Any]]] = []
            unassigned_ev: List[Dict[str, Any]] = []
            for ch in raw_event_channels:
                ch_id = str(ch["id"])
                if ch_id in existing_event_slots:
                    assigned_ev.append((existing_event_slots[ch_id], ch))
                else:
                    unassigned_ev.append(ch)

            max_slot = max(
                list(existing_event_slots.values()) + [pos for pos, _ in assigned_ev],
                default=0,
            )
            unassigned_ev.sort(key=lambda ch: int(ch["id"]) if str(ch["id"]).isdigit() else 0)
            for offset, ch in enumerate(unassigned_ev, start=1):
                assigned_ev.append((max_slot + offset, ch))

            assigned_ev.sort(key=lambda pair: pair[0])
            faux_cat_model = Category(
                id=faux_cat_id,
                name=faux_cat_name,
                position=faux_cat_pos,
                path=faux_cat_path,
            )

            for slot_pos, ch in assigned_ev:
                ch_id = str(ch["id"])
                slot_name = f"event-{slot_pos}"
                ch_type_int = int(ch.get("type", 0))
                ch_type_name = CHANNEL_TYPE_NAMES.get(ch_type_int, "GuildTextChat")
                ch_path = f"{faux_cat_path}/{slot_pos}# {slot_name}.json"
                ch_model = Channel(id=ch_id, name=slot_name, position=slot_pos, path=ch_path)

                if ch_type_int != 15:
                    syncable_items.append(
                        SyncableChannelItem(
                            discord_id=ch_id,
                            name=slot_name,
                            type=ch_type_name,
                            position=slot_pos,
                            path=ch_path,
                            category_discord_id=faux_cat_id,
                            category_name=faux_cat_name,
                            parent_discord_id=faux_cat_id,
                            parent_name=faux_cat_name,
                            discord_last_message_id=str(ch["last_message_id"]) if ch.get("last_message_id") else None,
                            topic=ch.get("topic"),
                            icon=ch.get("icon"),
                            is_thread=False,
                            is_event=True,
                        )
                    )

                ch_threads = threads_by_parent.get(ch_id, [])
                assigned_th: List[Tuple[int, Dict[str, Any]]] = []
                unassigned_th: List[Dict[str, Any]] = []
                for th in ch_threads:
                    tid = str(th["id"])
                    if tid in existing_event_thread_slots and existing_event_thread_slots[tid] > 0:
                        assigned_th.append((existing_event_thread_slots[tid], th))
                    else:
                        unassigned_th.append(th)

                max_th_pos = max([p for p, _ in assigned_th], default=0)
                unassigned_th.sort(key=lambda th: int(th["id"]) if str(th["id"]).isdigit() else 0)
                for offset, th in enumerate(unassigned_th, start=1):
                    assigned_th.append((max_th_pos + offset, th))
                assigned_th.sort(key=lambda pair: pair[0])

                for th_pos_slot, th in assigned_th:
                    tid = str(th["id"])
                    th_name = str(th.get("name") or tid)
                    th_type_int = int(th.get("type", 11))
                    th_type_name = CHANNEL_TYPE_NAMES.get(th_type_int, "GuildPublicThread")
                    th_path = f"{faux_cat_path}/Threads/{slot_pos}-{th_pos_slot}# {escape_dce_filename(th_name)}.json"
                    th_model = Thread(id=tid, name=th_name, position=th_pos_slot, path=th_path)
                    ch_model.add_thread(th_model)
                    syncable_items.append(
                        SyncableChannelItem(
                            discord_id=tid,
                            name=th_name,
                            type=th_type_name,
                            position=th_pos_slot,
                            path=th_path,
                            category_discord_id=faux_cat_id,
                            category_name=faux_cat_name,
                            parent_discord_id=ch_id,
                            parent_name=slot_name,
                            discord_last_message_id=str(th["last_message_id"]) if th.get("last_message_id") else None,
                            topic=th.get("topic"),
                            icon=th.get("icon"),
                            is_thread=True,
                            is_event=True,
                            is_archived=bool((th.get("thread_metadata") or {}).get("archived", False)),
                        )
                    )

                faux_cat_model.add_channel(ch_model)

            model_categories.append(faux_cat_model)

        model_categories.sort(key=lambda cat: cat.position)
        for cat_m in model_categories:
            cat_m.sort_channels()
            for ch_m in cat_m.channels:
                ch_m.sort_threads()

        return ServerTopology(
            guild_meta=guild_meta,
            roles_by_id=roles_by_id,
            channels_by_id=channels_by_id,
            categories=model_categories,
            syncable_items=syncable_items,
        )

    async def _resolve_thread_starter_message(self, raw_msg: Dict[str, Any]) -> Dict[str, Any]:
        if int(raw_msg.get("type", 0) or 0) != 21:
            return raw_msg
        ref = raw_msg.get("message_reference")
        if not isinstance(ref, dict):
            return raw_msg
        ref_cid = str(ref.get("channel_id") or "")
        ref_mid = str(ref.get("message_id") or "")
        if not (ref_cid.isdigit() and ref_mid.isdigit()):
            return raw_msg
        around_list = await self._request_json(
            "GET",
            f"channels/{ref_cid}/messages",
            params={"around": ref_mid, "limit": 1},
            optional=True,
        )
        if isinstance(around_list, list):
            for candidate in around_list:
                if isinstance(candidate, dict) and str(candidate.get("id")) == ref_mid:
                    return candidate
        return raw_msg

    async def fetch_channel_messages(
        self,
        channel_id: str,
        *,
        after_snowflake: str = "0",
        guild_id: str = "",
        channels_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
        roles_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
        members_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
        serialize: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Fetches messages chronologically (`after={after_snowflake}`, reversed batches of 100),
        probing terminal `omega` message via `limit=1` first (skipping forward pagination if empty).
        When `serialize=True`, converts each raw Discord API message to DCE §7 JSON format.
        """
        safe_cid = validate_snowflake(channel_id, "channel_id")
        await self.verify_bot_token()

        # Probe terminal omega message (optional so empty/inaccessible handled cleanly)
        omega_batch = await self._request_json(
            "GET",
            f"channels/{safe_cid}/messages",
            params={"limit": 1},
            optional=True,
        )
        if not isinstance(omega_batch, list) or not omega_batch:
            return []

        omega_id = int(omega_batch[0]["id"])
        after_int = int(after_snowflake) if str(after_snowflake).isdigit() else 0
        if omega_id <= after_int:
            return []

        raw_messages: List[Dict[str, Any]] = []
        current_boundary = str(after_int)

        while True:
            batch = await self._request_json(
                "GET",
                f"channels/{safe_cid}/messages",
                params={"limit": 100, "after": current_boundary},
                channel_scoped=True,
            )
            if not isinstance(batch, list) or not batch:
                break

            batch_chrono = list(reversed(batch))
            await self._check_message_content_intent(batch_chrono)

            reached_omega = False
            for raw_msg in batch_chrono:
                mid_int = int(raw_msg["id"])
                if mid_int > omega_id:
                    reached_omega = True
                    break
                resolved_msg = await self._resolve_thread_starter_message(raw_msg)
                raw_messages.append(resolved_msg)

            last_batch_id = str(batch_chrono[-1]["id"])
            if reached_omega or int(last_batch_id) >= omega_id or len(batch) < 100:
                break
            current_boundary = last_batch_id

        if not serialize:
            return raw_messages

        return [
            serialize_message(
                m,
                guild_id=guild_id,
                channels_by_id=channels_by_id,
                roles_by_id=roles_by_id,
                members_by_id=members_by_id,
            )
            for m in raw_messages
        ]

    async def fetch_message(
        self,
        channel_id: str,
        message_id: str,
        *,
        backup_id: Optional[str] = None,
        base_path: Optional[str] = None,
        channel_rel_path: Optional[str] = None,
        storage_mode: Optional[str] = None,
        guild_id: str = "",
        channels_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
        roles_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
        members_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Targeted single-message lookup for curation hydration:
        - In 'full' mode, checks local Data/<channel.path> first.
        - Otherwise calls `GET /channels/{id}/messages/{mid}`.
        - On HTTP 404, marks SkeletonFlags.IS_DELETED in skeletons.sqlite (if present) and returns None.
        - On HTTP 403 or auth failure, returns None cleanly.
        """
        safe_cid = validate_snowflake(channel_id, "channel_id")
        safe_mid = validate_snowflake(message_id, "message_id")

        if storage_mode == "full" and base_path and channel_rel_path:
            c_rel = Path(channel_rel_path)
            for cand in (Path(base_path) / "Data" / c_rel, Path(base_path) / c_rel):
                if cand.is_file():
                    try:
                        payload = t.load_from_json(cand.as_posix())
                        for m in payload.get("messages") or []:
                            if str(m.get("id")) == safe_mid:
                                return m
                    except Exception:
                        pass
                    break

        await self.verify_bot_token()
        client = await self._ensure_client()
        rel_path = f"channels/{safe_cid}/messages/{safe_mid}"
        r_key = _route_key("GET", rel_path)
        await self._wait_for_rate_limit(r_key)
        async with self._rate_lock:
            self._requests_total += 1

        try:
            resp = await client.request(
                "GET",
                rel_path,
                headers={"Authorization": f"Bot {self.token}"},
            )
            await self._update_rate_headers(r_key, resp)
        except httpx.RequestError as req_err:
            t.log("warning", f"  Warning: Message hydration request failed for {safe_cid}/{safe_mid}: {req_err}")
            return None

        if resp.status_code == 404:
            if base_path and has_skeleton_db(base_path, backup_id=backup_id):
                try:
                    with skeleton_db_session(backup_id=backup_id, backup_path=base_path) as skel_session:
                        row = skel_session.query(MessageSkeletonModel).filter(
                            MessageSkeletonModel.channel_discord_id == int(safe_cid),
                            MessageSkeletonModel.message_id == int(safe_mid),
                        ).first()
                        if row is not None:
                            row.flags = int(row.flags or 0) | int(SkeletonFlags.IS_DELETED)
                except Exception:
                    pass
            return None

        if resp.status_code != 200:
            return None

        raw_msg = resp.json()
        if not isinstance(raw_msg, dict):
            return None
        return serialize_message(
            raw_msg,
            guild_id=guild_id,
            channels_by_id=channels_by_id,
            roles_by_id=roles_by_id,
            members_by_id=members_by_id,
        )

    async def fetch_message_range(
        self,
        channel_id: str,
        start_id: str,
        end_id: str,
        *,
        guild_id: str = "",
        channels_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
        roles_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
        members_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetches chronological serialized messages within [start_id, end_id] inclusive."""
        safe_cid = validate_snowflake(channel_id, "channel_id")
        start_int = int(validate_snowflake(start_id, "start_id"))
        end_int = int(validate_snowflake(end_id, "end_id"))
        if end_int < start_int:
            return []

        await self.verify_bot_token()
        boundary = str(max(0, start_int - 1))
        collected: List[Dict[str, Any]] = []

        while True:
            batch = await self._request_json(
                "GET",
                f"channels/{safe_cid}/messages",
                params={"limit": 100, "after": boundary},
                optional=True,
            )
            if not isinstance(batch, list) or not batch:
                break
            batch_chrono = list(reversed(batch))
            reached_end = False
            for raw_msg in batch_chrono:
                mid_int = int(raw_msg["id"])
                if mid_int > end_int:
                    reached_end = True
                    break
                if mid_int >= start_int:
                    collected.append(
                        serialize_message(
                            raw_msg,
                            guild_id=guild_id,
                            channels_by_id=channels_by_id,
                            roles_by_id=roles_by_id,
                            members_by_id=members_by_id,
                        )
                    )
            last_id = str(batch_chrono[-1]["id"])
            if reached_end or int(last_id) >= end_int or len(batch) < 100:
                break
            boundary = last_id

        return collected


def _run_coro_sync(coro):
    """Runs an async coroutine safely from synchronous code (even if a loop is active)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_box: Dict[str, Any] = {}
    error_box: Dict[str, BaseException] = {}

    def _runner():
        try:
            result_box["value"] = asyncio.run(coro)
        except BaseException as exc_obj:
            error_box["error"] = exc_obj

    th = threading.Thread(target=_runner, daemon=True)
    th.start()
    th.join()
    if "error" in error_box:
        raise error_box["error"]
    return result_box.get("value")


def get_categories(
    server_id: str,
    *,
    token: Optional[str] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> Dict[str, str]:
    """
    Synchronous entrypoint used by src/server.py (`GET /api/servers/{server_id}/categories`).
    Validates `server_id` via `validate_snowflake`, verifies Bot token, and returns
    `{category_discord_id: "<pos># <name>"}`. Raises `exc.GetChannelListError` on invalid IDs or API errors.
    """
    try:
        safe_server_id = validate_snowflake(server_id, "server_id")
    except ValueError as ve:
        raise exc.GetChannelListError(f"Invalid server_id: {ve}") from ve

    async def _run() -> Dict[str, str]:
        async with DiscordExtractor(token=token, transport=transport) as extractor:
            return await extractor.fetch_categories(safe_server_id)

    try:
        return _run_coro_sync(_run())
    except exc.GetChannelListError:
        raise
    except Exception as e:
        raise exc.GetChannelListError(f"Failed to get the list of categories: {e}") from e


def fetch_message_content_sync(
    backup_id: str,
    channel_discord_id: str,
    message_id: str,
    *,
    token: Optional[str] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> Optional[str]:
    """
    Lightweight synchronous excerpt provider wrapper wired into `src/db/scene_service.py`.
    Returns raw/formatted message content or None silently if DISCORD_TOKEN is unset or request fails.
    """
    raw_tok = token if token is not None else os.environ.get("DISCORD_TOKEN", "").strip()
    if not raw_tok:
        return None
    try:
        validate_snowflake(channel_discord_id, "channel_id")
        validate_snowflake(message_id, "message_id")
    except ValueError:
        return None

    async def _run() -> Optional[str]:
        base_path = None
        try:
            base_path = t.get_backup_path(str(backup_id))
        except Exception:
            base_path = None
        async with DiscordExtractor(token=raw_tok, transport=transport) as extractor:
            msg = await extractor.fetch_message(
                channel_discord_id,
                message_id,
                backup_id=backup_id,
                base_path=base_path,
            )
            if isinstance(msg, dict):
                return str(msg.get("content") or "")
            return None

    try:
        return _run_coro_sync(_run())
    except Exception:
        return None

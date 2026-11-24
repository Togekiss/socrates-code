"""
Path containment, identifier validation, SQL LIKE escaping, and secret env scrubbing utilities.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Union

_CATEGORY_PREFIX_RE = re.compile(r"^\d+#\s*")


def strip_category_prefix(name: Any) -> str:
    """Strips a leading '<pos># ' position prefix from category names saved by DCE or UI selectors."""
    return _CATEGORY_PREFIX_RE.sub("", str(name or "")).strip()


def expand_category_names(names: Optional[Iterable[Any]]) -> Set[str]:
    """Builds a lookup set containing both raw and position-prefix-stripped category names."""
    expanded: Set[str] = set()
    for raw in names or ():
        raw_s = str(raw or "").strip()
        if raw_s:
            expanded.add(raw_s)
        stripped = strip_category_prefix(raw_s)
        if stripped:
            expanded.add(stripped)
    return expanded


def category_name_matches(cat_name: Any, targets: Set[str]) -> bool:
    """Returns True if cat_name (raw or stripped of leading '<pos># ') appears in targets."""
    raw_s = str(cat_name or "").strip()
    if raw_s in targets:
        return True
    stripped = strip_category_prefix(raw_s)
    return bool(stripped and stripped in targets)


def category_matches(cat_id: Any, cat_name: Any, targets: Set[str]) -> bool:
    """Returns True if cat_id matches an entry in targets, or cat_name matches via category_name_matches."""
    if not targets:
        return False
    cid = str(cat_id or "").strip()
    if cid and (cid in targets or any(str(x or "").strip() == cid for x in targets)):
        return True
    return category_name_matches(cat_name, targets)

SNOWFLAKE_RE = re.compile(r"^\d{15,22}$")
CHANNEL_ID_RE = re.compile(r"^\d{1,20}$")
BACKUP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SAFE_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SAFE_BACKUP_RELPATH_RE = re.compile(r"^Backups/[A-Za-z0-9_-]{1,64}$")
DISCORD_MSG_LINK_RE = re.compile(
    r"^https?://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/channels/"
    r"(?P<guild_id>\d{15,22})/(?P<channel_id>\d{15,22})/(?P<message_id>\d{15,22})"
    r"(?:[/?#].*)?$"
)

MAX_CHANNEL_IDS = 100
MAX_SEARCH_QUERY_LEN = 500
SENSITIVE_ENV_VARS = ("JWT_SECRET", "DISCORD_CLIENT_SECRET", "DISCORD_TOKEN")


def validate_snowflake(value: Any, field_name: str = "id") -> str:
    """Validates a Discord snowflake ID (15-22 ASCII digits)."""
    s = str(value).strip() if value is not None else ""
    if not SNOWFLAKE_RE.fullmatch(s):
        raise ValueError(f"Invalid {field_name}: must be 15-22 digits")
    return s


def validate_channel_ids(channel_ids: Any, max_count: int = MAX_CHANNEL_IDS) -> List[str]:
    """Validates a list of Discord channel/category IDs (`^\\d{1,20}$`, bounded count)."""
    if channel_ids is None:
        return []
    if not isinstance(channel_ids, list):
        raise ValueError("channel_ids must be a list of numeric strings")
    if len(channel_ids) > max_count:
        raise ValueError(f"channel_ids exceeds maximum of {max_count} items")
    validated: List[str] = []
    for raw in channel_ids:
        s = str(raw).strip() if raw is not None else ""
        if not CHANNEL_ID_RE.fullmatch(s):
            raise ValueError(f"Invalid channel_id '{s}': must match ^\\d{{1,20}}$")
        validated.append(s)
    return validated


def validate_backup_id(backup_id: Any) -> str:
    """Validates a backup ID (`^[A-Za-z0-9_-]{1,64}$`), blocking traversal or separator characters."""
    s = str(backup_id).strip() if backup_id is not None else ""
    if not BACKUP_ID_RE.fullmatch(s):
        raise ValueError("Invalid backup_id: must match ^[A-Za-z0-9_-]{1,64}$")
    return s


def sanitize_backup_slug(name: Optional[str], default: str = "backup") -> str:
    """Sanitizes a backup or server name into a safe single directory slug."""
    raw = str(name or "").strip()
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")[:64]
    if not slug or slug in {".", ".."}:
        return default
    return slug


def safe_join_within(base_dir: Union[str, Path], *parts: str) -> Path:
    """Safely joins path components under base_dir, rejecting traversal or escapes."""
    base_resolved = Path(base_dir).resolve()
    cleaned_parts: List[str] = []
    for part in parts:
        part_str = str(part or "")
        if not part_str or "\x00" in part_str or part_str.startswith(("/", "\\")):
            raise ValueError(f"Unsafe path component: {part!r}")
        p = Path(part_str)
        if p.is_absolute() or ".." in p.parts or "." in p.parts:
            raise ValueError(f"Path traversal not permitted: {part!r}")
        cleaned_parts.append(part_str)

    candidate = base_resolved.joinpath(*cleaned_parts).resolve()
    if not candidate.is_relative_to(base_resolved):
        raise ValueError("Resolved path escapes base directory")
    return candidate


def ensure_safe_backup_path(candidate: Union[str, Path], data_root: Union[str, Path]) -> Path:
    """Verifies candidate path stays strictly within `<data_root>/Backups`."""
    if candidate is None or str(candidate).strip() == "":
        raise ValueError("Backup path cannot be empty")
    raw_str = str(candidate)
    if "\x00" in raw_str:
        raise ValueError("Null byte in backup path")
    raw_path = Path(raw_str)
    if ".." in raw_path.parts:
        raise ValueError("Parent directory traversal is not allowed in backup path")

    # Use lexical normalization (abspath) rather than .resolve() so legitimate
    # directory junctions/symlinks configured under Backups/ remain valid.
    backups_root = Path(os.path.abspath(Path(data_root) / "Backups"))
    if raw_path.is_absolute():
        normalized = Path(os.path.abspath(raw_path))
    else:
        normalized = Path(os.path.abspath(Path(data_root) / raw_path))

    cmp_root = Path(os.path.normcase(str(backups_root))) if os.name == "nt" else backups_root
    cmp_cand = Path(os.path.normcase(str(normalized))) if os.name == "nt" else normalized

    if cmp_cand == cmp_root or not cmp_cand.is_relative_to(cmp_root):
        raise ValueError(f"Backup path escapes Backups directory: {normalized}")
    return normalized


def escape_like(value: str) -> str:
    """Escapes SQL LIKE special wildcards (\\, %, _) using backslash as the escape character."""
    return str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def validate_search_query_safety(
    value: Optional[str],
    max_len: int = MAX_SEARCH_QUERY_LEN,
) -> Optional[str]:
    """Bounds search query strings to prevent oversized or abusive filter inputs."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Search query must be a string")
    if len(value) > max_len:
        raise ValueError(f"Search query exceeds maximum length of {max_len} characters")
    return value


def scrub_sensitive_env(
    env: Optional[Dict[str, str]] = None,
    *,
    keep_discord_token: bool = False,
) -> Dict[str, str]:
    """Returns a copy of env with secret credentials removed for subprocess execution."""
    cleaned = dict(os.environ if env is None else env)
    cleaned.pop("JWT_SECRET", None)
    cleaned.pop("DISCORD_CLIENT_SECRET", None)
    if not keep_discord_token:
        cleaned.pop("DISCORD_TOKEN", None)
    return cleaned

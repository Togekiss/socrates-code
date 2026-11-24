import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

import utils.tricks as t

ROLE_LEVELS: Dict[str, int] = {
    "viewer": 1,
    "participant": 2,
    "curator": 3,
    "server_admin": 4,
    "instance_admin": 5,
}
VALID_ROLES: Set[str] = set(ROLE_LEVELS.keys())

ADMINISTRATOR_BIT = 0x8
MANAGE_GUILD_BIT = 0x20

SNOWFLAKE_RE = re.compile(r"^\d{15,22}$")

GUILD_ROLES_CACHE_TTL_SECONDS = 300.0
MEMBER_ROLES_CACHE_TTL_SECONDS = 300.0
RBAC_RATE_LIMIT_DEFAULT_SECONDS = 15.0
RBAC_ERROR_BACKOFF_SECONDS = 5.0

_RBAC_CACHE_LOCK = threading.Lock()
_RBAC_FETCH_LOCKS: Dict[Tuple[Any, ...], threading.Lock] = {}
_GUILD_ROLES_CACHE: Dict[str, Tuple[float, str, List[Dict[str, Any]]]] = {}
_MEMBER_ROLES_CACHE: Dict[Tuple[str, str], Tuple[float, str, Set[str]]] = {}
_GUILD_ROLES_BACKOFF: Dict[str, Tuple[float, str]] = {}
_MEMBER_ROLES_BACKOFF: Dict[Tuple[str, str], Tuple[float, str]] = {}


def _get_rbac_fetch_lock(key: Tuple[Any, ...]) -> threading.Lock:
    with _RBAC_CACHE_LOCK:
        lock = _RBAC_FETCH_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _RBAC_FETCH_LOCKS[key] = lock
        return lock


def parse_retry_after(resp: Any, default: float = RBAC_RATE_LIMIT_DEFAULT_SECONDS) -> float:
    """Extracts and clamps Discord's Retry-After delay (in seconds) from headers or JSON body."""
    headers = getattr(resp, "headers", None)
    if headers is not None and hasattr(headers, "get"):
        for hdr_name in ("Retry-After", "retry-after"):
            raw = headers.get(hdr_name)
            if isinstance(raw, (int, float, str)):
                try:
                    return max(1.0, min(float(raw), 120.0))
                except (TypeError, ValueError):
                    pass
    json_fn = getattr(resp, "json", None)
    if callable(json_fn):
        try:
            body = json_fn()
            if isinstance(body, dict):
                raw = body.get("retry_after")
                if isinstance(raw, (int, float, str)):
                    return max(1.0, min(float(raw), 120.0))
        except Exception:
            pass
    return default


def clear_rbac_caches(guild_id: Optional[str] = None) -> None:
    """Clears cached Discord guild roles, guild member role sets, and backoff windows."""
    with _RBAC_CACHE_LOCK:
        if guild_id is None:
            _GUILD_ROLES_CACHE.clear()
            _MEMBER_ROLES_CACHE.clear()
            _GUILD_ROLES_BACKOFF.clear()
            _MEMBER_ROLES_BACKOFF.clear()
        else:
            gid = str(guild_id)
            _GUILD_ROLES_CACHE.pop(gid, None)
            _GUILD_ROLES_BACKOFF.pop(gid, None)
            for cache_map in (_MEMBER_ROLES_CACHE, _MEMBER_ROLES_BACKOFF):
                keys_to_drop = [k for k in cache_map if k[0] == gid]
                for k in keys_to_drop:
                    cache_map.pop(k, None)


def _dedupe_str_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    seen: Set[str] = set()
    out: List[str] = []
    for item in values:
        if item is None:
            continue
        cleaned = str(item).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def normalize_rbac_config(raw: Any, include_user_roles: bool = False) -> Dict[str, List[str]]:
    """Normalizes a backup's RBAC mapping object with safe empty-list defaults."""
    src = raw if isinstance(raw, dict) else {}
    normalized = {
        "adminRoleIds": _dedupe_str_list(src.get("adminRoleIds")),
        "curatorRoleIds": _dedupe_str_list(src.get("curatorRoleIds")),
        "participantRoleIds": _dedupe_str_list(src.get("participantRoleIds")),
        "restrictedUserIds": _dedupe_str_list(src.get("restrictedUserIds")),
        "blockedUserIds": _dedupe_str_list(src.get("blockedUserIds")),
    }
    if include_user_roles:
        normalized["adminUserIds"] = _dedupe_str_list(src.get("adminUserIds"))
        normalized["curatorUserIds"] = _dedupe_str_list(src.get("curatorUserIds"))
        normalized["participantUserIds"] = _dedupe_str_list(src.get("participantUserIds"))
    return normalized


class RbacConfigSchema(BaseModel):
    """Strict schema for per-backup RBAC role and user restriction mappings."""

    model_config = ConfigDict(extra="forbid")

    adminRoleIds: List[str] = Field(default_factory=list)
    curatorRoleIds: List[str] = Field(default_factory=list)
    participantRoleIds: List[str] = Field(default_factory=list)
    restrictedUserIds: List[str] = Field(default_factory=list)
    blockedUserIds: List[str] = Field(default_factory=list)

    @field_validator(
        "adminRoleIds",
        "curatorRoleIds",
        "participantRoleIds",
        "restrictedUserIds",
        "blockedUserIds",
        mode="before",
    )
    @classmethod
    def _validate_snowflake_list(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Must be a list of Discord snowflake IDs")
        seen: Set[str] = set()
        result: List[str] = []
        for item in value:
            if not isinstance(item, (str, int)):
                raise ValueError("Snowflake ID must be a string")
            cleaned = str(item).strip()
            if not SNOWFLAKE_RE.fullmatch(cleaned):
                raise ValueError(f"Invalid Discord snowflake ID: {cleaned!r}")
            if cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result


def _resolve_rbac_target(
    base_path: Optional[str] = None,
    backup_id: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    b_id = str(backup_id).strip() if backup_id is not None and str(backup_id).strip() else None
    b_path = str(base_path).strip() if base_path is not None and str(base_path).strip() else None
    if b_id is None and b_path is not None:
        if "/" not in b_path and "\\" not in b_path and not Path(b_path).exists():
            b_id = b_path
            b_path = None
    return b_id, b_path


def load_backup_rbac_config(
    base_path: Optional[str] = None,
    backup_id: Optional[str] = None,
    include_user_roles: bool = False,
) -> Dict[str, List[str]]:
    """Reads normalized RBAC config from SQL (BackupRbacEntryModel) or backup_config.json fallback."""
    from db.config_service import load_rbac_config_dict

    b_id, b_path = _resolve_rbac_target(base_path=base_path, backup_id=backup_id)
    try:
        return load_rbac_config_dict(
            backup_id=b_id,
            backup_path=b_path,
            include_user_roles=include_user_roles,
        )
    except Exception as e:
        t.global_log("warning", f"RBAC: Failed to load RBAC config for path={b_path} id={b_id}: {e}")
        return normalize_rbac_config({}, include_user_roles=include_user_roles)


def save_backup_rbac_config(
    base_path: Optional[str] = None,
    rbac_data: Optional[Dict[str, Any]] = None,
    guild_id: Optional[str] = None,
    backup_id: Optional[str] = None,
) -> Dict[str, List[str]]:
    """Persists normalized RBAC config into SQL (or backup_config.json fallback) and invalidates member caches."""
    from db.config_service import save_rbac_config_dict

    b_id, b_path = _resolve_rbac_target(base_path=base_path, backup_id=backup_id)
    has_ext_user_keys = isinstance(rbac_data, dict) and any(
        k in rbac_data for k in ("adminUserIds", "curatorUserIds", "participantUserIds")
    )
    normalized = normalize_rbac_config(rbac_data, include_user_roles=has_ext_user_keys)
    saved = save_rbac_config_dict(backup_id=b_id, backup_path=b_path, rbac_data=normalized)
    if guild_id:
        clear_rbac_caches(str(guild_id))
    return saved


def _read_guild_roles_cache(gid: str, token: str, force_refresh: bool) -> Tuple[bool, List[Dict[str, Any]], bool]:
    if force_refresh:
        return (False, [], False)
    now = time.monotonic()
    with _RBAC_CACHE_LOCK:
        cached = _GUILD_ROLES_CACHE.get(gid)
        if cached and cached[1] == token and now < cached[0]:
            return (True, list(cached[2]), True)
        backoff = _GUILD_ROLES_BACKOFF.get(gid)
        if backoff and backoff[1] == token and now < backoff[0]:
            if cached and cached[1] == token:
                return (True, list(cached[2]), True)
            return (True, [], False)
    return (False, [], False)


def _stale_guild_roles(gid: str, token: str, backoff_seconds: float) -> Tuple[List[Dict[str, Any]], bool]:
    with _RBAC_CACHE_LOCK:
        _GUILD_ROLES_BACKOFF[gid] = (time.monotonic() + backoff_seconds, token)
        cached = _GUILD_ROLES_CACHE.get(gid)
        if cached and cached[1] == token:
            return (list(cached[2]), True)
    return ([], False)


def fetch_guild_roles(
    guild_id: str,
    bot_token: Optional[str],
    force_refresh: bool = False,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Fetches Discord guild roles via Bot API using single-flight locking, 300s TTL cache, and 429 backoff."""
    token = (bot_token or "").strip()
    gid = str(guild_id or "").strip()
    if not gid or not token or token == "your_bot_token_here":
        return ([], False)

    hit, cached_roles, cached_ok = _read_guild_roles_cache(gid, token, force_refresh)
    if hit:
        return (cached_roles, cached_ok)

    with _get_rbac_fetch_lock(("guild_roles", gid)):
        hit, cached_roles, cached_ok = _read_guild_roles_cache(gid, token, force_refresh)
        if hit:
            return (cached_roles, cached_ok)

        try:
            resp = httpx.get(
                f"https://discord.com/api/v10/guilds/{gid}/roles",
                headers={"Authorization": f"Bot {token}"},
                timeout=10.0,
            )
            if resp.status_code == 429:
                retry_after = parse_retry_after(resp)
                t.global_log(
                    "warning",
                    f"RBAC: Discord guild roles rate-limited for {gid} (HTTP 429, retry_after={retry_after:.1f}s)",
                )
                return _stale_guild_roles(gid, token, retry_after)
            if resp.status_code != 200:
                t.global_log("warning", f"RBAC: Discord guild roles lookup failed for {gid} (status={resp.status_code})")
                return _stale_guild_roles(gid, token, RBAC_ERROR_BACKOFF_SECONDS)
            raw_roles = resp.json()
            if not isinstance(raw_roles, list):
                return ([], False)
            roles: List[Dict[str, Any]] = []
            for r in raw_roles:
                if not isinstance(r, dict):
                    continue
                rid = str(r.get("id") or "")
                name = str(r.get("name") or "")
                if not rid or rid == gid or name == "@everyone":
                    continue
                roles.append(
                    {
                        "id": rid,
                        "name": name,
                        "color": int(r.get("color") or 0),
                        "position": int(r.get("position") or 0),
                    }
                )
            roles.sort(key=lambda item: item["position"], reverse=True)
            with _RBAC_CACHE_LOCK:
                _GUILD_ROLES_CACHE[gid] = (time.monotonic() + GUILD_ROLES_CACHE_TTL_SECONDS, token, roles)
                _GUILD_ROLES_BACKOFF.pop(gid, None)
            return (list(roles), True)
        except Exception as e:
            t.global_log("warning", f"RBAC: Error fetching guild roles for {gid}: {e}")
            return _stale_guild_roles(gid, token, RBAC_ERROR_BACKOFF_SECONDS)


def _read_member_roles_cache(
    cache_key: Tuple[str, str], token: str, force_refresh: bool
) -> Tuple[bool, Optional[Set[str]]]:
    if force_refresh:
        return (False, None)
    now = time.monotonic()
    with _RBAC_CACHE_LOCK:
        cached = _MEMBER_ROLES_CACHE.get(cache_key)
        if cached and cached[1] == token and now < cached[0]:
            return (True, set(cached[2]))
        backoff = _MEMBER_ROLES_BACKOFF.get(cache_key)
        if backoff and backoff[1] == token and now < backoff[0]:
            if cached and cached[1] == token:
                return (True, set(cached[2]))
            return (True, None)
    return (False, None)


def _stale_member_roles(
    cache_key: Tuple[str, str], token: str, backoff_seconds: float
) -> Optional[Set[str]]:
    with _RBAC_CACHE_LOCK:
        _MEMBER_ROLES_BACKOFF[cache_key] = (time.monotonic() + backoff_seconds, token)
        cached = _MEMBER_ROLES_CACHE.get(cache_key)
        if cached and cached[1] == token:
            return set(cached[2])
    return None


def fetch_guild_member_roles(
    guild_id: str,
    user_id: str,
    bot_token: Optional[str],
    force_refresh: bool = False,
) -> Optional[Set[str]]:
    """Fetches a Discord user's role IDs via Bot API using single-flight locking, 300s TTL cache, and 429 backoff."""
    token = (bot_token or "").strip()
    gid = str(guild_id or "").strip()
    uid = str(user_id or "").strip()
    if not gid or not uid or uid == "0" or not token or token == "your_bot_token_here":
        return None

    cache_key = (gid, uid)
    hit, cached_roles = _read_member_roles_cache(cache_key, token, force_refresh)
    if hit:
        return cached_roles

    with _get_rbac_fetch_lock(("member_roles", gid, uid)):
        hit, cached_roles = _read_member_roles_cache(cache_key, token, force_refresh)
        if hit:
            return cached_roles

        try:
            resp = httpx.get(
                f"https://discord.com/api/v10/guilds/{gid}/members/{uid}",
                headers={"Authorization": f"Bot {token}"},
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                role_ids = {str(rid) for rid in data.get("roles", []) if rid is not None} if isinstance(data, dict) else set()
                with _RBAC_CACHE_LOCK:
                    _MEMBER_ROLES_CACHE[cache_key] = (time.monotonic() + MEMBER_ROLES_CACHE_TTL_SECONDS, token, role_ids)
                    _MEMBER_ROLES_BACKOFF.pop(cache_key, None)
                return set(role_ids)
            if resp.status_code == 404:
                empty: Set[str] = set()
                with _RBAC_CACHE_LOCK:
                    _MEMBER_ROLES_CACHE[cache_key] = (time.monotonic() + MEMBER_ROLES_CACHE_TTL_SECONDS, token, empty)
                    _MEMBER_ROLES_BACKOFF.pop(cache_key, None)
                return set()
            if resp.status_code == 429:
                retry_after = parse_retry_after(resp)
                t.global_log(
                    "warning",
                    f"RBAC: Discord member lookup rate-limited for guild={gid} user={uid} (HTTP 429, retry_after={retry_after:.1f}s)",
                )
                return _stale_member_roles(cache_key, token, retry_after)
            t.global_log(
                "warning",
                f"RBAC: Discord guild member lookup failed for guild={gid} user={uid} (status={resp.status_code})",
            )
            return _stale_member_roles(cache_key, token, RBAC_ERROR_BACKOFF_SECONDS)
        except Exception as e:
            t.global_log("warning", f"RBAC: Error fetching guild member roles for guild={gid} user={uid}: {e}")
            return _stale_member_roles(cache_key, token, RBAC_ERROR_BACKOFF_SECONDS)


def _find_user_guild_entry(actor: Dict[str, Any], server_id: str) -> Optional[Dict[str, Any]]:
    auth_guilds = actor.get("authorized_guilds", [])
    if not isinstance(auth_guilds, list):
        return None
    for g in auth_guilds:
        if isinstance(g, dict) and str(g.get("id") or "") == server_id:
            return g
    return None


def resolve_backup_role(
    backup_id: str,
    entry: Dict[str, Any],
    base_path: str,
    actor: Dict[str, Any],
    is_instance_admin_fn: Callable[[Optional[Dict[str, Any]]], bool],
    effective_bot_guilds_fn: Callable[[Dict[str, Any]], Set[str]],
    extract_user_guild_ids_fn: Callable[[Dict[str, Any]], Set[str]],
    bot_token: Optional[str],
    is_production: bool,
    socrates_env: str,
) -> Tuple[str, int]:
    """Resolves (role_name, role_level) for an actor on a specific backup, raising 403 on denial."""
    if is_instance_admin_fn(actor):
        return ("instance_admin", ROLE_LEVELS["instance_admin"])

    if (
        actor.get("_direct_call") is True
        and actor.get("auth_method") == "cli"
        and actor.get("_verified_http") is not True
    ):
        return ("instance_admin", ROLE_LEVELS["instance_admin"])

    server_id = str(entry.get("server_id") or "")
    authorized_guilds = extract_user_guild_ids_fn(actor)
    if not server_id or server_id not in authorized_guilds:
        raise HTTPException(status_code=403, detail="Access denied for this backup")

    live_bot_guilds = effective_bot_guilds_fn(actor)
    if server_id not in live_bot_guilds:
        raise HTTPException(status_code=403, detail="Bot is no longer in this backup's server")

    rbac_cfg = load_backup_rbac_config(base_path, backup_id=backup_id, include_user_roles=True)
    user_id = str(actor.get("sub") or actor.get("id") or "").strip()

    if user_id and user_id in set(rbac_cfg["blockedUserIds"]):
        raise HTTPException(status_code=403, detail="Your access to this backup is blocked")

    if actor.get("auth_method") == "dev" and not is_production and socrates_env == "development":
        dev_role = str(actor.get("dev_role") or "viewer").strip().lower()
        if dev_role == "server_admin":
            return ("server_admin", ROLE_LEVELS["server_admin"])
        if user_id and user_id in set(rbac_cfg["restrictedUserIds"]):
            return ("viewer", ROLE_LEVELS["viewer"])
        if dev_role in ROLE_LEVELS:
            return (dev_role, ROLE_LEVELS[dev_role])
        return ("viewer", ROLE_LEVELS["viewer"])

    guild_entry = _find_user_guild_entry(actor, server_id) or {}
    is_owner = bool(guild_entry.get("owner", False))
    try:
        perms = int(guild_entry.get("permissions") or 0)
    except (TypeError, ValueError):
        perms = 0
    has_discord_admin_perm = is_owner or bool(perms & (ADMINISTRATOR_BIT | MANAGE_GUILD_BIT))

    member_roles = fetch_guild_member_roles(server_id, user_id, bot_token) or set()

    if (
        has_discord_admin_perm
        or (member_roles & set(rbac_cfg["adminRoleIds"]))
        or (user_id and user_id in set(rbac_cfg.get("adminUserIds", [])))
    ):
        return ("server_admin", ROLE_LEVELS["server_admin"])

    if user_id and user_id in set(rbac_cfg["restrictedUserIds"]):
        return ("viewer", ROLE_LEVELS["viewer"])

    if (member_roles & set(rbac_cfg["curatorRoleIds"])) or (
        user_id and user_id in set(rbac_cfg.get("curatorUserIds", []))
    ):
        return ("curator", ROLE_LEVELS["curator"])

    if (member_roles & set(rbac_cfg["participantRoleIds"])) or (
        user_id and user_id in set(rbac_cfg.get("participantUserIds", []))
    ):
        return ("participant", ROLE_LEVELS["participant"])

    return ("viewer", ROLE_LEVELS["viewer"])


def assert_participant_writer_update(
    backup_id: str,
    base_path: str,
    writer_id: int,
    caller_id: str,
    requested_discord_user_id: Optional[str],
) -> None:
    """Enforces Participant self-service ownership and field restrictions on writer updates."""
    from db.models import WriterModel
    from db.session import db_session, init_db, require_db

    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path, check_version=False)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        writer = (
            session.query(WriterModel)
            .filter(
                WriterModel.pk == writer_id,
                WriterModel.backup_id == str(backup_id),
            )
            .first()
        )
        if not writer:
            raise HTTPException(status_code=404, detail=f"Writer #{writer_id} not found.")
        owner_uid = str(writer.discord_user_id or "").strip()
        if not owner_uid or not caller_id or owner_uid != str(caller_id):
            raise HTTPException(status_code=403, detail="Participants can only edit their own linked writer profile")
        if requested_discord_user_id is not None and requested_discord_user_id.strip() != owner_uid:
            raise HTTPException(status_code=403, detail="Participants cannot change discord_user_id")


def assert_participant_character_update(
    backup_id: str,
    base_path: str,
    char_id: int,
    caller_id: str,
    requested_writer: Optional[List[str]],
    requested_writer_id: Optional[int] = None,
    writer_id_provided: bool = False,
) -> None:
    """Enforces Participant self-service ownership and rejects writer reassignment on character updates."""
    from db.models import CharacterModel
    from db.session import db_session, init_db, require_db

    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path, check_version=False)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        char = (
            session.query(CharacterModel)
            .filter(
                CharacterModel.backup_id == str(backup_id),
                CharacterModel.char_id == char_id,
            )
            .first()
        )
        if not char:
            raise HTTPException(status_code=404, detail=f"Character {char_id} not found")
        writer = char.writer
        owner_uid = str(writer.discord_user_id or "").strip() if writer else ""
        if not writer or not owner_uid or not caller_id or owner_uid != str(caller_id):
            raise HTTPException(status_code=403, detail="Participants can only edit characters assigned to them")

        if writer_id_provided and requested_writer_id != writer.pk:
            raise HTTPException(status_code=403, detail="Participants cannot reassign character writer")

        if requested_writer is not None:
            cleaned = [w.strip().lower() for w in requested_writer if w and w.strip()]
            own_names = {writer.display_name.strip().lower()}
            for a in writer.aliases:
                if a.alias and a.alias.strip():
                    own_names.add(a.alias.strip().lower())
            if not cleaned or any(name not in own_names for name in cleaned):
                raise HTTPException(status_code=403, detail="Participants cannot reassign character writer")


def assert_participant_characters_ownership(
    backup_id: str,
    base_path: str,
    char_ids: List[int],
    caller_id: str,
) -> None:
    """Enforces that every character in char_ids belongs to the Participant caller's linked writer."""
    from db.models import CharacterModel
    from db.session import db_session, init_db, require_db

    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path, check_version=False)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        for cid in char_ids:
            char = (
                session.query(CharacterModel)
                .filter(
                    CharacterModel.backup_id == str(backup_id),
                    CharacterModel.char_id == cid,
                )
                .first()
            )
            if not char:
                raise HTTPException(status_code=404, detail=f"Character {cid} not found")
            writer = char.writer
            owner_uid = str(writer.discord_user_id or "").strip() if writer else ""
            if not writer or not owner_uid or not caller_id or owner_uid != str(caller_id):
                raise HTTPException(
                    status_code=403,
                    detail="Participants can only nest or unnest their own assigned characters",
                )

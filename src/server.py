import asyncio
import base64
import contextvars
import hashlib
import hmac
import os
import re
import secrets
import sys
import json
import subprocess
import tempfile
import threading
import time
import traceback
import uuid
import weakref
from collections import deque
from contextlib import asynccontextmanager

################ File summary #################

"""
This module serves as the FastAPI backend for Socrates. It exposes REST API endpoints 
that the React frontend uses to query, manage, and execute background tasks related 
to Discord backups.

Main functionality:
    - Managing and tracking subprocesses for downloading and parsing Discord backups.
    - Providing read/write access to backup configurations and logs.
    - Exposing endpoints for complex Scene filtering with pagination via SQLite.
    - Exposing endpoints for manipulating Characters, Writers, Groups, Scene Issues,
      Flagged Messages, and Overrides backed exclusively by SQLite.
"""

###############################################

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Depends, Cookie, Response, Request, Body
from fastapi.params import Depends as DependsParam
from fastapi.responses import StreamingResponse, FileResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional, Set, Tuple
import httpx
import jwt
from pathlib import Path
import urllib.parse
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Add src to sys.path so that 'utils' and 'db' can be imported
sys.path.insert(0, Path(__file__).resolve().parent.as_posix())
import rbac
import utils.tricks as t
from utils import exceptions as exc
from utils.path_safety import (
    ensure_safe_backup_path,
    safe_join_within,
    sanitize_backup_slug,
    scrub_sensitive_env,
    validate_backup_id,
    validate_snowflake,
)
from models.config_schemas import BackupConfigSchema, GlobalConfigSchema
from db import audit_service, character_service, curation_service, status_service
from db.models import Step, Status, IssueResolution
from sqlalchemy.exc import SQLAlchemyError


def get_project_root():
    return Path(__file__).resolve().parent.parent.as_posix()


def get_data_root():
    return Path(os.environ.get("SOCRATES_DATA_DIR", get_project_root())).as_posix()


# Load .env before reading SOCRATES_ENV, JWT_SECRET, CORS, or FastAPI settings
load_dotenv((Path(get_project_root()) / '.env').as_posix())

VALID_DEV_ROLES = {"instance_admin", "server_admin", "curator", "participant", "viewer"}
KNOWN_WEAK_JWT_SECRETS = {
    "dev_secret",
    "dev-secret-change-me",
    "your_random_secure_jwt_secret_here",
}
_EPHEMERAL_DEV_JWT_SECRET: Optional[str] = None
_EPHEMERAL_DEV_JWT_WARNED: bool = False


def get_socrates_env() -> str:
    return (os.environ.get("SOCRATES_ENV") or "development").strip().lower()


def is_production_env() -> bool:
    return bool(os.environ.get("K_SERVICE", "").strip()) or get_socrates_env() == "production"


SOCRATES_ENV = get_socrates_env()
IS_PRODUCTION = is_production_env()


def _get_ephemeral_dev_jwt_secret() -> str:
    global _EPHEMERAL_DEV_JWT_SECRET, _EPHEMERAL_DEV_JWT_WARNED
    if _EPHEMERAL_DEV_JWT_SECRET is None:
        _EPHEMERAL_DEV_JWT_SECRET = secrets.token_urlsafe(32)
    if not _EPHEMERAL_DEV_JWT_WARNED:
        _EPHEMERAL_DEV_JWT_WARNED = True
        t.global_log(
            "warning",
            "API: JWT_SECRET is unset or placeholder in non-production; generated ephemeral process-wide secret.",
        )
    return _EPHEMERAL_DEV_JWT_SECRET


def resolve_jwt_secret() -> str:
    raw_secret = os.environ.get("JWT_SECRET", "").strip()
    if is_production_env():
        if not raw_secret or len(raw_secret) < 32 or raw_secret.lower() in KNOWN_WEAK_JWT_SECRETS:
            raise RuntimeError(
                "JWT_SECRET must be set to a strong secret (>= 32 characters, non-placeholder) in production."
            )
        return raw_secret

    if not raw_secret or raw_secret.lower() in KNOWN_WEAK_JWT_SECRETS:
        return _get_ephemeral_dev_jwt_secret()
    return raw_secret


def validate_startup_security() -> None:
    resolve_jwt_secret()


validate_startup_security()


class MergeCharactersRequest(BaseModel):
    source_id: int
    target_id: int


class NestCharacterRequest(BaseModel):
    child_id: int
    parent_id: int
    version_type: str = "npc"


class UpdateCharacterRequest(BaseModel):
    tags: Optional[List[str]] = None
    names: Optional[List[str]] = None
    writer: Optional[List[str]] = None
    writer_id: Optional[int] = None


class CreateGroupRequest(BaseModel):
    names: List[str]
    member_ids: List[int]


class UpdateGroupRequest(BaseModel):
    names: Optional[List[str]] = None
    member_ids: Optional[List[int]] = None


class CreateWriterRequest(BaseModel):
    display_name: str
    aliases: Optional[List[str]] = None
    discord_user_id: Optional[str] = None


class UpdateWriterRequest(BaseModel):
    display_name: Optional[str] = None
    aliases: Optional[List[str]] = None
    discord_user_id: Optional[str] = None


class AssignCharacterWriterRequest(BaseModel):
    writer_id: int


class ResolveIssueRequest(BaseModel):
    resolution: str
    note: Optional[str] = None


class PromoteFlaggedMessageRequest(BaseModel):
    content: Optional[str] = None
    author: Optional[Dict[str, Any]] = None


class ManualSplitRequest(BaseModel):
    discord_link: str
    note: Optional[str] = None


class ManualFlaggedMessageRequest(BaseModel):
    discord_link: str
    note: Optional[str] = None


class ResolveFlaggedMessageRequest(BaseModel):
    resolution: str
    note: Optional[str] = None
    override_content: Optional[str] = None
    override_author: Optional[Dict[str, Any]] = None


class UpdateSceneMetadataRequest(BaseModel):
    custom_name: Optional[str] = None
    name: Optional[str] = None


class MergeSceneRequest(BaseModel):
    direction: str
    force: bool = False
    note: Optional[str] = None


class UpdateEventMetadataRequest(BaseModel):
    name: Optional[str] = None
    channel_names: Optional[Dict[Any, Optional[str]]] = None


class MergeEventsRequest(BaseModel):
    event_pks: Optional[List[int]] = None
    target_event_pk: Optional[int] = None
    source_event_pk: Optional[int] = None
    name: Optional[str] = None
    merged_name: Optional[str] = None


class SplitEventRequest(BaseModel):
    scene_ids: Optional[List[Any]] = None
    scene_pks: Optional[List[Any]] = None
    channel_ids: Optional[List[Any]] = None
    new_name: Optional[str] = None
    new_event_name: Optional[str] = None


class AuthCallback(BaseModel):
    code: str
    state: Optional[str] = None
    redirect_uri: Optional[str] = None


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    yield
    from db.session import close_all_engines
    close_all_engines()


app = FastAPI(
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

PROD_CORS_ORIGINS = (
    "https://socrates-backend-509220.web.app",
    "https://socrates-backend-509220.firebaseapp.com",
)
DEV_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)
DEV_CORS_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$"
PROD_CORS_ORIGIN_REGEX = r"^https://socrates-backend-509220\.(web\.app|firebaseapp\.com)$"
_DEV_ORIGIN_RE = re.compile(DEV_CORS_ORIGIN_REGEX)
_PROD_ORIGIN_RE = re.compile(PROD_CORS_ORIGIN_REGEX)


def build_cors_config() -> Dict[str, Any]:
    is_prod = is_production_env()
    origins: List[str] = list(PROD_CORS_ORIGINS) if is_prod else [*DEV_CORS_ORIGINS, *PROD_CORS_ORIGINS]

    extra_origins = os.environ.get("CORS_ORIGINS", "")
    for raw_origin in extra_origins.split(","):
        origin = raw_origin.strip()
        if not origin or origin == "*":
            continue
        if is_prod and not origin.startswith("https://"):
            continue
        if origin not in origins:
            origins.append(origin)

    return {
        "allow_origins": origins,
        "allow_origin_regex": (
            None
            if is_prod
            else f"{DEV_CORS_ORIGIN_REGEX}|{PROD_CORS_ORIGIN_REGEX}"
        ),
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-CSRF-Token", "X-Requested-With"],
    }


def is_origin_allowed(origin: str) -> bool:
    clean = str(origin or "").strip()
    if not clean:
        return False
    cfg = build_cors_config()
    if clean in cfg["allow_origins"]:
        return True
    if _PROD_ORIGIN_RE.fullmatch(clean):
        return True
    if not is_production_env() and _DEV_ORIGIN_RE.fullmatch(clean):
        return True
    return False


app.add_middleware(CORSMiddleware, **build_cors_config())
app.add_middleware(GZipMiddleware, minimum_size=1000)


_REQUEST_AUDIT_CTX: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "_REQUEST_AUDIT_CTX", default=None
)


def _audit(
    *,
    action: str,
    target_type: str,
    target_id: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    actor_role: Optional[str] = None,
    backup_id: Optional[str] = None,
    backup_dir: Optional[str] = None,
    write_global: bool = False,
    before: Any = None,
    after: Any = None,
    metadata: Any = None,
    request: Optional[Request] = None,
    status: str = "success",
) -> None:
    ctx = _REQUEST_AUDIT_CTX.get() or {}
    req_ip = None if request is not None else ctx.get("request_ip")
    req_ua = None if request is not None else ctx.get("user_agent")
    meta = dict(metadata) if isinstance(metadata, dict) else ({"detail": metadata} if metadata is not None else None)
    if ctx and ("method" in ctx or "path" in ctx):
        meta = dict(meta) if meta else {}
        if "method" not in meta and ctx.get("method"):
            meta["method"] = ctx["method"]
        if "path" not in meta and ctx.get("path"):
            meta["path"] = ctx["path"]
    audit_service.record_audit_event(
        action=action,
        target_type=target_type,
        target_id=target_id,
        actor=actor,
        actor_role=actor_role,
        backup_id=backup_id,
        backup_dir=backup_dir,
        data_root=get_data_root(),
        write_global=write_global,
        before=before,
        after=after,
        metadata=meta,
        request=request,
        request_ip=req_ip,
        user_agent=req_ua,
        status=status,
    )


def _snapshot_backup_record(backup_id: str, base_path: str, kind: str, identifier: Any) -> Any:
    """Best-effort lightweight snapshot of a backup SQLite entity for audit before/after diffs."""
    try:
        from db.session import db_session, has_db
        from db.models import (
            CharacterModel,
            CharacterGroupModel,
            EventModel,
            FlaggedMessageModel,
            SceneIssueModel,
            SceneModel,
            WriterModel,
        )

        if not has_db(base_path, backup_id=backup_id):
            return None

        with db_session(backup_id=backup_id, backup_path=base_path) as session:
            if kind == "writer":
                w = session.query(WriterModel).filter_by(backup_id=str(backup_id), pk=int(identifier)).first()
                if not w:
                    return None
                return {
                    "id": w.pk,
                    "display_name": w.display_name,
                    "discord_user_id": w.discord_user_id,
                    "aliases": [a.alias for a in w.aliases],
                }
            if kind == "character":
                c = session.query(CharacterModel).filter_by(backup_id=str(backup_id), char_id=int(identifier)).first()
                if not c:
                    return None
                return {
                    "char_id": c.char_id,
                    "writer_pk": c.writer_pk,
                    "parent_pk": c.parent_pk,
                    "group_pk": c.group_pk,
                    "version_type": c.version_type,
                    "origin": c.origin,
                    "activity": c.activity,
                    "names": [n.name for n in sorted(c.names, key=lambda item: item.position)],
                }
            if kind == "group":
                g = session.query(CharacterGroupModel).filter_by(backup_id=str(backup_id), pk=int(identifier)).first()
                if not g:
                    return None
                return {
                    "id": g.pk,
                    "names": [n.name for n in sorted(g.names, key=lambda item: item.position)],
                    "member_ids": sorted(m.char_id for m in g.characters),
                }
            if kind == "scene":
                key_or_pk = str(identifier)
                q = session.query(SceneModel).filter_by(backup_id=str(backup_id))
                if key_or_pk.isdigit():
                    s = q.filter((SceneModel.pk == int(key_or_pk)) | (SceneModel.scene_key == key_or_pk)).first()
                else:
                    s = q.filter(SceneModel.scene_key == key_or_pk).first()
                if not s:
                    return None
                return {
                    "pk": s.pk,
                    "scene_key": s.scene_key,
                    "custom_name": s.custom_name,
                    "kind": s.kind,
                    "status": s.status,
                    "event_pk": s.event_pk,
                }
            if kind == "event":
                ev = session.query(EventModel).filter_by(backup_id=str(backup_id), pk=int(identifier)).first()
                if not ev:
                    return None
                return {
                    "pk": ev.pk,
                    "event_key": ev.event_key,
                    "name": ev.name,
                    "status": ev.status,
                }
            if kind == "scene_issue":
                issue = session.query(SceneIssueModel).filter_by(backup_id=str(backup_id), pk=int(identifier)).first()
                if not issue:
                    return None
                return {
                    "pk": issue.pk,
                    "resolution": issue.resolution,
                    "resolved_note": issue.resolved_note,
                    "scene_pk": issue.scene_pk,
                }
            if kind == "flagged_message":
                fm = session.query(FlaggedMessageModel).filter_by(backup_id=str(backup_id), message_id=str(identifier)).first()
                if not fm:
                    return None
                return {
                    "pk": fm.pk,
                    "message_id": fm.message_id,
                    "resolution": fm.resolution,
                    "resolved_note": fm.resolved_note,
                    "override_content": fm.override_content,
                    "override_author": fm.override_author,
                }
    except Exception:
        return None
    return None


_API_SECURITY_HEADERS = {
    "Cache-Control": "no-store, private",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def _apply_api_security_headers(request: Request, response):
    """Apply baseline security and anti-caching headers to all /api/* responses."""
    if request.url.path.startswith("/api/") and hasattr(response, "headers"):
        for header, value in _API_SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
    return response


@app.middleware("http")
async def sqlite_tmp_sync_middleware(request: Request, call_next):
    """Triggers debounced /tmp SQLite -> GCS sync on mutating requests or opportunistically on GET (safe under --cpu-throttling)."""
    xff = request.headers.get("x-forwarded-for")
    raw_ip = str(xff).split(",")[0].strip() if xff else (request.client.host if request.client else None)
    req_ip = audit_service.hash_ip_address(raw_ip)
    token = _REQUEST_AUDIT_CTX.set(
        {
            "request_ip": req_ip,
            "user_agent": request.headers.get("user-agent"),
            "method": request.method,
            "path": request.url.path,
        }
    )
    try:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin is not None and origin.strip() and not is_origin_allowed(origin.strip()):
                _audit(
                    action="csrf.denied",
                    target_type="auth",
                    write_global=True,
                    request=request,
                    metadata={"reason": "Untrusted Origin header", "origin": origin.strip()},
                    status="denied",
                )
                return _apply_api_security_headers(
                    request, JSONResponse(status_code=403, content={"detail": "Untrusted request origin"})
                )

            if request.headers.get("x-requested-with") != "Socrates-UI":
                _audit(
                    action="csrf.denied",
                    target_type="auth",
                    write_global=True,
                    request=request,
                    metadata={"reason": "Missing or invalid X-Requested-With header"},
                    status="denied",
                )
                return _apply_api_security_headers(
                    request,
                    JSONResponse(status_code=403, content={"detail": "Missing or invalid X-Requested-With header"}),
                )

            if request.url.path not in {"/api/auth/discord", "/api/auth/dev-login"}:
                session_tok = get_session_token(request)
                if session_tok:
                    payload = None
                    try:
                        payload = _decode_session_jwt(session_tok)
                    except jwt.InvalidTokenError:
                        payload = None
                    if isinstance(payload, dict):
                        expected_csrf = str(payload.get("csrf") or "")
                        provided_csrf = str(request.headers.get("x-csrf-token") or "")
                        if not expected_csrf or not provided_csrf or not hmac.compare_digest(provided_csrf, expected_csrf):
                            _audit(
                                action="csrf.denied",
                                target_type="auth",
                                target_id=str(payload.get("sub") or ""),
                                actor=payload,
                                actor_role="instance_admin" if is_instance_admin_user(payload) else (payload.get("dev_role") or payload.get("auth_method")),
                                write_global=True,
                                request=request,
                                metadata={"reason": "Invalid or missing CSRF token"},
                                status="denied",
                            )
                            return _apply_api_security_headers(
                                request,
                                JSONResponse(status_code=403, content={"detail": "Invalid or missing CSRF token"}),
                            )

        response = await call_next(request)
        return _apply_api_security_headers(request, response)
    finally:
        _REQUEST_AUDIT_CTX.reset(token)
        try:
            from db.session import is_sqlite_tmp_cache_enabled, sync_dirty_sqlite_dbs
            if is_sqlite_tmp_cache_enabled():
                sync_dirty_sqlite_dbs(force=False)
        except Exception:
            pass


@app.exception_handler(exc.DatabaseConnectionError)
async def db_connection_exception_handler(request: Request, e: exc.DatabaseConnectionError):
    return JSONResponse(
        status_code=404,
        content={"detail": str(e), "error": "database_not_found"}
    )


@app.exception_handler(exc.DatabaseSchemaMismatchError)
async def schema_mismatch_exception_handler(request: Request, e: exc.DatabaseSchemaMismatchError):
    return JSONResponse(
        status_code=400,
        content={"detail": str(e), "error": "schema_mismatch"}
    )


def _internal_error(context: str, err: Exception, backup_id: Optional[str] = None) -> HTTPException:
    err_id = uuid.uuid4().hex[:12]
    tb = traceback.format_exc()
    t.global_log("error", f"API [{err_id}] {context}: {err}\n{tb}")
    if backup_id:
        try:
            api_log(backup_id, "error", f"[{err_id}] {context}: {err}")
        except Exception:
            pass
    return HTTPException(status_code=500, detail=f"Internal server error (ref: {err_id})")


@app.exception_handler(exc.DatabaseError)
@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(request: Request, e: Exception):
    err_id = uuid.uuid4().hex[:12]
    err_line = str(e).splitlines()[0] if str(e) else type(e).__name__
    t.global_log("error", f"API [{err_id}]: Database error on {request.url.path}: {err_line}")
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"Internal database error (ref: {err_id})",
            "error": "database_error",
            "error_id": err_id,
        },
    )


def get_backup_path(backup_id: str):
    try:
        safe_id = validate_backup_id(backup_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid backup_id")
    index = t.get_backups_index()
    for b in index:
        if str(b.get("backup_id")) == safe_id:
            try:
                return ensure_safe_backup_path(b.get("path", ""), get_data_root()).as_posix()
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid backup path")
    raise HTTPException(status_code=404, detail="Backup ID not found in index")


def api_log(backup_id: str, level: str, message: str):
    try:
        base_path = get_backup_path(backup_id)
        log_path = (Path(base_path) / "log.txt").as_posix()
        t.write_log_line(log_path, level, f"API: {message}")
    except Exception:
        # Fallback to global log if backup_id is invalid
        t.global_log(level, f"API ({backup_id}): {message}")


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


# --- AUTHENTICATION & AUTHORIZATION ---

_BOT_GUILDS_CACHE_LOCK = threading.Lock()
_BOT_GUILDS_FETCH_LOCK = threading.Lock()
_BOT_GUILDS_ASYNC_LOCKS: "weakref.WeakKeyDictionary[Any, asyncio.Lock]" = weakref.WeakKeyDictionary()
_BOT_GUILDS_CACHE: Dict[str, Any] = {
    "guilds": None,
    "expires_at": 0.0,
    "backoff_until": 0.0,
    "token": None,
}
BOT_GUILDS_CACHE_TTL_SECONDS = 600.0
BOT_GUILDS_RATE_LIMIT_DEFAULT_SECONDS = 15.0
BOT_GUILDS_ERROR_BACKOFF_SECONDS = 5.0


def clear_bot_guilds_cache() -> None:
    with _BOT_GUILDS_CACHE_LOCK:
        _BOT_GUILDS_CACHE["guilds"] = None
        _BOT_GUILDS_CACHE["expires_at"] = 0.0
        _BOT_GUILDS_CACHE["backoff_until"] = 0.0
        _BOT_GUILDS_CACHE["token"] = None


def get_auth_config():
    return {
        "client_id": os.environ.get("DISCORD_CLIENT_ID"),
        "client_secret": os.environ.get("DISCORD_CLIENT_SECRET"),
        "redirect_uri": os.environ.get("DISCORD_REDIRECT_URI"),
        "jwt_secret": resolve_jwt_secret(),
        "bot_token": os.environ.get("DISCORD_TOKEN"),
    }


def get_instance_admin_ids() -> Set[str]:
    raw = os.environ.get("SOCRATES_INSTANCE_ADMINS", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def is_instance_admin_user(user: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(user, dict):
        return False
    if (
        user.get("_direct_call") is True
        and user.get("auth_method") == "cli"
        and user.get("_verified_http") is not True
    ):
        return True
    if user.get("auth_method") == "dev":
        return (
            not is_production_env()
            and get_socrates_env() == "development"
            and user.get("dev_role") == "instance_admin"
        )
    user_id = str(user.get("sub") or user.get("id") or "").strip()
    return bool(user_id) and user_id in get_instance_admin_ids()


def is_dev_login_enabled() -> bool:
    if is_production_env():
        return False
    if get_socrates_env() != "development":
        return False
    if os.environ.get("SOCRATES_ENABLE_DEV_LOGIN", "").strip().lower() != "true":
        return False
    dev_role = os.environ.get("SOCRATES_DEV_ROLE", "").strip().lower()
    return dev_role in VALID_DEV_ROLES


def _is_resolved_user(user: Any) -> bool:
    return not isinstance(user, DependsParam)


def _resolve_direct_call_user(user: Any) -> Dict[str, Any]:
    if isinstance(user, DependsParam):
        return {
            "sub": "0",
            "username": "system",
            "auth_method": "cli",
            "_direct_call": True,
        }
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not user.get("_verified_http") and "auth_method" not in user and "authorized_guilds" not in user:
        return {
            **user,
            "auth_method": "cli",
            "_direct_call": True,
        }
    return user


def _extract_user_guild_ids(user: Dict[str, Any]) -> Set[str]:
    auth_guilds = user.get("authorized_guilds", [])
    guild_ids: Set[str] = set()
    if not isinstance(auth_guilds, list):
        return guild_ids
    for g in auth_guilds:
        if isinstance(g, dict):
            gid = g.get("id")
            if gid is not None and str(gid).strip():
                guild_ids.add(str(gid))
        elif g is not None and str(g).strip():
            guild_ids.add(str(g))
    return guild_ids


def _get_bot_guilds_async_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    with _BOT_GUILDS_CACHE_LOCK:
        lock = _BOT_GUILDS_ASYNC_LOCKS.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            _BOT_GUILDS_ASYNC_LOCKS[loop] = lock
        return lock


def _read_bot_guilds_cache(bot_token: str, force_refresh: bool) -> Tuple[bool, Optional[Set[str]]]:
    if force_refresh:
        return (False, None)
    now = time.monotonic()
    with _BOT_GUILDS_CACHE_LOCK:
        if _BOT_GUILDS_CACHE["token"] == bot_token:
            cached = _BOT_GUILDS_CACHE["guilds"]
            if cached is not None and now < _BOT_GUILDS_CACHE["expires_at"]:
                return (True, set(cached))
            if now < _BOT_GUILDS_CACHE["backoff_until"]:
                return (True, set(cached) if cached is not None else None)
    return (False, None)


def _record_bot_guilds_response(bot_token: str, resp: Any) -> Optional[Set[str]]:
    if resp.status_code == 200:
        guilds = {str(g["id"]) for g in resp.json() if isinstance(g, dict) and "id" in g}
        with _BOT_GUILDS_CACHE_LOCK:
            _BOT_GUILDS_CACHE["guilds"] = set(guilds)
            _BOT_GUILDS_CACHE["expires_at"] = time.monotonic() + BOT_GUILDS_CACHE_TTL_SECONDS
            _BOT_GUILDS_CACHE["backoff_until"] = 0.0
            _BOT_GUILDS_CACHE["token"] = bot_token
        return guilds
    if resp.status_code == 429:
        retry_after = rbac.parse_retry_after(resp, default=BOT_GUILDS_RATE_LIMIT_DEFAULT_SECONDS)
        t.global_log(
            "warning",
            f"API: Rate-limited fetching bot guilds (HTTP 429, retry_after={retry_after:.1f}s)",
        )
        return _record_bot_guilds_backoff(bot_token, retry_after)
    t.global_log("error", f"API: Failed to fetch bot guilds (HTTP {resp.status_code})")
    return _record_bot_guilds_backoff(bot_token, BOT_GUILDS_ERROR_BACKOFF_SECONDS)


def _record_bot_guilds_backoff(bot_token: str, backoff_seconds: float) -> Optional[Set[str]]:
    with _BOT_GUILDS_CACHE_LOCK:
        _BOT_GUILDS_CACHE["backoff_until"] = time.monotonic() + backoff_seconds
        if _BOT_GUILDS_CACHE["token"] == bot_token and _BOT_GUILDS_CACHE["guilds"] is not None:
            return set(_BOT_GUILDS_CACHE["guilds"])
        _BOT_GUILDS_CACHE["token"] = bot_token
        _BOT_GUILDS_CACHE["guilds"] = None
        _BOT_GUILDS_CACHE["expires_at"] = 0.0
        return None


async def fetch_live_bot_guilds_async(
    client: Optional[httpx.AsyncClient] = None,
    force_refresh: bool = False,
) -> Optional[Set[str]]:
    bot_token = (get_auth_config().get("bot_token") or "").strip()
    if not bot_token or bot_token == "your_bot_token_here":
        return None

    hit, cached = _read_bot_guilds_cache(bot_token, force_refresh)
    if hit:
        return cached

    async with _get_bot_guilds_async_lock():
        hit, cached = _read_bot_guilds_cache(bot_token, force_refresh)
        if hit:
            return cached

        try:
            if client is not None:
                resp = await client.get(
                    "https://discord.com/api/v10/users/@me/guilds",
                    headers={"Authorization": f"Bot {bot_token}"},
                )
            else:
                async with httpx.AsyncClient(timeout=10.0) as local_client:
                    resp = await local_client.get(
                        "https://discord.com/api/v10/users/@me/guilds",
                        headers={"Authorization": f"Bot {bot_token}"},
                    )
            return _record_bot_guilds_response(bot_token, resp)
        except Exception as e:
            t.global_log("error", f"API: Error fetching bot guilds: {e}")
            return _record_bot_guilds_backoff(bot_token, BOT_GUILDS_ERROR_BACKOFF_SECONDS)


def get_live_bot_guilds(force_refresh: bool = False) -> Optional[Set[str]]:
    bot_token = (get_auth_config().get("bot_token") or "").strip()
    if not bot_token or bot_token == "your_bot_token_here":
        return None

    hit, cached = _read_bot_guilds_cache(bot_token, force_refresh)
    if hit:
        return cached

    with _BOT_GUILDS_FETCH_LOCK:
        hit, cached = _read_bot_guilds_cache(bot_token, force_refresh)
        if hit:
            return cached

        try:
            resp = httpx.get(
                "https://discord.com/api/v10/users/@me/guilds",
                headers={"Authorization": f"Bot {bot_token}"},
                timeout=10.0,
            )
            return _record_bot_guilds_response(bot_token, resp)
        except Exception as e:
            t.global_log("error", f"API: Error fetching bot guilds: {e}")
            return _record_bot_guilds_backoff(bot_token, BOT_GUILDS_ERROR_BACKOFF_SECONDS)


def _get_effective_bot_guilds(actor: Dict[str, Any]) -> Set[str]:
    live_guilds = get_live_bot_guilds()
    if live_guilds is not None:
        return live_guilds
    if actor.get("auth_method") == "dev" and not is_production_env() and get_socrates_env() == "development":
        return {str(b["server_id"]) for b in t.get_backups_index() if b.get("server_id")}
    return set()


_REVOKED_JTIS_LOCK = threading.Lock()
_REVOKED_JTIS: Dict[str, float] = {}


def clear_revoked_jtis() -> None:
    with _REVOKED_JTIS_LOCK:
        _REVOKED_JTIS.clear()


def _prune_revoked_jtis_locked(now: float) -> None:
    expired = [jti for jti, exp_ts in _REVOKED_JTIS.items() if exp_ts <= now]
    for jti in expired:
        _REVOKED_JTIS.pop(jti, None)


def _revoke_jti(jti: Optional[str], exp: Optional[Any] = None) -> None:
    if not jti:
        return
    now = time.time()
    try:
        exp_ts = float(exp) if exp is not None else (now + 12 * 3600)
    except (TypeError, ValueError):
        exp_ts = now + 12 * 3600
    with _REVOKED_JTIS_LOCK:
        _prune_revoked_jtis_locked(now)
        if exp_ts > now:
            _REVOKED_JTIS[str(jti)] = exp_ts


def _is_jti_revoked(jti: Optional[str]) -> bool:
    if not jti:
        return False
    now = time.time()
    with _REVOKED_JTIS_LOCK:
        _prune_revoked_jtis_locked(now)
        return str(jti) in _REVOKED_JTIS


def get_allowed_redirect_uris(configured_redirect_uri: Optional[str]) -> Set[str]:
    raw_allowed = os.environ.get("SOCRATES_ALLOWED_REDIRECT_URIS", "")
    allowed = {part.strip() for part in raw_allowed.split(",") if part.strip()}
    if not allowed and configured_redirect_uri and configured_redirect_uri.strip():
        allowed.add(configured_redirect_uri.strip())
    return allowed


def _validate_redirect_uri(config_redirect_uri: Optional[str], requested_redirect_uri: Optional[str] = None) -> str:
    configured = (config_redirect_uri or "").strip()
    allowed = get_allowed_redirect_uris(configured)
    if not allowed:
        raise HTTPException(status_code=500, detail="OAuth redirect URI not configured")
    if requested_redirect_uri is not None:
        req_uri = requested_redirect_uri.strip()
        if not req_uri or req_uri not in allowed:
            raise HTTPException(status_code=400, detail="Invalid OAuth redirect_uri")
        return req_uri
    if not configured:
        raise HTTPException(status_code=500, detail="OAuth redirect URI not configured")
    if configured not in allowed:
        raise HTTPException(status_code=400, detail="Configured OAuth redirect_uri is not in allowlist")
    return configured


def get_session_token(request: Request) -> Optional[str]:
    # Firebase Hosting rewrite CDN only preserves '__session'; fallback to 'session_token' for dev/direct access
    return request.cookies.get("__session") or request.cookies.get("session_token")


def _decode_session_jwt(token: str) -> Dict[str, Any]:
    config = get_auth_config()
    payload = jwt.decode(token, config["jwt_secret"], algorithms=["HS256"])
    if not isinstance(payload, dict) or not payload.get("sub"):
        raise jwt.InvalidTokenError("Missing subject claim")
    if payload.get("typ", "session") != "session" or payload.get("iss") != "socrates":
        raise jwt.InvalidTokenError("Invalid token type or issuer")
    if payload.get("auth_method") == "cli" or "_direct_call" in payload or "_verified_http" in payload:
        raise jwt.InvalidTokenError("Invalid session claims")
    if _is_jti_revoked(payload.get("jti")):
        raise jwt.InvalidTokenError("Session has been revoked")
    return payload


def get_current_user(request: Request):
    token = get_session_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = _decode_session_jwt(token)
        return {**payload, "_verified_http": True}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session")


def get_optional_user(request: Request):
    if not request:
        return None
    token = get_session_token(request)
    if not token:
        return None
    try:
        payload = _decode_session_jwt(token)
        return {**payload, "_verified_http": True}
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def require_instance_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if not is_instance_admin_user(user):
        _audit(
            action="rbac.denied",
            target_type="admin",
            actor=user,
            actor_role="non_admin",
            write_global=True,
            metadata={"reason": "Instance administrator access required"},
            status="denied",
        )
        raise HTTPException(status_code=403, detail="Instance administrator access required")
    return user


def _ensure_instance_admin(user: Any) -> Dict[str, Any]:
    actor = _resolve_direct_call_user(user)
    if not is_instance_admin_user(actor):
        _audit(
            action="rbac.denied",
            target_type="admin",
            actor=actor,
            actor_role="non_admin",
            write_global=True,
            metadata={"reason": "Instance administrator access required"},
            status="denied",
        )
        raise HTTPException(status_code=403, detail="Instance administrator access required")
    return actor


def resolve_authorized_backup(
    backup_id: str,
    user: Any,
    min_role: str = "viewer",
) -> Tuple[str, Dict[str, Any], str, int, Dict[str, Any]]:
    actor = _resolve_direct_call_user(user)
    try:
        safe_id = validate_backup_id(backup_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid backup_id")
    index = t.get_backups_index()
    entry = next((b for b in index if str(b.get("backup_id")) == safe_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Backup ID not found in index")

    try:
        base_path = ensure_safe_backup_path(entry.get("path", ""), get_data_root()).as_posix()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid backup path")
    try:
        role_name, role_level = rbac.resolve_backup_role(
            backup_id=str(backup_id),
            entry=entry,
            base_path=base_path,
            actor=actor,
            is_instance_admin_fn=is_instance_admin_user,
            effective_bot_guilds_fn=_get_effective_bot_guilds,
            extract_user_guild_ids_fn=_extract_user_guild_ids,
            bot_token=get_auth_config().get("bot_token"),
            is_production=is_production_env(),
            socrates_env=get_socrates_env(),
        )
    except HTTPException as exc_denied:
        if exc_denied.status_code == 403:
            is_blocked = "blocked" in str(exc_denied.detail).lower()
            _audit(
                action="rbac.denied",
                target_type="backup",
                target_id=str(backup_id),
                actor=actor,
                actor_role="blocked" if is_blocked else "denied",
                backup_id=str(backup_id),
                backup_dir=base_path if is_blocked else None,
                write_global=True,
                metadata={"reason": str(exc_denied.detail), "required_role": min_role},
                status="denied",
            )
        raise

    required_level = rbac.ROLE_LEVELS.get(min_role, rbac.ROLE_LEVELS["viewer"])
    if role_level < required_level:
        _audit(
            action="rbac.denied",
            target_type="backup",
            target_id=str(backup_id),
            actor=actor,
            actor_role=role_name,
            backup_id=str(backup_id),
            backup_dir=base_path,
            write_global=True,
            metadata={"reason": f"Requires {min_role} role or higher", "required_role": min_role, "actual_role": role_name},
            status="denied",
        )
        raise HTTPException(status_code=403, detail=f"Requires {min_role} role or higher")

    return base_path, actor, role_name, role_level, entry


def get_authorized_backup_path(backup_id: str, user: Any, min_role: str = "viewer") -> str:
    base_path, _, _, _, _ = resolve_authorized_backup(backup_id, user, min_role=min_role)
    return base_path


@app.get("/api/auth/login-url")
def get_login_url(response: Response, request: Request, redirect_uri: Optional[str] = Query(None)):
    config = get_auth_config()
    if not config["client_id"]:
        raise HTTPException(status_code=500, detail="OAuth not configured")

    redirect_uri = _validate_redirect_uri(config["redirect_uri"], redirect_uri)
    state = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(48)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )

    preauth_exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    preauth_token = jwt.encode(
        {
            "typ": "oauth_preauth",
            "iss": "socrates",
            "state": state,
            "code_verifier": code_verifier,
            "exp": preauth_exp,
        },
        config["jwt_secret"],
        algorithm="HS256",
    )
    is_secure = request.headers.get("x-forwarded-proto") == "https" or is_production_env()
    response.set_cookie(
        key="__session",
        value=preauth_token,
        path="/",
        httponly=True,
        samesite="lax",
        secure=is_secure,
        max_age=600,
    )

    url = "https://discord.com/api/oauth2/authorize?" + urllib.parse.urlencode({
        "client_id": config["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    return {"url": url, "state": state}


@app.post("/api/auth/discord")
async def auth_discord(callback: AuthCallback, response: Response, request: Request):
    config = get_auth_config()
    if not config["client_id"] or not config["client_secret"]:
        raise HTTPException(status_code=500, detail="OAuth not configured")

    redirect_uri = _validate_redirect_uri(config["redirect_uri"], callback.redirect_uri)

    preauth_token = request.cookies.get("__session") or request.cookies.get("session_token")
    if not preauth_token:
        _audit(action="auth.denied", target_type="auth", write_global=True, request=request, metadata={"reason": "Missing OAuth pre-auth cookie"}, status="denied")
        raise HTTPException(status_code=400, detail="Missing OAuth pre-auth cookie")
    try:
        preauth = jwt.decode(preauth_token, config["jwt_secret"], algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        _audit(action="auth.denied", target_type="auth", write_global=True, request=request, metadata={"reason": "OAuth pre-auth session expired"}, status="denied")
        raise HTTPException(status_code=400, detail="OAuth pre-auth session expired")
    except jwt.InvalidTokenError:
        _audit(action="auth.denied", target_type="auth", write_global=True, request=request, metadata={"reason": "Invalid OAuth pre-auth session"}, status="denied")
        raise HTTPException(status_code=400, detail="Invalid OAuth pre-auth session")

    if (
        not isinstance(preauth, dict)
        or preauth.get("typ") != "oauth_preauth"
        or preauth.get("iss") != "socrates"
        or not preauth.get("state")
        or not preauth.get("code_verifier")
    ):
        _audit(action="auth.denied", target_type="auth", write_global=True, request=request, metadata={"reason": "Invalid OAuth pre-auth payload"}, status="denied")
        raise HTTPException(status_code=400, detail="Invalid OAuth pre-auth payload")

    if not callback.state:
        _audit(action="auth.denied", target_type="auth", write_global=True, request=request, metadata={"reason": "Missing OAuth state parameter"}, status="denied")
        raise HTTPException(status_code=400, detail="Missing OAuth state parameter")
    if not hmac.compare_digest(str(callback.state), str(preauth["state"])):
        _audit(action="auth.denied", target_type="auth", write_global=True, request=request, metadata={"reason": "OAuth state mismatch"}, status="denied")
        raise HTTPException(status_code=403, detail="OAuth state mismatch")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Exchange code for user access token (with PKCE code_verifier)
        token_resp = await client.post("https://discord.com/api/v10/oauth2/token", data={
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "grant_type": "authorization_code",
            "code": callback.code,
            "redirect_uri": redirect_uri,
            "code_verifier": preauth["code_verifier"],
        })
        if token_resp.status_code != 200:
            _audit(action="auth.denied", target_type="auth", write_global=True, request=request, metadata={"reason": "Invalid authorization code"}, status="denied")
            raise HTTPException(status_code=400, detail="Invalid authorization code")
        
        token_data = token_resp.json()
        access_token = token_data.get("access_token")

        # 2. Get user info
        user_resp = await client.get("https://discord.com/api/v10/users/@me", headers={"Authorization": f"Bearer {access_token}"})
        if user_resp.status_code != 200:
            _audit(action="auth.denied", target_type="auth", write_global=True, request=request, metadata={"reason": "Failed to fetch user info"}, status="denied")
            raise HTTPException(status_code=400, detail="Failed to fetch user info")
        user_data = user_resp.json()

        # 3. Get user's guilds (preserving owner + permissions bitmask)
        guilds_resp = await client.get("https://discord.com/api/v10/users/@me/guilds", headers={"Authorization": f"Bearer {access_token}"})
        if guilds_resp.status_code != 200:
            _audit(
                action="auth.denied",
                target_type="auth",
                target_id=str(user_data.get("id") or ""),
                actor={"sub": str(user_data.get("id") or ""), "username": user_data.get("username"), "auth_method": "discord"},
                write_global=True,
                request=request,
                metadata={"reason": "Failed to fetch user guilds"},
                status="denied",
            )
            raise HTTPException(status_code=400, detail="Failed to fetch user guilds")
        user_guilds_raw = guilds_resp.json()
        user_guilds = {str(g["id"]) for g in user_guilds_raw}
        user_guilds_meta: Dict[str, Dict[str, Any]] = {}
        for g in user_guilds_raw:
            gid = str(g["id"])
            try:
                perms_int = int(g.get("permissions") or 0)
            except (TypeError, ValueError):
                perms_int = 0
            user_guilds_meta[gid] = {
                "name": g.get("name", "Unknown Server"),
                "owner": bool(g.get("owner", False)),
                "permissions": perms_int,
            }

        # 4. Get live bot guilds (do NOT union backups_index.json)
        bot_guilds = await fetch_live_bot_guilds_async(client=client)
        if bot_guilds is None:
            bot_guilds = set()

        # 5. Check overlap (InstanceAdmin may log in even with empty guild overlap)
        user_id_str = str(user_data["id"])
        is_inst_admin = user_id_str in get_instance_admin_ids()
        authorized_guilds_ids = list(user_guilds.intersection(bot_guilds))

        if not authorized_guilds_ids and not is_inst_admin:
            _audit(
                action="auth.denied",
                target_type="auth",
                target_id=user_id_str,
                actor={"sub": user_id_str, "username": user_data.get("username"), "auth_method": "discord"},
                write_global=True,
                request=request,
                metadata={"reason": "User is not a member of any authorized servers"},
                status="denied",
            )
            raise HTTPException(status_code=403, detail="User is not a member of any authorized servers")

        # Build list of dicts with names, owner, and permissions
        authorized_guilds = []
        for gid in authorized_guilds_ids:
            meta = user_guilds_meta.get(gid, {})
            authorized_guilds.append({
                "id": gid,
                "name": meta.get("name", "Unknown Server"),
                "owner": bool(meta.get("owner", False)),
                "permissions": int(meta.get("permissions") or 0),
            })

        # 6. Issue JWT (12h TTL with jti, iat, iss, typ, csrf)
        now_dt = datetime.now(timezone.utc)
        exp = now_dt + timedelta(hours=12)
        jti = secrets.token_hex(16)
        csrf = secrets.token_urlsafe(24)
        payload = {
            "sub": user_id_str,
            "username": user_data["username"],
            "avatar": user_data.get("avatar"),
            "auth_method": "discord",
            "authorized_guilds": authorized_guilds,
            "jti": jti,
            "iat": now_dt,
            "iss": "socrates",
            "typ": "session",
            "csrf": csrf,
            "exp": exp,
        }
        
        token = jwt.encode(payload, config["jwt_secret"], algorithm="HS256")
        
        # In production/HTTPS, use secure cookies. Firebase CDN exclusively preserves '__session'.
        is_secure = request.headers.get("x-forwarded-proto") == "https" or is_production_env()

        for cookie_key in ("__session", "session_token"):
            response.set_cookie(
                key=cookie_key,
                value=token,
                path="/",
                httponly=True,
                samesite="lax",
                secure=is_secure,
                max_age=12 * 60 * 60,
            )

        _audit(
            action="auth.login",
            target_type="auth",
            target_id=user_id_str,
            actor={"sub": user_id_str, "username": user_data["username"], "auth_method": "discord"},
            actor_role="instance_admin" if is_inst_admin else "discord",
            write_global=True,
            request=request,
            metadata={"guild_count": len(authorized_guilds), "is_instance_admin": is_inst_admin},
        )

        return {
            "status": "success",
            "csrf_token": csrf,
            "user": {
                "id": user_id_str,
                "sub": user_id_str,
                "username": user_data["username"],
                "avatar": user_data.get("avatar"),
                "is_instance_admin": is_inst_admin,
                "authorized_guilds": authorized_guilds,
            }
        }


@app.post("/api/auth/logout")
def logout(response: Response, request: Request):
    token = get_session_token(request)
    logout_actor: Optional[Dict[str, Any]] = None
    if token:
        try:
            config = get_auth_config()
            payload = jwt.decode(
                token,
                config["jwt_secret"],
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
            if (
                isinstance(payload, dict)
                and payload.get("typ", "session") == "session"
                and payload.get("iss") == "socrates"
                and payload.get("jti")
            ):
                _revoke_jti(payload.get("jti"), payload.get("exp"))
                logout_actor = payload
        except jwt.InvalidTokenError:
            pass
    if logout_actor is not None:
        _audit(
            action="auth.logout",
            target_type="auth",
            target_id=str(logout_actor.get("sub") or ""),
            actor=logout_actor,
            actor_role="instance_admin" if is_instance_admin_user(logout_actor) else (logout_actor.get("dev_role") or logout_actor.get("auth_method")),
            write_global=True,
            request=request,
        )
    is_secure = request.headers.get("x-forwarded-proto") == "https" or is_production_env()
    response.delete_cookie("session_token", path="/", httponly=True, samesite="lax", secure=is_secure)
    response.delete_cookie("__session", path="/", httponly=True, samesite="lax", secure=is_secure)
    return {"status": "success"}


@app.get("/api/auth/me")
def get_me(user = Depends(get_optional_user)):
    if not user or not isinstance(user, dict):
        return {"user": None}
    enriched = {k: v for k, v in user.items() if k not in {"_verified_http", "_direct_call"}}
    enriched["id"] = str(user.get("sub") or user.get("id") or "")
    enriched["is_instance_admin"] = is_instance_admin_user(user)
    return {"user": enriched, "csrf_token": user.get("csrf")}


def dev_login(response: Response, request: Request):
    if not is_dev_login_enabled():
        _audit(action="auth.denied", target_type="auth", write_global=True, request=request, metadata={"reason": "Dev login disabled"}, status="denied")
        raise HTTPException(status_code=403, detail="Dev login disabled")

    headers_lower = {str(k).lower(): v for k, v in (request.headers or {}).items()}
    if "x-forwarded-for" in headers_lower or "forwarded" in headers_lower:
        _audit(action="auth.denied", target_type="auth", write_global=True, request=request, metadata={"reason": "Dev login cannot be used behind a proxy"}, status="denied")
        raise HTTPException(status_code=403, detail="Dev login cannot be used behind a proxy")

    client_host = request.client.host if getattr(request, "client", None) else None
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        _audit(action="auth.denied", target_type="auth", write_global=True, request=request, metadata={"reason": "Dev login is restricted to localhost", "client_host": client_host}, status="denied")
        raise HTTPException(status_code=403, detail="Dev login is restricted to localhost")

    dev_role = os.environ.get("SOCRATES_DEV_ROLE", "").strip().lower()
    dev_id = os.environ.get("SOCRATES_DEV_ID", "0").strip() or "0"

    config = get_auth_config()
    index = t.get_backups_index()
    authorized_guilds = []
    seen_guild_ids = set()
    for b in index:
        if "server_id" in b and b["server_id"]:
            gid = str(b["server_id"])
            if gid not in seen_guild_ids:
                seen_guild_ids.add(gid)
                authorized_guilds.append({
                    "id": gid,
                    "name": b.get("server_name", "Local Server")
                })

    now_dt = datetime.now(timezone.utc)
    exp = now_dt + timedelta(hours=12)
    jti = secrets.token_hex(16)
    csrf = secrets.token_urlsafe(24)
    payload = {
        "sub": dev_id,
        "username": "DevUser",
        "avatar": None,
        "auth_method": "dev",
        "dev_role": dev_role,
        "authorized_guilds": authorized_guilds,
        "jti": jti,
        "iat": now_dt,
        "iss": "socrates",
        "typ": "session",
        "csrf": csrf,
        "exp": exp,
    }
    token = jwt.encode(payload, config["jwt_secret"], algorithm="HS256")

    is_secure = headers_lower.get("x-forwarded-proto") == "https" or is_production_env()
    for key in ("__session", "session_token"):
        response.set_cookie(
            key=key,
            value=token,
            path="/",
            httponly=True,
            samesite="lax",
            secure=is_secure,
            max_age=12 * 60 * 60
        )
    is_inst_admin = is_instance_admin_user(payload)
    _audit(
        action="auth.dev_login",
        target_type="auth",
        target_id=dev_id,
        actor=payload,
        actor_role="instance_admin" if is_inst_admin else dev_role,
        write_global=True,
        request=request,
        metadata={"dev_role": dev_role, "is_instance_admin": is_inst_admin},
    )
    return {
        "status": "success",
        "csrf_token": csrf,
        "user": {
            "id": dev_id,
            "sub": dev_id,
            "username": payload["username"],
            "avatar": None,
            "auth_method": "dev",
            "dev_role": dev_role,
            "is_instance_admin": is_inst_admin,
            "authorized_guilds": authorized_guilds,
        }
    }


def register_dev_login_route(target_app: FastAPI) -> bool:
    if is_dev_login_enabled():
        target_app.add_api_route(
            "/api/auth/dev-login",
            dev_login,
            methods=["POST"],
            include_in_schema=False,
        )
        return True
    return False


register_dev_login_route(app)

# --- END AUTHENTICATION ---


def _coerce_config_payload(config: Any, schema_cls: type[BaseModel]) -> Dict[str, Any]:
    if isinstance(config, schema_cls):
        return config.model_dump(exclude_unset=True)
    if isinstance(config, dict):
        return schema_cls.model_validate(config).model_dump(exclude_unset=True)
    raise HTTPException(status_code=422, detail="Invalid configuration payload")


@app.get("/api/servers/{server_id}/categories")
def get_server_categories(server_id: str, user = Depends(get_current_user)):
    actor = _resolve_direct_call_user(user)
    if not is_instance_admin_user(actor):
        authorized_guilds = _extract_user_guild_ids(actor)
        live_bot_guilds = _get_effective_bot_guilds(actor)
        if str(server_id) not in authorized_guilds or str(server_id) not in live_bot_guilds:
            _audit(
                action="rbac.denied",
                target_type="server",
                target_id=str(server_id),
                actor=actor,
                actor_role="non_admin",
                metadata={"reason": "Access denied for this server"},
                status="denied",
            )
            raise HTTPException(status_code=403, detail="Access denied for this server")
    try:
        safe_server_id = validate_snowflake(server_id, "server_id")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid server_id")
    from get_server_info import get_categories
    try:
        categories = get_categories(safe_server_id)
        return categories
    except Exception as e:
        raise _internal_error(f"get_server_categories({safe_server_id})", e)


def _read_global_config_file() -> Dict[str, Any]:
    config_path = (Path(get_project_root()) / 'res' / 'config.json').as_posix()
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


@app.get("/api/config/global")
def get_global_config(user = Depends(require_instance_admin)):
    _ensure_instance_admin(user)
    try:
        return _read_global_config_file()
    except Exception as e:
        raise _internal_error("get_global_config", e)


@app.put("/api/config/global")
def update_global_config(config: GlobalConfigSchema, user = Depends(require_instance_admin)):
    actor = _ensure_instance_admin(user)
    payload = _coerce_config_payload(config, GlobalConfigSchema)
    config_path = (Path(get_project_root()) / 'res' / 'config.json').as_posix()
    before_cfg = None
    try:
        before_cfg = _read_global_config_file()
    except Exception:
        before_cfg = None
    try:
        t.save_json_atomic(payload, config_path)
        _audit(
            action="config.global_update",
            target_type="config",
            target_id="global",
            actor=actor,
            actor_role="instance_admin",
            write_global=True,
            before=before_cfg,
            after=payload,
        )
        return {"status": "success"}
    except Exception as e:
        raise _internal_error("update_global_config", e)


def _filter_non_admin_backups(actor: Dict[str, Any], all_backups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    bot_token = get_auth_config().get("bot_token")
    is_prod = is_production_env()
    soc_env = get_socrates_env()
    data_root = get_data_root()
    result = []
    for b in all_backups:
        bid = str(b.get("backup_id") or "")
        if not bid or not b.get("path"):
            continue
        try:
            validate_backup_id(bid)
            b_path = ensure_safe_backup_path(b["path"], data_root).as_posix()
        except ValueError:
            continue
        try:
            role_name, role_level = rbac.resolve_backup_role(
                backup_id=bid,
                entry=b,
                base_path=b_path,
                actor=actor,
                is_instance_admin_fn=is_instance_admin_user,
                effective_bot_guilds_fn=_get_effective_bot_guilds,
                extract_user_guild_ids_fn=_extract_user_guild_ids,
                bot_token=bot_token,
                is_production=is_prod,
                socrates_env=soc_env,
            )
        except HTTPException:
            continue
        item = dict(b)
        item["bot_in_guild"] = True
        item["effective_role"] = role_name
        item["role_level"] = role_level
        result.append(item)
    return result


@app.get("/api/backups")
def get_backups(user = Depends(get_current_user)):
    actor = _resolve_direct_call_user(user)
    all_backups = t.get_backups_index()
    if is_instance_admin_user(actor):
        raw_live = get_live_bot_guilds()
        effective_live = raw_live if raw_live is not None else set()
        result = []
        for b in all_backups:
            item = dict(b)
            item["bot_in_guild"] = str(b.get("server_id", "")) in effective_live
            item["effective_role"] = "instance_admin"
            item["role_level"] = rbac.ROLE_LEVELS["instance_admin"]
            result.append(item)
        return result

    return _filter_non_admin_backups(actor, all_backups)


@app.get("/api/backups-paths")
def get_all_backup_paths(user = Depends(get_current_user)):
    actor = _resolve_direct_call_user(user)
    all_backups = t.get_backups_index()
    if is_instance_admin_user(actor):
        return [b.get("path") for b in all_backups if "path" in b]
    return [b.get("path") for b in _filter_non_admin_backups(actor, all_backups) if "path" in b]


@app.get("/api/backups/{backup_id}")
def get_backup_info(backup_id: str, user = Depends(get_current_user)):
    base_path, actor, role_name, role_level, entry = resolve_authorized_backup(backup_id, user, min_role="viewer")

    from sqlalchemy import func
    from db.session import db_session, has_db, require_db
    from db.models import CURRENT_SCHEMA_VERSION, SchemaVersionModel, CharacterModel, WriterModel
    from db.serializers import build_backup_info_dict

    current_schema_version = CURRENT_SCHEMA_VERSION
    schema_version = None
    is_schema_outdated = False

    if not has_db(base_path, backup_id=backup_id):
        require_db(base_path, backup_id=backup_id)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        try:
            latest = session.query(SchemaVersionModel).order_by(SchemaVersionModel.version.desc()).first()
            schema_version = latest.version if latest else 0
            is_schema_outdated = bool(schema_version < current_schema_version) if schema_version is not None else False
        except Exception as e:
            session.rollback()
            schema_version = 0
            is_schema_outdated = True
            t.global_log("debug", f"API: Failed to check schema version for {backup_id}: {e}")

        try:
            data = build_backup_info_dict(
                session=session,
                backup_id=str(backup_id),
                is_schema_outdated=is_schema_outdated,
            )
        except Exception as e:
            session.rollback()
            if is_schema_outdated:
                t.global_log("debug", f"API: Failed to load backup state on outdated schema ({e}), using fallback info")
                index = t.get_backups_index()
                backup_meta = next((b for b in index if str(b.get("backup_id")) == str(backup_id)), {})
                data = {
                    "id": backup_meta.get("server_id", backup_id),
                    "name": backup_meta.get("backup_name", backup_meta.get("server_name", f"Backup {backup_id}")),
                    "server_name": backup_meta.get("server_name", ""),
                    "status": "pending",
                    "steps": {},
                    "number_of_categories": 0,
                    "number_of_channels": 0,
                    "number_of_threads": 0,
                    "number_of_scenes": 0,
                    "number_of_sessions": 0,
                    "number_of_events": 0,
                    "number_of_characters": 0,
                    "number_of_writers": 0,
                    "categories": [],
                }
            else:
                raise HTTPException(status_code=404, detail=f"Failed to load backup state: {e}")

        try:
            data["number_of_characters"] = session.query(func.count(CharacterModel.pk)).filter(
                CharacterModel.backup_id == str(backup_id),
                CharacterModel.parent_pk.is_(None),
            ).scalar() or 0
            data["number_of_writers"] = session.query(func.count(WriterModel.pk)).filter(
                WriterModel.backup_id == str(backup_id),
            ).scalar() or 0
        except Exception:
            session.rollback()
            data["number_of_characters"] = 0
            data["number_of_writers"] = 0

    data["current_schema_version"] = current_schema_version
    data["schema_version"] = schema_version
    data["is_schema_outdated"] = is_schema_outdated
    data["effective_role"] = role_name
    data["role_level"] = role_level
    if is_instance_admin_user(actor):
        raw_live = get_live_bot_guilds()
        effective_live = raw_live if raw_live is not None else set()
        data["bot_in_guild"] = str(entry.get("server_id", "")) in effective_live
    else:
        data["bot_in_guild"] = True

    return data


@app.get("/api/backups/{backup_id}/discord-roles")
def get_backup_discord_roles(backup_id: str, user = Depends(get_current_user)):
    _, _, _, _, entry = resolve_authorized_backup(backup_id, user, min_role="server_admin")
    guild_id = str(entry.get("server_id") or "").strip()
    roles, bot_available = rbac.fetch_guild_roles(guild_id, get_auth_config().get("bot_token"))
    return {"roles": roles, "bot_available": bot_available}


@app.get("/api/backups/{backup_id}/rbac")
def get_backup_rbac(backup_id: str, user = Depends(get_current_user)):
    base_path = get_authorized_backup_path(backup_id, user, min_role="server_admin")
    return rbac.load_backup_rbac_config(base_path)


@app.put("/api/backups/{backup_id}/rbac")
def update_backup_rbac(backup_id: str, req: rbac.RbacConfigSchema, user = Depends(get_current_user)):
    base_path, actor, role_name, _, entry = resolve_authorized_backup(backup_id, user, min_role="server_admin")
    guild_id = str(entry.get("server_id") or "").strip() or None
    before_rbac = rbac.load_backup_rbac_config(base_path)
    saved = rbac.save_backup_rbac_config(base_path, req.model_dump(), guild_id=guild_id)
    _audit(
        action="rbac.update",
        target_type="rbac",
        target_id=str(backup_id),
        actor=actor,
        actor_role=role_name,
        backup_id=str(backup_id),
        backup_dir=base_path,
        before=before_rbac,
        after=saved,
    )
    api_log(backup_id, "info", "Updated backup RBAC configuration.")
    return {"status": "success", "rbac": saved}


@app.get("/api/backups/{backup_id}/audit-logs")
def get_backup_audit_logs(
    backup_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    actor_user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    from_ts: Optional[str] = Query(None),
    to_ts: Optional[str] = Query(None),
    user = Depends(get_current_user),
):
    base_path, _, _, _, _ = resolve_authorized_backup(backup_id, user, min_role="server_admin")
    from db.session import audit_db_session
    try:
        with audit_db_session(base_path) as session:
            return audit_service.query_audit_logs(
                session,
                page=page,
                per_page=per_page,
                actor_user_id=actor_user_id,
                action=action,
                target_type=target_type,
                status=status,
                from_ts=from_ts,
                to_ts=to_ts,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/backups/{backup_id}/config")
def get_backup_config(backup_id: str, user = Depends(get_current_user)):
    base_path = get_authorized_backup_path(backup_id, user, min_role="server_admin")
    config_path = safe_join_within(base_path, 'backup_config.json').as_posix()
    if not Path(config_path).exists():
        # Fallback to global config if local doesn't exist yet
        try:
            return _read_global_config_file()
        except Exception as e:
            raise _internal_error(f"get_backup_config({backup_id})", e, backup_id=backup_id)
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_backup_config_preserving_rbac(base_path: str, config: Dict[str, Any]) -> None:
    config_path = safe_join_within(base_path, 'backup_config.json').as_posix()
    Path(config_path).parent.mkdir(parents=True, exist_ok=True)
    cfg_to_save = dict(config)
    if "rbac" not in cfg_to_save and Path(config_path).exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                existing_cfg = json.load(f)
            if isinstance(existing_cfg, dict) and "rbac" in existing_cfg:
                cfg_to_save["rbac"] = existing_cfg["rbac"]
        except Exception:
            pass
    t.save_json_atomic(cfg_to_save, config_path)


@app.put("/api/backups/{backup_id}/config")
def update_backup_config(backup_id: str, config: BackupConfigSchema, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="server_admin")
    payload = _coerce_config_payload(config, BackupConfigSchema)
    config_path = safe_join_within(base_path, 'backup_config.json').as_posix()
    before_cfg = None
    if Path(config_path).exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                before_cfg = json.load(f)
        except Exception:
            before_cfg = None
    try:
        _save_backup_config_preserving_rbac(base_path, payload)
        _audit(
            action="config.update",
            target_type="config",
            target_id=str(backup_id),
            actor=actor,
            actor_role=role_name,
            backup_id=str(backup_id),
            backup_dir=base_path,
            before=before_cfg,
            after=payload,
        )
        return {"status": "success"}
    except Exception as e:
        raise _internal_error(f"Failed to save config for backup {backup_id}", e, backup_id=backup_id)


ALLOWED_STEPS: Dict[str, Dict[str, Any]] = {
    "backup_server.py": {"keep_discord_token": True},
    "assign_ids.py": {"keep_discord_token": False},
    "fix_bad_messages.py": {"keep_discord_token": False},
    "index_scenes.py": {"keep_discord_token": False},
}
active_processes_lock = threading.Lock()
active_processes: Dict[str, subprocess.Popen] = {}


def run_script_in_background(script_name: str, backup_id: str, step_name: Optional[str] = None):
    if script_name not in ALLOWED_STEPS:
        t.global_log("error", f"API: Disallowed background script requested: {script_name}")
        return
    try:
        safe_backup_id = validate_backup_id(backup_id)
    except ValueError as e:
        t.global_log("error", f"API: Invalid backup_id for background script: {e}")
        return

    python_exec = sys.executable
    project_root = get_project_root()
    src_dir = (Path(project_root) / 'src').resolve().as_posix()
    script_path = safe_join_within(src_dir, script_name).as_posix()

    try:
        base_path = get_backup_path(safe_backup_id)
    except Exception as e:
        t.global_log("error", f"API: Cannot resolve backup path for {safe_backup_id}: {e}")
        return

    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512)

    step_meta = ALLOWED_STEPS[script_name]
    env = scrub_sensitive_env(os.environ, keep_discord_token=bool(step_meta.get("keep_discord_token", False)))
    existing_pythonpath = env.get("PYTHONPATH", "")
    paths = [src_dir, project_root]
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(paths)

    stderr_lines: List[str] = []
    try:
        from db.session import is_sqlite_tmp_cache_enabled, sync_dirty_sqlite_dbs
        if is_sqlite_tmp_cache_enabled():
            sync_dirty_sqlite_dbs(force=True)
        process = subprocess.Popen(
            [python_exec, script_path, '--backup-id', safe_backup_id],
            cwd=project_root,
            env=env,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs
        )
        with active_processes_lock:
            active_processes[safe_backup_id] = process

        if process.stderr:
            for line in process.stderr:
                clean_line = line.rstrip()
                if clean_line:
                    stderr_lines.append(clean_line)
                    api_log(safe_backup_id, "error", clean_line)

        process.wait()
    except Exception as e:
        api_log(safe_backup_id, "error", f"Failed to execute {script_name}: {e}")
        if step_name:
            status_service.update_step_status(safe_backup_id, base_path, step_name, Status.FAILED.value, error=str(e))
        else:
            status_service.fail_running_steps(safe_backup_id, base_path, error=str(e))
        return
    finally:
        with active_processes_lock:
            active_processes.pop(safe_backup_id, None)
        try:
            from db.session import is_sqlite_tmp_cache_enabled, sync_dirty_sqlite_dbs
            if is_sqlite_tmp_cache_enabled():
                sync_dirty_sqlite_dbs(force=True)
            t.flush_logs()
        except Exception:
            pass

    if process.returncode != 0:
        err_msg = "\n".join(stderr_lines[-5:]) if stderr_lines else f"Process exited with code {process.returncode}"
        api_log(backup_id, "error", f"Execution of {script_name} failed (exit code {process.returncode})")
        if step_name:
            status_service.update_step_status(backup_id, base_path, step_name, Status.FAILED.value, error=err_msg)
        else:
            status_service.fail_running_steps(backup_id, base_path, error=err_msg)
    else:
        if step_name:
            step_statuses = status_service.get_step_statuses(backup_id, base_path)
            if step_statuses.get(step_name) == Status.RUNNING.value:
                status_service.update_step_status(backup_id, base_path, step_name, Status.SUCCESS.value)


@app.post("/api/backups/{backup_id}/cancel")
def cancel_backup_action(backup_id: str, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="server_admin")
    t.global_log("info", f"API: Received cancel request for backup {backup_id}")

    with active_processes_lock:
        process = active_processes.get(backup_id)

    if process is not None:
        import signal
        if os.name == 'nt':
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
            
        t.global_log("info", f"API: Canceled ongoing process for backup {backup_id}")
        _audit(
            action="pipeline.cancel",
            target_type="backup",
            target_id=str(backup_id),
            actor=actor,
            actor_role=role_name,
            backup_id=str(backup_id),
            backup_dir=base_path,
            metadata={"active_process_canceled": True},
        )
        return {"status": "canceled"}

    if base_path:
        status_service.fail_running_steps(backup_id, base_path, error="Canceled by user")
        api_log(backup_id, "info", "Cleared stuck running steps via cancel request.")
    _audit(
        action="pipeline.cancel",
        target_type="backup",
        target_id=str(backup_id),
        actor=actor,
        actor_role=role_name,
        backup_id=str(backup_id),
        backup_dir=base_path,
        metadata={"active_process_canceled": False},
    )
    return {"status": "canceled"}


@app.post("/api/backups/{backup_id}/run")
def run_backup(
    backup_id: str,
    background_tasks: BackgroundTasks = None,
    config: Optional[BackupConfigSchema] = Body(default=None),
    user = Depends(get_current_user),
):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="server_admin")
    payload = _coerce_config_payload(config, BackupConfigSchema) if config is not None else None
    if payload:
        try:
            _save_backup_config_preserving_rbac(base_path, payload)
        except Exception as e:
            raise _internal_error(f"Failed to save backup config for {backup_id}", e, backup_id=backup_id)

    t.global_log("info", f"API: Starting backup pipeline for {backup_id}...")
    if background_tasks:
        background_tasks.add_task(run_script_in_background, 'backup_server.py', backup_id)
    _audit(
        action="pipeline.run",
        target_type="backup",
        target_id=str(backup_id),
        actor=actor,
        actor_role=role_name,
        backup_id=str(backup_id),
        backup_dir=base_path,
        after={"config_updated": bool(payload)},
    )
    return {"status": "started"}


@app.post("/api/backups/{backup_id}/rerun/{action}")
def rerun_backup_step(backup_id: str, action: str, background_tasks: BackgroundTasks, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="server_admin")
    action_map = {
        "reapply_characters": ("assign_ids.py", Step.ASSIGN_IDS.value),
        "fix_messages": ("fix_bad_messages.py", Step.FIX_MESSAGES.value),
        "reindex": ("index_scenes.py", Step.INDEX_SCENES.value)
    }
    
    if action not in action_map:
        raise HTTPException(status_code=400, detail=f"Invalid action. Allowed actions are: {', '.join(action_map.keys())}")
        
    script_name, step_name = action_map[action]
    status_service.update_step_status(backup_id, base_path, step_name, Status.RUNNING.value)
    t.global_log("info", f"API: Rerunning {action} for backup {backup_id}...")
    background_tasks.add_task(run_script_in_background, script_name, backup_id, step_name)
    _audit(
        action="pipeline.rerun",
        target_type="backup",
        target_id=str(backup_id),
        actor=actor,
        actor_role=role_name,
        backup_id=str(backup_id),
        backup_dir=base_path,
        metadata={"step": step_name, "action": action},
    )
    return {"status": "started", "action": action}


@app.post("/api/backups")
def create_new_backup(config: GlobalConfigSchema, background_tasks: BackgroundTasks, user = Depends(require_instance_admin)):
    actor = _ensure_instance_admin(user)
    payload = _coerce_config_payload(config, GlobalConfigSchema)
    admin_section = payload.get("admin")
    if isinstance(admin_section, dict):
        raw_path = admin_section.get("path")
        if raw_path:
            try:
                ensure_safe_backup_path(raw_path, get_data_root())
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid backup path")
        else:
            slug = sanitize_backup_slug(
                admin_section.get("backupName") or admin_section.get("serverName") or payload.get("server_name")
            )
            admin_section["path"] = f"Backups/{slug}"
            try:
                ensure_safe_backup_path(admin_section["path"], get_data_root())
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid backup path")

    global_config_path = (Path(get_project_root()) / 'res' / 'config.json').as_posix()
    before_cfg = None
    try:
        before_cfg = _read_global_config_file()
    except Exception:
        before_cfg = None
    try:
        t.save_json_atomic(payload, global_config_path)
    except Exception as e:
        raise _internal_error("create_new_backup save_global_config", e)
        
    t.global_log("info", f"API: Creating new backup pipeline from global config...")
    python_exec = sys.executable
    project_root = get_project_root()
    src_dir = (Path(project_root) / 'src').resolve().as_posix()
    script_path = safe_join_within(src_dir, 'backup_server.py').as_posix()
    env = scrub_sensitive_env(os.environ, keep_discord_token=True)
    existing_pythonpath = env.get("PYTHONPATH", "")
    paths = [src_dir, project_root]
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    subprocess.Popen([python_exec, script_path], cwd=project_root, env=env)
    _audit(
        action="backup.create",
        target_type="backup",
        actor=actor,
        actor_role="instance_admin",
        write_global=True,
        before=before_cfg,
        after=payload,
    )
    
    return {"status": "started", "detail": "Starting new backup pipeline. Check global logs."}


# --- CHARACTER ENDPOINTS ---


def _mask_writer_privacy(writers: List[Dict[str, Any]], actor: Dict[str, Any], role_level: int) -> List[Dict[str, Any]]:
    caller_id = str(actor.get("sub") or actor.get("id") or "").strip()
    for w in writers:
        if not isinstance(w, dict):
            continue
        w_uid = str(w.get("discord_user_id") or "").strip()
        is_self = bool(w_uid and caller_id and w_uid == caller_id)
        w["is_self"] = is_self
        if role_level < rbac.ROLE_LEVELS["curator"] and not is_self:
            w["discord_user_id"] = None
    return writers


@app.get("/api/backups/{backup_id}/characters")
def get_characters(
    backup_id: str,
    format: str = Query("legacy"),
    by_me: bool = Query(False),
    request: Request = None,
    auth_user = Depends(get_current_user),
):
    base_path, actor, _, role_level, _ = resolve_authorized_backup(backup_id, auth_user, min_role="viewer")
    if not isinstance(format, str):
        format = "legacy"
    if not isinstance(by_me, bool):
        by_me = False

    from db.session import require_db, init_db
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    writer_id = None
    if by_me and (request or not actor.get("_direct_call")):
        by_me_user = get_optional_user(request) if request else None
        if by_me_user is None and not actor.get("_direct_call"):
            by_me_user = actor
        if by_me_user and by_me_user.get("sub"):
            writer_info = curation_service.get_my_writer(backup_id, base_path, str(by_me_user["sub"]))
            if writer_info:
                writer_id = writer_info["id"]
            else:
                return [] if format == "legacy" else {"writers": [], "groups": [], "characters": []}
        else:
            return [] if format == "legacy" else {"writers": [], "groups": [], "characters": []}

    try:
        res = character_service.get_characters(
            backup_id=backup_id,
            base_path=base_path,
            format_type=format,
            by_writer_id=writer_id
        )
        if isinstance(res, dict) and isinstance(res.get("writers"), list):
            _mask_writer_privacy(res["writers"], actor, role_level)
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Failed to load characters: {e}")


@app.post("/api/backups/{backup_id}/characters/merge")
def merge_characters(backup_id: str, req: MergeCharactersRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_source = _snapshot_backup_record(backup_id, base_path, "character", req.source_id)
    before_target = _snapshot_backup_record(backup_id, base_path, "character", req.target_id)
    try:
        character_service.merge_characters(backup_id, base_path, req.source_id, req.target_id)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        after_target = _snapshot_backup_record(backup_id, base_path, "character", req.target_id)
        _audit(
            action="character.merge",
            target_type="character",
            target_id=str(req.target_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before={"source": before_source, "target": before_target},
            after={"target": after_target},
            metadata={"source_id": req.source_id, "target_id": req.target_id},
        )
        api_log(backup_id, "base", "Merge completed successfully.")
        return {"status": "success"}
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        api_log(backup_id, "error", f"Merge failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/backups/{backup_id}/characters/nest")
def nest_character(backup_id: str, req: NestCharacterRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, role_level, _ = resolve_authorized_backup(backup_id, user, min_role="participant")
    if role_level == rbac.ROLE_LEVELS["participant"]:
        try:
            rbac.assert_participant_characters_ownership(
                backup_id, base_path, [req.child_id, req.parent_id], str(actor.get("sub") or "")
            )
        except HTTPException as exc_denied:
            if exc_denied.status_code == 403:
                _audit(
                    action="rbac.denied",
                    target_type="character",
                    target_id=str(req.child_id),
                    actor=actor,
                    actor_role=role_name,
                    backup_id=backup_id,
                    backup_dir=base_path,
                    write_global=True,
                    metadata={"reason": str(exc_denied.detail), "parent_id": req.parent_id},
                    status="denied",
                )
            raise
    before_child = _snapshot_backup_record(backup_id, base_path, "character", req.child_id)
    try:
        character_service.nest_character(backup_id, base_path, req.child_id, req.parent_id, req.version_type)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        after_child = _snapshot_backup_record(backup_id, base_path, "character", req.child_id)
        _audit(
            action="character.nest",
            target_type="character",
            target_id=str(req.child_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_child,
            after=after_child,
            metadata={"parent_id": req.parent_id, "version_type": req.version_type},
        )
        api_log(backup_id, "base", "Nest completed successfully.")
        return {"status": "success"}
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        api_log(backup_id, "error", f"Nest failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/backups/{backup_id}/characters/{char_id}/unnest")
def unnest_character(backup_id: str, char_id: int, user = Depends(get_current_user)):
    base_path, actor, role_name, role_level, _ = resolve_authorized_backup(backup_id, user, min_role="participant")
    if role_level == rbac.ROLE_LEVELS["participant"]:
        try:
            rbac.assert_participant_characters_ownership(
                backup_id, base_path, [char_id], str(actor.get("sub") or "")
            )
        except HTTPException as exc_denied:
            if exc_denied.status_code == 403:
                _audit(
                    action="rbac.denied",
                    target_type="character",
                    target_id=str(char_id),
                    actor=actor,
                    actor_role=role_name,
                    backup_id=backup_id,
                    backup_dir=base_path,
                    write_global=True,
                    metadata={"reason": str(exc_denied.detail)},
                    status="denied",
                )
            raise
    before_char = _snapshot_backup_record(backup_id, base_path, "character", char_id)
    try:
        character_service.unnest_character(backup_id, base_path, char_id)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        after_char = _snapshot_backup_record(backup_id, base_path, "character", char_id)
        _audit(
            action="character.unnest",
            target_type="character",
            target_id=str(char_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_char,
            after=after_char,
        )
        api_log(backup_id, "base", "Unnest completed successfully.")
        return {"status": "success"}
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        api_log(backup_id, "error", f"Unnest failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/backups/{backup_id}/characters/{char_id}")
def update_character(backup_id: str, char_id: int, req: UpdateCharacterRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, role_level, _ = resolve_authorized_backup(backup_id, user, min_role="participant")
    eff_writer = req.writer
    eff_writer_id = req.writer_id
    eff_update_writer_id = "writer_id" in getattr(req, "model_fields_set", set())
    if role_level == rbac.ROLE_LEVELS["participant"]:
        try:
            rbac.assert_participant_character_update(
                backup_id,
                base_path,
                char_id,
                str(actor.get("sub") or ""),
                req.writer,
                requested_writer_id=req.writer_id,
                writer_id_provided=eff_update_writer_id,
            )
        except HTTPException as exc_denied:
            if exc_denied.status_code == 403:
                _audit(
                    action="rbac.denied",
                    target_type="character",
                    target_id=str(char_id),
                    actor=actor,
                    actor_role=role_name,
                    backup_id=backup_id,
                    backup_dir=base_path,
                    write_global=True,
                    metadata={"reason": str(exc_denied.detail)},
                    status="denied",
                )
            raise
        eff_writer = None
        eff_update_writer_id = False
    before_char = _snapshot_backup_record(backup_id, base_path, "character", char_id)
    try:
        char_dict = character_service.update_character(
            backup_id,
            base_path,
            char_id,
            names=req.names,
            tags=req.tags,
            writer=eff_writer,
            writer_id=eff_writer_id,
            update_writer_id=eff_update_writer_id,
        )
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        after_char = _snapshot_backup_record(backup_id, base_path, "character", char_id) or char_dict
        _audit(
            action="character.update",
            target_type="character",
            target_id=str(char_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_char,
            after=after_char,
        )
        api_log(backup_id, "base", "Attributes updated successfully.")
        return {"status": "success", "character": char_dict}
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except ValueError as e:
        api_log(backup_id, "error", f"Character {char_id} update failed: {e}")
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Update failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/backups/{backup_id}/writers")
def get_writers(backup_id: str, user = Depends(get_current_user)):
    base_path = get_authorized_backup_path(backup_id, user)
    try:
        return character_service.get_writers(backup_id, base_path)
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        raise _internal_error("endpoint error", e)


# --- SCENE ENDPOINTS ---


@app.get("/api/backups/{backup_id}/scenes")
def get_scenes(
    backup_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    channels: Optional[List[str]] = Query(None),
    categories: Optional[List[str]] = Query(None),
    statuses: Optional[List[str]] = Query(None),
    types: Optional[List[str]] = Query(None),
    characters: Optional[List[int]] = Query(None),
    character_groups: Optional[List[int]] = Query(None),
    character_logic: str = Query('AND'),
    writers: Optional[List[str]] = Query(None),
    writer_logic: str = Query('AND'),
    include_alter_egos: bool = Query(True),
    include_familiars: bool = Query(True),
    include_npcs: bool = Query(True),
    before: Optional[str] = Query(None),
    after: Optional[str] = Query(None),
    by_me: bool = Query(False),
    search: Optional[str] = Query(None, max_length=500),
    sort: str = Query("asc"),
    request: Request = None,
    auth_user = Depends(get_current_user),
):
    actor = _resolve_direct_call_user(auth_user)
    base_path = get_authorized_backup_path(backup_id, actor)
    if not isinstance(page, int) or page < 1: page = 1
    if not isinstance(per_page, int) or per_page < 1: per_page = 50
    per_page = min(per_page, 200)
    if not isinstance(channels, (list, tuple, set)): channels = None
    if not isinstance(categories, (list, tuple, set)): categories = None
    if not isinstance(statuses, (list, tuple, set)): statuses = None
    if not isinstance(types, (list, tuple, set)): types = None
    if not isinstance(characters, (list, tuple, set)): characters = None
    if not isinstance(character_groups, (list, tuple, set)): character_groups = None
    if not isinstance(character_logic, str): character_logic = 'AND'
    if not isinstance(writers, (list, tuple, set)): writers = None
    if not isinstance(writer_logic, str): writer_logic = 'AND'
    if not isinstance(include_alter_egos, bool): include_alter_egos = True
    if not isinstance(include_familiars, bool): include_familiars = True
    if not isinstance(include_npcs, bool): include_npcs = True
    if not isinstance(before, str): before = None
    if not isinstance(after, str): after = None
    if not isinstance(search, str): search = None
    if not isinstance(sort, str): sort = "asc"

    if by_me and (request or not actor.get("_direct_call")):
        from db.session import require_db, init_db
        require_db(base_path, backup_id=backup_id)
        init_db(engine_or_backup_id=backup_id, backup_path=base_path)
        by_me_user = get_optional_user(request) if request else None
        if by_me_user is None and not actor.get("_direct_call"):
            by_me_user = actor
        if by_me_user and by_me_user.get("sub"):
            writer_info = curation_service.get_my_writer(backup_id, base_path, str(by_me_user["sub"]))
            if writer_info:
                writers = [writer_info["display_name"]]
            else:
                return {
                    "total_items": 0,
                    "current_page": 1,
                    "per_page": per_page,
                    "total_pages": 0,
                    "scenes": []
                }
        else:
            return {
                "total_items": 0,
                "current_page": 1,
                "per_page": per_page,
                "total_pages": 0,
                "scenes": []
            }

    from models import SceneManager
    manager = SceneManager.get_instance(backup_id, base_path)
    return manager.get_paginated_scenes(
        page=page,
        per_page=per_page,
        kind="scene",
        channels=channels,
        categories=categories,
        statuses=statuses,
        types=types,
        character_ids=characters,
        character_group_ids=character_groups,
        character_logic=character_logic,
        writer_names=writers,
        writer_logic=writer_logic,
        include_alter_egos=include_alter_egos,
        include_familiars=include_familiars,
        include_npcs=include_npcs,
        before=before,
        after=after,
        search=search,
        sort=sort,
    )


@app.put("/api/backups/{backup_id}/scenes/{scene_id}")
def update_scene(backup_id: str, scene_id: str, req: UpdateSceneMetadataRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_scene = _snapshot_backup_record(backup_id, base_path, "scene", scene_id)
    try:
        check_not_indexing(backup_id, base_path)
        custom_name = req.custom_name if req.custom_name is not None else req.name
        res = curation_service.update_scene_metadata(
            backup_id,
            base_path,
            scene_id=scene_id,
            custom_name=custom_name,
        )
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        after_scene = _snapshot_backup_record(backup_id, base_path, "scene", scene_id) or res
        _audit(
            action="scene.update",
            target_type="scene",
            target_id=str(scene_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_scene,
            after=after_scene,
        )
        api_log(backup_id, "base", f"Scene #{scene_id} metadata updated successfully.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except exc.ConflictError as e:
        api_log(backup_id, "error", f"Scene update conflict: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except exc.NotFoundError as e:
        api_log(backup_id, "error", f"Scene not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except (exc.ValidationError, ValueError) as e:
        api_log(backup_id, "error", f"Scene update validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Scene update failed: {e}")
        raise _internal_error("endpoint error", e)


@app.get("/api/backups/{backup_id}/scenes/{scene_id}/merge-neighbors")
def get_scene_merge_neighbors(backup_id: str, scene_id: str, user = Depends(get_current_user)):
    base_path = get_authorized_backup_path(backup_id, user)
    try:
        check_not_indexing(backup_id, base_path)
        res = curation_service.get_scene_merge_neighbors(backup_id, base_path, scene_id)
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except exc.NotFoundError as e:
        api_log(backup_id, "error", f"Scene merge neighbors not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except (exc.ValidationError, ValueError) as e:
        api_log(backup_id, "error", f"Scene merge neighbors validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Fetch scene merge neighbors failed: {e}")
        raise _internal_error("endpoint error", e)


@app.post("/api/backups/{backup_id}/scenes/{scene_id}/merge")
def merge_scene(backup_id: str, scene_id: str, req: MergeSceneRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_scene = _snapshot_backup_record(backup_id, base_path, "scene", scene_id)
    try:
        check_not_indexing(backup_id, base_path)
        res = curation_service.merge_adjacent_scene(
            backup_id,
            base_path,
            scene_id,
            direction=req.direction,
            force=req.force,
            note=req.note,
        )
        if res.get("status") == "success":
            from models import SceneManager
            SceneManager.clear_cache(backup_id)
            after_scene = _snapshot_backup_record(backup_id, base_path, "scene", scene_id) or res
            _audit(
                action="scene.merge",
                target_type="scene",
                target_id=str(scene_id),
                actor=actor,
                actor_role=role_name,
                backup_id=backup_id,
                backup_dir=base_path,
                before=before_scene,
                after=after_scene,
                metadata={"direction": req.direction, "force": req.force},
            )
            api_log(backup_id, "base", f"Scene '{scene_id}' merged successfully with {req.direction} scene.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except exc.ConflictError as e:
        api_log(backup_id, "error", f"Scene merge conflict: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except exc.NotFoundError as e:
        api_log(backup_id, "error", f"Scene merge not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except (exc.ValidationError, ValueError) as e:
        api_log(backup_id, "error", f"Scene merge validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Scene merge failed: {e}")
        raise _internal_error("endpoint error", e)


@app.get("/api/backups/{backup_id}/sessions")
def get_sessions(
    backup_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    channels: Optional[List[str]] = Query(None),
    statuses: Optional[List[str]] = Query(None),
    characters: Optional[List[int]] = Query(None),
    character_groups: Optional[List[int]] = Query(None),
    character_logic: str = Query('AND'),
    writers: Optional[List[str]] = Query(None),
    writer_logic: str = Query('AND'),
    include_alter_egos: bool = Query(True),
    include_familiars: bool = Query(True),
    include_npcs: bool = Query(True),
    before: Optional[str] = Query(None),
    after: Optional[str] = Query(None),
    by_me: bool = Query(False),
    search: Optional[str] = Query(None, max_length=500),
    sort: str = Query("asc"),
    request: Request = None,
    auth_user = Depends(get_current_user),
):
    actor = _resolve_direct_call_user(auth_user)
    base_path = get_authorized_backup_path(backup_id, actor)
    if not isinstance(page, int) or page < 1: page = 1
    if not isinstance(per_page, int) or per_page < 1: per_page = 50
    per_page = min(per_page, 200)
    if not isinstance(channels, (list, tuple, set)): channels = None
    if not isinstance(statuses, (list, tuple, set)): statuses = None
    if not isinstance(characters, (list, tuple, set)): characters = None
    if not isinstance(character_groups, (list, tuple, set)): character_groups = None
    if not isinstance(character_logic, str): character_logic = 'AND'
    if not isinstance(writers, (list, tuple, set)): writers = None
    if not isinstance(writer_logic, str): writer_logic = 'AND'
    if not isinstance(include_alter_egos, bool): include_alter_egos = True
    if not isinstance(include_familiars, bool): include_familiars = True
    if not isinstance(include_npcs, bool): include_npcs = True
    if not isinstance(before, str): before = None
    if not isinstance(after, str): after = None
    if not isinstance(search, str): search = None
    if not isinstance(sort, str): sort = "asc"

    if by_me and (request or not actor.get("_direct_call")):
        from db.session import require_db, init_db
        require_db(base_path, backup_id=backup_id)
        init_db(engine_or_backup_id=backup_id, backup_path=base_path)
        by_me_user = get_optional_user(request) if request else None
        if by_me_user is None and not actor.get("_direct_call"):
            by_me_user = actor
        if by_me_user and by_me_user.get("sub"):
            writer_info = curation_service.get_my_writer(backup_id, base_path, str(by_me_user["sub"]))
            if writer_info:
                writers = [writer_info["display_name"]]
            else:
                return {
                    "total_items": 0,
                    "current_page": 1,
                    "per_page": per_page,
                    "total_pages": 0,
                    "sessions": [],
                    "scenes": []
                }
        else:
            return {
                "total_items": 0,
                "current_page": 1,
                "per_page": per_page,
                "total_pages": 0,
                "sessions": [],
                "scenes": []
            }

    from models import SceneManager
    manager = SceneManager.get_instance(backup_id, base_path)
    return manager.get_paginated_scenes(
        page=page,
        per_page=per_page,
        kind="session",
        channels=channels,
        statuses=statuses,
        character_ids=characters,
        character_group_ids=character_groups,
        character_logic=character_logic,
        writer_names=writers,
        writer_logic=writer_logic,
        include_alter_egos=include_alter_egos,
        include_familiars=include_familiars,
        include_npcs=include_npcs,
        before=before,
        after=after,
        search=search,
        sort=sort,
    )


# --- EVENTS ENDPOINTS ---


@app.get("/api/backups/{backup_id}/events")
def get_events(
    backup_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    channels: Optional[List[str]] = Query(None),
    statuses: Optional[List[str]] = Query(None),
    status: str = Query("all"),
    characters: Optional[List[int]] = Query(None),
    character_groups: Optional[List[int]] = Query(None),
    character_logic: str = Query("AND"),
    character_name: Optional[str] = Query(None),
    writers: Optional[List[str]] = Query(None),
    writer_logic: str = Query("AND"),
    include_alter_egos: bool = Query(True),
    include_familiars: bool = Query(True),
    include_npcs: bool = Query(True),
    before: Optional[str] = Query(None),
    after: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    search: Optional[str] = Query(None, max_length=500),
    sort: str = Query("asc"),
    by_me: bool = Query(False),
    request: Request = None,
    auth_user = Depends(get_current_user),
):
    actor = _resolve_direct_call_user(auth_user)
    base_path = get_authorized_backup_path(backup_id, actor)
    if not isinstance(page, int) or page < 1: page = 1
    if not isinstance(per_page, int) or per_page < 1: per_page = 50
    per_page = min(per_page, 200)
    if not isinstance(channels, (list, tuple, set)): channels = None
    if not isinstance(statuses, (list, tuple, set)): statuses = None
    if not isinstance(status, str): status = "all"
    if not isinstance(characters, (list, tuple, set)): characters = None
    if not isinstance(character_groups, (list, tuple, set)): character_groups = None
    if not isinstance(character_logic, str): character_logic = "AND"
    if not isinstance(character_name, str): character_name = None
    if not isinstance(writers, (list, tuple, set)): writers = None
    if not isinstance(writer_logic, str): writer_logic = "AND"
    if not isinstance(include_alter_egos, bool): include_alter_egos = True
    if not isinstance(include_familiars, bool): include_familiars = True
    if not isinstance(include_npcs, bool): include_npcs = True
    if not isinstance(before, str): before = None
    if not isinstance(after, str): after = None
    if not isinstance(start_date, str): start_date = None
    if not isinstance(end_date, str): end_date = None
    if not isinstance(search, str): search = None
    if not isinstance(sort, str): sort = "asc"

    if by_me and (request or not actor.get("_direct_call")):
        from db.session import require_db, init_db
        require_db(base_path, backup_id=backup_id)
        init_db(engine_or_backup_id=backup_id, backup_path=base_path)
        by_me_user = get_optional_user(request) if request else None
        if by_me_user is None and not actor.get("_direct_call"):
            by_me_user = actor
        if by_me_user and by_me_user.get("sub"):
            writer_info = curation_service.get_my_writer(backup_id, base_path, str(by_me_user["sub"]))
            if writer_info:
                writers = [writer_info["display_name"]]
            else:
                return {
                    "total_items": 0,
                    "current_page": 1,
                    "per_page": per_page,
                    "total_pages": 0,
                    "events": [],
                    "scenes": [],
                }
        else:
            return {
                "total_items": 0,
                "current_page": 1,
                "per_page": per_page,
                "total_pages": 0,
                "events": [],
                "scenes": [],
            }

    from models import SceneManager
    manager = SceneManager.get_instance(backup_id, base_path)
    return manager.get_paginated_events(
        page=page,
        per_page=per_page,
        channels=channels,
        statuses=statuses,
        status=status,
        character_ids=characters,
        character_group_ids=character_groups,
        character_logic=character_logic,
        character_name=character_name,
        writer_names=writers,
        writer_logic=writer_logic,
        include_alter_egos=include_alter_egos,
        include_familiars=include_familiars,
        include_npcs=include_npcs,
        before=before,
        after=after,
        start_date=start_date,
        end_date=end_date,
        search=search,
        sort=sort,
    )


@app.put("/api/backups/{backup_id}/events/{event_pk}")
def update_event(backup_id: str, event_pk: int, req: UpdateEventMetadataRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_ev = _snapshot_backup_record(backup_id, base_path, "event", event_pk)
    try:
        check_not_indexing(backup_id, base_path)
        res = curation_service.update_event_metadata(
            backup_id,
            base_path,
            event_pk=event_pk,
            name=req.name,
            channel_names=req.channel_names,
        )
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        after_ev = _snapshot_backup_record(backup_id, base_path, "event", event_pk) or res
        _audit(
            action="event.update",
            target_type="event",
            target_id=str(event_pk),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_ev,
            after=after_ev,
        )
        api_log(backup_id, "base", "Event metadata updated successfully.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except exc.ConflictError as e:
        api_log(backup_id, "error", f"Event update conflict: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except exc.NotFoundError as e:
        api_log(backup_id, "error", f"Event not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except (exc.ValidationError, ValueError) as e:
        api_log(backup_id, "error", f"Event update validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Event update failed: {e}")
        raise _internal_error("endpoint error", e)


@app.post("/api/backups/{backup_id}/events/merge")
def merge_events(backup_id: str, req: MergeEventsRequest, user = Depends(get_current_user)):
    eff_pks = list(req.event_pks or [])
    if not eff_pks and req.target_event_pk is not None and req.source_event_pk is not None:
        eff_pks = [req.target_event_pk, req.source_event_pk]
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_events = [_snapshot_backup_record(backup_id, base_path, "event", pk) for pk in eff_pks]
    try:
        check_not_indexing(backup_id, base_path)
        res = curation_service.merge_events(
            backup_id,
            base_path,
            event_pks=eff_pks,
            target_name=req.name if req.name is not None else req.merged_name,
        )
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        _audit(
            action="event.merge",
            target_type="event",
            target_id=str(eff_pks[0]) if eff_pks else None,
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before={"events": before_events},
            after=res if isinstance(res, dict) else None,
            metadata={"event_pks": eff_pks},
        )
        api_log(backup_id, "base", "Events merged successfully.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except exc.ConflictError as e:
        api_log(backup_id, "error", f"Merge events conflict: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except exc.NotFoundError as e:
        api_log(backup_id, "error", f"Merge events not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except (exc.ValidationError, ValueError) as e:
        api_log(backup_id, "error", f"Merge events validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Merge events failed: {e}")
        raise _internal_error("endpoint error", e)


@app.post("/api/backups/{backup_id}/events/{event_pk}/split")
def split_event(backup_id: str, event_pk: int, req: SplitEventRequest, user = Depends(get_current_user)):
    raw_ids = req.scene_ids or req.scene_pks or req.channel_ids or []
    ids_to_extract = [str(x) for x in raw_ids]
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_ev = _snapshot_backup_record(backup_id, base_path, "event", event_pk)
    try:
        check_not_indexing(backup_id, base_path)
        res = curation_service.split_event(
            backup_id,
            base_path,
            event_pk=event_pk,
            scene_ids_to_extract=ids_to_extract,
            new_event_name=req.new_name if req.new_name is not None else req.new_event_name,
        )
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        _audit(
            action="event.split",
            target_type="event",
            target_id=str(event_pk),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_ev,
            after=res if isinstance(res, dict) else None,
            metadata={"extracted_ids": ids_to_extract},
        )
        api_log(backup_id, "base", "Event split successfully.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except exc.ConflictError as e:
        api_log(backup_id, "error", f"Split event conflict: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except exc.NotFoundError as e:
        api_log(backup_id, "error", f"Split event not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except (exc.ValidationError, ValueError) as e:
        api_log(backup_id, "error", f"Split event validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Split event failed: {e}")
        raise _internal_error("endpoint error", e)


# --- CHARACTER GROUPS ENDPOINTS ---


@app.get("/api/backups/{backup_id}/groups")
def get_groups(backup_id: str, user = Depends(get_current_user)):
    base_path = get_authorized_backup_path(backup_id, user)
    try:
        return character_service.get_groups(backup_id, base_path)
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        raise _internal_error("endpoint error", e)


@app.post("/api/backups/{backup_id}/groups")
def create_group(backup_id: str, req: CreateGroupRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    try:
        res = character_service.create_group(backup_id, base_path, req.names, req.member_ids)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        gid = res.get("id") if isinstance(res, dict) else None
        _audit(
            action="group.create",
            target_type="group",
            target_id=str(gid) if gid is not None else None,
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            after=res if isinstance(res, dict) else {"names": req.names, "member_ids": req.member_ids},
        )
        api_log(backup_id, "base", "Group created successfully.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        api_log(backup_id, "error", f"Group creation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/backups/{backup_id}/groups/{group_id}")
def update_group(backup_id: str, group_id: int, req: UpdateGroupRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_group = _snapshot_backup_record(backup_id, base_path, "group", group_id)
    try:
        res = character_service.update_group(backup_id, base_path, group_id, names=req.names, member_ids=req.member_ids)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        after_group = _snapshot_backup_record(backup_id, base_path, "group", group_id) or res
        _audit(
            action="group.update",
            target_type="group",
            target_id=str(group_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_group,
            after=after_group,
        )
        api_log(backup_id, "base", "Group updated successfully.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except ValueError as e:
        api_log(backup_id, "error", f"Group update failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Group update failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/backups/{backup_id}/groups/{group_id}")
def delete_group(backup_id: str, group_id: int, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_group = _snapshot_backup_record(backup_id, base_path, "group", group_id)
    try:
        res = curation_service.delete_group(backup_id, base_path, group_id)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        _audit(
            action="group.delete",
            target_type="group",
            target_id=str(group_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_group,
        )
        api_log(backup_id, "base", "Group deleted successfully.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except ValueError as e:
        api_log(backup_id, "error", f"Group deletion failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Group deletion failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# --- CURATION & WRITERS MANAGEMENT ENDPOINTS ---


@app.get("/api/backups/{backup_id}/writers/detailed")
def get_writers_detailed(backup_id: str, user = Depends(get_current_user)):
    base_path, actor, _, role_level, _ = resolve_authorized_backup(backup_id, user, min_role="viewer")
    try:
        writers = curation_service.get_writers_detailed(backup_id, base_path)
        return _mask_writer_privacy(writers, actor, role_level)
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        raise _internal_error("endpoint error", e)


@app.post("/api/backups/{backup_id}/writers")
def create_writer(backup_id: str, req: CreateWriterRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    try:
        res = curation_service.create_writer(
            backup_id,
            base_path,
            display_name=req.display_name,
            aliases=req.aliases,
            discord_user_id=req.discord_user_id
        )
        wid = res.get("id") if isinstance(res, dict) else None
        _audit(
            action="writer.create",
            target_type="writer",
            target_id=str(wid) if wid is not None else None,
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            after=res if isinstance(res, dict) else {"display_name": req.display_name, "aliases": req.aliases},
        )
        api_log(backup_id, "base", "Writer created successfully.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except ValueError as e:
        api_log(backup_id, "error", f"Writer creation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Writer creation failed: {e}")
        raise _internal_error("endpoint error", e)


@app.put("/api/backups/{backup_id}/writers/{writer_id}")
def update_writer(backup_id: str, writer_id: int, req: UpdateWriterRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, role_level, _ = resolve_authorized_backup(backup_id, user, min_role="participant")
    eff_discord_user_id = req.discord_user_id
    if role_level == rbac.ROLE_LEVELS["participant"]:
        try:
            rbac.assert_participant_writer_update(
                backup_id, base_path, writer_id, str(actor.get("sub") or ""), req.discord_user_id
            )
        except HTTPException as exc_denied:
            if exc_denied.status_code == 403:
                _audit(
                    action="rbac.denied",
                    target_type="writer",
                    target_id=str(writer_id),
                    actor=actor,
                    actor_role=role_name,
                    backup_id=backup_id,
                    backup_dir=base_path,
                    write_global=True,
                    metadata={"reason": str(exc_denied.detail)},
                    status="denied",
                )
            raise
        eff_discord_user_id = None
    before_writer = _snapshot_backup_record(backup_id, base_path, "writer", writer_id)
    try:
        res = curation_service.update_writer(
            backup_id,
            base_path,
            writer_id=writer_id,
            display_name=req.display_name,
            aliases=req.aliases,
            discord_user_id=eff_discord_user_id,
        )
        after_writer = _snapshot_backup_record(backup_id, base_path, "writer", writer_id) or res
        _audit(
            action="writer.update",
            target_type="writer",
            target_id=str(writer_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_writer,
            after=after_writer,
        )
        api_log(backup_id, "base", "Writer updated successfully.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except ValueError as e:
        api_log(backup_id, "error", f"Writer update failed: {e}")
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Writer update failed: {e}")
        raise _internal_error("endpoint error", e)


@app.delete("/api/backups/{backup_id}/writers/{writer_id}")
def delete_writer(backup_id: str, writer_id: int, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_writer = _snapshot_backup_record(backup_id, base_path, "writer", writer_id)
    try:
        res = curation_service.delete_writer(backup_id, base_path, writer_id=writer_id)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        _audit(
            action="writer.delete",
            target_type="writer",
            target_id=str(writer_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_writer,
        )
        api_log(backup_id, "base", "Writer deleted successfully.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except ValueError as e:
        api_log(backup_id, "error", f"Writer deletion failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Writer deletion failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/backups/{backup_id}/writers/link-suggestions")
def get_writer_link_suggestions(backup_id: str, user = Depends(get_current_user)):
    base_path = get_authorized_backup_path(backup_id, user, min_role="curator")
    try:
        return curation_service.get_writer_link_suggestions(backup_id, base_path)
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        raise _internal_error("endpoint error", e)


@app.get("/api/backups/{backup_id}/curation/summary")
def get_curation_summary(backup_id: str, user = Depends(get_current_user)):
    base_path, _, _, role_level, _ = resolve_authorized_backup(backup_id, user, min_role="viewer")
    try:
        if role_level < rbac.ROLE_LEVELS["curator"]:
            from db.session import require_db
            require_db(base_path, backup_id=backup_id)
            return {
                "unresolved_issues": 0,
                "unassigned_characters": 0,
                "flagged_messages": 0,
                "unlinked_writers": 0,
                "link_suggestions": 0,
            }
        return curation_service.get_curation_summary(backup_id, base_path)
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        raise _internal_error("endpoint error", e)


# --- REVIEW QUEUES & OVERRIDES ENDPOINTS ---


@app.get("/api/backups/{backup_id}/characters/unassigned-writers")
def get_unassigned_characters(backup_id: str, user = Depends(get_current_user)):
    base_path = get_authorized_backup_path(backup_id, user, min_role="curator")
    try:
        return curation_service.get_unassigned_characters(backup_id, base_path)
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        raise _internal_error("endpoint error", e)


@app.put("/api/backups/{backup_id}/characters/{char_id}/assign-writer")
def assign_character_writer(backup_id: str, char_id: int, req: AssignCharacterWriterRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_char = _snapshot_backup_record(backup_id, base_path, "character", char_id)
    try:
        res = curation_service.assign_character_writer(backup_id, base_path, char_id=char_id, writer_id=req.writer_id)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        after_char = _snapshot_backup_record(backup_id, base_path, "character", char_id) or res
        _audit(
            action="character.assign_writer",
            target_type="character",
            target_id=str(char_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_char,
            after=after_char,
            metadata={"writer_id": req.writer_id},
        )
        api_log(backup_id, "base", "Character assigned to writer successfully.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except ValueError as e:
        api_log(backup_id, "error", f"Assigning writer failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Assigning writer failed: {e}")
        raise _internal_error("endpoint error", e)


@app.get("/api/backups/{backup_id}/scene-issues")
def get_scene_issues(
    backup_id: str,
    kind: Optional[str] = Query(None),
    reason: Optional[str] = Query(None),
    status: Optional[str] = Query("unresolved"),
    channel_id: Optional[str] = Query(None),
    scene_type: Optional[str] = Query(None),
    scene_kind: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user = Depends(get_current_user),
):
    base_path = get_authorized_backup_path(backup_id, user, min_role="curator")
    if not isinstance(page, int) or page < 1: page = 1
    if not isinstance(per_page, int) or per_page < 1: per_page = 50
    per_page = min(per_page, 200)
    try:
        return curation_service.get_scene_issues(
            backup_id,
            base_path,
            kind=kind,
            reason=reason,
            status=status,
            channel_id=channel_id,
            scene_type=scene_type or scene_kind,
            page=page,
            per_page=per_page
        )
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        raise _internal_error("endpoint error", e)


def check_not_indexing(backup_id: str, base_path: str):
    try:
        statuses = status_service.get_step_statuses(backup_id, base_path)
        if statuses.get(Step.INDEX_SCENES.value) == Status.RUNNING.value:
            raise exc.ConflictError("Cannot modify scene issues while scene indexing is in progress.")
    except exc.ConflictError:
        raise
    except Exception:
        pass


@app.put("/api/backups/{backup_id}/scene-issues/{issue_id}/resolve")
def resolve_scene_issue(backup_id: str, issue_id: int, req: ResolveIssueRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_issue = _snapshot_backup_record(backup_id, base_path, "scene_issue", issue_id)
    try:
        check_not_indexing(backup_id, base_path)
        res = curation_service.resolve_scene_issue(
            backup_id, base_path, issue_id=issue_id, note=req.note, resolution=req.resolution
        )
        after_issue = _snapshot_backup_record(backup_id, base_path, "scene_issue", issue_id) or res
        _audit(
            action="scene_issue.resolve",
            target_type="scene_issue",
            target_id=str(issue_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_issue,
            after=after_issue,
        )
        api_log(backup_id, "base", "Scene issue resolved.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except exc.ConflictError as e:
        api_log(backup_id, "error", f"Resolving scene issue conflict: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except exc.NotFoundError as e:
        api_log(backup_id, "error", f"Scene issue not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except (exc.ValidationError, ValueError) as e:
        api_log(backup_id, "error", f"Resolving scene issue validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Resolving scene issue failed: {e}")
        raise _internal_error("endpoint error", e)


@app.put("/api/backups/{backup_id}/scene-issues/{issue_id}/reopen")
def reopen_scene_issue(backup_id: str, issue_id: int, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_issue = _snapshot_backup_record(backup_id, base_path, "scene_issue", issue_id)
    try:
        check_not_indexing(backup_id, base_path)
        res = curation_service.reopen_scene_issue(backup_id, base_path, issue_id=issue_id)
        after_issue = _snapshot_backup_record(backup_id, base_path, "scene_issue", issue_id) or res
        _audit(
            action="scene_issue.reopen",
            target_type="scene_issue",
            target_id=str(issue_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_issue,
            after=after_issue,
        )
        api_log(backup_id, "base", "Scene issue reopened.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except exc.ConflictError as e:
        api_log(backup_id, "error", f"Reopening scene issue conflict: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except exc.NotFoundError as e:
        api_log(backup_id, "error", f"Scene issue not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except (exc.ValidationError, ValueError) as e:
        api_log(backup_id, "error", f"Reopening scene issue validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Reopening scene issue failed: {e}")
        raise _internal_error("endpoint error", e)


@app.post("/api/backups/{backup_id}/scene-issues/manual-split")
def create_manual_scene_split(backup_id: str, req: ManualSplitRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    try:
        check_not_indexing(backup_id, base_path)
        res = curation_service.create_manual_scene_split(
            backup_id, base_path, discord_link=req.discord_link, note=req.note
        )
        _audit(
            action="scene_issue.manual_split",
            target_type="scene_issue",
            target_id=str(res.get("issue_id") or res.get("id") or "") if isinstance(res, dict) else None,
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            after=res if isinstance(res, dict) else {"discord_link": req.discord_link, "note": req.note},
        )
        api_log(backup_id, "base", "Manual scene split created.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except exc.ConflictError as e:
        api_log(backup_id, "error", f"Manual scene split conflict: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except exc.NotFoundError as e:
        api_log(backup_id, "error", f"Manual scene split not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except (exc.ValidationError, ValueError) as e:
        api_log(backup_id, "error", f"Manual scene split validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Manual scene split failed: {e}")
        raise _internal_error("endpoint error", e)


@app.get("/api/backups/{backup_id}/flagged-messages")
def get_flagged_messages(
    backup_id: str,
    status: Optional[str] = Query("unresolved"),
    kind: Optional[str] = Query(None),
    resolution: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(None),
    scene_type: Optional[str] = Query(None),
    scene_kind: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user = Depends(get_current_user),
):
    base_path = get_authorized_backup_path(backup_id, user, min_role="curator")
    if not isinstance(page, int) or page < 1: page = 1
    if not isinstance(per_page, int) or per_page < 1: per_page = 50
    per_page = min(per_page, 200)
    try:
        return curation_service.get_flagged_messages(
            backup_id,
            base_path,
            status=status,
            kind=kind,
            resolution=resolution,
            channel_id=channel_id,
            scene_type=scene_type or scene_kind,
            page=page,
            per_page=per_page
        )
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        raise _internal_error("endpoint error", e)


@app.post("/api/backups/{backup_id}/flagged-messages/manual")
def add_manual_flagged_message(backup_id: str, req: ManualFlaggedMessageRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    try:
        check_not_indexing(backup_id, base_path)
        res = curation_service.add_manual_flagged_message(
            backup_id, base_path, discord_link=req.discord_link, note=req.note
        )
        _audit(
            action="flagged_message.manual",
            target_type="flagged_message",
            target_id=str(res.get("message_id") or "") if isinstance(res, dict) else None,
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            after=res if isinstance(res, dict) else {"discord_link": req.discord_link, "note": req.note},
        )
        api_log(backup_id, "base", "Manual flagged message added.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except exc.ConflictError as e:
        api_log(backup_id, "error", f"Add manual flagged message conflict: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except exc.NotFoundError as e:
        api_log(backup_id, "error", f"Add manual flagged message not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except (exc.ValidationError, ValueError) as e:
        api_log(backup_id, "error", f"Add manual flagged message validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Add manual flagged message failed: {e}")
        raise _internal_error("endpoint error", e)


@app.put("/api/backups/{backup_id}/flagged-messages/{message_id}/resolve")
def resolve_flagged_message(backup_id: str, message_id: str, req: ResolveFlaggedMessageRequest, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_fm = _snapshot_backup_record(backup_id, base_path, "flagged_message", message_id)
    try:
        check_not_indexing(backup_id, base_path)
        res = curation_service.resolve_flagged_message(
            backup_id,
            base_path,
            message_id=message_id,
            resolution=req.resolution,
            note=req.note,
            override_content=req.override_content,
            override_author=req.override_author,
        )
        after_fm = _snapshot_backup_record(backup_id, base_path, "flagged_message", message_id) or res
        _audit(
            action="flagged_message.resolve",
            target_type="flagged_message",
            target_id=str(message_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_fm,
            after=after_fm,
        )
        api_log(backup_id, "base", "Flagged message resolved.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except exc.ConflictError as e:
        api_log(backup_id, "error", f"Resolving flagged message conflict: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except exc.NotFoundError as e:
        api_log(backup_id, "error", f"Flagged message not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except (exc.ValidationError, ValueError) as e:
        api_log(backup_id, "error", f"Resolving flagged message validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Resolving flagged message failed: {e}")
        raise _internal_error("endpoint error", e)


@app.put("/api/backups/{backup_id}/flagged-messages/{message_id}/reopen")
def reopen_flagged_message(backup_id: str, message_id: str, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_fm = _snapshot_backup_record(backup_id, base_path, "flagged_message", message_id)
    try:
        check_not_indexing(backup_id, base_path)
        res = curation_service.reopen_flagged_message(backup_id, base_path, message_id=message_id)
        after_fm = _snapshot_backup_record(backup_id, base_path, "flagged_message", message_id) or res
        _audit(
            action="flagged_message.reopen",
            target_type="flagged_message",
            target_id=str(message_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_fm,
            after=after_fm,
        )
        api_log(backup_id, "base", "Flagged message reopened.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except exc.ConflictError as e:
        api_log(backup_id, "error", f"Reopening flagged message conflict: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except exc.NotFoundError as e:
        api_log(backup_id, "error", f"Flagged message not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except (exc.ValidationError, ValueError) as e:
        api_log(backup_id, "error", f"Reopening flagged message validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Reopening flagged message failed: {e}")
        raise _internal_error("endpoint error", e)


@app.post("/api/backups/{backup_id}/flagged-messages/{message_id}/promote")
def promote_flagged_message(backup_id: str, message_id: str, req: Optional[PromoteFlaggedMessageRequest] = None, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_fm = _snapshot_backup_record(backup_id, base_path, "flagged_message", message_id)
    content = req.content if req else None
    author = req.author if req else None
    try:
        res = curation_service.promote_flagged_message(
            backup_id,
            base_path,
            message_id=message_id,
            content=content,
            author=author
        )
        after_fm = _snapshot_backup_record(backup_id, base_path, "flagged_message", message_id) or res
        _audit(
            action="flagged_message.promote",
            target_type="flagged_message",
            target_id=str(message_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_fm,
            after=after_fm,
        )
        api_log(backup_id, "base", "Flagged message promoted successfully.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except ValueError as e:
        api_log(backup_id, "error", f"Promoting flagged message failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Promoting flagged message failed: {e}")
        raise _internal_error("endpoint error", e)


@app.get("/api/backups/{backup_id}/message-overrides")
def get_message_overrides(
    backup_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user = Depends(get_current_user),
):
    base_path = get_authorized_backup_path(backup_id, user, min_role="curator")
    if not isinstance(page, int) or page < 1: page = 1
    if not isinstance(per_page, int) or per_page < 1: per_page = 50
    per_page = min(per_page, 200)
    try:
        return curation_service.get_message_overrides(
            backup_id,
            base_path,
            page=page,
            per_page=per_page
        )
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        raise _internal_error("endpoint error", e)


@app.delete("/api/backups/{backup_id}/message-overrides/{message_id}")
def delete_message_override(backup_id: str, message_id: str, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="curator")
    before_fm = _snapshot_backup_record(backup_id, base_path, "flagged_message", message_id)
    try:
        res = curation_service.delete_message_override(backup_id, base_path, message_id=message_id)
        after_fm = _snapshot_backup_record(backup_id, base_path, "flagged_message", message_id) or res
        _audit(
            action="message_override.delete",
            target_type="message_override",
            target_id=str(message_id),
            actor=actor,
            actor_role=role_name,
            backup_id=backup_id,
            backup_dir=base_path,
            before=before_fm,
            after=after_fm,
        )
        api_log(backup_id, "base", "Message override deleted.")
        return res
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except ValueError as e:
        api_log(backup_id, "error", f"Deleting message override failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Deleting message override failed: {e}")
        raise _internal_error("endpoint error", e)


# --- USER PROFILE & LOGS ENDPOINTS ---


@app.get("/api/backups/{backup_id}/me/writer")
def get_my_writer(backup_id: str, user = Depends(get_current_user)):
    actor = _resolve_direct_call_user(user)
    base_path = get_authorized_backup_path(backup_id, actor)
    discord_user_id = actor.get("sub") if isinstance(actor, dict) else None
    if not discord_user_id:
        return None
    try:
        return curation_service.get_my_writer(backup_id, base_path, str(discord_user_id))
    except (HTTPException, exc.DatabaseConnectionError, exc.DatabaseSchemaMismatchError):
        raise
    except Exception as e:
        raise _internal_error("endpoint error", e)


SSE_MAX_DURATION_SECONDS = 300.0
SSE_MAX_CONCURRENT_STREAMS_PER_USER = 5
_SSE_ACTIVE_STREAMS_LOCK = threading.Lock()
_SSE_ACTIVE_STREAMS: Dict[str, int] = {}


@app.get("/api/backups/{backup_id}/logs")
def get_backup_logs(backup_id: str, lines: int = Query(100, ge=1, le=2000), user = Depends(get_current_user)):
    base_path = get_authorized_backup_path(backup_id, user, min_role="server_admin")
    if not isinstance(lines, int) or lines < 1:
        lines = 100
    lines = min(lines, 2000)
    log_file = safe_join_within(base_path, "log.txt").as_posix()
    t.flush_logs(log_file)
    if not Path(log_file).exists():
        return {"lines": []}
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            last_lines = list(deque(f, lines))
        return {"lines": [line.strip() for line in last_lines]}
    except Exception as e:
        raise _internal_error(f"get_backup_logs({backup_id})", e, backup_id=backup_id)


@app.get("/api/backups/{backup_id}/logs/raw")
def get_raw_log(backup_id: str, user = Depends(get_current_user)):
    base_path = get_authorized_backup_path(backup_id, user, min_role="server_admin")
    log_file = safe_join_within(base_path, "log.txt").as_posix()
    t.flush_logs(log_file)
    if not Path(log_file).exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    return FileResponse(log_file, media_type="text/plain")


@app.delete("/api/backups/{backup_id}/logs")
def clear_backup_logs(backup_id: str, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="server_admin")
    log_file = safe_join_within(base_path, "log.txt").as_posix()
    t.close_log_handlers(log_file)
    if Path(log_file).exists():
        with open(log_file, "w", encoding="utf-8"):
            pass
    _audit(
        action="log.backup_delete",
        target_type="log",
        target_id=str(backup_id),
        actor=actor,
        actor_role=role_name,
        backup_id=str(backup_id),
        backup_dir=base_path,
    )
    return {"status": "cleared"}


@app.get("/api/backups/{backup_id}/logs/stream")
def stream_logs(backup_id: str, user = Depends(get_current_user)):
    base_path, actor, _, _, _ = resolve_authorized_backup(backup_id, user, min_role="server_admin")
    log_file = safe_join_within(base_path, "log.txt").as_posix()
    user_key = str(actor.get("sub") or actor.get("id") or "anonymous")

    with _SSE_ACTIVE_STREAMS_LOCK:
        active_count = _SSE_ACTIVE_STREAMS.get(user_key, 0)
        if active_count >= SSE_MAX_CONCURRENT_STREAMS_PER_USER:
            raise HTTPException(status_code=429, detail="Too many concurrent log streams")
        _SSE_ACTIVE_STREAMS[user_key] = active_count + 1

    def log_generator():
        started_at = time.monotonic()
        try:
            t.flush_logs(log_file)
            # Wait for the file to be created if it doesn't exist yet
            for _ in range(20):
                if time.monotonic() - started_at >= SSE_MAX_DURATION_SECONDS:
                    yield "event: end\ndata: [Stream duration limit reached]\n\n"
                    return
                t.flush_logs(log_file)
                if Path(log_file).exists():
                    break
                time.sleep(0.5)

            if not Path(log_file).exists():
                yield "data: [Log file not found]\n\n"
                return

            with open(log_file, mode='r', encoding='utf-8') as f:
                # Yield the last 10 lines instantly to avoid UI fast-forwarding
                last_lines = deque(f, 10)
                for line in last_lines:
                    yield f"data: {line.strip()}\n\n"

                while True:
                    if time.monotonic() - started_at >= SSE_MAX_DURATION_SECONDS:
                        yield "event: end\ndata: [Stream duration limit reached]\n\n"
                        break
                    t.flush_logs(log_file)
                    line = f.readline()
                    if not line:
                        time.sleep(0.1)
                    else:
                        yield f"data: {line.strip()}\n\n"
        finally:
            with _SSE_ACTIVE_STREAMS_LOCK:
                remaining = _SSE_ACTIVE_STREAMS.get(user_key, 1) - 1
                if remaining <= 0:
                    _SSE_ACTIVE_STREAMS.pop(user_key, None)
                else:
                    _SSE_ACTIVE_STREAMS[user_key] = remaining

    return StreamingResponse(log_generator(), media_type="text/event-stream")


@app.get("/api/logs/global")
def get_global_logs(lines: int = Query(100, ge=1, le=2000), user = Depends(require_instance_admin)):
    _ensure_instance_admin(user)
    if not isinstance(lines, int) or lines < 1:
        lines = 100
    lines = min(lines, 2000)
    global_log_file = (Path(get_data_root()) / "out" / "log.txt").as_posix()
    t.flush_logs(global_log_file)
    if not Path(global_log_file).exists():
        return {"logs": []}

    try:
        with open(global_log_file, "r", encoding="utf-8") as f:
            last_lines = list(deque(f, lines))
        return {"logs": [line.strip() for line in last_lines]}
    except Exception as e:
        raise _internal_error("get_global_logs", e)


@app.delete("/api/logs/global")
def clear_global_logs(user = Depends(require_instance_admin)):
    actor = _ensure_instance_admin(user)
    log_path = (Path(get_data_root()) / "out" / "log.txt").as_posix()
    t.close_log_handlers(log_path)
    if Path(log_path).exists():
        open(log_path, "w").close()
    _audit(
        action="log.global_delete",
        target_type="log",
        target_id="global",
        actor=actor,
        actor_role="instance_admin",
        write_global=True,
    )
    return {"status": "cleared"}


# --- ADMIN TESTING & VERIFICATION ENDPOINTS ---

TEST_BACKUP_ID = "1791895360"


def _release_db_locks():
    """Releases SQLite WAL engine locks and clears SceneManager cache in the server process."""
    try:
        from db.session import close_all_engines
        from models import SceneManager
        SceneManager.clear_cache()
        close_all_engines()
    except Exception:
        pass


@app.post("/api/admin/test-backup/reset")
def reset_testing_backup(user = Depends(require_instance_admin)):
    actor = _ensure_instance_admin(user)
    t.global_log("info", "API: Resetting testing backup (Elysium-sql-tests)...")
    _release_db_locks()
    try:
        from tests.reset_test_backup import reset_test_backup
        ok = reset_test_backup()
        _release_db_locks()
        if not ok:
            t.global_log("error", "API: Failed to reset testing backup: pristine seed copy (Backups/Elysium-sql-tests-clean) not found.")
            raise HTTPException(status_code=500, detail="Failed to reset testing backup: pristine seed copy not found.")
        msg = "Successfully restored Backups/Elysium-sql-tests from pristine copy."
        t.global_log("base", f"API: {msg}")
        _audit(
            action="admin.test_backup_reset",
            target_type="admin",
            target_id=TEST_BACKUP_ID,
            actor=actor,
            actor_role="instance_admin",
            write_global=True,
        )
        return {"status": "success", "message": msg}
    except HTTPException:
        raise
    except Exception as e:
        t.global_log("error", f"API: Error resetting testing backup: {e}")
        raise _internal_error("endpoint error", e)


@app.post("/api/admin/test-backup/migrate")
def migrate_testing_backup(user = Depends(require_instance_admin)):
    actor = _ensure_instance_admin(user)
    t.global_log("info", f"API: Migrating testing backup (ID: {TEST_BACKUP_ID}) to SQLite...")
    _release_db_locks()
    try:
        from db.migrate import migrate_single_backup
        from models.backup_context import BackupContext

        index = t.get_backups_index()
        backup = next((b for b in index if str(b.get("backup_id")) == TEST_BACKUP_ID), None)
        if not backup:
            msg = f"Testing backup ID '{TEST_BACKUP_ID}' not found in backups_index.json"
            t.global_log("error", f"API: {msg}")
            raise HTTPException(status_code=404, detail=msg)

        with BackupContext.activate(backup_id=TEST_BACKUP_ID):
            report = migrate_single_backup(backup, dry_run=False, skip_snapshots=False)

        _release_db_locks()
        msg = (
            f"Successfully migrated '{backup['backup_name']}' to SQLite "
            f"({report.get('characters_count', 0)} characters, "
            f"{report.get('scenes_count', 0)} scenes, "
            f"{report.get('writers_count', 0)} writers)."
        )
        t.global_log("base", f"API: {msg}")
        _audit(
            action="admin.test_backup_migrate",
            target_type="admin",
            target_id=TEST_BACKUP_ID,
            actor=actor,
            actor_role="instance_admin",
            write_global=True,
            after=report if isinstance(report, dict) else None,
        )
        return {"status": "success", "message": msg, "report": report}
    except HTTPException:
        raise
    except Exception as e:
        t.global_log("error", f"API: Error migrating testing backup: {e}")
        raise _internal_error("endpoint error", e)


@app.post("/api/backups/{backup_id}/upgrade")
def upgrade_backup_database(backup_id: str, user = Depends(get_current_user)):
    base_path, actor, role_name, _, _ = resolve_authorized_backup(backup_id, user, min_role="server_admin")
    t.global_log("info", f"API: Upgrading database for backup {backup_id}...")
    _release_db_locks()
    try:
        index = t.get_backups_index()
        backup = next((b for b in index if str(b.get("backup_id")) == str(backup_id)), None)
        if not backup:
            backup = {
                "backup_id": backup_id,
                "backup_name": backup_id,
                "path": Path(base_path).name,
            }

        from db.upgrade import upgrade_single_backup
        report = upgrade_single_backup(backup, dry_run=False, reindex_scenes=False)
        _release_db_locks()
        msg = f"Database upgraded successfully for backup {backup_id}."
        t.global_log("base", f"API: {msg}")
        _audit(
            action="backup.upgrade",
            target_type="backup",
            target_id=str(backup_id),
            actor=actor,
            actor_role=role_name,
            backup_id=str(backup_id),
            backup_dir=base_path,
            after=report if isinstance(report, dict) else None,
        )
        return {"status": "success", "message": msg, "report": report}
    except HTTPException:
        _release_db_locks()
        raise
    except Exception as e:
        _release_db_locks()
        t.global_log("error", f"API: Error upgrading database for backup {backup_id}: {e}")
        raise _internal_error("endpoint error", e)


@app.post("/api/admin/upgrade-all")
def upgrade_all_databases(user = Depends(require_instance_admin)):
    actor = _ensure_instance_admin(user)
    t.global_log("info", "API: Upgrading all SQLite databases...")
    _release_db_locks()
    try:
        from db.upgrade import run_all_upgrades
        run_all_upgrades(dry_run=False, reindex_scenes=False)
        _release_db_locks()
        msg = "All databases upgraded successfully."
        t.global_log("base", f"API: {msg}")
        _audit(
            action="admin.upgrade_all",
            target_type="admin",
            target_id="all",
            actor=actor,
            actor_role="instance_admin",
            write_global=True,
        )
        return {"status": "success", "message": msg}
    except HTTPException:
        _release_db_locks()
        raise
    except Exception as e:
        _release_db_locks()
        t.global_log("error", f"API: Error upgrading all databases: {e}")
        raise _internal_error("endpoint error", e)


_TEST_RUN_LOCK = threading.Lock()
_TEST_RUN_SCRUB_ENV_KEYS = ("DISCORD_TOKEN", "DISCORD_CLIENT_SECRET", "JWT_SECRET")


@app.post("/api/admin/tests/run")
def run_python_tests(user = Depends(require_instance_admin)):
    actor = _ensure_instance_admin(user)
    if not _TEST_RUN_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Test suite is already running")

    try:
        t.global_log("info", "API: Running Python test suite (unittest discover tests)...")
        _release_db_locks()

        python_exec = sys.executable
        project_root = get_project_root()
        src_dir = (Path(project_root) / "src").as_posix()
        prod_mode = is_production_env() or (
            os.environ.get("SOCRATES_PRODUCTION_TESTS_ONLY", "").strip().lower() in ("1", "true", "yes")
        )

        env = os.environ.copy()
        for sensitive_key in _TEST_RUN_SCRUB_ENV_KEYS:
            env.pop(sensitive_key, None)
        env.pop("K_SERVICE", None)
        env["SOCRATES_ENV"] = "test"
        env["SOCRATES_TEST_SUITE"] = "1"
        if prod_mode:
            env["SOCRATES_PRODUCTION_TESTS_ONLY"] = "1"

        existing_pythonpath = env.get("PYTHONPATH", "")
        paths = [src_dir, project_root]
        if existing_pythonpath:
            paths.append(existing_pythonpath)
        env["PYTHONPATH"] = os.pathsep.join(paths)

        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from tests.test_env import stage_tmp_test_data_root

        with tempfile.TemporaryDirectory(prefix="socrates_test_data_") as tmp_data_dir:
            stage_tmp_test_data_root(get_data_root(), tmp_data_dir)
            env["SOCRATES_DATA_DIR"] = Path(tmp_data_dir).as_posix()
            env["SOCRATES_GLOBAL_AUDIT_DB_PATH"] = (Path(tmp_data_dir) / "out" / "global_audit.sqlite").as_posix()
            env["SOCRATES_SQLITE_TMP_CACHE"] = "0"
            env["SOCRATES_TEST_DATA_STAGE_DONE"] = "1"
            proc = subprocess.run(
                [python_exec, "-m", "unittest", "discover", "-s", "tests", "-v"],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            _release_db_locks()

        output_parts = []
        if proc.stdout and proc.stdout.strip():
            output_parts.append(proc.stdout.strip())
        if proc.stderr and proc.stderr.strip():
            output_parts.append(proc.stderr.strip())
        combined_output = "\n".join(output_parts)
        cleaned_output = t.clean(combined_output)

        _audit(
            action="admin.tests_run",
            target_type="admin",
            target_id="tests",
            actor=actor,
            actor_role="instance_admin",
            write_global=True,
            metadata={"returncode": proc.returncode},
            status="success" if proc.returncode == 0 else "error",
        )

        if proc.returncode == 0:
            msg = "Python test suite passed (exit code 0)."
            t.global_log("base", f"API: {msg}")
            return {
                "status": "success",
                "returncode": 0,
                "message": msg,
                "output": cleaned_output,
            }
        else:
            msg = f"Python test suite failed (exit code {proc.returncode})."
            t.global_log("error", f"API: {msg}")
            return {
                "status": "failed",
                "returncode": proc.returncode,
                "message": msg,
                "output": cleaned_output,
            }
    except HTTPException:
        raise
    except Exception as e:
        t.global_log("error", f"API: Failed to execute Python test suite: {e}")
        raise _internal_error("endpoint error", e)
    finally:
        _TEST_RUN_LOCK.release()


@app.get("/api/admin/audit-logs")
def get_global_audit_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    actor_user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    from_ts: Optional[str] = Query(None),
    to_ts: Optional[str] = Query(None),
    user = Depends(require_instance_admin),
):
    _ensure_instance_admin(user)
    from db.session import global_audit_db_session
    try:
        with global_audit_db_session(get_data_root()) as session:
            return audit_service.query_audit_logs(
                session,
                page=page,
                per_page=per_page,
                actor_user_id=actor_user_id,
                action=action,
                target_type=target_type,
                status=status,
                from_ts=from_ts,
                to_ts=to_ts,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


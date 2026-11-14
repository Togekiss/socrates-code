import json
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

import utils.tricks as t
from .audit_models import AuditLog, ensure_utc_datetime, format_utc_iso
from .session import (
    audit_db_session,
    global_audit_db_session,
    resolve_backup_audit_db_path,
    resolve_global_audit_db_path,
)

MAX_AUDIT_JSON_BYTES = 16384
MAX_AUDIT_LIST_SAMPLE = 50
PRUNE_INTERVAL_SECONDS = 3600.0
DEFAULT_MAX_AUDIT_ROWS = 100_000

_prune_lock = threading.RLock()
_last_prune_times: Dict[str, float] = {}


def clear_prune_throttle() -> None:
    """Clears the in-memory pruning throttle map (primarily for unit tests)."""
    with _prune_lock:
        _last_prune_times.clear()


def _summarize_large_lists(value: Any) -> Any:
    """Recursively replaces lists longer than MAX_AUDIT_LIST_SAMPLE with a truncated summary."""
    if isinstance(value, list):
        if len(value) > MAX_AUDIT_LIST_SAMPLE:
            return {
                "_truncated": True,
                "count": len(value),
                "sample": [_summarize_large_lists(item) for item in value[:MAX_AUDIT_LIST_SAMPLE]],
            }
        return [_summarize_large_lists(item) for item in value]
    if isinstance(value, tuple):
        return _summarize_large_lists(list(value))
    if isinstance(value, dict):
        return {str(k): _summarize_large_lists(v) for k, v in value.items()}
    return value


def serialize_capped_json(data: Any, max_bytes: int = MAX_AUDIT_JSON_BYTES) -> Optional[str]:
    """Serializes data to UTF-8 JSON capped at max_bytes with _truncated markers when exceeded."""
    if data is None:
        return None

    summarized = _summarize_large_lists(data)
    raw = json.dumps(summarized, ensure_ascii=False, separators=(",", ":"), default=str)
    raw_bytes = raw.encode("utf-8")
    if len(raw_bytes) <= max_bytes:
        return raw

    if max_bytes < 64:
        return json.dumps({"_truncated": True})

    # Binary search the largest UTF-8 prefix for preview that guarantees total JSON bytes <= max_bytes
    low, high = 0, min(len(raw), max_bytes)
    best = json.dumps({"_truncated": True, "original_bytes": len(raw_bytes), "preview": ""})
    while low <= high:
        mid = (low + high) // 2
        candidate_obj = {
            "_truncated": True,
            "original_bytes": len(raw_bytes),
            "preview": raw[:mid],
        }
        candidate = json.dumps(candidate_obj, ensure_ascii=False, separators=(",", ":"))
        if len(candidate.encode("utf-8")) <= max_bytes:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


def normalize_auth_method(raw_method: Optional[str]) -> str:
    val = str(raw_method or "").strip().lower()
    if val in ("discord", "discord_oauth"):
        return "discord_oauth"
    if val == "dev":
        return "dev"
    if val == "cli":
        return "cli"
    return "unauthenticated"


def _extract_request_context(
    request: Any,
    request_ip: Optional[str],
    user_agent: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    resolved_ip = request_ip
    resolved_ua = user_agent
    if request is not None:
        headers = getattr(request, "headers", None)
        if resolved_ip is None:
            xff = headers.get("x-forwarded-for") if headers else None
            if xff:
                resolved_ip = str(xff).split(",")[0].strip()
            else:
                client = getattr(request, "client", None)
                host = getattr(client, "host", None) if client else None
                if host:
                    resolved_ip = str(host).strip()
        if resolved_ua is None and headers is not None:
            ua = headers.get("user-agent")
            if ua:
                resolved_ua = str(ua).strip()
    if resolved_ip is not None:
        resolved_ip = str(resolved_ip)[:64] or None
    if resolved_ua is not None:
        resolved_ua = str(resolved_ua)[:512] or None
    return resolved_ip, resolved_ua


def prune_audit_logs(
    session: Session,
    db_key: Optional[str] = None,
    now_utc: Optional[datetime] = None,
    max_rows: int = DEFAULT_MAX_AUDIT_ROWS,
    force_prune: bool = False,
) -> Dict[str, Any]:
    """Prunes denied (>90d), expired (>365d), and overflow (>max_rows) rows from an audit DB."""
    now_mono = time.monotonic()
    if not force_prune and db_key:
        with _prune_lock:
            last_run = _last_prune_times.get(db_key)
            if last_run is not None and (now_mono - last_run) < PRUNE_INTERVAL_SECONDS:
                return {
                    "skipped": True,
                    "deleted_denied": 0,
                    "deleted_expired": 0,
                    "deleted_overflow": 0,
                }

    ref_now = ensure_utc_datetime(now_utc) if now_utc is not None else datetime.now(timezone.utc)
    denied_cutoff = ref_now - timedelta(days=90)
    expired_cutoff = ref_now - timedelta(days=365)

    deleted_denied = (
        session.query(AuditLog)
        .filter(AuditLog.status == "denied", AuditLog.created_at < denied_cutoff)
        .delete(synchronize_session=False)
    )
    deleted_expired = (
        session.query(AuditLog)
        .filter(AuditLog.created_at < expired_cutoff)
        .delete(synchronize_session=False)
    )

    deleted_overflow = 0
    cap = max(1, int(max_rows))
    total_rows = int(session.query(func.count(AuditLog.id)).scalar() or 0)
    if total_rows > cap:
        excess = total_rows - cap
        overflow_ids = [
            row[0]
            for row in (
                session.query(AuditLog.id)
                .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
                .limit(excess)
                .all()
            )
        ]
        if overflow_ids:
            # Chunk deletes to stay well below SQLite's bind parameter limit
            chunk_size = 500
            for idx in range(0, len(overflow_ids), chunk_size):
                chunk = overflow_ids[idx : idx + chunk_size]
                deleted_overflow += (
                    session.query(AuditLog)
                    .filter(AuditLog.id.in_(chunk))
                    .delete(synchronize_session=False)
                )

    session.flush()
    if db_key:
        with _prune_lock:
            _last_prune_times[db_key] = time.monotonic()

    return {
        "skipped": False,
        "deleted_denied": int(deleted_denied or 0),
        "deleted_expired": int(deleted_expired or 0),
        "deleted_overflow": int(deleted_overflow or 0),
    }


def _write_single_audit_row(
    session: Session,
    *,
    db_key: str,
    created_at: datetime,
    actor_user_id: str,
    actor_username: str,
    actor_role: str,
    auth_method: str,
    backup_id: Optional[str],
    action: str,
    target_type: str,
    target_id: Optional[str],
    before_json: Optional[str],
    after_json: Optional[str],
    metadata_json: Optional[str],
    request_ip: Optional[str],
    user_agent: Optional[str],
    status: str,
    force_prune: bool,
    now_utc: Optional[datetime],
    max_rows: int,
) -> None:
    row = AuditLog(
        created_at=created_at,
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        actor_role=actor_role,
        auth_method=auth_method,
        backup_id=backup_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_json=before_json,
        after_json=after_json,
        metadata_json=metadata_json,
        request_ip=request_ip,
        user_agent=user_agent,
        status=status,
    )
    session.add(row)
    session.flush()
    prune_audit_logs(
        session,
        db_key=db_key,
        now_utc=now_utc,
        max_rows=max_rows,
        force_prune=force_prune,
    )


def record_audit_event(
    *,
    action: str,
    target_type: str,
    target_id: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    actor_role: Optional[str] = None,
    backup_id: Optional[str] = None,
    backup_dir: Optional[str] = None,
    data_root: Optional[str] = None,
    write_global: bool = False,
    before: Any = None,
    after: Any = None,
    metadata: Any = None,
    request: Any = None,
    request_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    status: str = "success",
    created_at: Optional[datetime] = None,
    force_prune: bool = False,
    now_utc: Optional[datetime] = None,
    max_rows: int = DEFAULT_MAX_AUDIT_ROWS,
) -> None:
    """
    Best-effort audit log writer. Never raises so primary API responses and security denials
    are never masked by audit persistence failures.
    """
    try:
        actor_dict = actor if isinstance(actor, dict) else {}
        actor_user_id = str(actor_dict.get("sub") or actor_dict.get("id") or "0")[:64]
        actor_username = str(
            actor_dict.get("username")
            or ("system" if actor_dict.get("auth_method") == "cli" else "anonymous")
        )[:128]
        auth_method = normalize_auth_method(actor_dict.get("auth_method"))
        resolved_role = (actor_role or "").strip().lower()
        if not resolved_role:
            if auth_method == "cli":
                resolved_role = "cli"
            elif auth_method == "unauthenticated":
                resolved_role = "anonymous"
            else:
                resolved_role = "viewer"

        resolved_ip, resolved_ua = _extract_request_context(request, request_ip, user_agent)
        before_json = serialize_capped_json(before)
        after_json = serialize_capped_json(after)
        metadata_json = serialize_capped_json(metadata)
        event_ts = ensure_utc_datetime(created_at) if created_at is not None else datetime.now(timezone.utc)
        target_id_str = str(target_id)[:128] if target_id is not None else None
        backup_id_str = str(backup_id)[:64] if backup_id is not None else None

        if backup_dir:
            db_key = resolve_backup_audit_db_path(backup_dir)
            with audit_db_session(backup_dir) as session:
                _write_single_audit_row(
                    session,
                    db_key=db_key,
                    created_at=event_ts,
                    actor_user_id=actor_user_id,
                    actor_username=actor_username,
                    actor_role=resolved_role,
                    auth_method=auth_method,
                    backup_id=backup_id_str,
                    action=str(action)[:128],
                    target_type=str(target_type)[:64],
                    target_id=target_id_str,
                    before_json=before_json,
                    after_json=after_json,
                    metadata_json=metadata_json,
                    request_ip=resolved_ip,
                    user_agent=resolved_ua,
                    status=str(status)[:16],
                    force_prune=force_prune,
                    now_utc=now_utc,
                    max_rows=max_rows,
                )

        if write_global or not backup_dir:
            resolved_root = data_root or t.get_data_root()
            db_key = resolve_global_audit_db_path(resolved_root)
            with global_audit_db_session(resolved_root) as session:
                _write_single_audit_row(
                    session,
                    db_key=db_key,
                    created_at=event_ts,
                    actor_user_id=actor_user_id,
                    actor_username=actor_username,
                    actor_role=resolved_role,
                    auth_method=auth_method,
                    backup_id=backup_id_str,
                    action=str(action)[:128],
                    target_type=str(target_type)[:64],
                    target_id=target_id_str,
                    before_json=before_json,
                    after_json=after_json,
                    metadata_json=metadata_json,
                    request_ip=resolved_ip,
                    user_agent=resolved_ua,
                    status=str(status)[:16],
                    force_prune=force_prune,
                    now_utc=now_utc,
                    max_rows=max_rows,
                )
    except Exception as e:
        try:
            t.global_log("warning", f"Audit log write failed for action={action}: {e}")
        except Exception:
            pass


def _parse_json_or_raw(raw: Optional[str]) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw


def serialize_audit_log(row: AuditLog) -> Dict[str, Any]:
    created_iso = format_utc_iso(row.created_at)
    return {
        "id": row.id,
        "created_at": created_iso,
        "timestamp": created_iso,
        "actor_user_id": row.actor_user_id,
        "actor_username": row.actor_username,
        "actor_role": row.actor_role,
        "auth_method": row.auth_method,
        "backup_id": row.backup_id,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "before": _parse_json_or_raw(row.before_json),
        "after": _parse_json_or_raw(row.after_json),
        "metadata": _parse_json_or_raw(row.metadata_json),
        "before_json": row.before_json,
        "after_json": row.after_json,
        "metadata_json": row.metadata_json,
        "request_ip": row.request_ip,
        "user_agent": row.user_agent,
        "status": row.status,
    }


def _parse_iso_filter_ts(value: Optional[str | datetime], label: str) -> Optional[datetime]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        return ensure_utc_datetime(value)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as e:
        raise ValueError(f"Invalid {label} ISO-8601 timestamp: {value}") from e
    return ensure_utc_datetime(parsed)


def query_audit_logs(
    session: Session,
    *,
    page: int = 1,
    per_page: int = 50,
    actor_user_id: Optional[str] = None,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    status: Optional[str] = None,
    from_ts: Optional[str | datetime] = None,
    to_ts: Optional[str | datetime] = None,
) -> Dict[str, Any]:
    """Queries paginated, filtered audit logs newest-first with UTC ISO-8601 timestamps."""
    page_num = max(1, int(page))
    limit = max(1, min(200, int(per_page)))

    q = session.query(AuditLog)
    if actor_user_id and str(actor_user_id).strip():
        q = q.filter(AuditLog.actor_user_id == str(actor_user_id).strip())
    if action and str(action).strip():
        q = q.filter(AuditLog.action == str(action).strip())
    if target_type and str(target_type).strip():
        q = q.filter(AuditLog.target_type == str(target_type).strip())
    if status and str(status).strip():
        q = q.filter(AuditLog.status == str(status).strip())

    parsed_from = _parse_iso_filter_ts(from_ts, "from_ts")
    parsed_to = _parse_iso_filter_ts(to_ts, "to_ts")
    if parsed_from is not None:
        q = q.filter(AuditLog.created_at >= parsed_from)
    if parsed_to is not None:
        q = q.filter(AuditLog.created_at <= parsed_to)

    total = int(q.count())
    total_pages = max(1, math.ceil(total / limit)) if total > 0 else 1
    offset = (page_num - 1) * limit
    rows: List[AuditLog] = (
        q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [serialize_audit_log(r) for r in rows],
        "total": total,
        "page": page_num,
        "per_page": limit,
        "total_pages": total_pages,
    }

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base

AuditBase = declarative_base()


def ensure_utc_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalizes a naive or timezone-aware datetime into UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_utc_iso(dt: Optional[datetime]) -> Optional[str]:
    """Formats a datetime as an ISO-8601 UTC string ending in 'Z'."""
    normalized = ensure_utc_datetime(dt)
    if normalized is None:
        return None
    return normalized.isoformat().replace("+00:00", "Z")


class AuditLog(AuditBase):
    """Dedicated audit log record stored in per-backup audit.sqlite or out/global_audit.sqlite."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )
    actor_user_id = Column(String(64), nullable=False, index=True)
    actor_username = Column(String(128), nullable=False)
    actor_role = Column(String(32), nullable=False)
    auth_method = Column(String(32), nullable=False)
    backup_id = Column(String(64), nullable=True, index=True)
    action = Column(String(128), nullable=False, index=True)
    target_type = Column(String(64), nullable=False)
    target_id = Column(String(128), nullable=True)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    request_ip = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    status = Column(String(16), nullable=False, default="success", index=True)

"""
Strict Pydantic v2 validation schemas for global and backup configuration payloads.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.path_safety import (
    SAFE_BACKUP_RELPATH_RE,
    validate_backup_id,
    validate_channel_ids,
    validate_snowflake,
)

_FORBIDDEN_NESTED_KEYS = frozenset(
    {
        "script",
        "args",
        "command",
        "shell",
        "executable",
        "discord_token",
        "client_id",
        "client_secret",
        "redirect_uri",
        "jwt_secret",
    }
)
_NUMERIC_ID_RE = re.compile(r"^\d{1,22}$")
_STEP_NAME_RE = re.compile(r"^[a-z0-9_]{1,40}$")
_VERBOSITY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _assert_no_forbidden_keys(obj: Any) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) in _FORBIDDEN_NESTED_KEYS:
                raise ValueError(f"Forbidden key in configuration: {k}")
            _assert_no_forbidden_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_forbidden_keys(item)


class AdminConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verbosity: Optional[Dict[str, bool]] = None
    eventCategories: Optional[List[str]] = None
    chatroomCategories: Optional[List[str]] = None
    categoriesToKeep: Optional[List[str]] = None
    categoriesToIgnore: Optional[List[str]] = None
    dmCategories: Optional[List[str]] = None
    keepMode: Optional[bool] = None
    serverId: Optional[str] = None
    serverName: Optional[str] = Field(default=None, max_length=200)
    backupName: Optional[str] = Field(default=None, max_length=200)
    path: Optional[str] = Field(default=None, max_length=200)
    storageMode: Optional[Literal["backupless", "full"]] = None

    @field_validator("verbosity")
    @classmethod
    def _validate_verbosity(cls, v: Optional[Dict[str, bool]]) -> Optional[Dict[str, bool]]:
        if v is None:
            return None
        if len(v) > 20:
            raise ValueError("Too many verbosity keys")
        for key in v:
            if not _VERBOSITY_KEY_RE.fullmatch(str(key)):
                raise ValueError(f"Invalid verbosity key: {key}")
        return v

    @field_validator("serverId")
    @classmethod
    def _validate_server_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        return validate_snowflake(v, "serverId")

    @field_validator("path")
    @classmethod
    def _validate_path(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        normalized = v.replace("\\", "/")
        if ".." in normalized or normalized.startswith("/") or ":" in normalized:
            raise ValueError("Backup path must be a relative path under Backups/<slug>")
        if not SAFE_BACKUP_RELPATH_RE.fullmatch(normalized):
            raise ValueError("Backup path must match Backups/[A-Za-z0-9_-]{1,64}")
        return normalized


class UserConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    searchFolder: Optional[str] = Field(default=None, max_length=200)
    character: Optional[str] = Field(default=None, max_length=200)
    includeAllWriters: Optional[bool] = None
    includeAlterEgos: Optional[bool] = None
    includeFamiliars: Optional[bool] = None
    includeNpcs: Optional[bool] = None
    filters: Optional[Dict[str, Any]] = None

    @field_validator("searchFolder")
    @classmethod
    def _validate_search_folder(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if "\x00" in v or ".." in v:
            raise ValueError("Invalid searchFolder")
        return v

    @field_validator("filters")
    @classmethod
    def _validate_filters(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is None:
            return None
        _assert_no_forbidden_keys(v)
        return v


class StepConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: Optional[bool] = None
    channel_ids: Optional[List[str]] = None

    @field_validator("channel_ids")
    @classmethod
    def _validate_channel_ids(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        return validate_channel_ids(v)


class RbacConfigSchema(BaseModel):
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
    )
    @classmethod
    def _validate_id_list(cls, v: List[str]) -> List[str]:
        if len(v) > 200:
            raise ValueError("Too many RBAC entries")
        cleaned: List[str] = []
        for item in v:
            s = str(item).strip()
            if not _NUMERIC_ID_RE.fullmatch(s):
                raise ValueError(f"Invalid Discord ID in RBAC list: {s}")
            cleaned.append(s)
        return cleaned


class _BaseConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: Optional[str] = None
    server_name: Optional[str] = Field(default=None, max_length=200)
    format: Optional[str] = Field(default=None, max_length=50)
    categories: Optional[List[str]] = None
    channels: Optional[List[str]] = None
    threads: Optional[List[str]] = None
    include_archived: Optional[bool] = None
    export_formats: Optional[List[str]] = None
    timezone: Optional[str] = Field(default=None, max_length=100)
    SceneBreakThreshold: Optional[int] = Field(default=None, ge=1, le=100000)
    storageMode: Optional[Literal["backupless", "full"]] = None
    admin: Optional[AdminConfigSchema] = None
    user: Optional[UserConfigSchema] = None
    steps: Optional[Dict[str, StepConfigSchema]] = None

    @field_validator("server_id")
    @classmethod
    def _validate_server_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        return validate_snowflake(v, "server_id")

    @field_validator("steps")
    @classmethod
    def _validate_steps(
        cls, v: Optional[Dict[str, StepConfigSchema]]
    ) -> Optional[Dict[str, StepConfigSchema]]:
        if v is None:
            return None
        for step_key in v:
            if not _STEP_NAME_RE.fullmatch(str(step_key)):
                raise ValueError(f"Invalid step name: {step_key}")
        return v


class BackupConfigSchema(_BaseConfigSchema):
    model_config = ConfigDict(extra="forbid")

    backup_id: Optional[str] = None
    backup_name: Optional[str] = Field(default=None, max_length=200)
    rbac: Optional[RbacConfigSchema] = None

    @field_validator("backup_id")
    @classmethod
    def _validate_backup_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        return validate_backup_id(v)


class GlobalConfigSchema(_BaseConfigSchema):
    model_config = ConfigDict(extra="forbid")

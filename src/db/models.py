from enum import StrEnum
from typing import Optional
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    Boolean,
    Text,
    ForeignKey,
    UniqueConstraint,
    Index,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase, relationship

CURRENT_SCHEMA_VERSION = 3  # See docs/database_design.md for full schema changelog


class Scope(StrEnum):
    BASE = "base"
    UPDATE = "update"


class Step(StrEnum):
    GET_INFO = "get_info"
    CLEAN_INFO = "clean_info"
    DOWNLOAD = "download"
    VERIFY = "verify"
    ASSIGN_IDS = "assign_ids"
    COMPARE = "compare"
    MERGE = "merge"
    FIX_MESSAGES = "fix_messages"
    INDEX_SCENES = "index_scenes"
    UPDATE = "update"



class Status(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class SceneStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    NO_END_TAG = "no_end_tag"


class IssueKind(StrEnum):
    AUTO_SPLIT = "auto_split"
    SOFT_BOUNDARY = "soft_boundary"


class IssueReason(StrEnum):
    SEPARATE_ROSTER = "separate_roster"
    START_TAG_ROSTER_CHANGE = "start_tag_roster_change"
    START_TAG_SAME_ROSTER = "start_tag_same_roster"
    ROSTER_CHANGE = "roster_change"
    MANUAL = "manual"


class IssueResolution(StrEnum):
    SPLIT = "split"
    MERGED = "merged"


def get_default_resolution(kind: str | IssueKind) -> str:
    k = kind.value if isinstance(kind, IssueKind) else str(kind)
    if k == IssueKind.AUTO_SPLIT.value:
        return IssueResolution.SPLIT.value
    if k == IssueKind.SOFT_BOUNDARY.value:
        return IssueResolution.MERGED.value
    return IssueResolution.SPLIT.value


def is_action_performed(kind: str | IssueKind, resolution: Optional[str | IssueResolution] = None) -> bool:
    if not resolution:
        return False
    res_val = resolution.value if isinstance(resolution, IssueResolution) else str(resolution)
    return res_val != get_default_resolution(kind)


class FlaggedKind(StrEnum):
    FAILED_TUPPER = "failed_tupper"
    OOC_BOUNDARY = "ooc_boundary"
    OOC_MESSAGE = "ooc_message"
    MANUAL = "manual"


class FlaggedResolution(StrEnum):
    OVERRIDE = "override"
    IGNORED = "ignored"
    KEPT = "kept"



class VersionType(StrEnum):
    ALTER_EGO = "alter_ego"
    NPC = "npc"
    FAMILIAR = "familiar"


class Origin(StrEnum):
    CANON = "canon"
    OC = "oc"


class Activity(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"



class Base(DeclarativeBase):
    pass


class BackupModel(Base):
    __tablename__ = "backups"

    backup_id = Column(String(64), primary_key=True)
    backup_name = Column(String(128), nullable=False)
    server_id = Column(String(20), index=True, nullable=True)
    server_name = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)

    exports = relationship("ExportModel", back_populates="backup", cascade="all, delete-orphan")
    writers = relationship("WriterModel", back_populates="backup", cascade="all, delete-orphan")
    character_groups = relationship("CharacterGroupModel", back_populates="backup", cascade="all, delete-orphan")
    characters = relationship("CharacterModel", back_populates="backup", cascade="all, delete-orphan")
    scenes = relationship("SceneModel", back_populates="backup", cascade="all, delete-orphan")
    flagged_messages = relationship("FlaggedMessageModel", back_populates="backup", cascade="all, delete-orphan")


class ExportModel(Base):
    __tablename__ = "exports"
    __table_args__ = (
        UniqueConstraint("backup_id", "scope", name="uq_backup_scope"),
    )

    pk = Column(Integer, primary_key=True, autoincrement=True)
    backup_id = Column(String(64), ForeignKey("backups.backup_id", ondelete="CASCADE"), nullable=False, index=True)
    scope = Column(String(16), nullable=False)  # "base" or "update"
    exported_from = Column(DateTime(timezone=True), nullable=True)
    exported_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    backup = relationship("BackupModel", back_populates="exports")
    steps = relationship("BackupStepModel", back_populates="export", cascade="all, delete-orphan")
    channels = relationship("ChannelModel", back_populates="export", cascade="all, delete-orphan")


class BackupStepModel(Base):
    __tablename__ = "backup_steps"
    __table_args__ = (
        UniqueConstraint("export_pk", "step", name="uq_export_step"),
    )

    pk = Column(Integer, primary_key=True, autoincrement=True)
    export_pk = Column(Integer, ForeignKey("exports.pk", ondelete="CASCADE"), nullable=False, index=True)
    step = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)

    export = relationship("ExportModel", back_populates="steps")


class ChannelModel(Base):
    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("export_pk", "discord_id", name="uq_export_channel_discord"),
    )

    pk = Column(Integer, primary_key=True, autoincrement=True)
    export_pk = Column(Integer, ForeignKey("exports.pk", ondelete="CASCADE"), nullable=False, index=True)
    discord_id = Column(String(20), nullable=False)
    type = Column(String(32), nullable=False)  # GuildCategory, GuildTextChat, GuildPublicThread
    parent_pk = Column(Integer, ForeignKey("channels.pk", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(64), nullable=False)
    position = Column(Integer, nullable=False)
    path = Column(String(255), nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    message_count = Column(Integer, nullable=True)

    export = relationship("ExportModel", back_populates="channels")
    parent = relationship("ChannelModel", remote_side=[pk], back_populates="children")
    children = relationship("ChannelModel", back_populates="parent", cascade="all, delete-orphan")


class WriterModel(Base):
    __tablename__ = "writers"
    __table_args__ = (
        UniqueConstraint("backup_id", "discord_user_id", name="uq_backup_writer_discord"),
    )

    pk = Column(Integer, primary_key=True, autoincrement=True)
    backup_id = Column(String(64), ForeignKey("backups.backup_id", ondelete="CASCADE"), nullable=False, index=True)
    display_name = Column(String(64), nullable=False)
    discord_user_id = Column(String(20), nullable=True, index=True)

    backup = relationship("BackupModel", back_populates="writers")
    aliases = relationship("WriterAliasModel", back_populates="writer", cascade="all, delete-orphan")
    characters = relationship("CharacterModel", back_populates="writer")


class WriterAliasModel(Base):
    __tablename__ = "writer_aliases"

    pk = Column(Integer, primary_key=True, autoincrement=True)
    writer_pk = Column(Integer, ForeignKey("writers.pk", ondelete="CASCADE"), nullable=False, index=True)
    alias = Column(String(64), nullable=False, index=True)

    writer = relationship("WriterModel", back_populates="aliases")


class CharacterGroupModel(Base):
    __tablename__ = "character_groups"

    pk = Column(Integer, primary_key=True, autoincrement=True)
    backup_id = Column(String(64), ForeignKey("backups.backup_id", ondelete="CASCADE"), nullable=False, index=True)

    backup = relationship("BackupModel", back_populates="character_groups")
    names = relationship("GroupNameModel", back_populates="group", cascade="all, delete-orphan")
    characters = relationship("CharacterModel", back_populates="group")


class GroupNameModel(Base):
    __tablename__ = "group_names"

    pk = Column(Integer, primary_key=True, autoincrement=True)
    group_pk = Column(Integer, ForeignKey("character_groups.pk", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(64), nullable=False, index=True)
    position = Column(Integer, default=0, nullable=False)

    group = relationship("CharacterGroupModel", back_populates="names")


class CharacterModel(Base):
    __tablename__ = "characters"
    __table_args__ = (
        UniqueConstraint("backup_id", "char_id", name="uq_backup_char_id"),
    )

    pk = Column(Integer, primary_key=True, autoincrement=True)
    backup_id = Column(String(64), ForeignKey("backups.backup_id", ondelete="CASCADE"), nullable=False, index=True)
    char_id = Column(Integer, nullable=False)  # Preserved tupper ID
    writer_pk = Column(Integer, ForeignKey("writers.pk", ondelete="SET NULL"), nullable=True, index=True)
    group_pk = Column(Integer, ForeignKey("character_groups.pk", ondelete="SET NULL"), nullable=True, index=True)
    parent_pk = Column(Integer, ForeignKey("characters.pk", ondelete="CASCADE"), nullable=True, index=True)
    version_type = Column(String(32), nullable=True)  # "alter_ego", "npc", "familiar"
    origin = Column(String(32), nullable=True)        # "canon", "oc"
    activity = Column(String(32), nullable=True)      # "active", "inactive"

    backup = relationship("BackupModel", back_populates="characters")
    writer = relationship("WriterModel", back_populates="characters")
    group = relationship("CharacterGroupModel", back_populates="characters")
    names = relationship("CharacterNameModel", back_populates="character", cascade="all, delete-orphan")
    parent = relationship("CharacterModel", remote_side=[pk], back_populates="children")
    children = relationship("CharacterModel", back_populates="parent", cascade="all, delete-orphan")
    scene_participations = relationship("SceneParticipantModel", back_populates="character", cascade="all, delete-orphan")


class CharacterNameModel(Base):
    __tablename__ = "character_names"

    pk = Column(Integer, primary_key=True, autoincrement=True)
    character_pk = Column(Integer, ForeignKey("characters.pk", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(64), nullable=False, index=True)
    position = Column(Integer, default=0, nullable=False)

    character = relationship("CharacterModel", back_populates="names")


class SceneModel(Base):
    __tablename__ = "scenes"
    __table_args__ = (
        UniqueConstraint("backup_id", "scene_key", name="uq_backup_scene_key"),
        Index("ix_scenes_backup_start", "backup_id", "start_at"),
        Index("ix_scenes_category_start", "category_pk", "start_at"),
    )

    pk = Column(Integer, primary_key=True, autoincrement=True)
    backup_id = Column(String(64), ForeignKey("backups.backup_id", ondelete="CASCADE"), nullable=False, index=True)
    scene_key = Column(String(32), nullable=False)
    channel_pk = Column(Integer, ForeignKey("channels.pk", ondelete="CASCADE"), nullable=False, index=True)
    category_pk = Column(Integer, ForeignKey("channels.pk", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(32), nullable=False, index=True)  # "open", "closed", "no_end_tag"
    start_message_id = Column(String(20), nullable=False)
    end_message_id = Column(String(20), nullable=False)
    start_index = Column(Integer, nullable=False)
    end_index = Column(Integer, nullable=False)
    start_at = Column(DateTime(timezone=True), nullable=False)  # UTC
    end_at = Column(DateTime(timezone=True), nullable=False)    # UTC
    start_author_id = Column(String(20), nullable=False)
    end_author_id = Column(String(20), nullable=False)
    start_excerpt = Column(String(250), nullable=True)
    end_excerpt = Column(String(250), nullable=True)

    backup = relationship("BackupModel", back_populates="scenes")
    channel = relationship("ChannelModel", foreign_keys=[channel_pk])
    category = relationship("ChannelModel", foreign_keys=[category_pk])
    participants = relationship("SceneParticipantModel", back_populates="scene", cascade="all, delete-orphan")
    issues = relationship("SceneIssueModel", foreign_keys="[SceneIssueModel.scene_pk]", back_populates="scene", passive_deletes=True)


class SceneParticipantModel(Base):
    __tablename__ = "scene_participants"

    scene_pk = Column(Integer, ForeignKey("scenes.pk", ondelete="CASCADE"), primary_key=True)
    character_pk = Column(Integer, ForeignKey("characters.pk", ondelete="CASCADE"), primary_key=True, index=True)

    scene = relationship("SceneModel", back_populates="participants")
    character = relationship("CharacterModel", back_populates="scene_participations")


class SceneIssueModel(Base):
    __tablename__ = "scene_issues"

    pk = Column(Integer, primary_key=True, autoincrement=True)
    backup_id = Column(String(64), ForeignKey("backups.backup_id", ondelete="CASCADE"), nullable=False, index=True)
    scene_pk = Column(Integer, ForeignKey("scenes.pk", ondelete="SET NULL"), nullable=True, index=True)
    next_scene_pk = Column(Integer, ForeignKey("scenes.pk", ondelete="SET NULL"), nullable=True, index=True)
    kind = Column(String(32), nullable=False)
    reason = Column(String(32), nullable=False)
    candidate_message_id = Column(String(20), nullable=True, index=True)
    candidate_index = Column(Integer, nullable=True)
    candidate_excerpt = Column(String(250), nullable=True)
    previous_chars = Column(JSON, nullable=True)
    next_chars = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_note = Column(Text, nullable=True)
    resolution = Column(String(32), nullable=True, index=True)

    scene = relationship("SceneModel", foreign_keys=[scene_pk], back_populates="issues")
    next_scene = relationship("SceneModel", foreign_keys=[next_scene_pk])


class FlaggedMessageModel(Base):
    __tablename__ = "flagged_messages"
    __table_args__ = (
        UniqueConstraint("backup_id", "message_id", name="uq_backup_flagged_msg"),
    )

    pk = Column(Integer, primary_key=True, autoincrement=True)
    backup_id = Column(String(64), ForeignKey("backups.backup_id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(String(20), nullable=False)
    channel_pk = Column(Integer, ForeignKey("channels.pk", ondelete="SET NULL"), nullable=True, index=True)
    kind = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    author = Column(JSON, nullable=False)
    flagged_at = Column(DateTime(timezone=True), nullable=False)
    resolution = Column(String(32), nullable=True, index=True)
    override_content = Column(Text, nullable=True)
    override_author = Column(JSON, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_note = Column(Text, nullable=True)

    backup = relationship("BackupModel", back_populates="flagged_messages")
    channel = relationship("ChannelModel")


class SchemaVersionModel(Base):
    __tablename__ = "schema_version"

    version = Column(Integer, primary_key=True)
    applied_at = Column(DateTime(timezone=True), nullable=False)
    description = Column(String(255), nullable=True)

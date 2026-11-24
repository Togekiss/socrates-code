import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure src and project root are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
for p in (SRC_DIR.as_posix(), PROJECT_ROOT.as_posix()):
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from tests.test_env import skip_in_production_or_missing_fixture, skip_in_production_or_missing_live_backups

# pyrefly: ignore [missing-import]
from db.models import (
    Base,
    BackupModel,
    BackupCategoryConfigModel,
    BackupRbacEntryModel,
    CategoryConfigKind,
    RbacTargetType,
    RbacAccessLevel,
    ChannelModel,
    WriterModel,
    WriterAliasModel,
    CharacterGroupModel,
    GroupNameModel,
    CharacterModel,
    CharacterNameModel,
    EventModel,
    SceneModel,
    SceneParticipantModel,
    SceneIssueModel,
    SeenDiscordUserModel,
    FlaggedResolution,
    FlaggedMessageModel,
    SchemaVersionModel,
    CURRENT_SCHEMA_VERSION,
    Scope,
    Step,
    Status,
    SyncStatus,
    StorageMode,
    SceneStatus,
    SceneKind,
    IssueKind,
    IssueReason,
    FlaggedKind,
    VersionType,
    Origin,
    Activity,
)
from db.skeleton_models import (
    SkeletonBase,
    SkeletonFlags,
    MessageSkeletonModel,
    SkeletonSchemaVersionModel,
    CURRENT_SKELETON_SCHEMA_VERSION,
    compute_skeleton_flags,
)

# pyrefly: ignore [missing-import]
from db.session import init_db, get_db_schema_version, has_db, require_db, close_all_engines
# pyrefly: ignore [missing-import]
from db import status_service, character_service, config_service
# pyrefly: ignore [missing-import]
from db.test_backup_service import seed_test_backup
# pyrefly: ignore [missing-import]
from db.upgrade import extract_database_data, populate_schema
# pyrefly: ignore [missing-import]
from utils import exceptions as exc
# pyrefly: ignore [missing-import]
import utils.tricks as t


class TestDatabaseSchemaAndModels(unittest.TestCase):
    """Tests the SQLAlchemy schema creation and core ORM model operations in SQLite."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        init_db(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_sqlite_schema_creation_all_tables_present(self):
        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        expected_tables = {
            "backups",
            "backup_category_configs",
            "backup_rbac_entries",
            "channels",
            "writers",
            "writer_aliases",
            "character_groups",
            "group_names",
            "characters",
            "character_names",
            "events",
            "scenes",
            "scene_participants",
            "scene_issues",
            "flagged_messages",
            "seen_discord_users",
            "schema_version",
        }
        missing = expected_tables - tables
        self.assertEqual(len(missing), 0, f"Missing expected tables: {missing}")
        self.assertNotIn("exports", tables)
        self.assertNotIn("backup_steps", tables)

    def test_backup_and_character_model_relationships(self):
        with self.Session() as session:
            backup = BackupModel(
                backup_id="test_backup_1",
                backup_name="Test Backup 1",
                server_id="123456789012345678",
                server_name="Test Server",
                storage_mode=StorageMode.BACKUPLESS.value,
                sync_status=SyncStatus.IDLE.value,
            )
            session.add(backup)
            session.flush()

            channel = ChannelModel(
                backup_id=backup.backup_id,
                discord_id="100200300401",
                type="GuildTextChat",
                name="general",
                position=1,
                path="1# Cat/1# general.json",
                sync_status="synced",
                last_message_id="999888777",
            )
            session.add(channel)

            seen_user = SeenDiscordUserModel(
                backup_id=backup.backup_id,
                discord_user_id="111222333444",
                username="test_writer",
                global_name="Test Writer",
                nickname="TW",
                is_current_member=True,
                message_count=42,
            )
            session.add(seen_user)

            writer = WriterModel(
                backup_id=backup.backup_id,
                display_name="TestWriter",
                discord_user_id="111222333444",
            )
            session.add(writer)
            session.flush()

            alias = WriterAliasModel(
                writer_pk=writer.pk,
                alias="TW",
            )
            session.add(alias)

            group = CharacterGroupModel(backup_id=backup.backup_id)
            session.add(group)
            session.flush()

            group_name = GroupNameModel(group_pk=group.pk, name="TestGroup", position=0)
            session.add(group_name)

            char = CharacterModel(
                backup_id=backup.backup_id,
                char_id=1,
                writer_pk=writer.pk,
                group_pk=group.pk,
                origin=Origin.CANON,
                activity=Activity.ACTIVE,
            )
            session.add(char)
            session.flush()

            char_name = CharacterNameModel(
                character_pk=char.pk,
                name="Protagonist",
                position=0,
            )
            session.add(char_name)
            session.commit()

        # Query back and verify in a new session
        with self.Session() as session:
            loaded_backup = session.query(BackupModel).filter_by(backup_id="test_backup_1").first()
            self.assertIsNotNone(loaded_backup)
            self.assertEqual(loaded_backup.storage_mode, "backupless")
            self.assertEqual(loaded_backup.sync_status, "idle")
            self.assertEqual(len(loaded_backup.channels), 1)
            self.assertEqual(loaded_backup.channels[0].last_message_id, "999888777")
            self.assertEqual(len(loaded_backup.seen_users), 1)
            self.assertTrue(loaded_backup.seen_users[0].is_current_member)

            loaded_char = session.query(CharacterModel).filter_by(char_id=1).first()
            self.assertIsNotNone(loaded_char)
            self.assertEqual(loaded_char.names[0].name, "Protagonist")
            self.assertEqual(loaded_char.writer.display_name, "TestWriter")
            self.assertEqual(loaded_char.group.names[0].name, "TestGroup")

            # Verify cascade delete from backups -> channels & seen_users
            session.delete(loaded_backup)
            session.commit()
            self.assertEqual(session.query(ChannelModel).count(), 0)
            self.assertEqual(session.query(SeenDiscordUserModel).count(), 0)

    def test_scenes_and_flagged_messages(self):
        with self.Session() as session:
            backup = BackupModel(
                backup_id="test_backup_scenes",
                backup_name="Test Backup Scenes",
                server_id="100200300400500600",
                server_name="Test RP Server",
            )
            session.add(backup)
            session.flush()

            channel = ChannelModel(
                backup_id=backup.backup_id,
                discord_id="100200300400",
                type="GuildTextChat",
                name="rp-general",
                position=1,
                path="Data/rp-general",
            )
            session.add(channel)
            session.flush()

            import datetime
            now = datetime.datetime.now(datetime.timezone.utc)
            scene = SceneModel(
                backup_id=backup.backup_id,
                scene_key="1-1-1",
                category_pk=channel.pk,
                channel_pk=channel.pk,
                status=SceneStatus.OPEN,
                start_message_id="111",
                end_message_id="222",
                start_index=0,
                end_index=9,
                message_count=10,
                start_at=now,
                end_at=now,
                start_author_id="123",
                end_author_id="456",
            )
            session.add(scene)
            session.flush()

            flagged = FlaggedMessageModel(
                backup_id=backup.backup_id,
                channel_pk=channel.pk,
                message_id="555666777888",
                kind=FlaggedKind.OOC_MESSAGE.value,
                content="Hello from non-tupper bot",
                is_excerpt_truncated=True,
                author={"id": "555", "name": "BadBot"},
                flagged_at=now,
            )
            session.add(flagged)
            session.commit()

            loaded_scene = session.query(SceneModel).filter_by(scene_key="1-1-1").first()
            self.assertIsNotNone(loaded_scene)
            self.assertEqual(loaded_scene.start_message_id, "111")
            self.assertEqual(loaded_scene.message_count, 10)
            self.assertEqual(loaded_scene.channel.name, "rp-general")

            loaded_flag = session.query(FlaggedMessageModel).filter_by(message_id="555666777888").first()
            self.assertIsNotNone(loaded_flag)
            self.assertEqual(loaded_flag.kind, FlaggedKind.OOC_MESSAGE.value)
            self.assertTrue(loaded_flag.is_excerpt_truncated)
            self.assertEqual(loaded_flag.author["name"], "BadBot")

    def test_issue_kind_and_scene_status_enums(self):
        """Verifies that IssueKind and SceneStatus enums only contain active modern members."""
        expected_kinds = {"auto_split", "soft_boundary"}
        actual_kinds = {k.value for k in IssueKind}
        self.assertEqual(actual_kinds, expected_kinds)

        expected_statuses = {"open", "closed", "no_end_tag"}
        actual_statuses = {s.value for s in SceneStatus}
        self.assertEqual(actual_statuses, expected_statuses)

        expected_reasons = {"separate_roster", "start_tag_roster_change", "start_tag_same_roster", "roster_change", "manual", "inactivity_gap", "tupper_end_tag"}
        actual_reasons = {r.value for r in IssueReason}
        self.assertEqual(actual_reasons, expected_reasons)

    def test_schema_version_tracking(self):
        """Verifies that schema_version table correctly tracks CURRENT_SCHEMA_VERSION."""
        self.assertEqual(CURRENT_SCHEMA_VERSION, 7)
        current_ver = get_db_schema_version(self.engine)
        self.assertEqual(current_ver, 7)

        with self.Session() as session:
            record = session.query(SchemaVersionModel).filter_by(version=CURRENT_SCHEMA_VERSION).first()
            self.assertIsNotNone(record)
            self.assertIsNotNone(record.applied_at)

    def test_scene_kind_and_participant_details_schema(self):
        """Verifies SceneKind enum and columns on SceneModel, EventModel, and SceneParticipantModel."""
        expected_kinds = {"scene", "session", "event"}
        actual_kinds = {k.value for k in SceneKind}
        self.assertEqual(actual_kinds, expected_kinds)

        inspector = inspect(self.engine)
        scene_cols = {c["name"]: c for c in inspector.get_columns("scenes")}
        self.assertIn("kind", scene_cols)
        self.assertIn("event_pk", scene_cols)
        self.assertIn("custom_name", scene_cols)
        self.assertIn("message_count", scene_cols)

        event_cols = {c["name"]: c for c in inspector.get_columns("events")}
        for col_name in ("pk", "backup_id", "event_key", "name", "status", "start_at", "end_at", "message_count", "character_movements"):
            self.assertIn(col_name, event_cols)

        part_cols = {c["name"]: c for c in inspector.get_columns("scene_participants")}
        for col_name in ("position", "message_count", "first_message_id", "first_at", "last_message_id", "last_at"):
            self.assertIn(col_name, part_cols)

        flagged_cols = {c["name"]: c for c in inspector.get_columns("flagged_messages")}
        self.assertIn("is_excerpt_truncated", flagged_cols)
        self.assertIn("override_flags", flagged_cols)
        self.assertNotIn("is_deleted", flagged_cols)

    def test_event_model_and_upgrade_roundtrip(self):
        """Verifies EventModel creation, SceneModel.event_pk relationship, and upgrade extraction/population."""
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        with self.Session() as session:
            backup = BackupModel(
                backup_id="test_ev_backup",
                backup_name="Test Event Backup",
                server_id="999",
                server_name="Event Server",
            )
            session.add(backup)
            session.flush()

            channel = ChannelModel(
                backup_id=backup.backup_id,
                discord_id="1008065639467982868",
                type="GuildTextChat",
                name="event-1",
                position=1,
                path="6# Events/1# event-1.json",
            )
            session.add(channel)
            session.flush()

            ev = EventModel(
                backup_id=backup.backup_id,
                event_key="ev-1",
                name="Summer Beach Festival",
                status="closed",
                start_at=now,
                end_at=now,
                message_count=42,
                character_movements={"1": [{"channel_id": "10", "channel_name": "event-1", "first_message_id": "100"}]},
            )
            session.add(ev)
            session.flush()

            scene = SceneModel(
                backup_id=backup.backup_id,
                scene_key="6-1-ev1",
                channel_pk=channel.pk,
                category_pk=channel.pk,
                kind=SceneKind.EVENT.value,
                event_pk=ev.pk,
                custom_name="beach-shore",
                status="closed",
                start_message_id="100",
                end_message_id="141",
                start_index=0,
                end_index=41,
                start_at=now,
                end_at=now,
                start_author_id="1",
                end_author_id="1",
            )
            session.add(scene)
            session.commit()

        # Extract and re-populate into a fresh engine to verify upgrade preservation
        data = extract_database_data(self.engine)
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(data["events"][0]["name"], "Summer Beach Festival")

        fresh_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(fresh_engine)
        counts = populate_schema(fresh_engine, data)
        self.assertEqual(counts["events"], 1)
        self.assertEqual(counts["scenes"], 1)

        FreshSession = sessionmaker(bind=fresh_engine)
        with FreshSession() as s2:
            loaded_ev = s2.query(EventModel).filter_by(event_key="ev-1").first()
            self.assertIsNotNone(loaded_ev)
            self.assertEqual(loaded_ev.name, "Summer Beach Festival")
            self.assertEqual(len(loaded_ev.scenes), 1)
            self.assertEqual(loaded_ev.scenes[0].custom_name, "beach-shore")
        fresh_engine.dispose()

    def test_schema_version_mismatch_raises_error(self):
        """Verifies that init_db raises DatabaseSchemaMismatchError when DB version < CURRENT_SCHEMA_VERSION."""
        with self.Session() as session:
            session.query(SchemaVersionModel).delete()
            session.commit()

        self.assertEqual(get_db_schema_version(self.engine), 0)

        with self.assertRaises(exc.DatabaseSchemaMismatchError) as ctx:
            init_db(self.engine, check_version=True)
        self.assertIn("older than required version", str(ctx.exception))

    def test_central_database_url_without_local_sqlite_file(self):
        """Verifies services and db checks work via DATABASE_URL without a local backup.sqlite file."""
        from unittest.mock import patch

        close_all_engines()
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_folder = Path(tmpdir) / "empty_backup_dir"
            backup_folder.mkdir()
            central_db_path = Path(tmpdir) / "central_service.db"
            central_url = f"sqlite:///{central_db_path.as_posix()}"

            with patch.dict(os.environ, {"DATABASE_URL": central_url}):
                close_all_engines()
                try:
                    self.assertTrue(has_db(backup_folder.as_posix()))
                    require_db(backup_folder.as_posix())

                    status_service.init_backup_export(
                        backup_id="central_backup_1",
                        backup_path=backup_folder.as_posix(),
                        backup_name="Central DB Test Backup",
                        server_id="123456",
                        server_name="Central Test Server",
                    )
                    character_service.save_new_characters(
                        backup_id="central_backup_1",
                        base_path=backup_folder.as_posix(),
                        new_characters=[(101, "CentralHero")],
                        write_snapshot=False,
                    )
                    chars = character_service.get_characters(
                        backup_id="central_backup_1",
                        base_path=backup_folder.as_posix(),
                    )
                    self.assertEqual(len(chars), 1)
                    self.assertEqual(chars[0]["names"][0], "CentralHero")
                    self.assertFalse((backup_folder / "backup.sqlite").exists())
                finally:
                    close_all_engines()

    def test_backup_category_config_and_rbac_models_constraints_and_cascade(self):
        """Verifies Schema v7 BackupCategoryConfigModel & BackupRbacEntryModel constraints, columns, and cascade delete."""
        with self.Session() as session:
            backup = BackupModel(
                backup_id="cfg_v7_1",
                backup_name="Config V7 Backup",
                server_id="857848490683269161",
                server_name="Elysium",
                path="Backups/Elysium",
                keep_mode=True,
                log_info=True,
                log_debug=False,
                log_console=True,
                log_file=False,
                debug_files=True,
            )
            session.add(backup)
            session.flush()

            cat_entry = BackupCategoryConfigModel(
                backup_id="cfg_v7_1",
                kind=CategoryConfigKind.KEEP.value,
                category_ref="1019770957172326470",
            )
            rbac_entry = BackupRbacEntryModel(
                backup_id="cfg_v7_1",
                target_type=RbacTargetType.ROLE.value,
                access_level=RbacAccessLevel.ADMIN.value,
                discord_id="100000000000000001",
            )
            session.add_all([cat_entry, rbac_entry])
            session.commit()

        # Verify unique constraint on backup_category_configs
        with self.Session() as session:
            session.add(
                BackupCategoryConfigModel(
                    backup_id="cfg_v7_1",
                    kind=CategoryConfigKind.KEEP.value,
                    category_ref="1019770957172326470",
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()

        # Verify unique constraint on backup_rbac_entries
        with self.Session() as session:
            session.add(
                BackupRbacEntryModel(
                    backup_id="cfg_v7_1",
                    target_type=RbacTargetType.ROLE.value,
                    access_level=RbacAccessLevel.ADMIN.value,
                    discord_id="100000000000000001",
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()

        # Verify ON DELETE CASCADE when parent BackupModel is deleted
        with self.Session() as session:
            session.execute(text("PRAGMA foreign_keys=ON"))
            loaded = session.query(BackupModel).filter_by(backup_id="cfg_v7_1").first()
            self.assertIsNotNone(loaded)
            self.assertTrue(loaded.keep_mode)
            self.assertFalse(loaded.log_debug)
            self.assertTrue(loaded.debug_files)
            self.assertEqual(len(loaded.category_configs), 1)
            self.assertEqual(len(loaded.rbac_entries), 1)
            session.delete(loaded)
            session.commit()

        with self.Session() as session:
            self.assertEqual(session.query(BackupCategoryConfigModel).count(), 0)
            self.assertEqual(session.query(BackupRbacEntryModel).count(), 0)

    def test_config_service_roundtrip_rbac_and_upgrade_category_ids(self):
        """Verifies config_service SQL roundtrip, RBAC persistence, debug snapshot, and category ID promotion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "Backups" / "CfgRoundtrip"
            backup_dir.mkdir(parents=True, exist_ok=True)
            b_id = "cfg_rt_1"
            b_path = backup_dir.as_posix()

            try:
                cfg_payload = {
                    "admin": {
                        "serverName": "Roundtrip Guild",
                        "serverId": "857848490683269161",
                        "storageMode": "full",
                        "backupName": "CfgRoundtrip",
                        "path": "Backups/CfgRoundtrip",
                        "keepMode": True,
                        "categoriesToKeep": ["14# The Twisted Viper Bar", "1019770957172326470", "Group Chats"],
                        "categoriesToIgnore": ["1# Staff Only"],
                        "chatroomCategories": ["Group Chats"],
                        "eventCategories": ["CURRENT EVENT"],
                        "verbosity": {
                            "info": True,
                            "debug": False,
                            "console": True,
                            "log": False,
                            "debugFiles": True,
                        },
                    },
                    "rbac": {
                        "adminRoleIds": ["100000000000000001"],
                        "curatorRoleIds": ["100000000000000002"],
                        "participantRoleIds": [],
                        "restrictedUserIds": ["200000000000000001"],
                        "blockedUserIds": [],
                    },
                }

                saved = config_service.save_backup_config_dict(
                    backup_id=b_id,
                    backup_path=b_path,
                    config_data=cfg_payload,
                    create_db_if_missing=True,
                )
                self.assertEqual(saved["admin"]["serverId"], "857848490683269161")
                self.assertEqual(saved["admin"]["storageMode"], "full")
                self.assertTrue(saved["admin"]["keepMode"])
                self.assertEqual(saved["admin"]["categoriesToKeep"], ["The Twisted Viper Bar", "1019770957172326470", "Group Chats"])
                self.assertEqual(saved["admin"]["categoriesToIgnore"], ["Staff Only"])
                self.assertEqual(saved["admin"]["verbosity"]["debug"], False)
                self.assertEqual(saved["admin"]["verbosity"]["debugFiles"], True)
                self.assertTrue((backup_dir / "Info" / "backup_config.json").is_file())

                loaded = config_service.load_backup_config_dict(backup_id=b_id, backup_path=b_path)
                self.assertEqual(loaded, saved)

                # Updating config without "rbac" key preserves existing RBAC rows
                updated_no_rbac = {
                    "admin": {
                        **saved["admin"],
                        "keepMode": False,
                    }
                }
                config_service.save_backup_config_dict(
                    backup_id=b_id,
                    backup_path=b_path,
                    config_data=updated_no_rbac,
                )
                loaded_rbac = config_service.load_rbac_config_dict(backup_id=b_id, backup_path=b_path)
                self.assertEqual(loaded_rbac["adminRoleIds"], ["100000000000000001"])
                self.assertEqual(loaded_rbac["restrictedUserIds"], ["200000000000000001"])

                # save_rbac_config_dict updates RBAC cleanly
                new_rbac = {
                    "adminRoleIds": ["100000000000000009"],
                    "curatorRoleIds": [],
                    "participantRoleIds": ["100000000000000003"],
                    "restrictedUserIds": [],
                    "blockedUserIds": ["200000000000000099"],
                }
                saved_rbac = config_service.save_rbac_config_dict(
                    backup_id=b_id,
                    backup_path=b_path,
                    rbac_data=new_rbac,
                )
                self.assertEqual(saved_rbac, new_rbac)
                self.assertEqual(config_service.load_rbac_config_dict(backup_id=b_id, backup_path=b_path), new_rbac)

                # upgrade_category_names_to_ids promotes names & collapses duplicates
                from db.session import db_session
                with db_session(backup_id=b_id, backup_path=b_path) as session:
                    upgraded = config_service.upgrade_category_names_to_ids(
                        session,
                        b_id,
                        {
                            "The Twisted Viper Bar": "1019770957172326470",
                            "7# Group Chats": "1106268351220678767",
                        },
                    )
                    self.assertEqual(upgraded, 3)  # collapsed "The Twisted Viper Bar" keep + updated Group Chats keep & chatroom

                after_upgrade = config_service.load_backup_config_dict(backup_id=b_id, backup_path=b_path)
                self.assertEqual(after_upgrade["admin"]["categoriesToKeep"], ["1019770957172326470", "1106268351220678767"])
                self.assertEqual(after_upgrade["admin"]["chatroomCategories"], ["1106268351220678767"])
                self.assertEqual(after_upgrade["admin"]["categoriesToIgnore"], ["Staff Only"])
                self.assertEqual(after_upgrade["admin"]["eventCategories"], ["CURRENT EVENT"])

                # Auto-import fallback when DB exists with empty config/RBAC tables and backup_config.json is on disk
                legacy_dir = Path(tmpdir) / "Backups" / "LegacyJsonAutoImport"
                legacy_dir.mkdir(parents=True, exist_ok=True)
                t.save_json_atomic(
                    {
                        "admin": {
                            "serverName": "AutoImport",
                            "serverId": "857848490683269161",
                            "keepMode": True,
                            "categoriesToKeep": ["14# The Twisted Viper Bar"],
                        },
                        "rbac": {
                            "adminRoleIds": ["100000000000000011"],
                            "curatorRoleIds": [],
                            "participantRoleIds": [],
                            "restrictedUserIds": [],
                            "blockedUserIds": [],
                        },
                    },
                    (legacy_dir / "backup_config.json").as_posix(),
                )
                status_service.init_backup_export(
                    backup_id="legacy_auto_1",
                    backup_path=legacy_dir.as_posix(),
                    backup_name="AutoImport",
                )
                auto_loaded = config_service.load_backup_config_dict(
                    backup_id="legacy_auto_1",
                    backup_path=legacy_dir.as_posix(),
                )
                self.assertTrue(auto_loaded["admin"]["keepMode"])
                self.assertEqual(auto_loaded["admin"]["categoriesToKeep"], ["The Twisted Viper Bar"])
                self.assertEqual(auto_loaded["rbac"]["adminRoleIds"], ["100000000000000011"])
            finally:
                close_all_engines()




    def test_config_service_central_database_url_empty_init_and_roundtrip(self):
        """Verifies config_service initializes an empty central DB (DATABASE_URL) when create_db_if_missing=True."""
        from unittest.mock import patch

        close_all_engines()
        with tempfile.TemporaryDirectory() as tmpdir:
            central_db_path = Path(tmpdir) / "central_cfg.db"
            central_url = f"sqlite:///{central_db_path.as_posix()}"

            with patch.dict(os.environ, {"DATABASE_URL": central_url}):
                close_all_engines()
                try:
                    saved = config_service.save_backup_config_dict(
                        backup_id="central_cfg_1",
                        backup_path=None,
                        config_data={
                            "admin": {
                                "serverName": "Central Guild",
                                "serverId": "857848490683269161",
                                "storageMode": "backupless",
                                "backupName": "CentralCfg",
                                "path": "Backups/CentralCfg",
                                "keepMode": True,
                                "categoriesToKeep": ["1019770957172326470"],
                                "verbosity": {
                                    "info": True,
                                    "debug": True,
                                    "console": False,
                                    "log": True,
                                    "debugFiles": False,
                                },
                            },
                            "rbac": {
                                "adminRoleIds": ["100000000000000001"],
                                "curatorRoleIds": [],
                                "participantRoleIds": [],
                                "restrictedUserIds": [],
                                "blockedUserIds": [],
                            },
                        },
                        create_db_if_missing=True,
                    )
                    self.assertEqual(saved["admin"]["backupName"], "CentralCfg")
                    self.assertEqual(saved["admin"]["categoriesToKeep"], ["1019770957172326470"])
                    self.assertEqual(saved["rbac"]["adminRoleIds"], ["100000000000000001"])

                    loaded = config_service.load_backup_config_dict(backup_id="central_cfg_1", backup_path=None)
                    self.assertEqual(loaded, saved)

                    loaded_rbac = config_service.load_rbac_config_dict(backup_id="central_cfg_1", backup_path=None)
                    self.assertEqual(loaded_rbac["adminRoleIds"], ["100000000000000001"])
                finally:
                    close_all_engines()

    @skip_in_production_or_missing_fixture()
    def test_seed_test_backup_populates_v7_config_and_category_ids(self):
        """Verifies seed_test_backup() populates BackupModel v7 columns and resolves category names to IDs."""
        data_root = Path(os.environ.get("SOCRATES_DATA_DIR") or PROJECT_ROOT.as_posix())
        clean_dir = data_root / "Backups" / "Elysium-sql-tests-clean"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_backup = Path(tmpdir) / "Elysium-v7-seed"
            shutil.copytree(clean_dir, tmp_backup)
            try:
                seed_test_backup(
                    backup_id="seed_v7_test",
                    backup_path=tmp_backup.as_posix(),
                    backup={
                        "backup_id": "seed_v7_test",
                        "backup_name": "Elysium-sql-tests",
                        "server_id": "857848490683269161",
                        "server_name": "(+18) Diabolik: Elysium",
                        "path": "Backups/Elysium-sql-tests",
                    },
                    include_scenes=False,
                    include_skeletons=False,
                )
                loaded = config_service.load_backup_config_dict(
                    backup_id="seed_v7_test",
                    backup_path=tmp_backup.as_posix(),
                )
                self.assertTrue(loaded["admin"]["keepMode"])
                self.assertEqual(loaded["admin"]["path"], "Backups/Elysium-sql-tests")
                self.assertIn("1019770957172326470", loaded["admin"]["categoriesToKeep"])
                self.assertIn("1106268351220678767", loaded["admin"]["categoriesToKeep"])
                self.assertIn("1106268351220678767", loaded["admin"]["chatroomCategories"])
                self.assertFalse(loaded["admin"]["verbosity"]["debugFiles"])
            finally:
                close_all_engines()


class TestAutoDiscoveryBackupContextAndRbacSql(unittest.TestCase):
    """Step 3 tests: SQLite/Postgres auto-discovery registry, BackupContext SQL loading, and RBAC SQL integration."""

    def tearDown(self):
        close_all_engines()
        t.invalidate_backups_index_cache()

    def test_get_backups_index_auto_discovery_caching_and_exclusions(self):
        from unittest.mock import patch
        from db.session import db_session

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                root = Path(tmpdir)
                backups_dir = root / "Backups"
                (backups_dir / "Elysium-sql-tests-clean").mkdir(parents=True)
                (backups_dir / "Elysium-sql-tests-clean" / "backup_config.json").write_text("{}", encoding="utf-8")

                # Nested subfolder backup.sqlite must NOT be discovered
                nested_dir = backups_dir / "archived" / "OldBackup"
                nested_dir.mkdir(parents=True)
                init_db(backup_id="nested_1", backup_path=nested_dir.as_posix())
                with db_session(backup_id="nested_1", backup_path=nested_dir.as_posix()) as session:
                    session.add(
                        BackupModel(
                            backup_id="nested_1",
                            backup_name="NestedOld",
                            server_id="999000111222333444",
                            server_name="Old Guild",
                            path="Backups/archived/OldBackup",
                        )
                    )

                # Pre-v7 SQLite DB (without path column) in direct child directory must be discovered gracefully
                legacy_dir = backups_dir / "LegacyV6"
                legacy_dir.mkdir(parents=True)
                conn = sqlite3.connect((legacy_dir / "backup.sqlite").as_posix())
                try:
                    conn.execute(
                        "CREATE TABLE backups (backup_id VARCHAR(64) PRIMARY KEY, backup_name VARCHAR(128) NOT NULL, server_id VARCHAR(20), server_name VARCHAR(128))"
                    )
                    conn.execute(
                        "INSERT INTO backups (backup_id, backup_name, server_id, server_name) VALUES (?, ?, ?, ?)",
                        ("legacy_6", "Legacy V6", "111222333444555666", "Legacy Guild"),
                    )
                    conn.commit()
                finally:
                    conn.close()

                with patch.dict(os.environ, {"SOCRATES_DATA_DIR": root.as_posix()}, clear=False):
                    t.invalidate_backups_index_cache()

                    # add_backup_to_index creates v7 backup.sqlite without writing backups_index.json
                    created_id = t.add_backup_to_index(
                        backup_name="Alpha Backup",
                        server_id="222333444555666777",
                        server_name="Alpha Guild",
                        path="Backups/AlphaBackup",
                        backup_id="alpha_7",
                    )
                    self.assertEqual(created_id, "alpha_7")
                    self.assertFalse((backups_dir / "backups_index.json").exists())

                    index = t.get_backups_index()
                    ids = {b["backup_id"] for b in index}
                    self.assertEqual(ids, {"alpha_7", "legacy_6"})

                    alpha_entry = next(b for b in index if b["backup_id"] == "alpha_7")
                    self.assertEqual(alpha_entry["path"], "Backups/AlphaBackup")
                    self.assertEqual(alpha_entry["server_id"], "222333444555666777")

                    legacy_entry = next(b for b in index if b["backup_id"] == "legacy_6")
                    self.assertEqual(legacy_entry["path"], "Backups/LegacyV6")

                    # Second call uses in-memory cache (does not re-open SQLite)
                    with patch("utils.tricks._read_backup_index_entry_from_sqlite") as mock_read:
                        cached = t.get_backups_index()
                        self.assertEqual(len(cached), 2)
                        mock_read.assert_not_called()

                    # Explicit invalidation forces re-read
                    t.invalidate_backups_index_cache()
                    with patch("utils.tricks._read_backup_index_entry_from_sqlite", wraps=t._read_backup_index_entry_from_sqlite) as mock_read_again:
                        refreshed = t.get_backups_index()
                        self.assertEqual(len(refreshed), 2)
                        self.assertEqual(mock_read_again.call_count, 2)

                    # Resetting Elysium-sql-tests (folder exists without backup.sqlite) keeps ID 1791895360 resolvable
                    test_dir = backups_dir / "Elysium-sql-tests"
                    (test_dir / "Info").mkdir(parents=True)
                    t.invalidate_backups_index_cache()
                    with_fixture = t.get_backups_index()
                    self.assertIn("1791895360", {b["backup_id"] for b in with_fixture})
                    self.assertTrue(t.get_backup_path("1791895360").endswith("Backups/Elysium-sql-tests"))
            finally:
                close_all_engines()

    def test_get_backups_index_central_database_url_and_legacy_json_fallback(self):
        import json
        from unittest.mock import patch
        from db.session import db_session

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backups_dir = root / "Backups"
            backups_dir.mkdir(parents=True)

            # 1. Legacy JSON fallback when zero backup.sqlite files exist
            (backups_dir / "backups_index.json").write_text(
                json.dumps([
                    {
                        "backup_id": "json_only_1",
                        "backup_name": "JsonOnly",
                        "server_id": "333444555666777888",
                        "server_name": "JSON Guild",
                        "path": "Backups/JsonOnly",
                    }
                ]),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"SOCRATES_DATA_DIR": root.as_posix()}, clear=False):
                t.invalidate_backups_index_cache()
                fallback_idx = t.get_backups_index()
                self.assertEqual([b["backup_id"] for b in fallback_idx], ["json_only_1"])

            # 2. Central DATABASE_URL mode queries BackupModel directly
            central_db = root / "central.sqlite"
            with patch.dict(
                os.environ,
                {
                    "SOCRATES_DATA_DIR": root.as_posix(),
                    "DATABASE_URL": f"sqlite:///{central_db.as_posix()}",
                },
                clear=False,
            ):
                close_all_engines()
                t.invalidate_backups_index_cache()
                try:
                    self.assertEqual(t.get_backups_index(), [])
                    init_db(backup_id="pg_1")
                    with db_session(backup_id="pg_1") as session:
                        session.add(
                            BackupModel(
                                backup_id="pg_1",
                                backup_name="Postgres Backup",
                                server_id="444555666777888999",
                                server_name="Postgres Guild",
                                path="Backups/PostgresBackup",
                            )
                        )
                    pg_idx = t.get_backups_index()
                    self.assertEqual(len(pg_idx), 1)
                    self.assertEqual(pg_idx[0]["backup_id"], "pg_1")
                    self.assertEqual(pg_idx[0]["backup_name"], "Postgres Backup")
                    self.assertEqual(pg_idx[0]["path"], "Backups/PostgresBackup")
                finally:
                    close_all_engines()

    def test_backup_context_loads_from_sqlite_without_backup_config_json(self):
        import json
        from unittest.mock import patch
        from models.backup_context import BackupContext

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                root = Path(tmpdir)
                b_dir = root / "Backups" / "SqlOnlyBackup"
                b_dir.mkdir(parents=True)
                b_id = "ctx_sql_7"

                config_service.save_backup_config_dict(
                    backup_id=b_id,
                    backup_path=b_dir.as_posix(),
                    create_db_if_missing=True,
                    config_data={
                        "admin": {
                            "serverName": "SQL Guild",
                            "serverId": "555666777888999000",
                            "storageMode": "full",
                            "backupName": "SqlOnlyBackup",
                            "path": "Backups/SqlOnlyBackup",
                            "keepMode": True,
                            "categoriesToKeep": ["1019770957172326470"],
                            "categoriesToIgnore": ["1019770957172326471"],
                            "chatroomCategories": ["1106268351220678767"],
                            "eventCategories": ["1106268351220678768"],
                            "verbosity": {
                                "info": False,
                                "debug": True,
                                "console": False,
                                "log": True,
                                "debugFiles": False,
                            },
                        },
                        "rbac": {
                            "adminRoleIds": ["900000000000000001"],
                            "curatorRoleIds": [],
                            "participantRoleIds": [],
                            "restrictedUserIds": [],
                            "blockedUserIds": [],
                        },
                    },
                )
                self.assertFalse((b_dir / "backup_config.json").exists())

                with patch.dict(os.environ, {"SOCRATES_DATA_DIR": root.as_posix()}, clear=False):
                    t.invalidate_backups_index_cache()
                    ctx = BackupContext.create(backup_id=b_id)
                    self.assertEqual(ctx.backup_id, b_id)
                    self.assertEqual(ctx.server_id, "555666777888999000")
                    self.assertEqual(ctx.server_name, "SQL Guild")
                    self.assertEqual(ctx.backup_name, "SqlOnlyBackup")
                    self.assertTrue(ctx.keep_mode)
                    self.assertEqual(ctx.categories_to_keep, {"1019770957172326470"})
                    self.assertEqual(ctx.categories_to_ignore, {"1019770957172326471"})
                    self.assertEqual(ctx.chatroom_categories, ["1106268351220678767"])
                    self.assertEqual(ctx.event_categories, ["1106268351220678768"])
                    self.assertFalse(ctx.info)
                    self.assertTrue(ctx.debug)
                    self.assertFalse(ctx.console)
                    self.assertTrue(ctx.log)
                    self.assertFalse(ctx.debug_files)
                    self.assertFalse(ctx.dry_run)
                    self.assertEqual(ctx.dm_categories, [])

                    # Explicit config_path overrides SQL loading
                    custom_cfg = root / "custom.json"
                    custom_cfg.write_text(
                        json.dumps({"admin": {"serverName": "Custom Override", "verbosity": {"dryRun": True}}}),
                        encoding="utf-8",
                    )
                    ctx_override = BackupContext.create(
                        backup_id=b_id,
                        backup_path=b_dir.as_posix(),
                        config_path=custom_cfg.as_posix(),
                    )
                    self.assertEqual(ctx_override.server_name, "Custom Override")
                    self.assertTrue(ctx_override.dry_run)
            finally:
                close_all_engines()

    def test_rbac_sql_persistence_and_per_user_role_grants(self):
        from unittest.mock import patch
        from fastapi import HTTPException
        import rbac
        from db.session import db_session

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            b_dir = root / "Backups" / "RbacSqlTest"
            b_dir.mkdir(parents=True)
            b_id = "rbac_sql_1"
            guild_id = "666777888999000111"

            rbac.clear_rbac_caches()
            try:
                init_db(backup_id=b_id, backup_path=b_dir.as_posix())
                with db_session(backup_id=b_id, backup_path=b_dir.as_posix()) as session:
                    session.add(
                        BackupModel(
                            backup_id=b_id,
                            backup_name="RbacSqlTest",
                            server_id=guild_id,
                            server_name="RBAC SQL Guild",
                            path="Backups/RbacSqlTest",
                        )
                    )

                saved = rbac.save_backup_rbac_config(
                    b_dir.as_posix(),
                    {
                        "adminRoleIds": ["700000000000000001"],
                        "curatorRoleIds": ["700000000000000002"],
                        "participantRoleIds": ["700000000000000003"],
                        "restrictedUserIds": ["800000000000000004"],
                        "blockedUserIds": ["800000000000000005"],
                    },
                    guild_id=guild_id,
                    backup_id=b_id,
                )
                self.assertEqual(saved["adminRoleIds"], ["700000000000000001"])
                self.assertFalse((b_dir / "backup_config.json").exists())

                loaded = rbac.load_backup_rbac_config(b_dir.as_posix(), backup_id=b_id)
                self.assertEqual(
                    set(loaded.keys()),
                    {"adminRoleIds", "curatorRoleIds", "participantRoleIds", "restrictedUserIds", "blockedUserIds"},
                )
                self.assertEqual(loaded["curatorRoleIds"], ["700000000000000002"])

                # Add per-user admin / curator / participant grants directly in BackupRbacEntryModel
                with db_session(backup_id=b_id, backup_path=b_dir.as_posix()) as session:
                    session.add_all([
                        BackupRbacEntryModel(
                            backup_id=b_id,
                            target_type=RbacTargetType.USER.value,
                            access_level=RbacAccessLevel.ADMIN.value,
                            discord_id="800000000000000001",
                        ),
                        BackupRbacEntryModel(
                            backup_id=b_id,
                            target_type=RbacTargetType.USER.value,
                            access_level=RbacAccessLevel.CURATOR.value,
                            discord_id="800000000000000002",
                        ),
                        BackupRbacEntryModel(
                            backup_id=b_id,
                            target_type=RbacTargetType.USER.value,
                            access_level=RbacAccessLevel.PARTICIPANT.value,
                            discord_id="800000000000000003",
                        ),
                        BackupRbacEntryModel(
                            backup_id=b_id,
                            target_type=RbacTargetType.USER.value,
                            access_level=RbacAccessLevel.CURATOR.value,
                            discord_id="800000000000000004",  # also in restrictedUserIds -> capped to viewer
                        ),
                    ])

                # Standard 5-key load still omits extended user role keys for endpoint schema compatibility
                standard_loaded = rbac.load_backup_rbac_config(b_dir.as_posix(), backup_id=b_id)
                self.assertNotIn("adminUserIds", standard_loaded)

                entry = {"backup_id": b_id, "server_id": guild_id}

                def actor_for(uid: str) -> dict:
                    return {
                        "sub": uid,
                        "auth_method": "discord",
                        "authorized_guilds": [{"id": guild_id, "owner": False, "permissions": 0}],
                    }

                with patch.object(rbac, "fetch_guild_member_roles", return_value=set()):
                    def resolve(uid: str):
                        return rbac.resolve_backup_role(
                            backup_id=b_id,
                            entry=entry,
                            base_path=b_dir.as_posix(),
                            actor=actor_for(uid),
                            is_instance_admin_fn=lambda _a: False,
                            effective_bot_guilds_fn=lambda _a: {guild_id},
                            extract_user_guild_ids_fn=lambda _a: {guild_id},
                            bot_token="fake",
                            is_production=True,
                            socrates_env="production",
                        )

                    self.assertEqual(resolve("800000000000000001")[0], "server_admin")
                    self.assertEqual(resolve("800000000000000002")[0], "curator")
                    self.assertEqual(resolve("800000000000000003")[0], "participant")
                    self.assertEqual(resolve("800000000000000004")[0], "viewer")
                    self.assertEqual(resolve("800000000000000099")[0], "viewer")
                    with self.assertRaises(HTTPException) as ctx_exc:
                        resolve("800000000000000005")
                    self.assertEqual(ctx_exc.exception.status_code, 403)
            finally:
                rbac.clear_rbac_caches()
                close_all_engines()


class TestAtomicUtilities(unittest.TestCase):
    """Tests atomic file persistence and path resolution helpers."""

    def test_save_json_atomic_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_file = Path(tmpdir) / "test_data.json"
            sample_data = {
                "name": "Socrates",
                "version": 1.0,
                "items": [1, 2, 3],
                "nested": {"status": "ok"},
            }
            t.save_json_atomic(sample_data, target_file)
            self.assertTrue(target_file.exists())

            loaded = t.load_from_json(target_file)
            self.assertEqual(loaded, sample_data)

    @skip_in_production_or_missing_live_backups()
    def test_get_backup_path_resolution(self):
        path_elysium = t.get_backup_path("1")
        self.assertIn("Elysium", path_elysium)
        self.assertTrue(Path(path_elysium).exists())

        path_meu_server = t.get_backup_path("1789899843")
        self.assertIn("el_meu_server", path_meu_server)
        self.assertTrue(Path(path_meu_server).exists())


class TestSqliteWalCheckpointing(unittest.TestCase):
    """Ensures SQLite commits checkpoint WAL back into backup.sqlite so standalone .sqlite files stay up to date."""

    def test_status_update_is_checkpointed_into_standalone_sqlite_file(self):
        from db import status_service
        from db.session import close_all_engines

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backup_wal_test"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_id = "wal_test_1"
            base_path = backup_dir.as_posix()

            try:
                status_service.init_backup_export(
                    backup_id=backup_id,
                    backup_path=base_path,
                    backup_name="WAL Test",
                )
                # Step 1: mark index_scenes running
                status_service.update_step_status(backup_id, base_path, "index_scenes", "running", write_snapshot=False)
                # Simulate an active read from the pooled engine (uvicorn polling)
                state_running = status_service.load_backup_state(backup_id, base_path)
                self.assertEqual(state_running["steps"]["index_scenes"], "running")

                # Step 2: update step to success WITHOUT calling close_all_engines() first
                status_service.update_step_status(backup_id, base_path, "index_scenes", "success", write_snapshot=False)

                # Copy ONLY backup.sqlite (intentionally omitting -wal and -shm) to verify self-contained state
                standalone_copy = Path(tmpdir) / "standalone.sqlite"
                shutil.copy2(backup_dir / "backup.sqlite", standalone_copy)

                conn = sqlite3.connect(standalone_copy.as_posix())
                try:
                    rows = conn.execute(
                        "SELECT sync_status FROM backups WHERE backup_id = ?",
                        (backup_id,),
                    ).fetchall()
                finally:
                    conn.close()

                self.assertEqual(rows, [("idle",)])
            finally:
                close_all_engines()




class TestSqliteTmpCacheAndSync(unittest.TestCase):
    """Tests Option B: local /tmp SQLite caching, dirty tracking, debounced GCS sync, and stale-cache refresh."""

    def test_activation_guard(self):
        from unittest.mock import patch
        from db.session import is_sqlite_tmp_cache_enabled

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOCRATES_SQLITE_TMP_CACHE", None)
            os.environ.pop("SOCRATES_DATA_DIR", None)
            os.environ.pop("DATABASE_URL", None)
            self.assertFalse(is_sqlite_tmp_cache_enabled())

        with patch.dict(os.environ, {"SOCRATES_DATA_DIR": "/mnt/socrates-data"}, clear=False):
            os.environ.pop("SOCRATES_SQLITE_TMP_CACHE", None)
            os.environ.pop("DATABASE_URL", None)
            self.assertTrue(is_sqlite_tmp_cache_enabled())

        with patch.dict(os.environ, {"SOCRATES_DATA_DIR": "/mnt/socrates-data", "SOCRATES_SQLITE_TMP_CACHE": "0"}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            self.assertFalse(is_sqlite_tmp_cache_enabled())

        with patch.dict(os.environ, {"SOCRATES_SQLITE_TMP_CACHE": "1", "DATABASE_URL": "postgresql://localhost/db"}, clear=False):
            self.assertFalse(is_sqlite_tmp_cache_enabled())

    def test_copy_on_load_debounced_sync_and_stale_refresh(self):
        from unittest.mock import patch
        from db import status_service
        from db.session import (
            close_all_engines,
            get_engine,
            get_tmp_sqlite_path,
            invalidate_sqlite_tmp_cache,
            sync_dirty_sqlite_dbs,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backup_gcs"
            tmp_cache_root = Path(tmpdir) / "tmp_cache"
            backup_dir.mkdir(parents=True, exist_ok=True)
            tmp_cache_root.mkdir(parents=True, exist_ok=True)

            backup_id = "tmp_sync_test_1"
            base_path = backup_dir.as_posix()
            source_sqlite = os.path.abspath((backup_dir / "backup.sqlite").as_posix()).replace("\\", "/")

            # 1. Local dev mode (disabled): opens source_sqlite directly, no /tmp copy created
            env_disabled = {
                "SOCRATES_SQLITE_TMP_CACHE": "0",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
            }
            with patch.dict(os.environ, env_disabled, clear=False):
                close_all_engines()
                status_service.init_backup_export(
                    backup_id=backup_id,
                    backup_path=base_path,
                    backup_name="Tmp Cache Test",
                )
                eng_local = get_engine(backup_id=backup_id, backup_path=base_path)
                self.assertEqual(
                    os.path.abspath(eng_local.url.database).replace("\\", "/"),
                    os.path.abspath(source_sqlite).replace("\\", "/"),
                )
                self.assertFalse(os.path.exists(get_tmp_sqlite_path(source_sqlite)))
                close_all_engines()

            # 2. Cloud/FUSE mode (enabled): copies source_sqlite to /tmp on load
            env_enabled = {
                "SOCRATES_SQLITE_TMP_CACHE": "1",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
                "SOCRATES_SQLITE_SYNC_TIMER": "0",
            }
            with patch.dict(os.environ, env_enabled, clear=False):
                try:
                    invalidate_sqlite_tmp_cache(backup_id=backup_id, backup_path=base_path)
                    eng_tmp = get_engine(backup_id=backup_id, backup_path=base_path)
                    expected_tmp = get_tmp_sqlite_path(source_sqlite)
                    self.assertEqual(
                        os.path.abspath(eng_tmp.url.database).replace("\\", "/"),
                        os.path.abspath(expected_tmp).replace("\\", "/"),
                    )
                    self.assertTrue(os.path.exists(expected_tmp))

                    # 3. Committed write marks dirty; first sync materializes standalone backup.sqlite
                    status_service.update_step_status(
                        backup_id, base_path, "index_scenes", "running", write_snapshot=False
                    )
                    synced = sync_dirty_sqlite_dbs(force=False, min_interval=10.0)
                    self.assertEqual(synced, [source_sqlite])

                    # Verify standalone source_sqlite has "syncing"
                    conn = sqlite3.connect(source_sqlite)
                    try:
                        rows = conn.execute(
                            "SELECT sync_status FROM backups WHERE backup_id = ?",
                            (backup_id,),
                        ).fetchall()
                    finally:
                        conn.close()
                    self.assertEqual(rows, [("syncing",)])

                    # 4. Rapid second write within min_interval is debounced (skipped)
                    status_service.update_step_status(
                        backup_id, base_path, "index_scenes", "success", write_snapshot=False
                    )
                    skipped = sync_dirty_sqlite_dbs(force=False, min_interval=10.0)
                    self.assertEqual(skipped, [])

                    # Target source_sqlite still has "syncing" until forced or interval elapses
                    conn = sqlite3.connect(source_sqlite)
                    try:
                        rows = conn.execute(
                            "SELECT sync_status FROM backups WHERE backup_id = ?",
                            (backup_id,),
                        ).fetchall()
                    finally:
                        conn.close()
                    self.assertEqual(rows, [("syncing",)])

                    # 5. close_all_engines() forces sync before disposing
                    close_all_engines()
                    conn = sqlite3.connect(source_sqlite)
                    try:
                        rows = conn.execute(
                            "SELECT sync_status FROM backups WHERE backup_id = ?",
                            (backup_id,),
                        ).fetchall()
                    finally:
                        conn.close()
                    self.assertEqual(rows, [("idle",)])

                    # 6. External replacement of source_sqlite is picked up on next open
                    ext_copy = Path(tmpdir) / "external_modified.sqlite"
                    shutil.copy2(source_sqlite, ext_copy)
                    ext_conn = sqlite3.connect(ext_copy.as_posix())
                    try:
                        ext_conn.execute(
                            "UPDATE backups SET sync_status = 'failed' WHERE backup_id = ?",
                            (backup_id,),
                        )
                        ext_conn.commit()
                    finally:
                        ext_conn.close()
                    shutil.copy2(ext_copy, source_sqlite)

                    reloaded = status_service.load_backup_state(backup_id, base_path)
                    self.assertEqual(reloaded["sync_status"], "failed")
                    self.assertEqual(reloaded["steps"]["index_scenes"], "failed")
                finally:
                    close_all_engines()
                    invalidate_sqlite_tmp_cache(backup_id=backup_id, backup_path=base_path)

    def test_brand_new_backup_initialization_and_sync(self):
        from unittest.mock import patch
        from db import status_service
        from db.session import (
            close_all_engines,
            get_tmp_sqlite_path,
            has_db,
            require_db,
            sync_dirty_sqlite_dbs,
            invalidate_sqlite_tmp_cache,
            _stat_file,
            _read_source_meta,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "new_backup_gcs"
            tmp_cache_root = Path(tmpdir) / "tmp_cache"
            backup_dir.mkdir(parents=True, exist_ok=True)
            tmp_cache_root.mkdir(parents=True, exist_ok=True)

            backup_id = "brand_new_backup_1"
            base_path = backup_dir.as_posix()
            source_sqlite = os.path.abspath((backup_dir / "backup.sqlite").as_posix()).replace("\\", "/")

            env = {
                "SOCRATES_SQLITE_TMP_CACHE": "1",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
                "SOCRATES_SQLITE_SYNC_TIMER": "0",
            }
            with patch.dict(os.environ, env, clear=False):
                try:
                    close_all_engines()
                    self.assertFalse(has_db(backup_path=base_path))
                    with self.assertRaises(exc.DatabaseConnectionError):
                        require_db(backup_path=base_path)

                    # Initialize brand new backup in /tmp
                    status_service.init_backup_export(
                        backup_id=backup_id,
                        backup_path=base_path,
                        backup_name="Brand New Backup",
                    )
                    expected_tmp = get_tmp_sqlite_path(source_sqlite)
                    self.assertTrue(os.path.exists(expected_tmp))
                    # Source on GCS should not exist yet before sync
                    self.assertFalse(os.path.exists(source_sqlite))

                    # has_db() and require_db() recognize the /tmp cached DB
                    self.assertTrue(has_db(backup_path=base_path))
                    require_db(backup_path=base_path)

                    # Flush to GCS
                    synced = sync_dirty_sqlite_dbs(force=True)
                    self.assertEqual(synced, [source_sqlite])
                    self.assertTrue(os.path.exists(source_sqlite))

                    # Verify source_sqlite has valid tables and schema
                    conn = sqlite3.connect(source_sqlite)
                    try:
                        backup_rows = conn.execute("SELECT backup_id FROM backups").fetchall()
                    finally:
                        conn.close()
                    self.assertEqual(backup_rows, [(backup_id,)])

                    # Verify .source_meta.json matches source stat
                    source_stat = _stat_file(source_sqlite)
                    meta_stat = _read_source_meta(expected_tmp)
                    self.assertIsNotNone(source_stat)
                    self.assertEqual(source_stat, meta_stat)
                finally:
                    close_all_engines()
                    invalidate_sqlite_tmp_cache(backup_id=backup_id, backup_path=base_path)

    def test_cross_device_link_exdev_fallback(self):
        from unittest.mock import patch
        from db.session import (
            close_all_engines,
            get_tmp_sqlite_path,
            sync_dirty_sqlite_dbs,
            invalidate_sqlite_tmp_cache,
        )
        from db import status_service

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "exdev_backup"
            tmp_cache_root = Path(tmpdir) / "tmp_cache"
            backup_dir.mkdir(parents=True, exist_ok=True)
            tmp_cache_root.mkdir(parents=True, exist_ok=True)

            backup_id = "exdev_test_1"
            base_path = backup_dir.as_posix()
            source_sqlite = os.path.abspath((backup_dir / "backup.sqlite").as_posix()).replace("\\", "/")

            env = {
                "SOCRATES_SQLITE_TMP_CACHE": "1",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
                "SOCRATES_SQLITE_SYNC_TIMER": "0",
            }
            with patch.dict(os.environ, env, clear=False):
                try:
                    close_all_engines()
                    status_service.init_backup_export(
                        backup_id=backup_id,
                        backup_path=base_path,
                        backup_name="EXDEV Test",
                    )
                    expected_tmp = get_tmp_sqlite_path(source_sqlite)

                    real_replace = os.replace

                    # Simulate EXDEV on initial cross-device os.replace(staging_path, source_sqlite_path)
                    def mock_replace(src, dst):
                        if ".sync." in str(src) and str(dst) == source_sqlite and not str(src).startswith(str(backup_dir)):
                            raise OSError(18, "Invalid cross-device link")
                        return real_replace(src, dst)

                    with patch("os.replace", side_effect=mock_replace):
                        synced = sync_dirty_sqlite_dbs(force=True)
                        self.assertEqual(synced, [source_sqlite])
                        self.assertTrue(os.path.exists(source_sqlite))

                    # Verify database was copied cleanly despite simulated EXDEV
                    conn = sqlite3.connect(source_sqlite)
                    try:
                        backup_rows = conn.execute("SELECT backup_id FROM backups").fetchall()
                    finally:
                        conn.close()
                    self.assertEqual(backup_rows, [(backup_id,)])
                finally:
                    close_all_engines()
                    invalidate_sqlite_tmp_cache(backup_id=backup_id, backup_path=base_path)

    def test_exdev_sync_does_not_fail_when_copystat_raises_eperm(self):
        from unittest.mock import patch
        from db.session import (
            close_all_engines,
            sync_dirty_sqlite_dbs,
            invalidate_sqlite_tmp_cache,
        )
        from db import status_service

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "eperm_backup"
            tmp_cache_root = Path(tmpdir) / "tmp_cache"
            backup_dir.mkdir(parents=True, exist_ok=True)
            tmp_cache_root.mkdir(parents=True, exist_ok=True)

            backup_id = "eperm_test_1"
            base_path = backup_dir.as_posix()
            source_sqlite = os.path.abspath((backup_dir / "backup.sqlite").as_posix()).replace("\\", "/")

            env = {
                "SOCRATES_SQLITE_TMP_CACHE": "1",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
                "SOCRATES_SQLITE_SYNC_TIMER": "0",
            }
            with patch.dict(os.environ, env, clear=False):
                try:
                    close_all_engines()
                    status_service.init_backup_export(
                        backup_id=backup_id,
                        backup_path=base_path,
                        backup_name="EPERM Test",
                    )

                    real_replace = os.replace

                    def mock_replace(src, dst):
                        if ".sync." in str(src) and str(dst) == source_sqlite:
                            raise OSError(18, "Invalid cross-device link")
                        return real_replace(src, dst)

                    with patch("os.replace", side_effect=mock_replace), \
                         patch("shutil.copystat", side_effect=PermissionError(1, "Operation not permitted")):
                        synced = sync_dirty_sqlite_dbs(force=True)
                        self.assertEqual(synced, [source_sqlite])
                        self.assertTrue(os.path.exists(source_sqlite))
                finally:
                    close_all_engines()
                    invalidate_sqlite_tmp_cache(backup_id=backup_id, backup_path=base_path)

    def test_middleware_opportunistic_get_sync(self):
        from unittest.mock import patch, MagicMock
        from db import status_service
        from db.session import (
            close_all_engines,
            sync_dirty_sqlite_dbs,
            invalidate_sqlite_tmp_cache,
            _last_sync_times,
        )
        from server import sqlite_tmp_sync_middleware

        def run_coro_sync(coro):
            try:
                while True:
                    coro.send(None)
            except StopIteration as stop:
                return stop.value

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "middleware_backup"
            tmp_cache_root = Path(tmpdir) / "tmp_cache"
            backup_dir.mkdir(parents=True, exist_ok=True)
            tmp_cache_root.mkdir(parents=True, exist_ok=True)

            backup_id = "middleware_test_1"
            base_path = backup_dir.as_posix()
            source_sqlite = os.path.abspath((backup_dir / "backup.sqlite").as_posix()).replace("\\", "/")

            env = {
                "SOCRATES_SQLITE_TMP_CACHE": "1",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
                "SOCRATES_SQLITE_SYNC_TIMER": "0",
                "SOCRATES_SQLITE_SYNC_INTERVAL": "5.0",
            }
            with patch.dict(os.environ, env, clear=False):
                try:
                    close_all_engines()
                    status_service.init_backup_export(
                        backup_id=backup_id,
                        backup_path=base_path,
                        backup_name="Middleware Test",
                    )
                    # Initial sync
                    sync_dirty_sqlite_dbs(force=True)

                    # Mutate DB in /tmp to mark dirty
                    status_service.update_step_status(
                        backup_id, base_path, "index_scenes", "running", write_snapshot=False
                    )

                    # Simulate that last sync was 10s ago (> 5s min_interval)
                    import time
                    _last_sync_times[source_sqlite] = time.monotonic() - 10.0

                    # Simulate incoming GET request through middleware
                    mock_request = MagicMock()
                    mock_request.method = "GET"

                    async def dummy_call_next(req):
                        return "ok_response"

                    res = run_coro_sync(sqlite_tmp_sync_middleware(mock_request, dummy_call_next))
                    self.assertEqual(res, "ok_response")

                    # Verify that source_sqlite on GCS was updated by the opportunistic GET sync
                    conn = sqlite3.connect(source_sqlite)
                    try:
                        rows = conn.execute(
                            "SELECT sync_status FROM backups WHERE backup_id = ?",
                            (backup_id,),
                        ).fetchall()
                    finally:
                        conn.close()
                    self.assertEqual(rows, [("syncing",)])
                finally:
                    close_all_engines()
                    invalidate_sqlite_tmp_cache(backup_id=backup_id, backup_path=base_path)

    def test_upgrade_rollback_invalidates_cache_without_sync(self):
        from unittest.mock import patch
        from db import status_service
        from db.session import (
            close_all_engines,
            get_tmp_sqlite_path,
            sync_dirty_sqlite_dbs,
            invalidate_sqlite_tmp_cache,
        )
        from db.upgrade import upgrade_single_backup

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "upgrade_backup"
            tmp_cache_root = Path(tmpdir) / "tmp_cache"
            backup_dir.mkdir(parents=True, exist_ok=True)
            tmp_cache_root.mkdir(parents=True, exist_ok=True)

            backup_id = "upgrade_test_1"
            base_path = backup_dir.as_posix()
            source_sqlite = os.path.abspath((backup_dir / "backup.sqlite").as_posix()).replace("\\", "/")

            env = {
                "SOCRATES_SQLITE_TMP_CACHE": "1",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
                "SOCRATES_SQLITE_SYNC_TIMER": "0",
            }
            with patch.dict(os.environ, env, clear=False):
                try:
                    close_all_engines()
                    status_service.init_backup_export(
                        backup_id=backup_id,
                        backup_path=base_path,
                        backup_name="Upgrade Test",
                    )
                    status_service.update_step_status(
                        backup_id, base_path, "index_scenes", "success", write_snapshot=False
                    )
                    sync_dirty_sqlite_dbs(force=True)

                    backup_dict = {
                        "backup_id": backup_id,
                        "backup_name": "Upgrade Test",
                        "path": base_path,
                    }

                    # 1. Successful upgrade cleans up .bak and syncs
                    res = upgrade_single_backup(backup_dict, dry_run=False, reindex_scenes=False)
                    self.assertFalse(res["dry_run"])
                    self.assertFalse(os.path.exists(f"{source_sqlite}.bak"))

                    # 2. Failed upgrade rolls back safely, restores safety copy, and removes .bak
                    def fail_populate(*args, **kwargs):
                        raise RuntimeError("Simulated failure during table population")

                    with patch("db.upgrade.populate_schema", side_effect=fail_populate):
                        with self.assertRaises(exc.DatabaseUpgradeError):
                            upgrade_single_backup(backup_dict, dry_run=False, reindex_scenes=False)

                    # 3. Failed reindex_scenes during upgrade logs original error and raises DatabaseUpgradeError
                    with patch("index_scenes.index_scenes", side_effect=RuntimeError("Simulated reindex failure")):
                        with self.assertRaises(exc.DatabaseUpgradeError) as reindex_ctx:
                            upgrade_single_backup(backup_dict, dry_run=False, reindex_scenes=True)
                        self.assertIn("Simulated reindex failure", str(reindex_ctx.exception))

                    # Verify safety backup file was cleaned up and source_sqlite is still readable
                    self.assertFalse(os.path.exists(f"{source_sqlite}.bak"))
                    conn = sqlite3.connect(source_sqlite)
                    try:
                        rows = conn.execute(
                            "SELECT sync_status FROM backups WHERE backup_id = ?",
                            (backup_id,),
                        ).fetchall()
                    finally:
                        conn.close()
                    self.assertEqual(rows, [("idle",)])
                finally:
                    close_all_engines()
                    invalidate_sqlite_tmp_cache(backup_id=backup_id, backup_path=base_path)

    def test_reset_test_backup_invalidates_tmp_cache(self):
        from unittest.mock import patch
        from db import status_service
        from db.session import (
            close_all_engines,
            get_tmp_sqlite_path,
            has_db,
            invalidate_sqlite_tmp_cache,
        )
        import tests.reset_test_backup as rtb

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_root = Path(tmpdir)
            clean_dir = fake_root / "Backups" / "Elysium-sql-tests-clean"
            target_dir = fake_root / "Backups" / "Elysium-sql-tests"
            tmp_cache_root = fake_root / "tmp_cache"
            clean_dir.mkdir(parents=True, exist_ok=True)
            target_dir.mkdir(parents=True, exist_ok=True)
            tmp_cache_root.mkdir(parents=True, exist_ok=True)
            (clean_dir / "backup_config.json").write_text("{}", encoding="utf-8")

            base_path = target_dir.as_posix()
            source_sqlite = os.path.abspath((target_dir / "backup.sqlite").as_posix()).replace("\\", "/")

            env = {
                "SOCRATES_SQLITE_TMP_CACHE": "1",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
                "SOCRATES_SQLITE_SYNC_TIMER": "0",
            }
            with patch.dict(os.environ, env, clear=False), patch.object(rtb, "DATA_ROOT", fake_root):
                try:
                    close_all_engines()
                    status_service.init_backup_export(
                        backup_id="reset_tmp_test",
                        backup_path=base_path,
                        backup_name="Reset Tmp Test",
                    )
                    expected_tmp = get_tmp_sqlite_path(source_sqlite)
                    self.assertTrue(os.path.exists(expected_tmp))
                    self.assertTrue(has_db(backup_path=base_path))

                    self.assertTrue(rtb.reset_test_backup())
                    self.assertFalse(os.path.exists(source_sqlite))
                    self.assertFalse(os.path.exists(expected_tmp))
                    self.assertFalse(has_db(backup_path=base_path))
                finally:
                    close_all_engines()
                    invalidate_sqlite_tmp_cache(backup_path=base_path)


class TestSkeletonModelsAndSession(unittest.TestCase):
    """Tests skeletons.sqlite WITHOUT ROWID schema, 14-bit SkeletonFlags, /tmp path isolation, and format_excerpt."""

    def test_skeleton_table_without_rowid_and_schema_version(self):
        from db.session import (
            get_skeleton_engine,
            skeleton_db_session,
            get_skeleton_sqlite_path,
            close_all_engines,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "skel_test"
            backup_dir.mkdir(parents=True, exist_ok=True)
            try:
                eng = get_skeleton_engine(backup_path=backup_dir.as_posix())
                skel_path = get_skeleton_sqlite_path(backup_dir.as_posix())
                self.assertTrue(os.path.exists(skel_path))

                with skeleton_db_session(backup_path=backup_dir.as_posix()) as s:
                    ver = s.query(SkeletonSchemaVersionModel).first()
                    self.assertIsNotNone(ver)
                    self.assertEqual(ver.version, CURRENT_SKELETON_SCHEMA_VERSION)

                    s.add(MessageSkeletonModel(
                        channel_discord_id=1013915163423932496,
                        message_id=1018678482202542151,
                        author_id=7,
                        timestamp_unix=1700000000,
                        flags=int(SkeletonFlags.IS_DEFAULT | SkeletonFlags.IS_TUPPER | SkeletonFlags.IS_DELETED),
                    ))

                # Verify WITHOUT ROWID DDL in SQLite
                conn = sqlite3.connect(skel_path)
                try:
                    ddl = conn.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name='message_skeletons'"
                    ).fetchone()[0]
                    self.assertIn("WITHOUT ROWID", ddl.upper())
                    row = conn.execute("SELECT author_id, flags FROM message_skeletons").fetchone()
                    self.assertEqual(row[0], 7)
                    self.assertTrue(row[1] & SkeletonFlags.IS_DELETED)
                finally:
                    conn.close()
            finally:
                close_all_engines()




    def test_compute_skeleton_flags_all_14_bits(self):
        # 1. Default tupper with start + end + short end + online + apology
        m1 = {
            "type": "Default",
            "content": "[October 12th - Morning]\n`Online` Sorry, back! ```End```",
            "author": {"id": "7", "name": "Tama"},
            "attachments": [{"id": "a1"}],
            "is_deleted": True,
        }
        f1 = compute_skeleton_flags(m1)
        self.assertTrue(f1 & SkeletonFlags.IS_DEFAULT)
        self.assertTrue(f1 & SkeletonFlags.IS_TUPPER)
        self.assertTrue(f1 & SkeletonFlags.HAS_ATTACHMENT)
        self.assertFalse(f1 & SkeletonFlags.IS_BANNER)  # tupper cannot be banner
        self.assertTrue(f1 & SkeletonFlags.HAS_START_TAG)
        self.assertTrue(f1 & SkeletonFlags.HAS_END_TAG)
        self.assertFalse(f1 & SkeletonFlags.IS_SHORT_END_TAG)
        self.assertTrue(f1 & SkeletonFlags.HAS_ONLINE_TAG)
        self.assertTrue(f1 & SkeletonFlags.HAS_APOLOGY)
        self.assertTrue(f1 & SkeletonFlags.IS_DELETED)

        # 2. Short end tag + offline tag
        m2 = {"type": "Default", "content": "`Offline` [END]", "author": {"id": "5"}}
        f2 = compute_skeleton_flags(m2)
        self.assertTrue(f2 & SkeletonFlags.HAS_END_TAG)
        self.assertTrue(f2 & SkeletonFlags.IS_SHORT_END_TAG)
        self.assertTrue(f2 & SkeletonFlags.HAS_OFFLINE_TAG)

        # 3. Mention-only
        m3 = {"type": "Default", "content": "<@123456> @RUKI", "author": {"id": "999999999999"}}
        f3 = compute_skeleton_flags(m3)
        self.assertTrue(f3 & SkeletonFlags.IS_MENTION_ONLY)

        # 4. Non-tupper banner vs mod event end
        m4 = {"type": "Default", "content": "Event Banner", "author": {"id": "999999999999"}, "embeds": [{"title": "X"}]}
        f4 = compute_skeleton_flags(m4)
        self.assertTrue(f4 & SkeletonFlags.IS_BANNER)
        self.assertFalse(f4 & SkeletonFlags.IS_EVENT_END)

        m5 = {"type": "Default", "content": "[EVENT END]", "author": {"id": "999999999999"}, "attachments": [{"id": "x"}]}
        f5 = compute_skeleton_flags(m5)
        self.assertTrue(f5 & SkeletonFlags.IS_EVENT_END)
        self.assertTrue(f5 & SkeletonFlags.IS_MOD_END)
        self.assertFalse(f5 & SkeletonFlags.IS_BANNER)

    def test_tmp_cache_leaf_filename_isolation_and_central_db(self):
        from unittest.mock import patch
        from db.session import (
            get_tmp_sqlite_path,
            get_skeleton_engine,
            skeleton_db_session,
            close_all_engines,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            b_dir = Path(tmpdir) / "my_backup"
            b_dir.mkdir(parents=True, exist_ok=True)
            p_main = get_tmp_sqlite_path((b_dir / "backup.sqlite").as_posix())
            p_skel = get_tmp_sqlite_path((b_dir / "skeletons.sqlite").as_posix())
            p_audit = get_tmp_sqlite_path((b_dir / "audit.sqlite").as_posix())

            self.assertEqual(os.path.basename(p_main), "backup.sqlite")
            self.assertEqual(os.path.basename(p_skel), "skeletons.sqlite")
            self.assertEqual(os.path.basename(p_audit), "audit.sqlite")
            self.assertEqual(len({p_main, p_skel, p_audit}), 3)

            # Central DATABASE_URL fallback initializes both Base and SkeletonBase without local files
            central_db = Path(tmpdir) / "central.db"
            with patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{central_db.as_posix()}"}):
                close_all_engines()
                try:
                    eng = get_skeleton_engine(backup_id="c1", backup_path=b_dir.as_posix())
                    self.assertIn("message_skeletons", inspect(eng).get_table_names())
                    with skeleton_db_session(backup_id="c1", backup_path=b_dir.as_posix()) as s:
                        s.add(MessageSkeletonModel(
                            channel_discord_id=111,
                            message_id=222,
                            author_id=1,
                            timestamp_unix=1700000000,
                            flags=1,
                        ))
                    self.assertFalse((b_dir / "skeletons.sqlite").exists())
                finally:
                    close_all_engines()

    def test_format_excerpt_head_and_tail(self):
        short = "Short message."
        self.assertEqual(t.format_excerpt(short), short)

        exact = "a" * 250
        self.assertEqual(t.format_excerpt(exact), exact)

        long_txt = ("H" * 120) + ("M" * 50) + ("T" * 120)
        res = t.format_excerpt(long_txt)
        self.assertEqual(len(res), 247)
        self.assertEqual(res, ("H" * 120) + "\n[...]\n" + ("T" * 120))

    def test_load_channel_skeletons_does_not_create_missing_db(self):
        from db.scene_service import load_channel_skeletons
        from db.session import close_all_engines, has_skeleton_db, get_skeleton_sqlite_path

        with tempfile.TemporaryDirectory() as tmpdir:
            b_dir = Path(tmpdir) / "no_skel_backup"
            b_dir.mkdir(parents=True, exist_ok=True)
            skel_path = Path(get_skeleton_sqlite_path(b_dir.as_posix()))
            try:
                self.assertFalse(has_skeleton_db(backup_path=b_dir.as_posix()))
                rows = load_channel_skeletons("no_skel_id", b_dir.as_posix(), "1234567890")
                self.assertEqual(rows, [])
                self.assertFalse(skel_path.exists())
                self.assertFalse(has_skeleton_db(backup_path=b_dir.as_posix()))
            finally:
                close_all_engines()




if __name__ == "__main__":
    unittest.main()

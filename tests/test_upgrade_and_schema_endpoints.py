import os
import shutil
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

from unittest.mock import patch
from sqlalchemy import inspect
from tests.test_env import skip_in_production_or_missing_fixture
DATA_ROOT = Path(os.environ.get("SOCRATES_DATA_DIR") or PROJECT_ROOT.as_posix())
from tests.reset_test_backup import reset_test_backup
from tests.seed_test_backup import seed_v5_test_backup
from db.migrate import migrate_for_tests
from db.models import (
    CURRENT_SCHEMA_VERSION,
    BackupCategoryConfigModel,
    BackupModel,
    BackupRbacEntryModel,
    CategoryConfigKind,
    ChannelModel,
    CharacterModel,
    FlaggedMessageModel,
    RbacAccessLevel,
    RbacTargetType,
    SceneIssueModel,
    SceneModel,
    SceneParticipantModel,
    SeenDiscordUserModel,
    WriterModel,
)
from db.skeleton_models import MessageSkeletonModel, SkeletonFlags
from db.session import (
    db_session,
    skeleton_db_session,
    get_db_schema_version,
    get_engine,
    get_sqlite_path,
    get_skeleton_sqlite_path,
    close_all_engines,
)
from db.snapshots import (
    export_backup_config_snapshot,
    export_backup_info_snapshot,
    export_character_list_snapshot,
)
from db.upgrade import upgrade_single_backup
from models.backup_context import BackupContext
from utils import tricks as t


def _get_schema_version(backup_path: str) -> int:
    return get_db_schema_version(get_engine(backup_path=backup_path))
from server import (
    get_backup_info,
    get_scene_issues,
    upgrade_backup_database,
    upgrade_all_databases,
)


@skip_in_production_or_missing_fixture()
class TestUpgradeAndSchemaEndpoints(unittest.TestCase):
    """Tests for reason filter in scene issues, schema outdated detection, and upgrade endpoints."""

    TEST_BACKUP_ID = "1791895360"

    @classmethod
    def setUpClass(cls):
        reset_test_backup()
        migrate_for_tests(cls.TEST_BACKUP_ID)

    @classmethod
    def tearDownClass(cls):
        close_all_engines()
        reset_test_backup()

    def test_reason_filter_count_badges(self):
        """Test that filtering scene issues by reason updates status_counts appropriately."""
        # 1. Fetch without reason filter
        all_res = get_scene_issues(self.TEST_BACKUP_ID, status="all", per_page=100)
        total_all = all_res["status_counts"]["all"]

        # Insert test issues with distinct reasons if needed, or query existing reasons
        with db_session(self.TEST_BACKUP_ID) as session:
            existing_issue = session.query(SceneIssueModel).filter(
                SceneIssueModel.backup_id == str(self.TEST_BACKUP_ID)
            ).first()

            if existing_issue:
                reason = existing_issue.reason
                expected_count = session.query(SceneIssueModel).filter(
                    SceneIssueModel.backup_id == str(self.TEST_BACKUP_ID),
                    SceneIssueModel.reason == reason
                ).count()

                reason_res = get_scene_issues(self.TEST_BACKUP_ID, reason=reason, status="all")
                self.assertEqual(reason_res["status_counts"]["all"], expected_count)
                self.assertLessEqual(reason_res["status_counts"]["all"], total_all)

        # Non-existent reason should yield 0 counts
        non_existent_res = get_scene_issues(self.TEST_BACKUP_ID, reason="non_existent_reason_xyz")
        self.assertEqual(non_existent_res["status_counts"]["all"], 0)
        self.assertEqual(non_existent_res["status_counts"]["unresolved"], 0)
        self.assertEqual(non_existent_res["status_counts"]["resolved"], 0)

    def test_schema_version_in_get_backup_info(self):
        """Test that get_backup_info returns schema_version and outdated status."""
        info = get_backup_info(self.TEST_BACKUP_ID)
        self.assertIn("schema_version", info)
        self.assertIn("current_schema_version", info)
        self.assertIn("is_schema_outdated", info)
        self.assertEqual(info["current_schema_version"], CURRENT_SCHEMA_VERSION)
        self.assertIsInstance(info["schema_version"], int)
        self.assertIsInstance(info["is_schema_outdated"], bool)
        self.assertEqual(info["is_schema_outdated"], info["schema_version"] < CURRENT_SCHEMA_VERSION)

    def test_upgrade_backup_database_endpoint(self):
        """Test POST /api/backups/{backup_id}/upgrade."""
        res = upgrade_backup_database(self.TEST_BACKUP_ID)
        self.assertEqual(res["status"], "success")
        self.assertIn("Database upgraded successfully", res["message"])
        self.assertIn("report", res)
        self.assertEqual(res["report"]["new_version"], CURRENT_SCHEMA_VERSION)

    def test_upgrade_all_databases_endpoint(self):
        """Test POST /api/admin/upgrade-all."""
        with patch("utils.tricks.get_backups_index") as mock_index:
            mock_index.return_value = [
                {
                    "backup_id": self.TEST_BACKUP_ID,
                    "backup_name": "Elysium-sql-tests",
                    "path": "Backups/Elysium-sql-tests",
                }
            ]
            res = upgrade_all_databases()
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["message"], "All databases upgraded successfully.")


@skip_in_production_or_missing_fixture()
class TestSchemaV5ToV6Upgrade(unittest.TestCase):
    """Tests Schema v5 -> Schema v6 + skeletons.sqlite upgrade and rollback."""

    TEST_BACKUP_ID = "1791895360"

    def tearDown(self):
        close_all_engines()

    def test_v5_to_v6_upgrade_preserves_data_and_builds_skeletons(self):
        import sqlite3
        clean_dir = DATA_ROOT / "Backups" / "Elysium-sql-tests-clean"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_backup = Path(tmpdir) / "Elysium-v5"
            shutil.copytree(clean_dir, tmp_backup)

            try:
                seed_v5_test_backup(backup_id=self.TEST_BACKUP_ID, backup_path=str(tmp_backup))
                backup_sqlite = Path(get_sqlite_path(str(tmp_backup)))
                skeleton_sqlite = Path(get_skeleton_sqlite_path(str(tmp_backup)))
                self.assertTrue(backup_sqlite.exists())
                self.assertFalse(skeleton_sqlite.exists())
                self.assertEqual(_get_schema_version(str(tmp_backup)), 5)

                conn = sqlite3.connect(backup_sqlite.as_posix())
                try:
                    v5_writers = conn.execute("SELECT COUNT(*) FROM writers").fetchone()[0]
                    v5_chars = conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0]
                    v5_scenes = conn.execute("SELECT COUNT(*) FROM scenes").fetchone()[0]
                    v5_resolved_issues = conn.execute(
                        "SELECT COUNT(*) FROM scene_issues WHERE resolved_at IS NOT NULL"
                    ).fetchone()[0]
                    v5_overrides = conn.execute(
                        "SELECT COUNT(*) FROM flagged_messages WHERE resolution = 'override'"
                    ).fetchone()[0]
                finally:
                    conn.close()

                close_all_engines()
                report = upgrade_single_backup(
                    {
                        "backup_id": self.TEST_BACKUP_ID,
                        "backup_name": "Elysium-v5",
                        "path": str(tmp_backup),
                    }
                )
                self.assertEqual(report["old_version"], 5)
                self.assertEqual(report["new_version"], CURRENT_SCHEMA_VERSION)
                self.assertFalse(report["dry_run"])
                self.assertEqual(_get_schema_version(str(tmp_backup)), CURRENT_SCHEMA_VERSION)
                self.assertTrue(skeleton_sqlite.exists(), "Upgrade must create skeletons.sqlite when Data/*.json exist")

                with db_session(backup_path=str(tmp_backup)) as session:
                    tables = set(inspect(session.bind).get_table_names())
                    self.assertNotIn("exports", tables)
                    self.assertNotIn("backup_steps", tables)
                    self.assertIn("seen_discord_users", tables)
                    self.assertIn("backup_category_configs", tables)
                    self.assertIn("backup_rbac_entries", tables)

                    backup = session.query(BackupModel).filter(
                        BackupModel.backup_id == self.TEST_BACKUP_ID
                    ).first()
                    self.assertIsNotNone(backup)
                    self.assertEqual(backup.storage_mode, "full")
                    self.assertEqual(backup.sync_status, "idle")
                    self.assertIsNotNone(backup.last_synced_at)
                    self.assertEqual(backup.path, "Backups/Elysium-sql-tests")
                    self.assertTrue(backup.keep_mode)
                    self.assertTrue(backup.log_info)
                    self.assertTrue(backup.log_debug)
                    self.assertTrue(backup.log_console)
                    self.assertTrue(backup.log_file)
                    self.assertFalse(backup.debug_files)

                    cat_rows = session.query(BackupCategoryConfigModel).filter(
                        BackupCategoryConfigModel.backup_id == self.TEST_BACKUP_ID
                    ).all()
                    keep_refs = [r.category_ref for r in cat_rows if r.kind == CategoryConfigKind.KEEP.value]
                    ignore_refs = [r.category_ref for r in cat_rows if r.kind == CategoryConfigKind.IGNORE.value]
                    chatroom_refs = [r.category_ref for r in cat_rows if r.kind == CategoryConfigKind.CHATROOM.value]
                    event_refs = [r.category_ref for r in cat_rows if r.kind == CategoryConfigKind.EVENT.value]

                    self.assertIn("1019770957172326470", keep_refs)
                    self.assertIn("1106268351220678767", keep_refs)
                    self.assertNotIn("The Twisted Viper Bar", keep_refs)
                    self.assertNotIn("Group Chats", keep_refs)
                    self.assertIn("CURRENT EVENT", keep_refs)
                    self.assertIn("EVENT STORAGE", keep_refs)
                    self.assertEqual(chatroom_refs, ["1106268351220678767"])
                    self.assertEqual(event_refs, ["CURRENT EVENT", "EVENT STORAGE", "NSFW Events"])
                    self.assertEqual(len(ignore_refs), 9)
                    self.assertEqual(report["metrics"]["category_configs_count"], len(cat_rows))
                    self.assertEqual(report["metrics"]["rbac_entries_count"], 0)
                    self.assertFalse((tmp_backup / "Info" / "backup_config.json").exists())

                    channels = session.query(ChannelModel).filter(
                        ChannelModel.backup_id == self.TEST_BACKUP_ID
                    ).all()
                    self.assertGreater(len(channels), 0)

                    self.assertEqual(session.query(WriterModel).count(), v5_writers)
                    self.assertEqual(session.query(CharacterModel).count(), v5_chars)
                    self.assertEqual(session.query(SceneModel).count(), v5_scenes)
                    self.assertEqual(
                        session.query(SceneIssueModel).filter(SceneIssueModel.resolved_at.isnot(None)).count(),
                        v5_resolved_issues,
                    )
                    overrides = session.query(FlaggedMessageModel).filter(
                        FlaggedMessageModel.resolution == "override"
                    ).all()
                    self.assertEqual(len(overrides), v5_overrides)
                    self.assertTrue(any(o.override_flags is not None for o in overrides))

                    scene_counts = [s.message_count for s in session.query(SceneModel).all()]
                    self.assertTrue(all(c >= 0 for c in scene_counts))
                    self.assertTrue(any(c > 0 for c in scene_counts))
                    part_counts = [p.message_count for p in session.query(SceneParticipantModel).all()]
                    self.assertTrue(any(c >= 1 for c in part_counts))

                    seen_users = session.query(SeenDiscordUserModel).filter(
                        SeenDiscordUserModel.backup_id == self.TEST_BACKUP_ID
                    ).all()
                    self.assertGreater(len(seen_users), 0)

                with skeleton_db_session(backup_path=str(tmp_backup)) as skel_session:
                    skels = skel_session.query(MessageSkeletonModel).all()
                    self.assertGreater(len(skels), 0)
                    self.assertTrue(any((s.flags & int(SkeletonFlags.IS_TUPPER)) != 0 and s.author_id < 10000 for s in skels))
            finally:
                close_all_engines()

    def test_v5_to_v6_upgrade_rollback_restores_bak_on_failure(self):
        clean_dir = DATA_ROOT / "Backups" / "Elysium-sql-tests-clean"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_backup = Path(tmpdir) / "Elysium-v5-rollback"
            shutil.copytree(clean_dir, tmp_backup)
            try:
                seed_v5_test_backup(backup_id=self.TEST_BACKUP_ID, backup_path=str(tmp_backup))
                backup_sqlite = Path(get_sqlite_path(str(tmp_backup)))
                skeleton_sqlite = Path(get_skeleton_sqlite_path(str(tmp_backup)))
                close_all_engines()

                from utils import exceptions as exc
                with patch("db.upgrade._populate_skeletons_and_collect_users", side_effect=RuntimeError("simulated upgrade failure")):
                    with self.assertRaises(exc.DatabaseUpgradeError):
                        upgrade_single_backup(
                            {
                                "backup_id": self.TEST_BACKUP_ID,
                                "backup_name": "Elysium-v5-rollback",
                                "path": str(tmp_backup),
                            }
                        )

                close_all_engines()
                self.assertEqual(_get_schema_version(str(tmp_backup)), 5)
                self.assertFalse(skeleton_sqlite.exists(), "Partial skeletons.sqlite must be removed on rollback")
                self.assertTrue(backup_sqlite.exists())
            finally:
                close_all_engines()

    def test_v6_to_v7_and_idempotent_v7_upgrade_preserves_custom_configs_and_rbac(self):
        import json
        import sqlite3
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_backup = Path(tmpdir) / "Backups" / "V6UpgradeBackup"
            tmp_backup.mkdir(parents=True, exist_ok=True)
            b_id = "66778899"
            sqlite_file = Path(get_sqlite_path(str(tmp_backup)))
            now_iso = datetime.now(timezone.utc).isoformat()

            # Write a backup_config.json with debugFiles=True, RBAC, and no storageMode key
            t.save_json_atomic(
                {
                    "admin": {
                        "serverName": "V6 Guild",
                        "serverId": "857848490683269161",
                        "categoriesToKeep": ["14# The Twisted Viper Bar", "CURRENT EVENT"],
                        "keepMode": True,
                        "categoriesToIgnore": ["1# Staff Only"],
                        "chatroomCategories": ["Group Chats"],
                        "eventCategories": ["CURRENT EVENT"],
                        "backupName": "V6UpgradeBackup",
                        "verbosity": {
                            "info": True,
                            "debug": False,
                            "console": True,
                            "log": True,
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
                },
                (tmp_backup / "backup_config.json").as_posix(),
            )

            # Create a genuine Schema v6 SQLite database
            conn = sqlite3.connect(sqlite_file.as_posix())
            try:
                conn.executescript(
                    """
                    PRAGMA foreign_keys=ON;
                    CREATE TABLE backups (
                        backup_id VARCHAR(64) PRIMARY KEY,
                        backup_name VARCHAR(128) NOT NULL,
                        server_id VARCHAR(20),
                        server_name VARCHAR(128),
                        created_at DATETIME,
                        storage_mode VARCHAR(16) NOT NULL DEFAULT 'backupless',
                        sync_status VARCHAR(16) NOT NULL DEFAULT 'idle',
                        sync_started_at DATETIME,
                        last_synced_at DATETIME,
                        sync_error TEXT,
                        channels_total INTEGER NOT NULL DEFAULT 0,
                        channels_done INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE TABLE channels (
                        pk INTEGER PRIMARY KEY AUTOINCREMENT,
                        backup_id VARCHAR(64) NOT NULL REFERENCES backups(backup_id) ON DELETE CASCADE,
                        discord_id VARCHAR(20) NOT NULL,
                        type VARCHAR(32) NOT NULL,
                        parent_pk INTEGER REFERENCES channels(pk) ON DELETE CASCADE,
                        name VARCHAR(64) NOT NULL,
                        position INTEGER NOT NULL,
                        path VARCHAR(255) NOT NULL,
                        is_deleted BOOLEAN NOT NULL DEFAULT 0,
                        message_count INTEGER,
                        last_message_id VARCHAR(20),
                        last_synced_at DATETIME,
                        sync_status VARCHAR(16) NOT NULL DEFAULT 'pending',
                        sync_error TEXT,
                        UNIQUE(backup_id, discord_id)
                    );
                    CREATE TABLE schema_version (
                        version INTEGER PRIMARY KEY,
                        applied_at DATETIME NOT NULL,
                        description VARCHAR(255)
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
                    (6, now_iso, "Seeded Schema v6 fixture"),
                )
                conn.execute(
                    "INSERT INTO backups (backup_id, backup_name, server_id, server_name, storage_mode, sync_status) VALUES (?, ?, ?, ?, ?, ?)",
                    (b_id, "V6UpgradeBackup", "857848490683269161", "V6 Guild", "backupless", "idle"),
                )
                conn.execute(
                    "INSERT INTO channels (backup_id, discord_id, type, parent_pk, name, position, path) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (b_id, "1019770957172326470", "GuildCategory", None, "The Twisted Viper Bar", 14, "14# The Twisted Viper Bar"),
                )
                conn.execute(
                    "INSERT INTO channels (backup_id, discord_id, type, parent_pk, name, position, path) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (b_id, "1106268351220678767", "GuildCategory", None, "Group Chats", 7, "7# Group Chats"),
                )
                conn.commit()
            finally:
                conn.close()

            try:
                # Pre-v7 DB without debug_files column must fall back cleanly to backup_config.json
                self.assertTrue(t.is_debug_files_enabled(backup_id=None, backup_path=str(tmp_backup)))
                close_all_engines()

                report_v7 = upgrade_single_backup(
                    {"backup_id": b_id, "backup_name": "V6UpgradeBackup", "path": str(tmp_backup)}
                )
                self.assertEqual(report_v7["old_version"], 6)
                self.assertEqual(report_v7["new_version"], CURRENT_SCHEMA_VERSION)
                self.assertEqual(report_v7["metrics"]["category_configs_count"], 5)
                self.assertEqual(report_v7["metrics"]["rbac_entries_count"], 3)

                info_cfg_file = tmp_backup / "Info" / "backup_config.json"
                self.assertTrue(info_cfg_file.is_file(), "debug_files=True must export Info/backup_config.json on upgrade")

                with db_session(backup_id=b_id, backup_path=str(tmp_backup)) as session:
                    backup = session.query(BackupModel).filter_by(backup_id=b_id).first()
                    self.assertIsNotNone(backup)
                    self.assertEqual(backup.storage_mode, "backupless")
                    self.assertEqual(backup.path, "Backups/V6UpgradeBackup")
                    self.assertTrue(backup.keep_mode)
                    self.assertFalse(backup.log_debug)
                    self.assertTrue(backup.debug_files)

                    cats = session.query(BackupCategoryConfigModel).filter_by(backup_id=b_id).all()
                    keep_refs = {c.category_ref for c in cats if c.kind == CategoryConfigKind.KEEP.value}
                    chat_refs = {c.category_ref for c in cats if c.kind == CategoryConfigKind.CHATROOM.value}
                    self.assertEqual(keep_refs, {"1019770957172326470", "CURRENT EVENT"})
                    self.assertEqual(chat_refs, {"1106268351220678767"})

                    # Mutate SQL directly to simulate custom v7 config/RBAC + a legacy name row before v7->v7 rebuild
                    backup.keep_mode = False
                    backup.log_debug = True
                    backup.path = "Backups/CustomPath"
                    session.add(
                        BackupCategoryConfigModel(
                            backup_id=b_id,
                            kind=CategoryConfigKind.KEEP.value,
                            category_ref="Group Chats",
                        )
                    )
                    session.add(
                        BackupCategoryConfigModel(
                            backup_id=b_id,
                            kind=CategoryConfigKind.IGNORE.value,
                            category_ref="Custom Unresolved",
                        )
                    )
                    session.add(
                        BackupRbacEntryModel(
                            backup_id=b_id,
                            target_type=RbacTargetType.USER.value,
                            access_level=RbacAccessLevel.BLOCKED.value,
                            discord_id="999000111222333444",
                        )
                    )

                info_cfg_file.unlink()
                close_all_engines()

                report_v7_idem = upgrade_single_backup(
                    {"backup_id": b_id, "backup_name": "V6UpgradeBackup", "path": str(tmp_backup)}
                )
                self.assertEqual(report_v7_idem["old_version"], 7)
                self.assertEqual(report_v7_idem["new_version"], 7)
                self.assertEqual(report_v7_idem["metrics"]["category_configs_count"], 7)
                self.assertEqual(report_v7_idem["metrics"]["rbac_entries_count"], 4)
                self.assertTrue(info_cfg_file.is_file())

                snap_data = json.loads(info_cfg_file.read_text(encoding="utf-8"))
                self.assertFalse(snap_data["admin"]["keepMode"])
                self.assertTrue(snap_data["admin"]["verbosity"]["debug"])
                self.assertEqual(snap_data["admin"]["path"], "Backups/CustomPath")
                self.assertIn("1106268351220678767", snap_data["admin"]["categoriesToKeep"])
                self.assertNotIn("Group Chats", snap_data["admin"]["categoriesToKeep"])
                self.assertIn("Custom Unresolved", snap_data["admin"]["categoriesToIgnore"])
                self.assertEqual(snap_data["rbac"]["blockedUserIds"], ["999000111222333444"])

                # Clearing all config/RBAC rows in v7 and rebuilding v7->v7 must not resurrect stale backup_config.json
                with db_session(backup_id=b_id, backup_path=str(tmp_backup)) as session:
                    session.query(BackupCategoryConfigModel).filter_by(backup_id=b_id).delete()
                    session.query(BackupRbacEntryModel).filter_by(backup_id=b_id).delete()
                    b_row = session.query(BackupModel).filter_by(backup_id=b_id).first()
                    b_row.keep_mode = False
                    b_row.debug_files = False
                close_all_engines()

                report_v7_empty = upgrade_single_backup(
                    {"backup_id": b_id, "backup_name": "V6UpgradeBackup", "path": str(tmp_backup)}
                )
                self.assertEqual(report_v7_empty["metrics"]["category_configs_count"], 0)
                self.assertEqual(report_v7_empty["metrics"]["rbac_entries_count"], 0)
                with db_session(backup_id=b_id, backup_path=str(tmp_backup)) as session:
                    b_row = session.query(BackupModel).filter_by(backup_id=b_id).first()
                    self.assertFalse(b_row.keep_mode)
                    self.assertFalse(b_row.debug_files)
            finally:
                close_all_engines()

    def test_export_backup_config_snapshot_and_is_debug_files_enabled(self):
        import json
        from db.session import init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_backup = Path(tmpdir) / "Backups" / "SnapshotDebugTest"
            tmp_backup.mkdir(parents=True, exist_ok=True)
            b_id = "snap_dbg_1"
            b_path = tmp_backup.as_posix()

            # Write a conflicting disk backup_config.json (debugFiles=True) to prove SQLite wins when DB exists
            t.save_json_atomic(
                {"admin": {"serverName": "Disk", "verbosity": {"debugFiles": True}}},
                (tmp_backup / "backup_config.json").as_posix(),
            )

            try:
                engine = init_db(backup_id=b_id, backup_path=b_path)
                with db_session(backup_id=b_id, backup_path=b_path) as session:
                    session.add(
                        BackupModel(
                            backup_id=b_id,
                            backup_name="SnapshotDebugTest",
                            server_id="857848490683269161",
                            server_name="Test Guild",
                            path="Backups/SnapshotDebugTest",
                            keep_mode=True,
                            debug_files=False,
                        )
                    )
                    session.add(
                        BackupCategoryConfigModel(
                            backup_id=b_id,
                            kind=CategoryConfigKind.KEEP.value,
                            category_ref="1019770957172326470",
                        )
                    )
                    session.add(
                        BackupRbacEntryModel(
                            backup_id=b_id,
                            target_type=RbacTargetType.ROLE.value,
                            access_level=RbacAccessLevel.ADMIN.value,
                            discord_id="100000000000000001",
                        )
                    )

                self.assertFalse(t.is_debug_files_enabled(backup_id=b_id, backup_path=b_path))
                with db_session(backup_id=b_id, backup_path=b_path) as session:
                    self.assertIsNone(export_backup_config_snapshot(session, b_id, backup_path=b_path))
                    self.assertEqual(export_backup_info_snapshot(session, b_id, backup_path=b_path), {})
                    self.assertEqual(export_character_list_snapshot(session, b_id, backup_path=b_path), {})
                self.assertFalse((tmp_backup / "Info" / "backup_config.json").exists())

                # Enable debug_files in SQLite while disk backup_config.json has debugFiles=False
                t.save_json_atomic(
                    {"admin": {"serverName": "Disk", "verbosity": {"debugFiles": False}}},
                    (tmp_backup / "backup_config.json").as_posix(),
                )
                with db_session(backup_id=b_id, backup_path=b_path) as session:
                    b_row = session.query(BackupModel).filter_by(backup_id=b_id).first()
                    b_row.debug_files = True

                self.assertTrue(t.is_debug_files_enabled(backup_id=b_id, backup_path=b_path))
                with db_session(backup_id=b_id, backup_path=b_path) as session:
                    written = export_backup_config_snapshot(session, b_id, backup_path=b_path)
                    self.assertIsNotNone(written)
                    self.assertTrue(Path(written).is_file())
                    exported = json.loads(Path(written).read_text(encoding="utf-8"))
                    self.assertEqual(exported["admin"]["categoriesToKeep"], ["1019770957172326470"])
                    self.assertEqual(exported["rbac"]["adminRoleIds"], ["100000000000000001"])
                    self.assertTrue(exported["admin"]["verbosity"]["debugFiles"])

                    # Active BackupContext in-memory override must take precedence
                    ctx = BackupContext.create(backup_id=b_id, backup_path=b_path)
                    ctx.debug_files = False
                    with BackupContext.activate(context=ctx):
                        self.assertFalse(t.is_debug_files_enabled(backup_id=b_id, backup_path=b_path))
                        self.assertIsNone(export_backup_config_snapshot(session, b_id, backup_path=b_path))

                self.assertIsNotNone(engine)
            finally:
                close_all_engines()


if __name__ == "__main__":
    unittest.main()

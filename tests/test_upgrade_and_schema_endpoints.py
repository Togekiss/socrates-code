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
    BackupModel,
    ChannelModel,
    CharacterModel,
    FlaggedMessageModel,
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
from db.upgrade import upgrade_single_backup


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
                self.assertEqual(report["new_version"], 6)
                self.assertFalse(report["dry_run"])
                self.assertEqual(_get_schema_version(str(tmp_backup)), 6)
                self.assertTrue(skeleton_sqlite.exists(), "Upgrade must create skeletons.sqlite when Data/*.json exist")

                with db_session(backup_path=str(tmp_backup)) as session:
                    tables = set(inspect(session.bind).get_table_names())
                    self.assertNotIn("exports", tables)
                    self.assertNotIn("backup_steps", tables)
                    self.assertIn("seen_discord_users", tables)

                    backup = session.query(BackupModel).filter(
                        BackupModel.backup_id == self.TEST_BACKUP_ID
                    ).first()
                    self.assertIsNotNone(backup)
                    self.assertEqual(backup.storage_mode, "full")
                    self.assertEqual(backup.sync_status, "idle")
                    self.assertIsNotNone(backup.last_synced_at)

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


if __name__ == "__main__":
    unittest.main()

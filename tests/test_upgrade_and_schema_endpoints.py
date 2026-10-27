import os
import sys
import unittest
from pathlib import Path

# Ensure src and project root are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("SOCRATES_DATA_DIR", PROJECT_ROOT.as_posix()))
SRC_DIR = PROJECT_ROOT / "src"
for p in (SRC_DIR.as_posix(), PROJECT_ROOT.as_posix()):
    if p not in sys.path:
        sys.path.insert(0, p)

from unittest.mock import patch
from tests.reset_test_backup import reset_test_backup
from db.migrate import migrate_for_tests
from db.models import CURRENT_SCHEMA_VERSION, SceneIssueModel
from db.session import db_session, close_all_engines
from server import (
    get_backup_info,
    get_scene_issues,
    upgrade_backup_database,
    upgrade_all_databases,
)


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


if __name__ == "__main__":
    unittest.main()

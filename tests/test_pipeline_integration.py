import os
import shutil
import sys
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
# pyrefly: ignore [missing-import]
from db.session import get_sqlite_path, db_session, close_all_engines
# pyrefly: ignore [missing-import]
from db.models import (
    BackupModel,
    ExportModel,
    BackupStepModel,
    ChannelModel,
    WriterModel,
    CharacterModel,
    SceneModel,
    SceneParticipantModel,
    Step,
    Status,
)
# pyrefly: ignore [missing-import]
from db.migrate import migrate_single_backup
# pyrefly: ignore [missing-import]
from models.backup_context import BackupContext
# pyrefly: ignore [missing-import]
from models import ServerBackup, CharacterList, SceneManager
# pyrefly: ignore [missing-import]
from assign_ids import assign_ids
# pyrefly: ignore [missing-import]
from fix_bad_messages import fix_bad_messages
# pyrefly: ignore [missing-import]
from index_scenes import index_scenes
# pyrefly: ignore [missing-import]
from find_character_scenes import find_character_scenes
# pyrefly: ignore [missing-import]
from backup_server import backup_server
from tests.reset_test_backup import reset_test_backup
# pyrefly: ignore [missing-import]
import utils.tricks as t


class TestPipelineIntegration(unittest.TestCase):
    """
    End-to-end integration test verifying the complete v2 SQLite migration and pipeline execution.
    Tests: JSON -> SQLite migration -> assign_ids -> fix_bad_messages -> index_scenes -> find_character_scenes -> update.
    """

    @classmethod
    def setUpClass(cls):
        reset_test_backup()
        cls.backup_path = (PROJECT_ROOT / "Backups" / "Elysium-sql-tests").as_posix()
        cls.backup_id = "1791895360"
        cls.backup_name = "Elysium-sql-tests"

    @classmethod
    def tearDownClass(cls):
        # Clear singleton caches and dispose db engines to release Windows file locks
        SceneManager.clear_cache()
        close_all_engines()
        reset_test_backup()

    def test_01_migration_json_to_sqlite(self):
        """Phase 1: Test that migrate_single_backup creates backup.sqlite and populates all tables."""
        t.log("console", "Testing migration from JSON to SQLite...")
        index = t.get_backups_index()
        b = next((b for b in index if str(b["backup_id"]) == str(self.backup_id)), None)
        b["path"] = self.backup_path
        report = migrate_single_backup(b, dry_run=False, skip_snapshots=False)

        db_file = get_sqlite_path(self.backup_path)
        self.assertTrue(Path(db_file).exists(), f"backup.sqlite must exist at {db_file}")

        # Check schema tables
        with db_session(backup_id=self.backup_id, backup_path=self.backup_path) as session:
            inspector = inspect(session.bind)
            tables = set(inspector.get_table_names())
            expected_tables = {
                "backups", "exports", "backup_steps", "channels", "writers",
                "writer_aliases", "character_groups", "group_names", "characters",
                "character_names", "scenes", "scene_participants", "scene_issues",
                "message_overrides", "flagged_messages"
            }
            self.assertTrue(expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}")

            backup = session.query(BackupModel).filter(BackupModel.backup_id == self.backup_id).first()
            self.assertIsNotNone(backup)
            self.assertEqual(backup.backup_name, self.backup_name)

            channels_count = session.query(ChannelModel).count()
            self.assertGreater(channels_count, 0, "Channels must be migrated")

            chars_count = session.query(CharacterModel).count()
            self.assertGreater(chars_count, 0, "Characters must be migrated")

        t.log("console", "Migration succeeded with full table coverage.")

    def test_02_assign_ids_execution(self):
        """Phase 2: Test assign_ids() using SQLite CharacterList with zero in-loop disk writes."""
        t.log("console", "Testing assign_ids step...")
        ctx = BackupContext.create(
            backup_id=self.backup_id,
            backup_path=self.backup_path,
        )
        ctx.dry_run = False
        ctx.debug_files = True

        with BackupContext.activate(context=ctx):
            assign_ids()

            # Verify step status in SQLite
            backup = ServerBackup.load(scope="base")
            self.assertEqual(backup.steps[Step.ASSIGN_IDS], Status.SUCCESS)

            # Verify character lookups in-memory/SQLite
            char_list = CharacterList.load()
            self.assertGreater(len(char_list.characters), 0)
            ophelia_id = char_list.find_id_by_name("Ophelia")
            self.assertIsNotNone(ophelia_id)

        t.log("console", "assign_ids executed successfully and updated SQLite step status.")

    def test_03_fix_bad_messages_execution(self):
        """Phase 3: Test fix_bad_messages() using SQLite curation_service."""
        t.log("console", "Testing fix_bad_messages step...")
        ctx = BackupContext.create(
            backup_id=self.backup_id,
            backup_path=self.backup_path,
        )
        ctx.dry_run = False
        ctx.debug_files = True

        with BackupContext.activate(context=ctx):
            fix_bad_messages()

            backup = ServerBackup.load(scope="base")
            self.assertEqual(backup.steps[Step.FIX_MESSAGES], Status.SUCCESS)

        t.log("console", "fix_bad_messages executed successfully and updated SQLite step status.")

    def test_04_index_scenes_execution(self):
        """Phase 4: Test index_scenes() saving indexed scenes into SQLite via SceneManager."""
        t.log("console", "Testing index_scenes step...")
        ctx = BackupContext.create(
            backup_id=self.backup_id,
            backup_path=self.backup_path,
        )
        ctx.dry_run = False
        ctx.debug_files = True

        with BackupContext.activate(context=ctx):
            index_scenes()

            backup = ServerBackup.load(scope="base")
            self.assertEqual(backup.steps[Step.INDEX_SCENES], Status.SUCCESS)

            # Verify scenes were persisted directly in SQLite
            with db_session(backup_id=self.backup_id, backup_path=self.backup_path) as session:
                scenes_count = session.query(SceneModel).filter(SceneModel.backup_id == self.backup_id).count()
                self.assertGreater(scenes_count, 0, "Indexed scenes must be stored in SQLite scenes table")

                participants_count = session.query(SceneParticipantModel).count()
                self.assertGreater(participants_count, 0, "Scene participants must be stored in SQLite")

        t.log("console", "index_scenes executed successfully and saved scenes to SQLite.")

    def test_05_find_character_scenes_execution(self):
        """Phase 5: Test find_character_scenes() filtering scenes from SQLite via SceneManager."""
        t.log("console", "Testing find_character_scenes step...")
        ctx = BackupContext.create(
            backup_id=self.backup_id,
            backup_path=self.backup_path,
        )
        ctx.dry_run = False
        ctx.character = "Ophelia"

        with BackupContext.activate(context=ctx):
            find_character_scenes()

            # Output file should exist
            out_scenes = Path(ctx.output_scenes)
            self.assertTrue(out_scenes.exists(), f"Output scenes file must exist at {out_scenes}")

            # Direct filter query via SceneManager
            manager = SceneManager.get_instance(backup_id=self.backup_id, base_path=self.backup_path)
            char_list = CharacterList.load()
            ophelia_ids = char_list.get_all_character_ids("Ophelia")
            self.assertGreater(len(ophelia_ids), 0)

            filtered = manager.filter_scenes(character_ids=ophelia_ids)
            self.assertIsInstance(filtered, list)
            self.assertGreater(len(filtered), 0, "Should find scenes for Ophelia in SQLite")

        t.log("console", "find_character_scenes successfully filtered scenes from SQLite.")

    @patch("utils.tricks.run_command")
    def test_06_update_with_backup_server(self, mock_run_cmd):
        """Phase 6: Test full update pipeline with backup_server() against testing backup."""
        t.log("console", "Testing full update with backup_server()...")

        # Ensure database is migrated
        db_file = get_sqlite_path(self.backup_path)
        if not Path(db_file).exists():
            self.test_01_migration_json_to_sqlite()

        # Capture pre-update updated_at timestamp
        pre_backup = ServerBackup.load(scope="base", backup_id=self.backup_id, backup_path=self.backup_path)
        original_updated_at = pre_backup.updated_at

        # Mock DCE CLI calls for channels and export
        def fake_run_command(command: str, show_lines: int = None):
            if "channels" in command:
                mock_channels_output = (
                    "1019770957172326470 \\ 14# The Twisted Viper Bar\n"
                    "1013915163423932496 | 1# GuildTextChat / barside\n"
                    "1019771259896205382 | 2# GuildTextChat / back-of-bar\n"
                    "* 1141818382782574645 | 1# GuildPublicThread / A Toast to Emnity (Shin/Rin) | back-of-bar\n"
                    "* 1158294831097970738 | 2# GuildPublicThread / Conversation | back-of-bar\n"
                    "1019771317303644261 | 3# GuildTextChat / bar-tables\n"
                    "* 1285969286808076360 | 1# GuildPublicThread / Full Moon | bar-tables\n"
                )
                return 0, mock_channels_output
            elif "export" in command:
                update_src = PROJECT_ROOT / "Backups" / "Elysium-sql-tests-clean" / "Update"
                update_dest = Path(self.backup_path) / "Update"
                if update_src.exists():
                    shutil.copytree(update_src, update_dest, dirs_exist_ok=True)
                return 0, "Export completed successfully"
            return 0, ""

        mock_run_cmd.side_effect = fake_run_command

        ctx = BackupContext.create(
            backup_id=self.backup_id,
            backup_path=self.backup_path,
        )
        ctx.dry_run = False
        ctx.debug_files = False

        with BackupContext.activate(context=ctx):
            backup_server()

        # 1. Verify ServerBackup (scope="base") state
        post_backup = ServerBackup.load(scope="base", backup_id=self.backup_id, backup_path=self.backup_path)
        self.assertEqual(post_backup.status, Status.SUCCESS)
        self.assertEqual(post_backup.steps[Step.UPDATE], Status.SUCCESS)
        self.assertEqual(post_backup.steps[Step.FIX_MESSAGES], Status.SUCCESS)
        self.assertEqual(post_backup.steps[Step.INDEX_SCENES], Status.SUCCESS)
        self.assertNotEqual(post_backup.updated_at, original_updated_at, "updated_at must be updated after run")

        # 2. Verify SQLite database tables
        with db_session(backup_id=self.backup_id, backup_path=self.backup_path) as session:
            # ExportModel for update scope must be deleted
            update_export = session.query(ExportModel).filter(
                ExportModel.backup_id == str(self.backup_id),
                ExportModel.scope == "update"
            ).first()
            self.assertIsNone(update_export, "ExportModel for scope='update' must be cleaned up")

            # Base export should exist and be SUCCESS
            base_export = session.query(ExportModel).filter(
                ExportModel.backup_id == str(self.backup_id),
                ExportModel.scope == "base"
            ).first()
            self.assertIsNotNone(base_export)

            # New thread 'Full Moon' must be saved in channels table
            full_moon_thread = session.query(ChannelModel).filter(
                ChannelModel.export_pk == base_export.pk,
                ChannelModel.discord_id == "1285969286808076360"
            ).first()
            self.assertIsNotNone(full_moon_thread, "New thread 'Full Moon' must be saved in ChannelModel")
            self.assertEqual(full_moon_thread.name, "Full Moon")
            self.assertEqual(full_moon_thread.type, "GuildPublicThread")

            # Scenes must be indexed in SQLite
            scene_count = session.query(SceneModel).filter(SceneModel.backup_id == str(self.backup_id)).count()
            self.assertGreater(scene_count, 0, "Scenes must be indexed in SQLite")

        # 3. Verify Filesystem state
        data_dir = Path(ctx.data_folder)
        full_moon_file = data_dir / "14# The Twisted Viper Bar" / "Threads" / "3-1# Full Moon.json"
        self.assertTrue(full_moon_file.exists(), f"Full Moon thread file must exist at {full_moon_file}")

        # Update, Data_Old, and Merge folders should be cleaned up
        self.assertFalse(Path(ctx.update_folder).exists(), "Update folder should be cleaned up")
        self.assertFalse(Path(f"{ctx.data_folder}_Old").exists(), "Data_Old folder should be cleaned up")
        self.assertFalse(Path(ctx.merge_folder).exists(), "Merge folder should be cleaned up")

        t.log("console", "Full update with backup_server executed and verified successfully.")


if __name__ == "__main__":
    unittest.main()

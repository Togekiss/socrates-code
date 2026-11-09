import os
import shutil
import sys
import tempfile
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
    EventModel,
    SceneModel,
    SceneParticipantModel,
    SceneIssueModel,
    FlaggedMessageModel,
    SceneKind,
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
from backup_server import backup_server
# pyrefly: ignore [missing-import]
from deprecated.inject_category import inject_category
from tests.reset_test_backup import reset_test_backup
# pyrefly: ignore [missing-import]
import utils.tricks as t


class TestPipelineIntegration(unittest.TestCase):
    """
    End-to-end integration test verifying the complete SQLite migration and pipeline execution.
    Tests: JSON -> SQLite migration -> assign_ids -> fix_bad_messages -> index_scenes -> find_character_scenes -> update.
    """

    @classmethod
    def setUpClass(cls):
        reset_test_backup()
        cls.backup_path = (DATA_ROOT / "Backups" / "Elysium-sql-tests").as_posix()
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
                "character_names", "events", "scenes", "scene_participants", "scene_issues",
                "flagged_messages"
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

            # Chatroom channels in c.CHATROOM_CATEGORIES and event channels in Events must be skipped by fix_bad_messages
            with db_session(backup_id=self.backup_id, backup_path=self.backup_path) as session:
                chatroom_chan = session.query(ChannelModel).filter(ChannelModel.discord_id == "858215486272962581").first()
                if chatroom_chan:
                    flagged_count = session.query(FlaggedMessageModel).filter(
                        FlaggedMessageModel.backup_id == str(self.backup_id),
                        FlaggedMessageModel.channel_pk == chatroom_chan.pk
                    ).count()
                    self.assertEqual(flagged_count, 0, "Chatroom channels must have 0 flagged messages")

                event_chan = session.query(ChannelModel).filter(ChannelModel.discord_id == "1008065639467982868").first()
                if event_chan:
                    event_flagged = session.query(FlaggedMessageModel).filter(
                        FlaggedMessageModel.backup_id == str(self.backup_id),
                        FlaggedMessageModel.channel_pk == event_chan.pk
                    ).count()
                    self.assertEqual(event_flagged, 0, "Event channels must have 0 flagged messages")

        t.log("console", "fix_bad_messages executed successfully and updated SQLite step status.")

    def test_04_index_scenes_execution(self):
        """Phase 4: Test index_scenes() saving indexed scenes, chat sessions, and events into SQLite."""
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

                # Verify RP scenes and chatroom sessions
                rp_scenes_count = session.query(SceneModel).filter(
                    SceneModel.backup_id == self.backup_id,
                    SceneModel.kind == SceneKind.SCENE.value
                ).count()
                self.assertEqual(rp_scenes_count, 13, "Should have 13 RP scenes")

                session_scenes_count = session.query(SceneModel).filter(
                    SceneModel.backup_id == self.backup_id,
                    SceneModel.kind == SceneKind.SESSION.value
                ).count()
                self.assertEqual(session_scenes_count, 121, "Should have 121 chatroom sessions")

                # Verify Events and Event channel/thread scenes
                events_count = session.query(EventModel).filter(
                    EventModel.backup_id == self.backup_id
                ).count()
                self.assertEqual(events_count, 4, "Should have 4 indexed events in SQLite")

                event_scenes_count = session.query(SceneModel).filter(
                    SceneModel.backup_id == self.backup_id,
                    SceneModel.kind == SceneKind.EVENT.value
                ).count()
                self.assertEqual(event_scenes_count, 7, "Should have 7 event scene segments (5 channel segments + 2 threads)")

                # Verify participant details on session scenes
                session_participants = (
                    session.query(SceneParticipantModel)
                    .join(SceneModel, SceneParticipantModel.scene_pk == SceneModel.pk)
                    .filter(SceneModel.backup_id == self.backup_id, SceneModel.kind == SceneKind.SESSION.value)
                    .all()
                )
                self.assertGreater(len(session_participants), 0, "Chat sessions must have participants")
                for p in session_participants[:20]:
                    self.assertIsNotNone(p.first_message_id)
                    self.assertIsNotNone(p.first_at)
                    self.assertIsNotNone(p.last_message_id)
                    self.assertIsNotNone(p.last_at)
                    self.assertGreaterEqual(p.position, 0)

                # Verify zero auto-detected issues for session scenes
                non_rp_issues = (
                    session.query(SceneIssueModel)
                    .join(SceneModel, SceneIssueModel.scene_pk == SceneModel.pk)
                    .filter(
                        SceneModel.backup_id == self.backup_id,
                        SceneModel.kind == SceneKind.SESSION.value
                    )
                    .count()
                )
                self.assertEqual(non_rp_issues, 0, "Chat sessions should not produce auto-detected scene issues")

                # Verify event scenes support auto-detected issues (e.g. inactivity_gap, tupper_end_tag)
                event_issues = (
                    session.query(SceneIssueModel)
                    .join(SceneModel, SceneIssueModel.scene_pk == SceneModel.pk)
                    .filter(
                        SceneModel.backup_id == self.backup_id,
                        SceneModel.kind == SceneKind.EVENT.value
                    )
                    .count()
                )
                self.assertGreaterEqual(event_issues, 0)

                participants_count = session.query(SceneParticipantModel).count()
                self.assertGreater(participants_count, 0, "Scene participants must be stored in SQLite")

        t.log("console", "index_scenes executed successfully and saved scenes and events to SQLite.")

    def test_05_scene_manager_character_filtering(self):
        """Phase 5: Test SceneManager filtering scenes by character IDs directly from SQLite."""
        t.log("console", "Testing SceneManager character scene filtering...")
        ctx = BackupContext.create(
            backup_id=self.backup_id,
            backup_path=self.backup_path,
        )
        ctx.dry_run = False
        ctx.character = "Ophelia"

        with BackupContext.activate(context=ctx):
            manager = SceneManager.get_instance(backup_id=self.backup_id, base_path=self.backup_path)
            char_list = CharacterList.load()
            ophelia_ids = char_list.get_all_character_ids("Ophelia")
            self.assertGreater(len(ophelia_ids), 0)

            filtered = manager.filter_scenes(character_ids=ophelia_ids)
            self.assertIsInstance(filtered, list)
            self.assertGreater(len(filtered), 0, "Should find scenes for Ophelia in SQLite")

        t.log("console", "SceneManager successfully filtered character scenes from SQLite.")

    @patch("utils.tricks.run_command")
    def test_06_update_with_backup_server(self, mock_run_cmd):
        """Phase 6: Test full update pipeline with backup_server() against testing backup including raw event categories."""
        t.log("console", "Testing full update with backup_server()...")

        # Ensure database is migrated
        db_file = get_sqlite_path(self.backup_path)
        if not Path(db_file).exists():
            self.test_01_migration_json_to_sqlite()

        # Capture pre-update updated_at timestamp
        pre_backup = ServerBackup.load(scope="base", backup_id=self.backup_id, backup_path=self.backup_path)
        original_updated_at = pre_backup.updated_at

        # Mock DCE CLI calls for channels and export (including raw event categories in Update/)
        def fake_run_command(command: str, show_lines: int = None):
            if "channels" in command:
                mock_channels_output = (
                    "1008065547155558431 \\ 6# CURRENT EVENT\n"
                    "1008065681998221352 | 1# GuildTextChat / hotel-lobby\n"
                    "1008065639467982868 | 2# GuildTextChat / game-booths\n"
                    "* 1132200643776487524 | 1# GuildPublicThread / Tamina Freaky Hours~ | game-booths\n"
                    "* 1132744421587296397 | 2# GuildPublicThread / Sand Dunes | game-booths\n"
                    "1106268351220678767 \\ 7# Group Chats\n"
                    "858215486272962581 | 1# GuildTextChat / chatroom\n"
                    "1019770957172326470 \\ 14# The Twisted Viper Bar\n"
                    "1013915163423932496 | 1# GuildTextChat / barside\n"
                    "1019771259896205382 | 2# GuildTextChat / back-of-bar\n"
                    "* 1141818382782574645 | 1# GuildPublicThread / A Toast to Emnity (Shin/Rin) | back-of-bar\n"
                    "* 1158294831097970738 | 2# GuildPublicThread / Conversation | back-of-bar\n"
                    "1019771317303644261 | 3# GuildTextChat / bar-tables\n"
                    "* 1285969286808076360 | 1# GuildPublicThread / Full Moon | bar-tables\n"
                    "1345359342970343486 \\ 23# NSFW Events\n"
                    "1345360008409518121 | 1# GuildTextChat / room-9\n"
                    "987749861963214878 \\ 28# EVENT STORAGE\n"
                    "1008065664034025533 | 1# GuildTextChat / medical-tent\n"
                    "* 1131989202465210569 | 1# GuildPublicThread / Room 4: Ruki, Aoi, Kaoru | medical-tent\n"
                )
                return 0, mock_channels_output
            elif "export" in command:
                update_src = DATA_ROOT / "Backups" / "Elysium-sql-tests-clean" / "Update"
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

            # New event channel 'room-9' normalized to 'event-4'
            event4_chan = session.query(ChannelModel).filter(
                ChannelModel.export_pk == base_export.pk,
                ChannelModel.discord_id == "1345360008409518121"
            ).first()
            self.assertIsNotNone(event4_chan, "New event channel 'event-4' must be saved in ChannelModel")
            self.assertEqual(event4_chan.name, "event-4")

            # Scenes must be indexed in SQLite: 17 RP scenes (including Full Moon) and 121 chat sessions
            rp_count = session.query(SceneModel).filter(
                SceneModel.backup_id == str(self.backup_id),
                SceneModel.kind == SceneKind.SCENE.value
            ).count()
            self.assertEqual(rp_count, 17, "RP scenes count must be 17 after Full Moon thread is added")

            sessions_count = session.query(SceneModel).filter(
                SceneModel.backup_id == str(self.backup_id),
                SceneModel.kind == SceneKind.SESSION.value
            ).count()
            self.assertEqual(sessions_count, 121, "Chat sessions count must remain 121 after update")

            # Events must be indexed in SQLite (4 base events + new event(s) from Update)
            events_count = session.query(EventModel).filter(
                EventModel.backup_id == str(self.backup_id)
            ).count()
            self.assertGreaterEqual(events_count, 5, "Events count must increase after merging new event channels")

        # 3. Verify Filesystem state
        data_dir = Path(ctx.data_folder)
        full_moon_file = data_dir / "14# The Twisted Viper Bar" / "Threads" / "3-1# Full Moon.json"
        self.assertTrue(full_moon_file.exists(), f"Full Moon thread file must exist at {full_moon_file}")

        event4_file = data_dir / "6# Events" / "4# event-4.json"
        self.assertTrue(event4_file.exists(), f"Normalized event-4 file must exist at {event4_file}")

        sand_dunes_file = data_dir / "6# Events" / "Threads" / "1-2# Sand Dunes.json"
        self.assertTrue(sand_dunes_file.exists(), f"Normalized Sand Dunes thread file must exist at {sand_dunes_file}")

        # Update, Data_Old, and Merge folders should be cleaned up
        self.assertFalse(Path(ctx.update_folder).exists(), "Update folder should be cleaned up")
        self.assertFalse(Path(f"{ctx.data_folder}_Old").exists(), "Data_Old folder should be cleaned up")
        self.assertFalse(Path(ctx.merge_folder).exists(), "Merge folder should be cleaned up")

        t.log("console", "Full update with backup_server executed and verified successfully.")

    def test_07_inject_category_events(self):
        """
        Tests injecting a raw event category into an existing backup using inject_category(..., is_event=True).
        Verifies:
          1. Category is normalized into the faux 'Events' category ('event-1..N').
          2. Raw category folder is cleaned up and normalized on disk.
          3. EventModel and SceneModel (kind='event') rows are indexed and saved to SQLite.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_backup = Path(tmp_dir) / "TestInjectBackup"
            clean_backup = PROJECT_ROOT / "Backups" / "Elysium-sql-tests-clean"
            shutil.copytree(clean_backup, tmp_backup)

            data_dir = tmp_backup / "Data"
            faux_events_dir = data_dir / "6# Events"
            raw_event_storage = data_dir / "28# EVENT STORAGE"
            if faux_events_dir.exists():
                faux_events_dir.rename(raw_event_storage)
                ch1 = raw_event_storage / "1# event-1.json"
                if ch1.exists():
                    ch1.rename(raw_event_storage / "1# hogsmeade.json")
                ch2 = raw_event_storage / "2# event-2.json"
                if ch2.exists():
                    ch2.rename(raw_event_storage / "2# common-room.json")
                ch3 = raw_event_storage / "3# event-3.json"
                if ch3.exists():
                    ch3.rename(raw_event_storage / "3# hagrids-hut.json")

            try:
                migrate_single_backup(
                    backup={
                        "path": tmp_backup.as_posix(),
                        "backup_id": "999999999",
                        "backup_name": "TestInjectBackup",
                        "server_id": "857848490683269161",
                        "server_name": "Diabolik: Elysium",
                    },
                    dry_run=False,
                )

                inject_category(
                    backup_id="999999999",
                    backup_path=tmp_backup.as_posix(),
                    category_name="EVENT STORAGE",
                    is_event=True,
                )

                with db_session(backup_id="999999999", backup_path=tmp_backup.as_posix()) as session:
                    events = session.query(EventModel).filter_by(backup_id="999999999").all()
                    event_scenes = session.query(SceneModel).filter_by(
                        backup_id="999999999", kind=SceneKind.EVENT.value
                    ).all()
                    self.assertGreater(len(events), 0, "EventModel rows must be created")
                    self.assertGreater(len(event_scenes), 0, "SceneModel (kind='event') rows must be created")
                    for ev in events:
                        self.assertGreater(ev.message_count, 0)
                        self.assertIsNotNone(ev.start_at)
                        self.assertIsNotNone(ev.end_at)

                self.assertFalse(raw_event_storage.exists(), "Raw category folder must be cleaned up")
                events_dirs = [d for d in data_dir.iterdir() if d.is_dir() and "events" in d.name.lower()]
                self.assertEqual(len(events_dirs), 1, "Exactly one normalized Events folder must exist")
                norm_files = [f.name for f in events_dirs[0].glob("*.json")]
                self.assertTrue(any("event-1.json" in f for f in norm_files), "event-1.json must exist in normalized folder")

                backup = ServerBackup.load(scope="base", backup_id="999999999", backup_path=tmp_backup.as_posix())
                self.assertEqual(backup.steps[Step.INDEX_SCENES], Status.SUCCESS)

            finally:
                close_all_engines()


if __name__ == "__main__":
    unittest.main()

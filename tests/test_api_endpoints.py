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

from tests.reset_test_backup import reset_test_backup
# pyrefly: ignore [missing-import]
import utils.tricks as t
# pyrefly: ignore [missing-import]
from db.session import db_session, close_all_engines, stamp_schema_version
# pyrefly: ignore [missing-import]
from db.migrate import migrate_for_tests
# pyrefly: ignore [missing-import]
from db.models import CharacterGroupModel, GroupNameModel, CharacterModel, BackupStepModel
# pyrefly: ignore [missing-import]
from db.snapshots import export_character_list_snapshot
# pyrefly: ignore [missing-import]
from models import SceneManager
# pyrefly: ignore [missing-import]
from server import (
    get_backup_info,
    get_curation_summary,
    get_my_writer,
    rerun_backup_step,
    get_characters,
    get_scenes,
    get_sessions,
    get_events,
    get_writers,
    get_groups,
    create_group,
    update_group,
    update_character,
    nest_character,
    unnest_character,
    CreateGroupRequest,
    UpdateGroupRequest,
    UpdateCharacterRequest,
    NestCharacterRequest,
    get_backup_config,
    update_backup_config,
    run_backup,
    cancel_backup_action,
    run_script_in_background,
    get_backup_logs,
    reset_testing_backup,
    migrate_testing_backup,
    run_python_tests,
)


class TestBackupInfoEndpoint(unittest.TestCase):
    """Tests the backup metadata endpoint backed by SQLite / snapshot."""
    
    @classmethod
    def setUpClass(cls):
        if not (DATA_ROOT / "Backups" / "Elysium-sql-tests" / "backup.sqlite").exists():
            migrate_for_tests("1791895360")
            SceneManager.clear_cache()
            close_all_engines()

    @classmethod
    def tearDownClass(cls):
        SceneManager.clear_cache()
        close_all_engines()

    def test_get_backup_info_elysium(self):
        info = get_backup_info("1791895360")
        self.assertIsInstance(info, dict)
        self.assertEqual(info["number_of_scenes"], 12)
        self.assertEqual(info["number_of_characters"], 20)
        self.assertIn("categories", info)
        self.assertGreater(len(info["categories"]), 0)
        self.assertIn("steps", info)

    def test_rerun_backup_step_sets_running_status(self):
        from unittest.mock import MagicMock
        bg = MagicMock()
        backup_path = t.get_backup_path("1791895360")

        # Test triggering rerun for fix_messages
        res = rerun_backup_step("1791895360", "fix_messages", bg)
        self.assertEqual(res["status"], "started")
        bg.add_task.assert_called_once()

        # Verify SQLite immediately reflects running state
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            step = session.query(BackupStepModel).filter(
                BackupStepModel.export_pk == 1,
                BackupStepModel.step == "fix_messages"
            ).first()
            self.assertIsNotNone(step)
            self.assertEqual(step.status, "running")

            # Restore step to success
            step.status = "success"
            session.commit()

    def test_run_script_in_background_failure_marks_step_failed(self):
        from unittest.mock import patch, MagicMock
        backup_path = t.get_backup_path("1791895360")

        # Mock Popen to simulate a failed subprocess with exit code 1 and error output on stderr
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = ["Traceback (most recent call last):\n", "ModuleNotFoundError: No module named 'src'\n"]
        mock_proc.wait.return_value = 1

        with patch("subprocess.Popen", return_value=mock_proc):
            run_script_in_background("assign_ids.py", "1791895360", step_name="assign_ids")

        # Verify step was marked as failed in SQLite
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            step = session.query(BackupStepModel).filter(
                BackupStepModel.export_pk == 1,
                BackupStepModel.step == "assign_ids"
            ).first()
            self.assertIsNotNone(step)
            self.assertEqual(step.status, "failed")
            self.assertIn("ModuleNotFoundError", str(step.error))

            # Restore step to success
            step.status = "success"
            step.error = None
            session.commit()

    def test_cancel_backup_action_clears_running_steps(self):
        backup_path = t.get_backup_path("1791895360")
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            step = session.query(BackupStepModel).filter(
                BackupStepModel.export_pk == 1,
                BackupStepModel.step == "assign_ids"
            ).first()
            step.status = "running"
            session.commit()

        # Cancel should mark the stuck step as failed even when no process is active
        res = cancel_backup_action("1791895360")
        self.assertEqual(res["status"], "canceled")

        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            step = session.query(BackupStepModel).filter(
                BackupStepModel.export_pk == 1,
                BackupStepModel.step == "assign_ids"
            ).first()
            self.assertEqual(step.status, "failed")

            # Restore step to success
            step.status = "success"
            step.error = None
            session.commit()


class TestCharactersEndpoints(unittest.TestCase):
    """Tests the character retrieval, legacy formatting, and normalization endpoints."""

    @classmethod
    def setUpClass(cls):
        if not (DATA_ROOT / "Backups" / "Elysium-sql-tests" / "backup.sqlite").exists():
            migrate_for_tests("1791895360")
            SceneManager.clear_cache()
            close_all_engines()

    @classmethod
    def tearDownClass(cls):
        SceneManager.clear_cache()
        close_all_engines()

    def test_get_characters_legacy_format(self):
        chars = get_characters("1791895360", format="legacy")
        self.assertIsInstance(chars, list)
        self.assertEqual(len(chars), 20)

        sample = chars[0]
        for key in ("id", "names", "writer", "tags", "other_versions"):
            self.assertIn(key, sample)

    def test_get_characters_normalized_format(self):
        norm = get_characters("1791895360", format="normalized")
        self.assertIsInstance(norm, dict)
        self.assertIn("writers", norm)
        self.assertIn("groups", norm)
        self.assertIn("characters", norm)
        self.assertEqual(len(norm["characters"]), 20)

    def test_get_writers(self):
        writers = get_writers("1791895360")
        self.assertIsInstance(writers, list)
        self.assertGreater(len(writers), 2)

    def test_get_groups(self):
        groups = get_groups("1791895360")
        self.assertIsInstance(groups, list)
        self.assertGreater(len(groups), 0)


class TestScenesEndpoint(unittest.TestCase):
    """Tests scene querying, filtering, and pagination from SQLite."""

    @classmethod
    def setUpClass(cls):
        if not (DATA_ROOT / "Backups" / "Elysium-sql-tests" / "backup.sqlite").exists():
            migrate_for_tests("1791895360")
            SceneManager.clear_cache()
            close_all_engines()

    @classmethod
    def tearDownClass(cls):
        SceneManager.clear_cache()
        close_all_engines()

    def test_get_scenes_pagination(self):
        scenes_res = get_scenes("1791895360", page=1, per_page=5)
        self.assertIsInstance(scenes_res, dict)
        self.assertEqual(scenes_res["total_items"], 12)
        self.assertEqual(scenes_res["current_page"], 1)
        self.assertEqual(len(scenes_res["scenes"]), 5)

        first_scene = scenes_res["scenes"][0]
        for key in ("category", "channel", "type", "status", "start", "end", "characters", "issues"):
            self.assertIn(key, first_scene)

    def test_get_scenes_writer_filter(self):
        writers = get_writers("1791895360")
        self.assertGreater(len(writers), 2)
        target_writer = writers[0]

        filtered = get_scenes("1791895360", writers=[target_writer])
        self.assertIsInstance(filtered, dict)
        self.assertGreater(filtered["total_items"], 0)
        self.assertLessEqual(filtered["total_items"], 12)


class TestSessionsEndpoint(unittest.TestCase):
    """Tests chat session and event querying, filtering, and pagination from SQLite."""

    @classmethod
    def setUpClass(cls):
        reset_test_backup()
        migrate_for_tests("1791895360")
        SceneManager.clear_cache()
        close_all_engines()

        # Ensure chat sessions and events are indexed in Elysium-sql-tests
        from assign_ids import assign_ids
        from index_scenes import index_scenes
        from models.backup_context import BackupContext
        ctx = BackupContext.create(backup_id="1791895360")
        with BackupContext.activate(context=ctx):
            assign_ids()
            index_scenes()
        SceneManager.clear_cache()
        close_all_engines()

    @classmethod
    def tearDownClass(cls):
        SceneManager.clear_cache()
        close_all_engines()
        reset_test_backup()

    def test_get_sessions_pagination_and_structure(self):
        sessions_res = get_sessions("1791895360", page=1, per_page=10)
        self.assertIsInstance(sessions_res, dict)
        self.assertEqual(sessions_res["total_items"], 121)
        self.assertEqual(sessions_res["current_page"], 1)
        self.assertEqual(sessions_res["per_page"], 10)
        self.assertEqual(sessions_res["total_pages"], 13)
        self.assertEqual(len(sessions_res["sessions"]), 10)

        first_session = sessions_res["sessions"][0]
        for key in ("category", "channel", "status", "start", "end", "characters", "participants"):
            self.assertIn(key, first_session)
        self.assertEqual(first_session["channel"], "chatroom")

        participants = first_session["participants"]
        self.assertGreater(len(participants), 0)
        p0 = participants[0]
        self.assertEqual(p0["position"], 0)
        self.assertIn("name", p0)
        self.assertIn("first_message_id", p0)
        self.assertIn("first_timestamp", p0)
        self.assertIn("first_link", p0)
        self.assertIn("last_message_id", p0)
        self.assertIn("last_timestamp", p0)
        self.assertIn("last_link", p0)

    def test_get_sessions_channel_filter(self):
        res = get_sessions("1791895360", channels=["chatroom"])
        self.assertEqual(res["total_items"], 121)

        res_empty = get_sessions("1791895360", channels=["nonexistent"])
        self.assertEqual(res_empty["total_items"], 0)
        self.assertEqual(len(res_empty["sessions"]), 0)

    def test_get_sessions_character_filter(self):
        res = get_sessions("1791895360", per_page=5)
        self.assertGreater(len(res["sessions"]), 0)
        char_id = res["sessions"][0]["characters"][0]

        filtered = get_sessions("1791895360", characters=[char_id])
        self.assertGreater(filtered["total_items"], 0)
        self.assertLessEqual(filtered["total_items"], 121)
        for s in filtered["sessions"]:
            self.assertIn(char_id, s["characters"])

    def test_backup_info_number_of_sessions(self):
        info = get_backup_info("1791895360")
        self.assertEqual(info.get("number_of_sessions"), 121)
        self.assertEqual(info.get("number_of_events"), 4)

    def test_get_events_pagination_and_structure(self):
        events_res = get_events("1791895360", page=1, per_page=10)
        self.assertIsInstance(events_res, dict)
        self.assertEqual(events_res["total_items"], 4)
        self.assertEqual(events_res["current_page"], 1)
        self.assertEqual(len(events_res["events"]), 4)

        first_event = events_res["events"][0]
        for key in (
            "pk",
            "id",
            "event_key",
            "status",
            "is_curated",
            "start",
            "end",
            "start_timestamp",
            "end_timestamp",
            "message_count",
            "characters",
            "character_movements",
            "channels",
        ):
            self.assertIn(key, first_event)
        self.assertTrue(first_event["start_timestamp"])
        self.assertTrue(first_event["end_timestamp"])
        for ch in first_event["channels"]:
            self.assertIn("scene_pk", ch)
            self.assertIn("pk", ch)

        # Check multi-channel event has channels and movements
        multi_ch_events = [ev for ev in events_res["events"] if len(ev["channels"]) >= 2]
        self.assertGreaterEqual(len(multi_ch_events), 1)

        # Check event with threads has indented thread entries under parent channel
        threaded_events = [
            ev for ev in events_res["events"]
            if any(len(ch.get("threads", [])) > 0 for ch in ev["channels"])
        ]
        self.assertGreaterEqual(len(threaded_events), 1)
        th_ev = threaded_events[0]
        all_threads = [th for ch in th_ev["channels"] for th in ch.get("threads", [])]
        self.assertEqual(len(all_threads), 2)
        for th in all_threads:
            self.assertEqual(th["type"], "thread")
            self.assertGreater(len(th["participants"]), 0)

    def test_get_events_filters_and_sorting(self):
        # Filter by channel
        ch_res = get_events("1791895360", channels=["event-1"])
        self.assertEqual(ch_res["total_items"], 2)

        ch_res_3 = get_events("1791895360", channels=["event-3"])
        self.assertEqual(ch_res_3["total_items"], 2)

        # Filter by character
        all_res = get_events("1791895360")
        sample_cid = all_res["events"][0]["characters"][0]
        char_res = get_events("1791895360", characters=[sample_cid])
        self.assertGreater(char_res["total_items"], 0)
        for ev in char_res["events"]:
            self.assertIn(sample_cid, ev["characters"])

        # Sort order
        asc_res = get_events("1791895360", sort="asc")
        desc_res = get_events("1791895360", sort="desc")
        self.assertEqual(
            [e["id"] for e in asc_res["events"]],
            list(reversed([e["id"] for e in desc_res["events"]])),
        )


class TestCharacterAndGroupMutations(unittest.TestCase):
    """Tests mutating character and group state on backup_id='1791895360' (Elysium-sql-tests)."""

    @classmethod
    def setUpClass(cls):
        if not (DATA_ROOT / "Backups" / "Elysium-sql-tests" / "backup.sqlite").exists():
            migrate_for_tests("1791895360")
            SceneManager.clear_cache()
            close_all_engines()

    @classmethod
    def tearDownClass(cls):
        SceneManager.clear_cache()
        close_all_engines()

    def test_character_attribute_update_roundtrip(self):
        chars = get_characters("1791895360")
        self.assertGreater(len(chars), 0)
        target_char = chars[0]
        cid = target_char["id"]
        orig_tags = list(target_char["tags"])

        # Mutate tags by toggling origin
        if "canon" in orig_tags:
            test_tags = ["oc" if x == "canon" else x for x in orig_tags]
        else:
            test_tags = ["canon" if x == "oc" else x for x in orig_tags]

        upd_res = update_character("1791895360", cid, UpdateCharacterRequest(tags=test_tags))
        self.assertEqual(upd_res["status"], "success")

        # Verify mutation reflected
        updated_chars = {c["id"]: c for c in get_characters("1791895360")}
        self.assertEqual(updated_chars[cid]["tags"], test_tags)

        # Revert tags
        rev_res = update_character("1791895360", cid, UpdateCharacterRequest(tags=orig_tags))
        self.assertEqual(rev_res["status"], "success")

        # Verify revert
        reverted_chars = {c["id"]: c for c in get_characters("1791895360")}
        self.assertEqual(reverted_chars[cid]["tags"], orig_tags)

    def test_nest_and_unnest_character_roundtrip(self):
        chars = get_characters("1791895360")
        self.assertGreater(len(chars), 1)
        c_parent = chars[0]["id"]
        c_child = chars[-1]["id"]

        # Nest child under parent
        nest_res = nest_character(
            "1791895360",
            NestCharacterRequest(child_id=c_child, parent_id=c_parent, version_type="npc"),
        )
        self.assertEqual(nest_res["status"], "success")

        # Unnest back to root
        unnest_res = unnest_character("1791895360", c_child)
        self.assertEqual(unnest_res["status"], "success")

    def test_group_crud_roundtrip(self):
        chars = get_characters("1791895360")
        self.assertGreater(len(chars), 2)
        c1 = chars[1]["id"]
        c2 = chars[2]["id"]

        # Create group
        new_group = create_group(
            "1791895360",
            CreateGroupRequest(names=["TestSuite Alpha Group"], member_ids=[c1]),
        )
        self.assertIn("id", new_group)
        gid = new_group["id"]

        try:
            # Update group
            upd_res = update_group(
                "1791895360",
                gid,
                UpdateGroupRequest(names=["TestSuite Beta Group"], member_ids=[c1, c2]),
            )
            self.assertEqual(upd_res["status"], "success")

            # Verify in get_groups
            groups = get_groups("1791895360")
            matching = [g for g in groups if g["id"] == gid]
            self.assertEqual(len(matching), 1)
            self.assertIn("TestSuite Beta Group", matching[0]["names"])
        finally:
            # Clean up the test group from database and sync snapshot
            backup_path = t.get_backup_path("1791895360")
            with db_session(backup_id="1791895360", backup_path=backup_path) as session:
                session.query(CharacterModel).filter(CharacterModel.group_pk == gid).update({"group_pk": None})
                session.query(GroupNameModel).filter(GroupNameModel.group_pk == gid).delete()
                session.query(CharacterGroupModel).filter(CharacterGroupModel.pk == gid).delete()
                session.flush()
                export_character_list_snapshot(session, "1791895360", write_to_disk=True)

    def test_top_level_npc_tags_and_roundtrip(self):
        chars = get_characters("1791895360")
        # Character 18 ('Janitor') is a known top-level NPC in Elysium-sql-tests
        c18 = next((c for c in chars if c["id"] == 18), None)
        self.assertIsNotNone(c18)
        self.assertIn("npc", c18["tags"])

        # Check SQLite DB state directly
        backup_path = t.get_backup_path("1791895360")
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            db_char = session.query(CharacterModel).filter(
                CharacterModel.backup_id == "1791895360",
                CharacterModel.char_id == 18
            ).first()
            self.assertIsNotNone(db_char)
            self.assertIsNone(db_char.parent_pk)
            self.assertEqual(db_char.version_type, "npc")

        # Test updating a character on backup_id='1791895360' with NPC tag
        chars2 = get_characters("1791895360")
        target = chars2[0]
        cid = target["id"]
        orig_tags = list(target["tags"])
        new_tags = list(orig_tags)
        if "npc" not in new_tags:
            new_tags.append("npc")

        try:
            upd_res = update_character("1791895360", cid, UpdateCharacterRequest(tags=new_tags))
            self.assertEqual(upd_res["status"], "success")

            backup_path_2 = t.get_backup_path("1791895360")
            with db_session(backup_id="1791895360", backup_path=backup_path_2) as session:
                mutated = session.query(CharacterModel).filter(
                    CharacterModel.backup_id == "1791895360",
                    CharacterModel.char_id == cid
                ).first()
                self.assertEqual(mutated.version_type, "npc")
        finally:
            update_character("1791895360", cid, UpdateCharacterRequest(tags=orig_tags))


class TestBackupConfigEndpoints(unittest.TestCase):
    """Tests the backup config saving, loading, and run triggering endpoints."""

    @classmethod
    def setUpClass(cls):
        if not (DATA_ROOT / "Backups" / "Elysium-sql-tests" / "backup.sqlite").exists():
            migrate_for_tests("1791895360")
            SceneManager.clear_cache()
            close_all_engines()

    @classmethod
    def tearDownClass(cls):
        SceneManager.clear_cache()
        close_all_engines()
        reset_test_backup()

    def test_update_backup_config_and_run(self):
        from unittest.mock import MagicMock
        
        orig_config = get_backup_config("1791895360")
        modified_config = dict(orig_config)
        modified_config["test_field"] = "socrates_test_val"

        try:
            # 1. Test updating backup config succeeds without TypeError
            res = update_backup_config("1791895360", modified_config)
            self.assertEqual(res["status"], "success")

            # 2. Test reading back modified config
            saved = get_backup_config("1791895360")
            self.assertEqual(saved.get("test_field"), "socrates_test_val")

            # 3. Test run_backup without config passed (uses existing saved config)
            bg = MagicMock()
            res_run = run_backup("1791895360", bg, config=None)
            self.assertEqual(res_run["status"], "started")
            bg.add_task.assert_called_once()

            # 4. Test run_backup with config dict passed (saves config without error and starts)
            bg2 = MagicMock()
            res_run2 = run_backup("1791895360", bg2, config=modified_config)
            self.assertEqual(res_run2["status"], "started")
            bg2.add_task.assert_called_once()
        finally:
            # Clean up
            update_backup_config("1791895360", orig_config)

    def test_get_backup_logs(self):
        logs_res = get_backup_logs("1791895360", lines=5)
        self.assertIsInstance(logs_res, dict)
        self.assertIn("lines", logs_res)
        self.assertIsInstance(logs_res["lines"], list)

    def test_admin_reset_and_migrate_testing_backup(self):
        reset_res = reset_testing_backup()
        self.assertEqual(reset_res["status"], "success")
        self.assertFalse((DATA_ROOT / "Backups" / "Elysium-sql-tests" / "backup.sqlite").exists())

        mig_res = migrate_testing_backup()
        self.assertEqual(mig_res["status"], "success")
        self.assertIn("report", mig_res)
        self.assertTrue((DATA_ROOT / "Backups" / "Elysium-sql-tests" / "backup.sqlite").exists())
        self.assertEqual(mig_res["report"]["characters_count"], 20)
        self.assertEqual(mig_res["report"]["scenes_count"], 12)

    def test_admin_run_python_tests(self):
        from unittest.mock import patch, MagicMock

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "\033[92mTest output\033[0m\n"
        mock_proc.stderr = "Ran 37 tests in 1.234s\n\nOK\n"

        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            res = run_python_tests()
            mock_run.assert_called_once()
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["returncode"], 0)
            self.assertIn("Test output", res["output"])
            self.assertIn("Ran 37 tests", res["output"])
            self.assertNotIn("\033[92m", res["output"])


class TestOutdatedSchemaEndpoint(unittest.TestCase):
    """Tests loading backup info and curation summary on a database with an outdated schema."""

    TEST_BACKUP_ID = "1791895360"

    @classmethod
    def setUpClass(cls):
        reset_test_backup()
        migrate_for_tests(cls.TEST_BACKUP_ID)
        # Delete existing schema_version records and stamp as 3 to simulate an outdated database
        with db_session(cls.TEST_BACKUP_ID) as session:
            from db.models import SchemaVersionModel
            session.query(SchemaVersionModel).delete()
            stamp_schema_version(session, 3)

    @classmethod
    def tearDownClass(cls):
        close_all_engines()
        reset_test_backup()

    def test_outdated_schema_v3_loads_successfully(self):
        info = get_backup_info(self.TEST_BACKUP_ID)
        self.assertIsInstance(info, dict)
        self.assertTrue(info.get("is_schema_outdated"))
        self.assertEqual(info.get("schema_version"), 3)
        self.assertEqual(info.get("current_schema_version"), 5)
        self.assertGreater(info.get("number_of_scenes", 0), 0)

    def test_outdated_schema_curation_summary_does_not_fail(self):
        summary = get_curation_summary(self.TEST_BACKUP_ID)
        self.assertIsInstance(summary, dict)
        self.assertIn("unresolved_issues", summary)
        self.assertIn("unassigned_characters", summary)
        self.assertIn("flagged_messages", summary)
        self.assertIn("unlinked_writers", summary)

    def test_outdated_schema_my_writer_does_not_fail(self):
        writer = get_my_writer(self.TEST_BACKUP_ID, user={"sub": "nonexistent_discord_id"})
        self.assertIsNone(writer)


if __name__ == "__main__":
    unittest.main()

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from fastapi import HTTPException
from sqlalchemy import text, inspect
from sqlalchemy.exc import OperationalError

# Ensure src and project root are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
for p in (SRC_DIR.as_posix(), PROJECT_ROOT.as_posix()):
    if p not in sys.path:
        sys.path.insert(0, p)

from tests.test_env import skip_in_production_or_missing_fixture
DATA_ROOT = Path(os.environ.get("SOCRATES_DATA_DIR") or PROJECT_ROOT.as_posix())
from tests.reset_test_backup import reset_test_backup
# pyrefly: ignore [missing-import]
import utils.tricks as t
# pyrefly: ignore [missing-import]
from db.session import db_session, init_db, close_all_engines, stamp_schema_version
# pyrefly: ignore [missing-import]
from db.migrate import migrate_for_tests
# pyrefly: ignore [missing-import]
from db.models import CharacterGroupModel, GroupNameModel, CharacterModel, BackupModel
# pyrefly: ignore [missing-import]
from db.snapshots import export_character_list_snapshot
# pyrefly: ignore [missing-import]
from models import SceneManager
# pyrefly: ignore [missing-import]
import utils.exceptions as exc
# pyrefly: ignore [missing-import]
from server import (
    db_connection_exception_handler,
    schema_mismatch_exception_handler,
    database_exception_handler,
    get_backup_info,
    get_curation_summary,
    get_my_writer,
    sync_backup,
    reindex_backup,
    SyncBackupRequest,
    ReindexBackupRequest,
    get_characters,
    get_scenes,
    get_sessions,
    get_events,
    get_writers,
    get_writers_detailed,
    get_writer_link_suggestions,
    get_groups,
    get_scene_issues,
    get_flagged_messages,
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
    create_new_backup,
    run_backup,
    cancel_backup_action,
    run_script_in_background,
    get_backup_logs,
    clear_backup_logs,
    reset_testing_backup,
    migrate_testing_backup,
    run_python_tests,
)


@skip_in_production_or_missing_fixture()
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
        self.assertEqual(info["number_of_scenes"], 13)
        self.assertEqual(info["number_of_characters"], 20)
        self.assertIn("categories", info)
        self.assertGreater(len(info["categories"]), 0)
        self.assertIn("steps", info)
        self.assertIn("storage_mode", info)
        self.assertIn("sync_status", info)
        self.assertTrue(info["has_data_files"])

        # Verify has_data_files is False when Data/*.json files are absent
        import tempfile
        from unittest.mock import patch
        from db.status_service import init_backup_export
        from models import ServerBackup
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_b = Path(tmp_dir) / "EmptyBackupless"
            tmp_b.mkdir(parents=True, exist_ok=True)
            try:
                init_backup_export("777000201", tmp_b.as_posix(), ServerBackup("777000201", "EmptyBackupless", ""))
                with patch("server.resolve_authorized_backup", return_value=(tmp_b.as_posix(), {"sub": "1"}, "server_admin", 3, {"server_id": "1"})):
                    empty_info = get_backup_info("777000201")
                self.assertFalse(empty_info["has_data_files"])
            finally:
                close_all_engines()

    def test_sync_and_reindex_endpoints(self):
        from unittest.mock import MagicMock
        bg = MagicMock()
        backup_path = t.get_backup_path("1791895360")

        # 1. Incremental sync sets sync_status == 'syncing' and schedules backup_server.py
        res = sync_backup("1791895360", SyncBackupRequest(mode="incremental"), bg)
        self.assertEqual(res, {"status": "started", "mode": "incremental"})
        bg.add_task.assert_called_once()
        task_args = bg.add_task.call_args.args
        self.assertEqual(task_args[1], "backup_server.py")
        self.assertEqual(task_args[2], "1791895360")
        self.assertEqual(task_args[4], [])

        # 2. Duplicate sync or reindex while syncing raises 409
        with self.assertRaises(HTTPException) as ctx_sync:
            sync_backup("1791895360", SyncBackupRequest(mode="resume"), bg)
        self.assertEqual(ctx_sync.exception.status_code, 409)

        with self.assertRaises(HTTPException) as ctx_reindex:
            reindex_backup("1791895360", ReindexBackupRequest(rescan_json=False), bg)
        self.assertEqual(ctx_reindex.exception.status_code, 409)

        # Restore idle
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            backup = session.query(BackupModel).filter(
                BackupModel.backup_id == "1791895360"
            ).first()
            self.assertIsNotNone(backup)
            self.assertEqual(backup.sync_status, "syncing")
            backup.sync_status = "idle"
            backup.sync_started_at = None
            session.commit()

        # 3. Resume & rescan_discord pass strictly allowlisted CLI flags
        bg_resume = MagicMock()
        res_resume = sync_backup("1791895360", SyncBackupRequest(mode="resume"), bg_resume)
        self.assertEqual(res_resume["mode"], "resume")
        self.assertEqual(bg_resume.add_task.call_args.args[4], ["--resume"])
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            backup = session.query(BackupModel).filter_by(backup_id="1791895360").one()
            backup.sync_status = "idle"
            session.commit()

        bg_rescan = MagicMock()
        res_rescan = sync_backup("1791895360", SyncBackupRequest(mode="rescan_discord"), bg_rescan)
        self.assertEqual(res_rescan["mode"], "rescan_discord")
        self.assertEqual(bg_rescan.add_task.call_args.args[4], ["--rescan-discord"])
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            backup = session.query(BackupModel).filter_by(backup_id="1791895360").one()
            backup.sync_status = "idle"
            session.commit()

        # 4. rescan_local_json fails with 400 if storage_mode != 'full'
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            backup = session.query(BackupModel).filter_by(backup_id="1791895360").one()
            orig_mode = backup.storage_mode
            backup.storage_mode = "backupless"
            session.commit()

        try:
            with self.assertRaises(HTTPException) as ctx_400:
                sync_backup("1791895360", SyncBackupRequest(mode="rescan_local_json"), MagicMock())
            self.assertEqual(ctx_400.exception.status_code, 400)

            # In full mode (Elysium-sql-tests has Data/*.json), rescan_local_json succeeds
            with db_session(backup_id="1791895360", backup_path=backup_path) as session:
                backup = session.query(BackupModel).filter_by(backup_id="1791895360").one()
                backup.storage_mode = "full"
                session.commit()

            bg_local = MagicMock()
            res_local = sync_backup("1791895360", SyncBackupRequest(mode="rescan_local_json"), bg_local)
            self.assertEqual(res_local, {"status": "started", "mode": "rescan_local_json"})
            self.assertEqual(bg_local.add_task.call_args.args[1], "index_scenes.py")
            self.assertEqual(bg_local.add_task.call_args.args[4], ["--rescan-json"])
        finally:
            with db_session(backup_id="1791895360", backup_path=backup_path) as session:
                backup = session.query(BackupModel).filter_by(backup_id="1791895360").one()
                backup.storage_mode = orig_mode
                backup.sync_status = "idle"
                backup.sync_started_at = None
                session.commit()

        # 5. Offline reindex schedules index_scenes.py with no --rescan-json flag
        bg_reidx = MagicMock()
        res_reidx = reindex_backup("1791895360", ReindexBackupRequest(rescan_json=False), bg_reidx)
        self.assertEqual(res_reidx, {"status": "started", "rescan_json": False})
        self.assertEqual(bg_reidx.add_task.call_args.args[1], "index_scenes.py")
        self.assertEqual(bg_reidx.add_task.call_args.args[4], [])
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            backup = session.query(BackupModel).filter_by(backup_id="1791895360").one()
            backup.sync_status = "idle"
            backup.sync_started_at = None
            session.commit()

        # 6. Legacy /rerun/{action} route is removed
        import server as server_mod
        route_paths = {getattr(r, "path", "") for r in server_mod.app.routes}
        self.assertNotIn("/api/backups/{backup_id}/rerun/{action}", route_paths)
        self.assertIn("/api/backups/{backup_id}/sync", route_paths)
        self.assertIn("/api/backups/{backup_id}/reindex", route_paths)
        self.assertIn("/api/backups/{backup_id}/flagged-messages/{message_id}/full-content", route_paths)

    def test_run_script_in_background_failure_marks_step_failed(self):
        from unittest.mock import patch, MagicMock
        backup_path = t.get_backup_path("1791895360")

        # Disallowed scripts and disallowed flags must never spawn subprocesses
        with patch("subprocess.Popen") as mock_bad:
            run_script_in_background("assign_ids.py", "1791895360")
            run_script_in_background("index_scenes.py", "1791895360", extra_flags=["--evil"])
            mock_bad.assert_not_called()

        # Mock Popen to simulate a failed subprocess with exit code 1 and error output on stderr
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = ["Traceback (most recent call last):\n", "ModuleNotFoundError: No module named 'src'\n"]
        mock_proc.wait.return_value = 1

        with patch("subprocess.Popen", return_value=mock_proc):
            run_script_in_background("index_scenes.py", "1791895360", step_name="index_scenes")

        # Verify BackupModel was marked as failed in SQLite
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            backup = session.query(BackupModel).filter(
                BackupModel.backup_id == "1791895360"
            ).first()
            self.assertIsNotNone(backup)
            self.assertEqual(backup.sync_status, "failed")
            self.assertIn("ModuleNotFoundError", str(backup.sync_error))

            # Restore backup sync_status to idle
            backup.sync_status = "idle"
            backup.sync_error = None
            backup.sync_started_at = None
            session.commit()

    def test_cancel_backup_action_clears_running_steps(self):
        backup_path = t.get_backup_path("1791895360")
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            backup = session.query(BackupModel).filter(
                BackupModel.backup_id == "1791895360"
            ).first()
            self.assertIsNotNone(backup)
            backup.sync_status = "syncing"
            session.commit()

        # Cancel should mark the stuck sync as failed even when no process is active
        res = cancel_backup_action("1791895360")
        self.assertEqual(res["status"], "canceled")

        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            backup = session.query(BackupModel).filter(
                BackupModel.backup_id == "1791895360"
            ).first()
            self.assertEqual(backup.sync_status, "failed")

            # Restore backup sync_status to idle
            backup.sync_status = "idle"
            backup.sync_error = None
            backup.sync_started_at = None
            session.commit()

    def test_prelocked_sync_and_reindex_subprocesses_do_not_self_block(self):
        """
        Regression test: POST /reindex and POST /sync pre-set BackupModel.sync_status='syncing'
        in SQLite before spawning index_scenes.py / backup_server.py subprocesses.
        Subprocesses must NOT raise DataNotReadyError or false-positive AlreadyRunningError.
        """
        import httpx
        from unittest.mock import patch, MagicMock
        from db.models import SceneModel, SceneKind, EventModel
        from db.serializers import clear_runtime_step_overrides
        from index_scenes import index_scenes
        from backup_server import backup_server, _acquire_sync_lock, _release_sync_lock
        from models.backup_context import BackupContext
        from tests.test_env import use_socket_free_asyncio

        backup_path = t.get_backup_path("1791895360")
        try:
            # 1. Pre-lock via reindex_backup -> sets sync_status='syncing' + runtime Step.INDEX_SCENES='running'
            bg = MagicMock()
            reindex_backup("1791895360", ReindexBackupRequest(rescan_json=False), bg)

            # Simulate subprocess environment where in-memory _RUNTIME_STEP_OVERRIDES is empty
            clear_runtime_step_overrides("1791895360")

            with BackupContext.activate(backup_id="1791895360"):
                # Both skeleton offline re-index and full --rescan-json must succeed cleanly
                index_scenes(backup_id="1791895360", backup_path=backup_path, rescan_json=False)
                index_scenes(backup_id="1791895360", backup_path=backup_path, rescan_json=True)

            info = get_backup_info("1791895360")
            self.assertEqual(info["sync_status"], "idle")
            self.assertEqual(info["status"], "success")
            self.assertEqual(info["number_of_scenes"], 13)
            self.assertEqual(info["number_of_sessions"], 121)
            self.assertGreater(info["number_of_events"], 0)

            with db_session(backup_id="1791895360", backup_path=backup_path) as session:
                rp_cnt = session.query(SceneModel).filter_by(backup_id="1791895360", kind=SceneKind.SCENE.value).count()
                sess_cnt = session.query(SceneModel).filter_by(backup_id="1791895360", kind=SceneKind.SESSION.value).count()
                ev_cnt = session.query(EventModel).filter_by(backup_id="1791895360").count()
                self.assertEqual(rp_cnt, 13)
                self.assertEqual(sess_cnt, 121)
                self.assertEqual(ev_cnt, 4)

            # 2. Genuine concurrent lock must block, whereas pre-set DB sync_status='syncing' must NOT self-block
            _acquire_sync_lock(backup_path)
            try:
                with self.assertRaises(exc.AlreadyRunningError):
                    with BackupContext.activate(backup_id="1791895360"):
                        index_scenes(backup_id="1791895360", backup_path=backup_path, rescan_json=False)
            finally:
                _release_sync_lock(backup_path)

            def _ok_empty_handler(request: httpx.Request) -> httpx.Response:
                if request.url.path == "/api/v10/users/@me":
                    return httpx.Response(200, json={"id": "999", "username": "bot", "bot": True})
                if request.url.path.endswith("/members"):
                    return httpx.Response(200, json=[])
                if request.url.path.endswith("/threads/active"):
                    return httpx.Response(200, json={"threads": []})
                if request.url.path.endswith("/channels"):
                    return httpx.Response(200, json=[])
                if request.url.path.startswith("/api/v10/guilds/"):
                    return httpx.Response(200, json={"id": "857848490683269161", "name": "Diabolik: Elysium", "roles": []})
                return httpx.Response(404, json={"message": "Not Found"})

            sync_backup("1791895360", SyncBackupRequest(mode="incremental"), MagicMock())
            clear_runtime_step_overrides("1791895360")
            with use_socket_free_asyncio():
                with BackupContext.activate(backup_id="1791895360"):
                    sync_res = backup_server(
                        backup_id="1791895360",
                        backup_path=backup_path,
                        token="test-bot-token",
                        transport=httpx.MockTransport(_ok_empty_handler),
                    )
            self.assertEqual(sync_res["status"], "idle")
            with db_session(backup_id="1791895360", backup_path=backup_path) as session:
                b_row = session.query(BackupModel).filter_by(backup_id="1791895360").one()
                self.assertEqual(b_row.sync_status, "idle")
        finally:
            clear_runtime_step_overrides("1791895360")
            SceneManager.clear_cache()
            close_all_engines()
            migrate_for_tests("1791895360")
            SceneManager.clear_cache()
            close_all_engines()


@skip_in_production_or_missing_fixture()
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
        for key in ("id", "names", "writer", "tags", "other_versions", "scene_count", "last_active_at", "last_channel_name"):
            self.assertIn(key, sample)

        # Check other_versions has activity stats
        for c in chars:
            for child in c.get("other_versions", []):
                for key in ("id", "names", "scene_count", "last_active_at", "last_channel_name"):
                    self.assertIn(key, child)

    def test_get_characters_normalized_format(self):
        norm = get_characters("1791895360", format="normalized")
        self.assertIsInstance(norm, dict)
        self.assertIn("writers", norm)
        self.assertIn("groups", norm)
        self.assertIn("characters", norm)
        self.assertEqual(len(norm["characters"]), 20)
        sample = norm["characters"][0]
        for key in ("char_id", "names", "scene_count", "last_active_at", "last_channel_name"):
            self.assertIn(key, sample)

    def test_dev_login_deduplicates_authorized_guilds(self):
        from server import dev_login
        from unittest.mock import MagicMock, patch
        from fastapi import Response, Request

        mock_resp = Response()
        mock_req = MagicMock(spec=Request)
        mock_req.headers = {}
        mock_req.client = MagicMock(host="127.0.0.1")
        with patch.dict(
            os.environ,
            {
                "SOCRATES_ENV": "development",
                "SOCRATES_ENABLE_DEV_LOGIN": "true",
                "SOCRATES_DEV_ROLE": "instance_admin",
                "K_SERVICE": "",
            },
            clear=False,
        ):
            res = dev_login(mock_resp, mock_req)
        self.assertEqual(res["status"], "success")
        guilds = res["user"]["authorized_guilds"]
        guild_ids = [g["id"] for g in guilds]
        self.assertEqual(len(guild_ids), len(set(guild_ids)), "Guild IDs must be deduplicated in dev_login")

    def test_get_writers(self):
        writers = get_writers("1791895360")
        self.assertIsInstance(writers, list)
        self.assertGreater(len(writers), 2)

    def test_get_groups(self):
        groups = get_groups("1791895360")
        self.assertIsInstance(groups, list)
        self.assertGreater(len(groups), 0)


@skip_in_production_or_missing_fixture()
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
        self.assertEqual(scenes_res["total_items"], 13)
        self.assertEqual(scenes_res["current_page"], 1)
        self.assertEqual(len(scenes_res["scenes"]), 5)

        first_scene = scenes_res["scenes"][0]
        for key in ("category", "channel", "type", "status", "start", "end", "characters", "issues"):
            self.assertIn(key, first_scene)

    def test_get_scenes_search_matches_category_and_channel(self):
        all_res = get_scenes("1791895360", per_page=50)
        self.assertGreater(len(all_res["scenes"]), 0)
        sample_scene = all_res["scenes"][0]
        category_name = sample_scene["category"]
        self.assertTrue(category_name)

        cat_res = get_scenes("1791895360", search=category_name, per_page=50)
        self.assertGreater(cat_res["total_items"], 0)
        for s in cat_res["scenes"]:
            haystack = " ".join([
                s.get("custom_name") or "",
                s.get("scene_key") or "",
                s.get("channel") or "",
                s.get("category") or "",
            ]).lower()
            self.assertIn(category_name.lower(), haystack)

    def test_get_scenes_writer_filter(self):
        writers = get_writers("1791895360")
        self.assertGreater(len(writers), 2)
        target_writer = writers[0]

        filtered = get_scenes("1791895360", writers=[target_writer])
        self.assertIsInstance(filtered, dict)
        self.assertGreater(filtered["total_items"], 0)
        self.assertLessEqual(filtered["total_items"], 13)

    def test_get_scenes_character_group_filter(self):
        all_scenes = get_scenes("1791895360", per_page=50)["scenes"]
        scene_chars = []
        for s in all_scenes:
            for cid in (s.get("characters") or []):
                if cid not in scene_chars:
                    scene_chars.append(cid)
                if len(scene_chars) >= 2:
                    break
            if len(scene_chars) >= 2:
                break
        self.assertGreaterEqual(len(scene_chars), 2)

        member_ids = set(scene_chars[:2])
        expected_keys = {
            s["scene_key"] for s in all_scenes if set(s.get("characters") or []) & member_ids
        }
        new_group = create_group(
            "1791895360",
            CreateGroupRequest(names=["TestSuite Scene Filter Group"], member_ids=list(member_ids)),
        )
        gid = new_group["id"]
        try:
            filtered = get_scenes(
                "1791895360",
                character_groups=[gid],
                character_logic="AND",
            )
            self.assertIsInstance(filtered, dict)
            self.assertEqual(filtered["total_items"], len(expected_keys))
            returned_keys = {s["scene_key"] for s in filtered["scenes"]}
            self.assertEqual(returned_keys, expected_keys)
        finally:
            backup_path = t.get_backup_path("1791895360")
            with db_session(backup_id="1791895360", backup_path=backup_path) as session:
                session.query(CharacterModel).filter(CharacterModel.group_pk == gid).update({"group_pk": None})
                session.query(GroupNameModel).filter(GroupNameModel.group_pk == gid).delete()
                session.query(CharacterGroupModel).filter(CharacterGroupModel.pk == gid).delete()
                session.flush()
                export_character_list_snapshot(session, "1791895360", write_to_disk=True)


@skip_in_production_or_missing_fixture()
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

        # Search by category name ("Events")
        cat_search = get_events("1791895360", search="Events")
        self.assertEqual(cat_search["total_items"], all_res["total_items"])


@skip_in_production_or_missing_fixture()
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

    def test_character_writer_id_update_and_unassign(self):
        from server import get_writers_detailed
        chars = get_characters("1791895360")
        writers_detailed = get_writers_detailed("1791895360")
        self.assertGreater(len(chars), 0)
        self.assertGreater(len(writers_detailed), 1)

        target_char = chars[0]
        cid = target_char["id"]
        orig_writer_id = target_char.get("writer_id")
        alt_writer = next((w for w in writers_detailed if w["id"] != orig_writer_id), writers_detailed[0])

        try:
            # Assign by writer_id
            assign_res = update_character("1791895360", cid, UpdateCharacterRequest(writer_id=alt_writer["id"]))
            self.assertEqual(assign_res["status"], "success")
            self.assertEqual(assign_res["character"]["writer_id"], alt_writer["id"])

            # Unassign via explicit writer_id=None
            unassign_res = update_character("1791895360", cid, UpdateCharacterRequest(writer_id=None))
            self.assertEqual(unassign_res["status"], "success")
            self.assertIsNone(unassign_res["character"]["writer_id"])
            self.assertEqual(unassign_res["character"]["writer"], [])
        finally:
            update_character("1791895360", cid, UpdateCharacterRequest(writer_id=orig_writer_id))

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


@skip_in_production_or_missing_fixture()
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
        import copy
        import tempfile
        from unittest.mock import MagicMock, patch
        from db.models import BackupCategoryConfigModel, CategoryConfigKind

        orig_config = get_backup_config("1791895360")
        self.assertNotIn("rbac", orig_config)
        modified_config = copy.deepcopy(orig_config)
        modified_config["admin"]["keepMode"] = True
        modified_config["admin"]["categoriesToKeep"] = ["1019770957172326470"]
        modified_config["admin"]["chatroomCategories"] = ["1106268351220678767"]
        modified_config["admin"]["eventCategories"] = ["1106268351220678999"]
        modified_config["admin"]["verbosity"]["debugFiles"] = False

        backup_path = t.get_backup_path("1791895360")
        try:
            # 1. Test updating backup config succeeds and persists to SQLite
            res = update_backup_config("1791895360", modified_config)
            self.assertEqual(res["status"], "success")

            # 2. Test reading back modified config from SQLite
            saved = get_backup_config("1791895360")
            self.assertNotIn("rbac", saved)
            self.assertTrue(saved["admin"]["keepMode"])
            self.assertEqual(saved["admin"]["categoriesToKeep"], ["1019770957172326470"])
            self.assertEqual(saved["admin"]["chatroomCategories"], ["1106268351220678767"])
            self.assertEqual(saved["admin"]["eventCategories"], ["1106268351220678999"])
            self.assertFalse(saved["admin"]["verbosity"]["debugFiles"])

            with db_session(backup_id="1791895360", backup_path=backup_path) as session:
                b_row = session.query(BackupModel).filter_by(backup_id="1791895360").one()
                self.assertTrue(b_row.keep_mode)
                self.assertFalse(b_row.debug_files)
                cat_rows = (
                    session.query(BackupCategoryConfigModel)
                    .filter_by(backup_id="1791895360")
                    .all()
                )
                by_kind = {(r.kind, r.category_ref) for r in cat_rows}
                self.assertIn((CategoryConfigKind.KEEP.value, "1019770957172326470"), by_kind)
                self.assertIn((CategoryConfigKind.CHATROOM.value, "1106268351220678767"), by_kind)
                self.assertIn((CategoryConfigKind.EVENT.value, "1106268351220678999"), by_kind)

            # 3. Verify SQLite config read/write works even when backup_config.json is absent
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_backup_dir = Path(tmp_dir) / "Backups" / "NoJsonConfig"
                tmp_backup_dir.mkdir(parents=True, exist_ok=True)
                init_db(backup_id="777000301", backup_path=tmp_backup_dir.as_posix())
                with db_session(backup_id="777000301", backup_path=tmp_backup_dir.as_posix()) as session:
                    session.add(
                        BackupModel(
                            backup_id="777000301",
                            backup_name="NoJsonBackup",
                            server_id="857848490683269161",
                            server_name="NoJson Guild",
                            path="Backups/NoJsonConfig",
                        )
                    )
                self.assertFalse((tmp_backup_dir / "backup_config.json").exists())
                with patch(
                    "server.resolve_authorized_backup",
                    return_value=(tmp_backup_dir.as_posix(), {"sub": "1"}, "server_admin", 4, {"server_id": "857848490683269161"}),
                ), patch(
                    "server.get_authorized_backup_path",
                    return_value=tmp_backup_dir.as_posix(),
                ):
                    upd_res = update_backup_config(
                        "777000301",
                        {
                            "admin": {
                                "backupName": "UpdatedNoJson",
                                "keepMode": True,
                                "categoriesToKeep": ["999888777666555444"],
                            }
                        },
                    )
                    self.assertEqual(upd_res["status"], "success")
                    self.assertFalse((tmp_backup_dir / "backup_config.json").exists())
                    loaded_no_json = get_backup_config("777000301")
                    self.assertEqual(loaded_no_json["admin"]["backupName"], "UpdatedNoJson")
                    self.assertTrue(loaded_no_json["admin"]["keepMode"])
                    self.assertEqual(loaded_no_json["admin"]["categoriesToKeep"], ["999888777666555444"])

                    # Verify update_backup_config preserves existing RBAC even if payload contains rbac
                    from db.config_service import load_rbac_config_dict, save_rbac_config_dict
                    save_rbac_config_dict(
                        backup_id="777000301",
                        backup_path=tmp_backup_dir.as_posix(),
                        rbac_data={"adminRoleIds": ["123456789012345678"]},
                    )
                    update_backup_config(
                        "777000301",
                        {
                            "admin": {"backupName": "UpdatedWithRbacKey"},
                            "rbac": {"adminRoleIds": []},
                        },
                    )
                    self.assertEqual(
                        load_rbac_config_dict(backup_id="777000301", backup_path=tmp_backup_dir.as_posix())["adminRoleIds"],
                        ["123456789012345678"],
                    )
                close_all_engines()

            # 4. Test run_backup without config passed (uses existing saved config)
            bg = MagicMock()
            res_run = run_backup("1791895360", bg, config=None)
            self.assertEqual(res_run["status"], "started")
            bg.add_task.assert_called_once()

            # 5. Test run_backup with config dict passed (saves config without error and starts)
            bg2 = MagicMock()
            res_run2 = run_backup("1791895360", bg2, config=modified_config)
            self.assertEqual(res_run2["status"], "started")
            bg2.add_task.assert_called_once()
        finally:
            # Clean up
            update_backup_config("1791895360", orig_config)

    def test_create_new_backup_initializes_sql_and_does_not_touch_global_config(self):
        import asyncio
        import tempfile
        from fastapi import BackgroundTasks
        from unittest.mock import patch
        from db.models import BackupCategoryConfigModel, BackupRbacEntryModel, CategoryConfigKind, SyncStatus
        from tests.test_env import use_socket_free_asyncio

        global_cfg_path = PROJECT_ROOT / "res" / "config.json"
        global_cfg_before = global_cfg_path.read_text(encoding="utf-8") if global_cfg_path.exists() else None
        global_mtime_before = global_cfg_path.stat().st_mtime_ns if global_cfg_path.exists() else None

        payload = {
            "admin": {
                "serverId": "857848490683269161",
                "serverName": "Create Test Guild",
                "backupName": "My New SQL Backup!",
                "storageMode": "full",
                "keepMode": True,
                "categoriesToKeep": ["1019770957172326470"],
                "chatroomCategories": ["1106268351220678767"],
                "eventCategories": ["1106268351220678999"],
                "verbosity": {
                    "info": True,
                    "debug": False,
                    "console": True,
                    "log": True,
                    "debugFiles": False,
                },
            },
            "rbac": {
                "adminRoleIds": ["100000000000000001"],
                "curatorRoleIds": ["100000000000000002"],
                "participantRoleIds": [],
                "restrictedUserIds": [],
                "blockedUserIds": [],
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                t.invalidate_backups_index_cache()
                bg = BackgroundTasks()
                with patch.dict(os.environ, {"SOCRATES_DATA_DIR": tmp_dir}, clear=False):
                    with patch("server.run_script_in_background") as mock_bg_run:
                        res = create_new_backup(payload, bg)
                        with use_socket_free_asyncio():
                            asyncio.run(bg())

                self.assertEqual(res["status"], "started")
                created_id = res["backup_id"]
                rel_path = res["path"]
                self.assertTrue(created_id)
                self.assertTrue(rel_path.startswith("Backups/"))
                mock_bg_run.assert_called_once_with("backup_server.py", created_id)

                # Verify res/config.json was NOT touched
                if global_cfg_before is not None:
                    self.assertEqual(global_cfg_path.read_text(encoding="utf-8"), global_cfg_before)
                    self.assertEqual(global_cfg_path.stat().st_mtime_ns, global_mtime_before)

                # Verify backup.sqlite exists and has BackupModel, BackupCategoryConfigModel, and BackupRbacEntryModel
                new_backup_dir = Path(tmp_dir) / rel_path
                self.assertTrue((new_backup_dir / "backup.sqlite").is_file())
                with db_session(backup_id=created_id, backup_path=new_backup_dir.as_posix()) as session:
                    b_row = session.query(BackupModel).filter_by(backup_id=created_id).one()
                    self.assertEqual(b_row.backup_name, "My New SQL Backup!")
                    self.assertEqual(b_row.server_id, "857848490683269161")
                    self.assertEqual(b_row.storage_mode, "full")
                    self.assertTrue(b_row.keep_mode)
                    self.assertFalse(b_row.log_debug)
                    self.assertEqual(b_row.sync_status, SyncStatus.SYNCING.value)

                    cats = session.query(BackupCategoryConfigModel).filter_by(backup_id=created_id).all()
                    cat_pairs = {(c.kind, c.category_ref) for c in cats}
                    self.assertEqual(
                        cat_pairs,
                        {
                            (CategoryConfigKind.KEEP.value, "1019770957172326470"),
                            (CategoryConfigKind.CHATROOM.value, "1106268351220678767"),
                            (CategoryConfigKind.EVENT.value, "1106268351220678999"),
                        },
                    )

                    rbac_rows = session.query(BackupRbacEntryModel).filter_by(backup_id=created_id).all()
                    rbac_tuples = {(r.target_type, r.access_level, r.discord_id) for r in rbac_rows}
                    self.assertEqual(
                        rbac_tuples,
                        {
                            ("role", "admin", "100000000000000001"),
                            ("role", "curator", "100000000000000002"),
                        },
                    )

                # Verify t.get_backups_index() immediately discovers the newly created backup
                with patch.dict(os.environ, {"SOCRATES_DATA_DIR": tmp_dir}, clear=False):
                    t.invalidate_backups_index_cache()
                    idx = t.get_backups_index()
                self.assertTrue(any(str(item.get("backup_id")) == created_id for item in idx))
            finally:
                close_all_engines()
                t.invalidate_backups_index_cache()

    def test_get_backup_logs(self):
        logs_res = get_backup_logs("1791895360", lines=5)
        self.assertIsInstance(logs_res, dict)
        self.assertIn("lines", logs_res)
        self.assertIsInstance(logs_res["lines"], list)

    def test_clear_backup_logs(self):
        log_path = DATA_ROOT / "Backups" / "Elysium-sql-tests" / "log.txt"
        had_file = log_path.exists()
        orig_content = log_path.read_text(encoding="utf-8") if had_file else ""
        try:
            log_path.write_text("line1\nline2\n", encoding="utf-8")
            res = clear_backup_logs("1791895360")
            self.assertEqual(res, {"status": "cleared"})
            self.assertEqual(log_path.read_text(encoding="utf-8"), "")
        finally:
            if had_file:
                log_path.write_text(orig_content, encoding="utf-8")
            else:
                log_path.write_text("", encoding="utf-8")

    def test_dev_login_endpoint(self):
        # pyrefly: ignore [missing-import]
        from server import dev_login
        from fastapi import Response
        from unittest.mock import MagicMock, patch
        mock_req = MagicMock()
        mock_req.headers = {}
        mock_req.client = MagicMock(host="127.0.0.1")
        resp = Response()
        with patch.dict(
            os.environ,
            {
                "SOCRATES_ENV": "development",
                "SOCRATES_ENABLE_DEV_LOGIN": "true",
                "SOCRATES_DEV_ROLE": "instance_admin",
                "K_SERVICE": "",
            },
            clear=False,
        ):
            res = dev_login(resp, mock_req)
        self.assertEqual(res["status"], "success")
        self.assertIn("user", res)
        self.assertIn("authorized_guilds", res["user"])

    def test_admin_reset_and_migrate_testing_backup(self):
        reset_res = reset_testing_backup()
        self.assertEqual(reset_res["status"], "success")
        self.assertFalse((DATA_ROOT / "Backups" / "Elysium-sql-tests" / "backup.sqlite").exists())

        mig_res = migrate_testing_backup()
        self.assertEqual(mig_res["status"], "success")
        self.assertIn("report", mig_res)
        self.assertTrue((DATA_ROOT / "Backups" / "Elysium-sql-tests" / "backup.sqlite").exists())
        self.assertEqual(mig_res["report"]["characters_count"], 20)
        self.assertEqual(mig_res["report"]["scenes_count"], 13)

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


@skip_in_production_or_missing_fixture()
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
        try:
            with db_session(cls.TEST_BACKUP_ID) as session:
                from db.models import SchemaVersionModel, CURRENT_SCHEMA_VERSION
                session.query(SchemaVersionModel).delete()
                stamp_schema_version(
                    session,
                    CURRENT_SCHEMA_VERSION,
                    description="Restored after TestOutdatedSchemaEndpoint",
                )
        except Exception:
            pass
        close_all_engines()
        reset_test_backup()

    def test_outdated_schema_v3_loads_successfully(self):
        info = get_backup_info(self.TEST_BACKUP_ID)
        self.assertIsInstance(info, dict)
        self.assertTrue(info.get("is_schema_outdated"))
        self.assertEqual(info.get("schema_version"), 3)
        from db.models import CURRENT_SCHEMA_VERSION
        self.assertEqual(info.get("current_schema_version"), CURRENT_SCHEMA_VERSION)
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


@skip_in_production_or_missing_fixture()
class TestErrorHandlingHTTP(unittest.TestCase):
    """Tests graceful server error handling and exception handler payloads for nonexistent, missing-DB, and outdated-schema backups."""

    TEST_BACKUP_ID = "1791895360"
    MISSING_BACKUP_ID = "999999999999"

    def setUp(self):
        reset_test_backup()
        close_all_engines()

    def tearDown(self):
        close_all_engines()
        reset_test_backup()

    @staticmethod
    def _run_handler(coro):
        try:
            coro.send(None)
        except StopIteration as stop:
            return stop.value
        raise AssertionError("Exception handler unexpectedly yielded")

    @staticmethod
    def _mock_request(path: str = "/api/test"):
        req = MagicMock()
        req.url.path = path
        req.state = MagicMock()
        return req

    def test_exception_handlers_return_explicit_json_codes(self):
        req = self._mock_request("/api/backups/1791895360/scenes")

        resp_404 = self._run_handler(
            db_connection_exception_handler(req, exc.DatabaseConnectionError("No SQLite DB found"))
        )
        self.assertEqual(resp_404.status_code, 404)
        self.assertEqual(json.loads(resp_404.body), {"detail": "No SQLite DB found", "error": "database_not_found"})

        resp_400 = self._run_handler(
            schema_mismatch_exception_handler(req, exc.DatabaseSchemaMismatchError("Schema outdated"))
        )
        self.assertEqual(resp_400.status_code, 400)
        self.assertEqual(json.loads(resp_400.body), {"detail": "Schema outdated", "error": "schema_mismatch"})

        resp_500 = self._run_handler(
            database_exception_handler(req, OperationalError("SELECT 1", {}, Exception("line1\nline2")))
        )
        self.assertEqual(resp_500.status_code, 500)
        payload_500 = json.loads(resp_500.body)
        self.assertEqual(payload_500.get("error"), "database_error")
        self.assertNotIn("\n", payload_500.get("detail", ""))

    def test_missing_database_raises_database_connection_error(self):
        mock_req = self._mock_request()
        fake_user = {"sub": "test_user_123"}
        calls = [
            ("get_backup_info", lambda: get_backup_info(self.TEST_BACKUP_ID)),
            ("get_curation_summary", lambda: get_curation_summary(self.TEST_BACKUP_ID)),
            ("get_my_writer", lambda: get_my_writer(self.TEST_BACKUP_ID, user=fake_user)),
            ("get_characters", lambda: get_characters(self.TEST_BACKUP_ID)),
            ("get_characters_by_me", lambda: get_characters(self.TEST_BACKUP_ID, by_me=True, request=mock_req)),
            ("get_groups", lambda: get_groups(self.TEST_BACKUP_ID)),
            ("get_writers", lambda: get_writers(self.TEST_BACKUP_ID)),
            ("get_writers_detailed", lambda: get_writers_detailed(self.TEST_BACKUP_ID)),
            ("get_writer_link_suggestions", lambda: get_writer_link_suggestions(self.TEST_BACKUP_ID)),
            ("get_scenes", lambda: get_scenes(self.TEST_BACKUP_ID)),
            ("get_scenes_by_me", lambda: get_scenes(self.TEST_BACKUP_ID, by_me=True, request=mock_req)),
            ("get_sessions", lambda: get_sessions(self.TEST_BACKUP_ID)),
            ("get_sessions_by_me", lambda: get_sessions(self.TEST_BACKUP_ID, by_me=True, request=mock_req)),
            ("get_events", lambda: get_events(self.TEST_BACKUP_ID)),
            ("get_events_by_me", lambda: get_events(self.TEST_BACKUP_ID, by_me=True, request=mock_req)),
            ("get_scene_issues", lambda: get_scene_issues(self.TEST_BACKUP_ID)),
            ("get_flagged_messages", lambda: get_flagged_messages(self.TEST_BACKUP_ID)),
        ]
        for name, fn in calls:
            with self.subTest(endpoint=name):
                with self.assertRaises(exc.DatabaseConnectionError):
                    fn()

    def test_nonexistent_backup_raises_404_or_missing_db_not_500(self):
        fake_user = {"sub": "test_user_123"}
        calls = [
            ("get_backup_info", lambda: get_backup_info(self.MISSING_BACKUP_ID)),
            ("get_curation_summary", lambda: get_curation_summary(self.MISSING_BACKUP_ID)),
            ("get_my_writer", lambda: get_my_writer(self.MISSING_BACKUP_ID, user=fake_user)),
            ("get_characters", lambda: get_characters(self.MISSING_BACKUP_ID)),
            ("get_scenes", lambda: get_scenes(self.MISSING_BACKUP_ID)),
            ("get_sessions", lambda: get_sessions(self.MISSING_BACKUP_ID)),
            ("get_events", lambda: get_events(self.MISSING_BACKUP_ID)),
            ("get_scene_issues", lambda: get_scene_issues(self.MISSING_BACKUP_ID)),
            ("get_flagged_messages", lambda: get_flagged_messages(self.MISSING_BACKUP_ID)),
        ]
        for name, fn in calls:
            with self.subTest(endpoint=name):
                try:
                    fn()
                    self.fail(f"{name} unexpectedly succeeded for nonexistent backup")
                except HTTPException as http_err:
                    self.assertEqual(http_err.status_code, 404)
                except exc.DatabaseConnectionError:
                    pass

    def test_outdated_schema_does_not_mutate_db_or_return_500(self):
        migrate_for_tests(self.TEST_BACKUP_ID)
        with db_session(self.TEST_BACKUP_ID) as session:
            from db.models import SchemaVersionModel
            session.query(SchemaVersionModel).delete()
            stamp_schema_version(session, 4)
            # Simulate an older v4 database that did not yet have the events table
            session.execute(text("DROP TABLE IF EXISTS events"))
            session.commit()
        close_all_engines()

        info_data = get_backup_info(self.TEST_BACKUP_ID)
        self.assertTrue(info_data.get("is_schema_outdated"))
        self.assertEqual(info_data.get("schema_version"), 4)
        self.assertEqual(info_data.get("number_of_events"), 0)

        summary_data = get_curation_summary(self.TEST_BACKUP_ID)
        self.assertIsInstance(summary_data, dict)

        writer_data = get_my_writer(self.TEST_BACKUP_ID, user={"sub": "nonexistent_discord_id"})
        self.assertIsNone(writer_data)

        # Ensure read-only status/summary endpoints did NOT run create_all() to recreate 'events'
        tables = set(inspect(init_db(self.TEST_BACKUP_ID, check_version=False)).get_table_names())
        self.assertNotIn("events", tables)

        # Schema-dependent endpoints should fail explicitly with DatabaseSchemaMismatchError (400), never 500
        mismatch_calls = [
            ("get_scenes", lambda: get_scenes(self.TEST_BACKUP_ID)),
            ("get_sessions", lambda: get_sessions(self.TEST_BACKUP_ID)),
            ("get_events", lambda: get_events(self.TEST_BACKUP_ID)),
            ("get_characters", lambda: get_characters(self.TEST_BACKUP_ID)),
            ("get_groups", lambda: get_groups(self.TEST_BACKUP_ID)),
            ("get_writers_detailed", lambda: get_writers_detailed(self.TEST_BACKUP_ID)),
            ("get_writer_link_suggestions", lambda: get_writer_link_suggestions(self.TEST_BACKUP_ID)),
            ("get_scene_issues", lambda: get_scene_issues(self.TEST_BACKUP_ID)),
            ("get_flagged_messages", lambda: get_flagged_messages(self.TEST_BACKUP_ID)),
        ]
        for name, fn in mismatch_calls:
            with self.subTest(endpoint=name):
                with self.assertRaises(exc.DatabaseSchemaMismatchError):
                    fn()


if __name__ == "__main__":
    unittest.main()

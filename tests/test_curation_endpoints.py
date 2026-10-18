import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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
from db.models import (
    CharacterModel,
    FlaggedKind,
    FlaggedMessageModel,
    MessageOverrideModel,
    SceneIssueModel,
    WriterModel,
)
# pyrefly: ignore [missing-import]
from db.session import db_session, close_all_engines
# pyrefly: ignore [missing-import]
from db.migrate import migrate_for_tests
# pyrefly: ignore [missing-import]
from models import SceneManager
# pyrefly: ignore [missing-import]
from server import (
    AssignCharacterWriterRequest,
    CreateGroupRequest,
    CreateWriterRequest,
    PromoteFlaggedMessageRequest,
    ResolveIssueRequest,
    UpdateWriterRequest,
    assign_character_writer,
    create_group,
    create_writer,
    delete_group,
    delete_message_override,
    delete_writer,
    get_characters,
    get_curation_summary,
    get_flagged_messages,
    get_message_overrides,
    get_my_writer,
    get_scene_issues,
    get_scenes,
    get_unassigned_characters,
    get_writer_link_suggestions,
    get_writers_detailed,
    promote_flagged_message,
    reopen_scene_issue,
    resolve_scene_issue,
    update_writer,
)


class TestWritersCuration(unittest.TestCase):
    """Tests writers management and link suggestions endpoints."""

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

    def test_get_writers_detailed(self):
        writers = get_writers_detailed("1791895360")
        self.assertIsInstance(writers, list)
        self.assertGreater(len(writers), 0)

        sample = writers[0]
        for key in ("id", "display_name", "discord_user_id", "aliases", "character_count", "characters"):
            self.assertIn(key, sample)

    def test_writer_crud_roundtrip(self):
        # Create writer on backup 'Elysium-sql-tests'
        new_w = create_writer(
            "1791895360",
            CreateWriterRequest(
                display_name="TestSuite Author X",
                aliases=["AuthorX", "ax_alias"],
                discord_user_id="999888777666",
            ),
        )
        self.assertIn("id", new_w)
        wid = new_w["id"]

        try:
            # Update writer
            upd_w = update_writer(
                "1791895360",
                wid,
                UpdateWriterRequest(
                    display_name="TestSuite Author Y",
                    aliases=["AuthorY", "ay_alias"],
                    discord_user_id="999888777555",
                ),
            )
            self.assertEqual(upd_w["display_name"], "TestSuite Author Y")
            self.assertIn("AuthorY", upd_w["aliases"])
            self.assertEqual(upd_w["discord_user_id"], "999888777555")

            # Verify in detailed list
            detailed = get_writers_detailed("1791895360")
            matching = [w for w in detailed if w["id"] == wid]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["display_name"], "TestSuite Author Y")
        finally:
            # Delete writer
            del_res = delete_writer("1791895360", wid)
            self.assertEqual(del_res["status"], "success")

            # Verify writer is gone
            detailed_after = get_writers_detailed("1791895360")
            self.assertFalse(any(w["id"] == wid for w in detailed_after))

    def test_writer_link_suggestions(self):
        backup_path = t.get_backup_path("1791895360")
        # Temporarily ensure Tera is unlinked so suggestions can be tested deterministically
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            target_writer = (
                session.query(WriterModel)
                .filter(
                    WriterModel.backup_id == "1791895360",
                    WriterModel.display_name.in_(["Tera"]),
                )
                .first()
            )
            self.assertIsNotNone(target_writer)
            target_name = target_writer.display_name
            orig_discord_id = target_writer.discord_user_id
            target_writer.discord_user_id = None
            session.commit()

        try:
            suggestions = get_writer_link_suggestions("1791895360")
            self.assertIsInstance(suggestions, list)
            self.assertGreater(len(suggestions), 0)

            # Check structure
            sample = suggestions[0]
            for key in (
                "writer_pk",
                "display_name",
                "suggested_discord_user_id",
                "confidence",
                "reason",
            ):
                self.assertIn(key, sample)

            # Verify known suggestion (e.g. Maca or Slothy)
            suggested_names = {s["display_name"] for s in suggestions}
            self.assertTrue("Tera" in suggested_names)
        finally:
            with db_session(backup_id="1791895360", backup_path=backup_path) as session:
                session.query(WriterModel).filter(
                    WriterModel.backup_id == "1791895360",
                    WriterModel.display_name == target_name,
                ).update({"discord_user_id": orig_discord_id})
                session.commit()


class TestUnassignedCharactersQueue(unittest.TestCase):
    """Tests the queue and assignment of characters without a writer."""

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

    def test_unassigned_characters_queue_and_assignment(self):
        backup_path = t.get_backup_path("1791895360")

        # Pick a character in backup 'Elysium-sql-tests' and temporarily unassign their writer
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            char = session.query(CharacterModel).filter(
                CharacterModel.backup_id == "1791895360",
                CharacterModel.writer_pk.isnot(None),
            ).first()
            self.assertIsNotNone(char)
            target_cid = char.char_id
            orig_writer_pk = char.writer_pk

            char.writer_pk = None
            session.commit()

        try:
            # Verify character appears in unassigned queue
            unassigned = get_unassigned_characters("1791895360")
            self.assertTrue(any(c["id"] == target_cid for c in unassigned))

            # Assign writer back
            assign_res = assign_character_writer(
                "1791895360",
                target_cid,
                AssignCharacterWriterRequest(writer_id=orig_writer_pk),
            )
            self.assertEqual(assign_res["status"], "success")
            self.assertEqual(assign_res["char_id"], target_cid)

            # Verify character is no longer in unassigned queue
            unassigned_after = get_unassigned_characters("1791895360")
            self.assertFalse(any(c["id"] == target_cid for c in unassigned_after))
        finally:
            # Restore writer just in case
            with db_session(backup_id="1791895360", backup_path=backup_path) as session:
                session.query(CharacterModel).filter(
                    CharacterModel.backup_id == "1791895360",
                    CharacterModel.char_id == target_cid,
                ).update({"writer_pk": orig_writer_pk})
                session.commit()


class TestCharacterGroupsCuration(unittest.TestCase):
    """Tests character group creation and deletion."""

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

    def test_group_create_and_delete(self):
        chars = get_characters("1791895360")
        self.assertGreater(len(chars), 1)
        c1 = chars[0]["id"]

        # Create group
        new_g = create_group(
            "1791895360",
            CreateGroupRequest(names=["Group To Delete Test"], member_ids=[c1]),
        )
        gid = new_g["id"]

        # Delete group
        del_res = delete_group("1791895360", gid)
        self.assertEqual(del_res["status"], "success")

        # Verify character no longer associated with the deleted group
        backup_path = t.get_backup_path("1791895360")
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            c_check = session.query(CharacterModel).filter(
                CharacterModel.backup_id == "1791895360",
                CharacterModel.char_id == c1,
            ).first()
            self.assertIsNone(c_check.group_pk)


class TestSceneIssuesReviewQueue(unittest.TestCase):
    """Tests querying, resolving, and reopening scene issues."""

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

    def test_get_scene_issues_pagination_and_structure(self):
        issues_res = get_scene_issues("1791895360", status="all", per_page=10)
        self.assertIsInstance(issues_res, dict)
        self.assertGreater(issues_res["total_items"], 0)
        self.assertEqual(len(issues_res["issues"]), 10)

        first_issue = issues_res["issues"][0]
        for key in (
            "id",
            "kind",
            "scene_key",
            "channel_name",
            "channel_discord_id",
            "discord_link",
            "created_at",
        ):
            self.assertIn(key, first_issue)

    def test_resolve_and_reopen_issue_roundtrip(self):
        issues_res = get_scene_issues("1791895360", status="unresolved", per_page=1)
        self.assertGreater(len(issues_res["issues"]), 0)
        target_issue = issues_res["issues"][0]
        iid = target_issue["id"]

        # Resolve issue
        res_res = resolve_scene_issue(
            "1791895360",
            iid,
            ResolveIssueRequest(note="Verified intentional gap in automated test"),
        )
        self.assertEqual(res_res["status"], "success")
        self.assertIsNotNone(res_res["resolved_at"])
        self.assertEqual(res_res["resolved_note"], "Verified intentional gap in automated test")

        # Reopen issue
        reopen_res = reopen_scene_issue("1791895360", iid)
        self.assertEqual(reopen_res["status"], "success")
        self.assertTrue(reopen_res["reopened"])

        # Verify reopened issue is unresolved
        backup_path = t.get_backup_path("1791895360")
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            issue_check = session.query(SceneIssueModel).filter_by(pk=iid).first()
            self.assertIsNone(issue_check.resolved_at)
            self.assertIsNone(issue_check.resolved_note)


class TestFlaggedMessagesAndOverrides(unittest.TestCase):
    """Tests flagged messages querying, promotion to message overrides, and deletion."""

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

    def test_get_flagged_messages_pagination(self):
        flagged_res = get_flagged_messages("1", per_page=10)
        self.assertIsInstance(flagged_res, dict)
        self.assertGreater(flagged_res["total_items"], 0)
        self.assertEqual(len(flagged_res["messages"]), 10)

        first_msg = flagged_res["messages"][0]
        for key in ("id", "message_id", "kind", "channel_name", "content", "author", "discord_link"):
            self.assertIn(key, first_msg)

    def test_promote_and_delete_override_roundtrip(self):
        backup_path = t.get_backup_path("1791895360")

        # Insert a temporary flagged message in backup 'Elysium-sql-tests'
        test_msg_id = "888777666555444"
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            # Clean if existed
            session.query(FlaggedMessageModel).filter_by(backup_id="1791895360", message_id=test_msg_id).delete()
            session.query(MessageOverrideModel).filter_by(backup_id="1791895360", message_id=test_msg_id).delete()

            import datetime
            session.add(
                FlaggedMessageModel(
                    backup_id="1791895360",
                    message_id=test_msg_id,
                    channel_pk=None,
                    kind=FlaggedKind.NON_TUPPER,
                    content="Hello from test flagged message",
                    author={"id": "999", "name": "TestBot"},
                    flagged_at=datetime.datetime.now(datetime.timezone.utc),
                )
            )
            session.commit()

        try:
            # Promote to override
            promo_res = promote_flagged_message(
                "1791895360",
                test_msg_id,
                PromoteFlaggedMessageRequest(content="Corrected content override"),
            )
            self.assertEqual(promo_res["status"], "success")
            self.assertEqual(promo_res["message_id"], test_msg_id)

            # Verify present in message_overrides
            overrides = get_message_overrides("1791895360")
            matching = [o for o in overrides["overrides"] if o["message_id"] == test_msg_id]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["content"], "Corrected content override")

            # Verify deleted from flagged messages
            flagged = get_flagged_messages("1791895360")
            self.assertFalse(any(f["message_id"] == test_msg_id for f in flagged["messages"]))
        finally:
            # Delete override
            del_res = delete_message_override("1791895360", test_msg_id)
            self.assertEqual(del_res["status"], "success")

            overrides_after = get_message_overrides("1791895360")
            self.assertFalse(any(o["message_id"] == test_msg_id for o in overrides_after["overrides"]))


class TestByMeFiltering(unittest.TestCase):
    """Tests resolving user's writer profile and filtering scenes/characters 'by me'."""

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

    def test_get_my_writer(self):
        # Prim has discord_user_id = '200668852713947137' in Elysium
        # pyrefly: ignore [missing-import]
        from db.curation_service import get_my_writer as cs_get_my_writer
        writer_prim = cs_get_my_writer("1", t.get_backup_path("1"), "200668852713947137")
        self.assertIsNotNone(writer_prim)
        self.assertEqual(writer_prim["display_name"], "Prim")
        self.assertIn("cureprimulas", writer_prim["aliases"])

    def test_get_scenes_by_me(self):
        # Prim's scenes
        scenes_all = get_scenes("1", per_page=10)
        self.assertGreater(scenes_all["total_items"], 0)

        # Mock request with Prim's cookie
        import jwt
        # pyrefly: ignore [missing-import]
        from server import get_auth_config
        jwt_secret = get_auth_config()["jwt_secret"]
        token = jwt.encode({"sub": "200668852713947137", "username": "Prim"}, jwt_secret, algorithm="HS256")
        mock_req = MagicMock()
        mock_req.cookies = {"__session": token}

        scenes_by_prim = get_scenes("1", by_me=True, request=mock_req)
        self.assertGreater(scenes_by_prim["total_items"], 0)
        self.assertLess(scenes_by_prim["total_items"], scenes_all["total_items"])

        # Also test get_characters by_me
        chars_by_prim = get_characters("1", by_me=True, request=mock_req)
        self.assertIsInstance(chars_by_prim, list)
        self.assertGreater(len(chars_by_prim), 0)

    def test_get_curation_summary(self):
        summary = get_curation_summary("1")
        self.assertIn("unresolved_issues", summary)
        self.assertIn("unassigned_characters", summary)
        self.assertIn("flagged_messages", summary)
        self.assertIn("unlinked_writers", summary)
        self.assertIn("link_suggestions", summary)
        self.assertIsInstance(summary["unresolved_issues"], int)
        self.assertIsInstance(summary["unassigned_characters"], int)
        self.assertIsInstance(summary["flagged_messages"], int)
        self.assertIsInstance(summary["unlinked_writers"], int)
        self.assertIsInstance(summary["link_suggestions"], int)


if __name__ == "__main__":
    unittest.main()

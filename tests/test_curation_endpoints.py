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
    SceneModel,
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

        from datetime import datetime, timezone
        backup_path = t.get_backup_path("1791895360")
        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            count = session.query(SceneIssueModel).filter_by(backup_id="1791895360").count()
            if count == 0:
                scenes = session.query(SceneModel).filter_by(backup_id="1791895360").order_by(SceneModel.pk).all()
                if len(scenes) >= 2:
                    now = datetime.now(timezone.utc)
                    session.add_all([
                        SceneIssueModel(
                            backup_id="1791895360",
                            scene_pk=scenes[0].pk,
                            next_scene_pk=scenes[1].pk,
                            kind="auto_split",
                            reason="separate_roster",
                            candidate_message_id="1018678482202542151",
                            candidate_index=15,
                            candidate_excerpt="Separate roster cut candidate",
                            previous_chars=[1, 2],
                            next_chars=[3, 4],
                            created_at=now,
                        ),
                        SceneIssueModel(
                            backup_id="1791895360",
                            scene_pk=scenes[0].pk,
                            next_scene_pk=None,
                            kind="soft_boundary",
                            reason="start_tag_same_roster",
                            candidate_message_id="1020069775495397407",
                            candidate_index=25,
                            candidate_excerpt="Mid scene header candidate",
                            previous_chars=[1, 2],
                            next_chars=[1, 2],
                            created_at=now,
                        ),
                        SceneIssueModel(
                            backup_id="1791895360",
                            scene_pk=scenes[1].pk,
                            next_scene_pk=None,
                            kind="soft_boundary",
                            reason="roster_change",
                            candidate_message_id="1037732301469122591",
                            candidate_index=35,
                            candidate_excerpt="Roster change transition point",
                            previous_chars=[1, 3],
                            next_chars=[3, 5],
                            created_at=now,
                        ),
                    ])

    @classmethod
    def tearDownClass(cls):
        SceneManager.clear_cache()
        close_all_engines()

    def test_get_scene_issues_pagination_and_structure(self):
        issues_res = get_scene_issues("1791895360", status="all", per_page=2)
        self.assertIsInstance(issues_res, dict)
        self.assertGreater(issues_res["total_items"], 2)
        self.assertEqual(len(issues_res["issues"]), 2)
        self.assertIn("status_counts", issues_res)
        self.assertIn("unresolved", issues_res["status_counts"])
        self.assertIn("resolved", issues_res["status_counts"])
        self.assertIn("all", issues_res["status_counts"])
        self.assertEqual(
            issues_res["status_counts"]["all"],
            issues_res["status_counts"]["unresolved"] + issues_res["status_counts"]["resolved"],
        )

        first_issue = issues_res["issues"][0]
        for key in (
            "id",
            "kind",
            "reason",
            "scene_key",
            "channel_name",
            "channel_discord_id",
            "discord_link",
            "previous_chars",
            "next_chars",
            "previous_char_names",
            "next_char_names",
            "created_at",
        ):
            self.assertIn(key, first_issue)
        self.assertIsInstance(first_issue["previous_char_names"], list)
        self.assertIsInstance(first_issue["next_char_names"], list)

    def test_resolve_and_reopen_issue_roundtrip(self):
        issues_res = get_scene_issues("1791895360", status="unresolved", per_page=1)
        self.assertGreater(len(issues_res["issues"]), 0)
        target_issue = issues_res["issues"][0]
        iid = target_issue["id"]

        # Resolve issue
        res_res = resolve_scene_issue(
            "1791895360",
            iid,
            ResolveIssueRequest(resolution="merged", note="Verified intentional gap in automated test"),
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
        flagged_res = get_flagged_messages("1791895360", per_page=10)
        self.assertIsInstance(flagged_res, dict)
        self.assertGreater(flagged_res["total_items"], 0)
        self.assertEqual(len(flagged_res["messages"]), flagged_res["total_items"])

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
        # Prim has discord_user_id = '200668852713947137' in Elysium-sql-tests
        # pyrefly: ignore [missing-import]
        from db.curation_service import get_my_writer as cs_get_my_writer
        writer_prim = cs_get_my_writer("1791895360", t.get_backup_path("1791895360"), "200668852713947137")
        self.assertIsNotNone(writer_prim)
        self.assertEqual(writer_prim["display_name"], "Prim")
        self.assertIn("cureprimulas", writer_prim["aliases"])

    def test_get_scenes_by_me(self):
        # Prim's scenes
        scenes_all = get_scenes("1791895360", per_page=10)
        self.assertGreater(scenes_all["total_items"], 0)

        # Mock request with Prim's cookie
        import jwt
        # pyrefly: ignore [missing-import]
        from server import get_auth_config
        jwt_secret = get_auth_config()["jwt_secret"]
        token = jwt.encode({"sub": "200668852713947137", "username": "Prim"}, jwt_secret, algorithm="HS256")
        mock_req = MagicMock()
        mock_req.cookies = {"__session": token}

        scenes_by_prim = get_scenes("1791895360", by_me=True, request=mock_req)
        self.assertGreater(scenes_by_prim["total_items"], 0)
        self.assertLess(scenes_by_prim["total_items"], scenes_all["total_items"])

        # Also test get_characters by_me
        chars_by_prim = get_characters("1791895360", by_me=True, request=mock_req)
        self.assertIsInstance(chars_by_prim, list)
        self.assertGreater(len(chars_by_prim), 0)

    def test_get_curation_summary(self):
        summary = get_curation_summary("1791895360")
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


class TestNewSceneIndexingAndSuggestions(unittest.TestCase):
    """Tests new two-phase scene boundary detection, auto_split/split issues, and character suggestions."""

    def setUp(self):
        from datetime import datetime, timezone
        self.datetime = datetime
        self.timezone = timezone

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

    def test_end_and_start_tag_detection(self):
        from find_character_scenes import has_end_tag, has_start_tag

        # End tags
        self.assertTrue(has_end_tag("```End```"))
        self.assertTrue(has_end_tag("```close```"))
        self.assertTrue(has_end_tag("`moved to #lounge`"))
        self.assertTrue(has_end_tag("[end]"))
        self.assertTrue(has_end_tag({"content": "```End```"}))
        self.assertFalse(has_end_tag("Just a normal roleplay post without tags."))

        # Start tags
        self.assertTrue(has_start_tag("```DM with Alice```"))
        self.assertTrue(has_start_tag("[October 12th - Morning]"))
        self.assertTrue(has_start_tag("`continued from #viper-bar`"))
        self.assertTrue(has_start_tag({"content": "[Incoming Call from Bob]"}))
        self.assertFalse(has_start_tag("Hello there!"))

    def test_suggest_character_for_non_tupper_priorities(self):
        from db.curation_service import suggest_character_for_non_tupper
        backup_path = t.get_backup_path("1791895360")

        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            # 1. Priority 1 (name_prefix)
            sug_prefix = suggest_character_for_non_tupper(
                session=session,
                backup_id="1791895360",
                discord_user_id="111222333444",
                content="Ophelia: How nice to see you!",
            )
            self.assertIsNotNone(sug_prefix)
            self.assertEqual(sug_prefix["reason"], "name_prefix")
            self.assertIn("Ophelia", sug_prefix["name"])

            # 2. Priority 2 (active_in_scene) & Priority 3 (only_character)
            writer = session.query(WriterModel).filter(
                WriterModel.backup_id == "1791895360",
                WriterModel.discord_user_id.isnot(None)
            ).first()
            if writer and writer.characters:
                char_ids = [c.char_id for c in writer.characters]
                sug_active = suggest_character_for_non_tupper(
                    session=session,
                    backup_id="1791895360",
                    discord_user_id=writer.discord_user_id,
                    content="Hello everyone",
                    scene_tupper_char_ids=[char_ids[0]],
                )
                self.assertIsNotNone(sug_active)
                self.assertIn(sug_active["reason"], ["active_in_scene", "only_character"])
                self.assertEqual(sug_active["char_id"], char_ids[0])

    def test_flagged_messages_suggested_character_enrichment(self):
        res = get_flagged_messages("1791895360", per_page=10)
        self.assertIsInstance(res, dict)
        self.assertIn("messages", res)
        for msg in res["messages"]:
            self.assertIn("suggested_character", msg)


    def test_resolved_map_preserves_multiple_issues_across_reindexing(self):
        from datetime import datetime, timezone
        from db.scene_service import save_indexed_scenes
        backup_path = t.get_backup_path("1791895360")

        # Create simulated scene with 2 soft_boundarie issues and 1 auto_split issue
        raw_scenes = [
            {
                "channelId": "1019771317303644261",
                "status": "no_end_tag",
                "start": {"id": "999001", "index": 0, "timestamp": "2026-01-01T12:00:00Z"},
                "end": {"id": "999050", "index": 50, "timestamp": "2026-01-01T13:00:00Z"},
                "characters": [1, 2],
                "issues": [
                    {
                        "kind": "auto_split",
                        "reason": "separate_roster",
                        "candidate_id": "cand_split",
                        "candidate_index": 50,
                        "previous_chars": [1],
                        "next_chars": [2],
                    },
                    {
                        "kind": "soft_boundary",
                        "reason": "start_tag_same_roster",
                        "candidate_id": "cand_A",
                        "candidate_index": 15,
                        "previous_chars": [1],
                        "next_chars": [1, 2],
                    },
                    {
                        "kind": "soft_boundary",
                        "reason": "roster_change",
                        "candidate_id": "cand_B",
                        "candidate_index": 35,
                        "previous_chars": [1],
                        "next_chars": [2],
                    }
                ]
            }
        ]

        try:
            save_indexed_scenes("1791895360", backup_path, raw_scenes)

            with db_session(backup_id="1791895360", backup_path=backup_path) as session:
                issues = session.query(SceneIssueModel).filter(SceneIssueModel.backup_id == "1791895360").all()
                cand_a_iss = next(i for i in issues if i.candidate_message_id == "cand_A")
                cand_b_iss = next(i for i in issues if i.candidate_message_id == "cand_B")
                split_iss = next(i for i in issues if i.kind == "auto_split")

                # Resolve cand_A, leave cand_B and auto_split unresolved
                cand_a_iss.resolved_at = datetime.now(timezone.utc)
                cand_a_iss.resolution = "merged"
                cand_a_iss.resolved_note = "Resolved candidate A only"
                session.commit()

            # Re-index the same raw scenes
            save_indexed_scenes("1791895360", backup_path, raw_scenes)

            with db_session(backup_id="1791895360", backup_path=backup_path) as session:
                issues_after = session.query(SceneIssueModel).filter(SceneIssueModel.backup_id == "1791895360").all()
                cand_a_after = next(i for i in issues_after if i.candidate_message_id == "cand_A")
                cand_b_after = next(i for i in issues_after if i.candidate_message_id == "cand_B")
                split_after = next(i for i in issues_after if i.kind == "auto_split")

                # Cand A must be resolved, Cand B must remain unresolved!
                self.assertIsNotNone(cand_a_after.resolved_at)
                self.assertEqual(cand_a_after.resolved_note, "Resolved candidate A only")
                self.assertIsNone(cand_b_after.resolved_at)

                # Auto-split must remain unresolved
                self.assertIsNone(split_after.resolved_at)
        finally:
            # Restore test DB to clean migration state
            SceneManager.clear_cache()
            close_all_engines()
            migrate_for_tests("1791895360")

    def test_promote_flagged_message_author_formatting(self):
        from datetime import datetime, timezone
        backup_path = t.get_backup_path("1791895360")
        test_msg_id = "777888999111"

        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            session.add(FlaggedMessageModel(
                backup_id="1791895360",
                message_id=test_msg_id,
                kind=FlaggedKind.NON_TUPPER.value,
                content="Bob: *drinks coffee*",
                author={"id": "999888", "name": "DiscordUser", "discriminator": "0001"},
                flagged_at=datetime.now(timezone.utc),
            ))
            session.commit()

        # Promote with integer character ID and updated name
        res = promote_flagged_message(
            "1791895360",
            test_msg_id,
            PromoteFlaggedMessageRequest(content="*drinks coffee*", author={"id": 25, "name": "Bob"}),
        )
        self.assertEqual(res["status"], "success")

        with db_session(backup_id="1791895360", backup_path=backup_path) as session:
            override = session.query(MessageOverrideModel).filter_by(
                backup_id="1791895360", message_id=test_msg_id
            ).first()
            self.assertIsNotNone(override)
            self.assertEqual(override.content, "*drinks coffee*")
            self.assertEqual(override.author["id"], "25")
            self.assertEqual(override.author["name"], "Bob")
            self.assertTrue(override.author["isBot"])

            # Clean up
            session.delete(override)
            session.commit()


if __name__ == "__main__":
    unittest.main()

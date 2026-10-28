import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

# Ensure src and project root are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("SOCRATES_DATA_DIR", PROJECT_ROOT.as_posix()))
SRC_DIR = PROJECT_ROOT / "src"
for p in (SRC_DIR.as_posix(), PROJECT_ROOT.as_posix()):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import HTTPException
from tests.reset_test_backup import reset_test_backup
import utils.tricks as t
import utils.exceptions as exc
from db.models import (
    Base,
    BackupModel,
    SceneModel,
    SceneParticipantModel,
    SceneIssueModel,
    CharacterModel,
    ChannelModel,
    IssueKind,
    IssueResolution,
    SceneStatus,
    CURRENT_SCHEMA_VERSION,
)
from db.session import db_session, close_all_engines, init_db, stamp_schema_version
from db.scene_service import save_indexed_scenes
from db.migrate import migrate_for_tests
from models import SceneManager, BackupContext
from server import (
    resolve_scene_issue,
    reopen_scene_issue,
    get_scene_issues,
    ResolveIssueRequest,
)
from index_scenes import index_scenes


class TestSceneCurationOperations(unittest.TestCase):
    """
    Tests interactive scene curation mutations (merge and split),
    re-indexing hooks, and survival of resolved issues across runs.
    """

    BACKUP_ID = "1791895360"

    @classmethod
    def setUpClass(cls):
        close_all_engines()
        reset_test_backup()
        migrate_for_tests(cls.BACKUP_ID)
        SceneManager.clear_cache()
        close_all_engines()

    @classmethod
    def tearDownClass(cls):
        SceneManager.clear_cache()
        close_all_engines()
        reset_test_backup()
        close_all_engines()

    def setUp(self):
        self.backup_path = t.get_backup_path(self.BACKUP_ID)

    def test_01_merge_auto_split_scenes(self):
        """Tests merging two adjacent scenes flagged by an auto_split issue via resolve(merged)."""
        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            # Get adjacent scenes in barside channel (scenes 1 and 2)
            scenes = (
                session.query(SceneModel)
                .join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
                .filter(SceneModel.backup_id == self.BACKUP_ID, ChannelModel.name == "barside")
                .order_by(SceneModel.start_index)
                .all()
            )
            self.assertGreaterEqual(len(scenes), 2)
            scene1, scene2 = scenes[0], scenes[1]

            orig_s1_start = scene1.start_index
            orig_s2_end = scene2.end_index
            orig_s2_end_msg = scene2.end_message_id
            orig_s2_key = scene2.scene_key
            channel_pk = scene1.channel_pk

            # Create an auto_split issue linking scene1 and scene2
            issue = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=scene1.pk,
                next_scene_pk=scene2.pk,
                kind=IssueKind.AUTO_SPLIT.value,
                reason="separate_roster",
                candidate_message_id=scene2.start_message_id,
                candidate_index=scene2.start_index,
                candidate_excerpt="Test start of scene 2",
                created_at=scene1.start_at,
            )
            session.add(issue)
            session.commit()
            issue_id = issue.pk
            s1_pk = scene1.pk
            s2_pk = scene2.pk

            # Count total scenes in channel before merge
            before_count = session.query(SceneModel).filter_by(channel_pk=channel_pk).count()

        # Execute merge via resolve endpoint
        res = resolve_scene_issue(
            self.BACKUP_ID,
            issue_id,
            req=ResolveIssueRequest(resolution=IssueResolution.MERGED.value),
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["action"], "merge")
        self.assertEqual(res["resolution"], IssueResolution.MERGED.value)
        self.assertTrue(res["action_performed"])

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            # Verify Scene 1 expanded to cover Scene 2
            merged_s1 = session.query(SceneModel).filter_by(pk=s1_pk).first()
            self.assertIsNotNone(merged_s1)
            self.assertEqual(merged_s1.start_index, orig_s1_start)
            self.assertEqual(merged_s1.end_index, orig_s2_end)
            self.assertEqual(merged_s1.end_message_id, orig_s2_end_msg)

            # Verify Scene 2 was deleted
            deleted_s2 = session.query(SceneModel).filter_by(pk=s2_pk).first()
            self.assertIsNone(deleted_s2)

            # Verify total scenes in channel decreased by 1
            after_count = session.query(SceneModel).filter_by(channel_pk=channel_pk).count()
            self.assertEqual(after_count, before_count - 1)

            # Verify issue is marked resolved and merged
            updated_issue = session.query(SceneIssueModel).filter_by(pk=issue_id).first()
            self.assertIsNotNone(updated_issue.resolved_at)
            self.assertEqual(updated_issue.resolution, "merged")
            self.assertIsNone(updated_issue.next_scene_pk)

    def test_02_split_soft_boundary_scene(self):
        """Tests splitting a single scene flagged by a soft_boundary issue at candidate point."""
        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            scene = (
                session.query(SceneModel)
                .join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
                .filter(SceneModel.backup_id == self.BACKUP_ID, ChannelModel.name == "barside")
                .order_by(SceneModel.start_index.desc())
                .first()
            )
            self.assertIsNotNone(scene)
            s_pk = scene.pk
            channel_pk = scene.channel_pk
            orig_s_start = scene.start_index
            orig_s_end = scene.end_index

            # Candidate index 210
            cand_idx = 210
            cand_mid = "1128073156926656512"

            issue = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=scene.pk,
                next_scene_pk=None,
                kind=IssueKind.SOFT_BOUNDARY.value,
                reason="roster_change",
                candidate_message_id=cand_mid,
                candidate_index=cand_idx,
                candidate_excerpt="Test possible split candidate excerpt",
                created_at=scene.start_at,
            )
            session.add(issue)
            session.commit()
            issue_id = issue.pk

            before_count = session.query(SceneModel).filter_by(channel_pk=channel_pk).count()

        # Execute split via resolve endpoint
        res = resolve_scene_issue(
            self.BACKUP_ID,
            issue_id,
            req=ResolveIssueRequest(resolution=IssueResolution.SPLIT.value),
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["action"], "split")
        self.assertEqual(res["resolution"], IssueResolution.SPLIT.value)
        self.assertTrue(res["action_performed"])
        new_scene_pk = res["next_scene_pk"]

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            # Verify Scene 1 was truncated
            truncated_s1 = session.query(SceneModel).filter_by(pk=s_pk).first()
            self.assertIsNotNone(truncated_s1)
            self.assertEqual(truncated_s1.start_index, orig_s_start)
            self.assertLess(truncated_s1.end_index, cand_idx)
            self.assertEqual(truncated_s1.status, SceneStatus.NO_END_TAG.value)

            # Verify Scene 2 was inserted starting at cand_idx
            inserted_s2 = session.query(SceneModel).filter_by(pk=new_scene_pk).first()
            self.assertIsNotNone(inserted_s2)
            self.assertEqual(inserted_s2.start_index, cand_idx)
            self.assertEqual(inserted_s2.start_message_id, cand_mid)
            self.assertEqual(inserted_s2.end_index, orig_s_end)

            # Verify total scenes in channel increased by 1
            after_count = session.query(SceneModel).filter_by(channel_pk=channel_pk).count()
            self.assertEqual(after_count, before_count + 1)

            # Verify issue has next_scene_pk and resolution="split"
            updated_issue = session.query(SceneIssueModel).filter_by(pk=issue_id).first()
            self.assertIsNotNone(updated_issue.resolved_at)
            self.assertEqual(updated_issue.resolution, "split")
            self.assertEqual(updated_issue.next_scene_pk, new_scene_pk)

    def test_03_reopen_scene_issue_no_action(self):
        """Tests reopening an issue resolved with default resolution resets resolution and timestamps."""
        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            # Create a fresh issue and resolve it with default resolution (no scene mutation)
            sc = session.query(SceneModel).filter_by(backup_id=self.BACKUP_ID).first()
            iss = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=sc.pk,
                kind=IssueKind.AUTO_SPLIT.value,
                reason="separate_roster",
                candidate_message_id="999888777",
                created_at=datetime.now(timezone.utc),
            )
            session.add(iss)
            session.commit()
            issue_id = iss.pk

        # Resolve with kind default
        resolve_scene_issue(
            self.BACKUP_ID,
            issue_id,
            req=ResolveIssueRequest(resolution="split", note="Default resolve test"),
        )

        res = reopen_scene_issue(self.BACKUP_ID, issue_id)
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["reopened"])

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            reopened = session.query(SceneIssueModel).filter_by(pk=issue_id).first()
            self.assertIsNone(reopened.resolved_at)
            self.assertIsNone(reopened.resolution)
            self.assertIsNone(reopened.resolved_note)

    def test_04_resolve_issue_with_resolution(self):
        """Tests resolving an issue with explicit resolution type ('split')."""
        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            issue = (
                session.query(SceneIssueModel)
                .filter(
                    SceneIssueModel.backup_id == self.BACKUP_ID,
                    SceneIssueModel.resolved_at.is_(None),
                )
                .first()
            )
            self.assertIsNotNone(issue)
            issue_id = issue.pk

        res = resolve_scene_issue(
            self.BACKUP_ID,
            issue_id,
            ResolveIssueRequest(note="Accepted split decision", resolution="split"),
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["resolution"], "split")
        self.assertEqual(res["resolved_note"], "Accepted split decision")

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            checked = session.query(SceneIssueModel).filter_by(pk=issue_id).first()
            self.assertEqual(checked.resolution, "split")
            self.assertIsNotNone(checked.resolved_at)

    def test_05_reindexing_preserves_resolved_decisions(self):
        """
        Tests that index_scenes() loads resolved boundary decisions from SQLite,
        applies split/merge decisions during pipeline scanning, and preserves
        resolved issues with re-linked scene foreign keys.
        """
        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            # Create a resolved 'merged' issue
            iss_merge = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=None,
                kind=IssueKind.AUTO_SPLIT.value,
                reason="separate_roster",
                candidate_message_id="1051700736016265286",
                candidate_index=51,
                created_at=datetime.now(timezone.utc),
                resolved_at=datetime.now(timezone.utc),
                resolution=IssueResolution.MERGED.value,
                resolved_note="Manual merge test",
            )
            # Create a resolved 'split' issue
            iss_split = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=None,
                kind=IssueKind.SOFT_BOUNDARY.value,
                reason="roster_change",
                candidate_message_id="1128073156926656512",
                candidate_index=210,
                created_at=datetime.now(timezone.utc),
                resolved_at=datetime.now(timezone.utc),
                resolution=IssueResolution.SPLIT.value,
                resolved_note="Manual split test",
            )
            session.add(iss_merge)
            session.add(iss_split)
            session.commit()
            m_id = iss_merge.pk
            s_id = iss_split.pk

        # Run index_scenes in BackupContext targeting test backup
        ctx = BackupContext.create(
            backup_id=self.BACKUP_ID,
            backup_path=self.backup_path,
        )
        ctx.dry_run = False
        ctx.debug_files = False

        with BackupContext.activate(context=ctx):
            index_scenes()
            # Re-index a second time to verify complete idempotency and participant deletion/insertion
            index_scenes()

        # Verify that both resolved issues survived the index_scenes run
        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            survived_merge = session.query(SceneIssueModel).filter_by(pk=m_id).first()
            survived_split = session.query(SceneIssueModel).filter_by(pk=s_id).first()

            self.assertIsNotNone(survived_merge, "Resolved merged issue should survive re-indexing")
            self.assertEqual(survived_merge.resolution, "merged")
            self.assertIsNotNone(survived_merge.resolved_at)
            self.assertIsNotNone(survived_merge.scene_pk, "Merged issue should be re-linked to containing scene")

            self.assertIsNotNone(survived_split, "Resolved split issue should survive re-indexing")
            self.assertEqual(survived_split.resolution, "split")
            self.assertIsNotNone(survived_split.resolved_at)
            self.assertIsNotNone(survived_split.scene_pk, "Split issue should be re-linked to scene 1")
            self.assertIsNotNone(survived_split.next_scene_pk, "Split issue should be re-linked to scene 2")

    def test_06_error_validation(self):
        """Tests error validation on invalid resolve calls."""
        # Non-existent issue -> 404
        with self.assertRaises(HTTPException) as cm:
            resolve_scene_issue(self.BACKUP_ID, 9999999, req=ResolveIssueRequest(resolution="merged"))
        self.assertEqual(cm.exception.status_code, 404)

        # Invalid resolution -> 400
        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            iss = (
                session.query(SceneIssueModel)
                .filter(
                    SceneIssueModel.backup_id == self.BACKUP_ID,
                    SceneIssueModel.resolved_at.is_(None),
                )
                .first()
            )
            if not iss:
                iss = session.query(SceneIssueModel).filter_by(backup_id=self.BACKUP_ID).first()
                iss.resolved_at = None
                iss.resolution = None
                session.flush()
            valid_id = iss.pk

        with self.assertRaises(HTTPException) as cm:
            resolve_scene_issue(self.BACKUP_ID, valid_id, req=ResolveIssueRequest(resolution="invalid_resolution"))
        self.assertEqual(cm.exception.status_code, 400)

        # Resolving an already-resolved issue -> 400
        resolve_scene_issue(self.BACKUP_ID, valid_id, req=ResolveIssueRequest(resolution="split"))
        with self.assertRaises(HTTPException) as cm:
            resolve_scene_issue(self.BACKUP_ID, valid_id, req=ResolveIssueRequest(resolution="split"))
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("already resolved", cm.exception.detail.lower())

    def test_07_custom_notes_and_relinking_on_merge(self):
        """Tests merging with custom notes and verifies that other issues on scene2 re-link to scene1."""
        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            first_scene = session.query(SceneModel).filter_by(backup_id=self.BACKUP_ID).first()
            chan_scenes = (
                session.query(SceneModel)
                .filter_by(backup_id=self.BACKUP_ID, channel_pk=first_scene.channel_pk)
                .order_by(SceneModel.start_index)
                .all()
            )
            s1 = chan_scenes[0]
            s2 = chan_scenes[1]

            split_issue = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=s1.pk,
                next_scene_pk=s2.pk,
                kind=IssueKind.AUTO_SPLIT.value,
                reason="separate_roster",
                candidate_message_id=s2.start_message_id,
                candidate_index=s2.start_index,
                created_at=datetime.now(timezone.utc),
            )
            session.add(split_issue)

            other_issue = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=s2.pk,
                kind=IssueKind.SOFT_BOUNDARY.value,
                reason="start_tag_same_roster",
                created_at=datetime.now(timezone.utc),
            )
            session.add(other_issue)
            session.commit()
            split_id = split_issue.pk
            other_id = other_issue.pk
            s1_pk = s1.pk
            s2_pk = s2.pk

        custom_note = "Custom reviewer note for merge"
        res = resolve_scene_issue(
            self.BACKUP_ID,
            split_id,
            req=ResolveIssueRequest(resolution=IssueResolution.MERGED.value, note=custom_note),
        )
        self.assertEqual(res["status"], "success")

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            merged_iss = session.query(SceneIssueModel).filter_by(pk=split_id).first()
            self.assertEqual(merged_iss.resolved_note, custom_note)
            self.assertEqual(merged_iss.resolution, "merged")
            self.assertIsNone(merged_iss.next_scene_pk)

            relinked_iss = session.query(SceneIssueModel).filter_by(pk=other_id).first()
            self.assertIsNotNone(relinked_iss)
            self.assertEqual(relinked_iss.scene_pk, s1_pk)

            s2_in_db = session.query(SceneModel).filter_by(pk=s2_pk).first()
            self.assertIsNone(s2_in_db)

    def test_08_reopen_undo_roundtrip_merge(self):
        """Tests that reopening a merged auto_split issue perfectly restores Scene 2 and issue.next_scene_pk."""
        close_all_engines()
        reset_test_backup()
        migrate_for_tests(self.BACKUP_ID)

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            # Get scenes 1 and 2 in barside
            scenes = (
                session.query(SceneModel)
                .join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
                .filter(SceneModel.backup_id == self.BACKUP_ID, ChannelModel.name == "barside")
                .order_by(SceneModel.start_index)
                .all()
            )
            s1, s2 = scenes[0], scenes[1]
            s1.status = SceneStatus.NO_END_TAG.value
            session.commit()
            orig_s1_bounds = (s1.scene_key, s1.start_index, s1.end_index, s1.start_message_id, s1.end_message_id, s1.status)
            orig_s2_bounds = (s2.scene_key, s2.start_index, s2.end_index, s2.start_message_id, s2.end_message_id, s2.status)
            orig_s1_parts = {p.character_pk for p in s1.participants}
            orig_s2_parts = {p.character_pk for p in s2.participants}

            issue = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=s1.pk,
                next_scene_pk=s2.pk,
                kind=IssueKind.AUTO_SPLIT.value,
                reason="separate_roster",
                candidate_message_id=s2.start_message_id,
                candidate_index=s2.start_index,
                created_at=s1.start_at,
            )
            session.add(issue)
            session.commit()
            issue_id = issue.pk

        # 1. Merge
        res_merge = resolve_scene_issue(self.BACKUP_ID, issue_id, req=ResolveIssueRequest(resolution="merged"))
        self.assertEqual(res_merge["status"], "success")
        self.assertTrue(res_merge["action_performed"])

        # 2. Reopen (Undo Merge)
        res_reopen = reopen_scene_issue(self.BACKUP_ID, issue_id)
        self.assertEqual(res_reopen["status"], "success")
        self.assertTrue(res_reopen["reopened"])

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            reopened_issue = session.query(SceneIssueModel).filter_by(pk=issue_id).first()
            self.assertIsNone(reopened_issue.resolved_at)
            self.assertIsNone(reopened_issue.resolution)
            self.assertIsNotNone(reopened_issue.next_scene_pk, "next_scene_pk must be restored so merge works again")

            # Check that scene 1 and scene 2 match original bounds and participants
            cur_s1 = session.query(SceneModel).filter_by(pk=reopened_issue.scene_pk).first()
            cur_s2 = session.query(SceneModel).filter_by(pk=reopened_issue.next_scene_pk).first()
            self.assertIsNotNone(cur_s1)
            self.assertIsNotNone(cur_s2)

            cur_s1_bounds = (cur_s1.scene_key, cur_s1.start_index, cur_s1.end_index, cur_s1.start_message_id, cur_s1.end_message_id, cur_s1.status)
            cur_s2_bounds = (cur_s2.scene_key, cur_s2.start_index, cur_s2.end_index, cur_s2.start_message_id, cur_s2.end_message_id, cur_s2.status)

            self.assertEqual(cur_s1_bounds, orig_s1_bounds)
            self.assertEqual(cur_s2_bounds, orig_s2_bounds)
            self.assertEqual({p.character_pk for p in cur_s1.participants}, orig_s1_parts)
            self.assertEqual({p.character_pk for p in cur_s2.participants}, orig_s2_parts)

    def test_09_reopen_undo_roundtrip_split(self):
        """Tests that reopening a split soft_boundary issue merges the scene back and clears next_scene_pk."""
        close_all_engines()
        reset_test_backup()
        migrate_for_tests(self.BACKUP_ID)

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            scene = (
                session.query(SceneModel)
                .join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
                .filter(SceneModel.backup_id == self.BACKUP_ID, ChannelModel.name == "barside")
                .order_by(SceneModel.start_index.desc())
                .first()
            )
            orig_bounds = (scene.scene_key, scene.start_index, scene.end_index, scene.start_message_id, scene.end_message_id, scene.status)
            orig_parts = {p.character_pk for p in scene.participants}
            s_pk = scene.pk

            cand_idx = 210
            cand_mid = "1128073156926656512"

            issue = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=s_pk,
                next_scene_pk=None,
                kind=IssueKind.SOFT_BOUNDARY.value,
                reason="roster_change",
                candidate_message_id=cand_mid,
                candidate_index=cand_idx,
                created_at=scene.start_at,
            )
            session.add(issue)
            session.commit()
            issue_id = issue.pk

        # 1. Split
        res_split = resolve_scene_issue(self.BACKUP_ID, issue_id, req=ResolveIssueRequest(resolution="split"))
        self.assertEqual(res_split["status"], "success")
        self.assertTrue(res_split["action_performed"])

        # 2. Reopen (Undo Split)
        res_reopen = reopen_scene_issue(self.BACKUP_ID, issue_id)
        self.assertEqual(res_reopen["status"], "success")

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            reopened_issue = session.query(SceneIssueModel).filter_by(pk=issue_id).first()
            self.assertIsNone(reopened_issue.resolved_at)
            self.assertIsNone(reopened_issue.next_scene_pk)

            cur_s = session.query(SceneModel).filter_by(pk=s_pk).first()
            self.assertIsNotNone(cur_s)
            cur_bounds = (cur_s.scene_key, cur_s.start_index, cur_s.end_index, cur_s.start_message_id, cur_s.end_message_id, cur_s.status)
            self.assertEqual(cur_bounds, orig_bounds)
            self.assertEqual({p.character_pk for p in cur_s.participants}, orig_parts)

    def test_10_two_channel_reindex_relink(self):
        """Tests that re-indexing correctly re-links decisions per channel without channel crosstalk."""
        close_all_engines()
        reset_test_backup()
        migrate_for_tests(self.BACKUP_ID)

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            # Get two distinct channels
            chan1 = session.query(ChannelModel).filter_by(name="barside").first()
            chan2 = session.query(ChannelModel).filter_by(name="back-of-bar").first()
            self.assertIsNotNone(chan1)
            self.assertIsNotNone(chan2)
            c1_pk, c2_pk = chan1.pk, chan2.pk
            chan1_discord_id = chan1.discord_id
            chan2_discord_id = chan2.discord_id

            # Create resolved issue in Channel 1 at candidate message cand_c1
            iss1 = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=None,
                kind=IssueKind.SOFT_BOUNDARY.value,
                reason="roster_change",
                candidate_message_id="cand_c1",
                candidate_index=10,
                created_at=datetime.now(timezone.utc),
                resolved_at=datetime.now(timezone.utc),
                resolution="merged",
            )
            # Create resolved issue in Channel 2 at candidate message cand_c2 (same relative candidate_index=10!)
            iss2 = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=None,
                kind=IssueKind.SOFT_BOUNDARY.value,
                reason="roster_change",
                candidate_message_id="cand_c2",
                candidate_index=10,
                created_at=datetime.now(timezone.utc),
                resolved_at=datetime.now(timezone.utc),
                resolution="merged",
            )
            session.add_all([iss1, iss2])
            session.commit()
            i1_pk, i2_pk = iss1.pk, iss2.pk

        # Simulate raw scenes generated by indexer reporting resolved_inside per channel
        simulated_scenes = [
            {
                "channelId": chan1_discord_id,
                "status": "closed",
                "start": {"id": "1001", "index": 0, "timestamp": "2026-01-01T10:00:00Z"},
                "end": {"id": "1020", "index": 20, "timestamp": "2026-01-01T11:00:00Z"},
                "characters": [1, 2],
                "resolved_inside": ["cand_c1"],
                "issues": [],
            },
            {
                "channelId": chan2_discord_id,
                "status": "closed",
                "start": {"id": "2001", "index": 0, "timestamp": "2026-01-01T10:00:00Z"},
                "end": {"id": "2020", "index": 20, "timestamp": "2026-01-01T11:00:00Z"},
                "characters": [1, 3],
                "resolved_inside": ["cand_c2"],
                "issues": [],
            },
        ]

        save_indexed_scenes(self.BACKUP_ID, self.backup_path, simulated_scenes)

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            check_iss1 = session.query(SceneIssueModel).filter_by(pk=i1_pk).first()
            check_iss2 = session.query(SceneIssueModel).filter_by(pk=i2_pk).first()

            self.assertIsNotNone(check_iss1.scene_pk)
            self.assertIsNotNone(check_iss2.scene_pk)

            # Issue 1's scene must belong to Channel 1
            sc1 = session.query(SceneModel).filter_by(pk=check_iss1.scene_pk).first()
            self.assertEqual(sc1.channel_pk, c1_pk)

            # Issue 2's scene must belong to Channel 2
            sc2 = session.query(SceneModel).filter_by(pk=check_iss2.scene_pk).first()
            self.assertEqual(sc2.channel_pk, c2_pk)

    def test_11_split_left_half_always_no_end_tag(self):
        """Tests that splitting a scene always sets status='no_end_tag' on the left half."""
        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            scene = (
                session.query(SceneModel)
                .join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
                .filter(SceneModel.backup_id == self.BACKUP_ID, ChannelModel.name == "barside")
                .first()
            )
            # Ensure starting status is closed
            scene.status = SceneStatus.CLOSED.value
            session.commit()
            s_pk = scene.pk

            cand_idx = 15
            cand_mid = "1019416174397763624"
            issue = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=s_pk,
                kind=IssueKind.SOFT_BOUNDARY.value,
                reason="roster_change",
                candidate_message_id=cand_mid,
                candidate_index=cand_idx,
                created_at=scene.start_at,
            )
            session.add(issue)
            session.commit()
            issue_id = issue.pk

        res = resolve_scene_issue(self.BACKUP_ID, issue_id, req=ResolveIssueRequest(resolution="split"))
        self.assertEqual(res["status"], "success")

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            left_half = session.query(SceneModel).filter_by(pk=s_pk).first()
            self.assertEqual(left_half.status, SceneStatus.NO_END_TAG.value)

    def test_12_decision_load_failure_propagates(self):
        """Tests that if SQLite exists and decision loading fails, index_scenes raises IndexScenesError."""
        ctx = BackupContext.create(backup_id=self.BACKUP_ID, backup_path=self.backup_path)
        with BackupContext.activate(context=ctx):
            with patch("db.curation_service.get_resolved_boundary_decisions", side_effect=RuntimeError("Corrupt DB")):
                with self.assertRaises(exc.IndexScenesError):
                    index_scenes(backup_id=self.BACKUP_ID, backup_path=self.backup_path)

    def test_13_split_outside_boundaries_rejected(self):
        """Tests that splitting at an index outside the target scene is rejected with 400."""
        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            scene = (
                session.query(SceneModel)
                .join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
                .filter(SceneModel.backup_id == self.BACKUP_ID, ChannelModel.name == "barside")
                .order_by(SceneModel.start_index.desc())
                .first()
            )
            issue = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=scene.pk,
                kind=IssueKind.SOFT_BOUNDARY.value,
                reason="roster_change",
                candidate_message_id="1018678482202542151",
                candidate_index=0,  # Message 0 is outside this scene!
                created_at=datetime.now(timezone.utc),
            )
            session.add(issue)
            session.commit()
            issue_id = issue.pk

        with self.assertRaises(HTTPException) as cm:
            resolve_scene_issue(self.BACKUP_ID, issue_id, req=ResolveIssueRequest(resolution="split"))
        self.assertEqual(cm.exception.status_code, 400)

    def test_14_non_adjacent_and_cross_channel_merge_rejected(self):
        """Tests that merging non-adjacent scenes or cross-channel scenes is rejected with 400."""
        close_all_engines()
        reset_test_backup()
        migrate_for_tests(self.BACKUP_ID)

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            scenes = (
                session.query(SceneModel)
                .join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
                .filter(SceneModel.backup_id == self.BACKUP_ID, ChannelModel.name == "barside")
                .order_by(SceneModel.start_index)
                .all()
            )
            self.assertGreaterEqual(len(scenes), 3)
            # Pick non-adjacent scenes (scene 0 and scene 2)
            s0, s2 = scenes[0], scenes[2]

            issue_non_adj = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=s0.pk,
                next_scene_pk=s2.pk,
                kind=IssueKind.AUTO_SPLIT.value,
                reason="separate_roster",
                candidate_message_id=s2.start_message_id,
                created_at=datetime.now(timezone.utc),
            )
            # Pick cross-channel scenes
            chan2_scene = (
                session.query(SceneModel)
                .join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
                .filter(SceneModel.backup_id == self.BACKUP_ID, ChannelModel.name == "back-of-bar")
                .first()
            )
            issue_cross_chan = SceneIssueModel(
                backup_id=self.BACKUP_ID,
                scene_pk=s0.pk,
                next_scene_pk=chan2_scene.pk,
                kind=IssueKind.AUTO_SPLIT.value,
                reason="separate_roster",
                candidate_message_id=chan2_scene.start_message_id,
                created_at=datetime.now(timezone.utc),
            )
            session.add_all([issue_non_adj, issue_cross_chan])
            session.commit()
            i_non_adj = issue_non_adj.pk
            i_cross_chan = issue_cross_chan.pk

        with self.assertRaises(HTTPException) as cm1:
            resolve_scene_issue(self.BACKUP_ID, i_non_adj, req=ResolveIssueRequest(resolution="merged"))
        self.assertEqual(cm1.exception.status_code, 400)

        with self.assertRaises(HTTPException) as cm2:
            resolve_scene_issue(self.BACKUP_ID, i_cross_chan, req=ResolveIssueRequest(resolution="merged"))
        self.assertEqual(cm2.exception.status_code, 400)

    def test_15_end_to_end_merge_and_reindex_unchanged(self):
        """Tests that end-to-end API merge persists across full index_scenes() runs."""
        close_all_engines()
        reset_test_backup()
        migrate_for_tests(self.BACKUP_ID)

        # Index once to generate natural issues
        ctx = BackupContext.create(backup_id=self.BACKUP_ID, backup_path=self.backup_path)
        with BackupContext.activate(context=ctx):
            index_scenes(backup_id=self.BACKUP_ID, backup_path=self.backup_path)

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            before_count = (
                session.query(SceneModel)
                .join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
                .filter(SceneModel.backup_id == self.BACKUP_ID, ChannelModel.name == "barside")
                .count()
            )
            issue = (
                session.query(SceneIssueModel)
                .filter_by(backup_id=self.BACKUP_ID, kind=IssueKind.AUTO_SPLIT.value)
                .first()
            )
            self.assertIsNotNone(issue)
            issue_id = issue.pk

        res = resolve_scene_issue(self.BACKUP_ID, issue_id, req=ResolveIssueRequest(resolution="merged"))
        self.assertEqual(res["status"], "success")

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            after_merge_count = (
                session.query(SceneModel)
                .join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
                .filter(SceneModel.backup_id == self.BACKUP_ID, ChannelModel.name == "barside")
                .count()
            )
            self.assertEqual(after_merge_count, before_count - 1)

        # Run re-indexing
        with BackupContext.activate(context=ctx):
            index_scenes(backup_id=self.BACKUP_ID, backup_path=self.backup_path)

        with db_session(backup_id=self.BACKUP_ID, backup_path=self.backup_path) as session:
            after_reindex_count = (
                session.query(SceneModel)
                .join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
                .filter(SceneModel.backup_id == self.BACKUP_ID, ChannelModel.name == "barside")
                .count()
            )
            self.assertEqual(after_reindex_count, after_merge_count, "Scene count must remain merged across index_scenes()")

    def test_16_schema_upgrade_v1_to_v2_migration(self):
        """Tests that populate_schema migrates v1 values ('accepted', 'possible_split', drops details) to v2."""
        from sqlalchemy import create_engine
        from db.upgrade import populate_schema
        from db.session import get_db_schema_version

        mem_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=mem_engine)

        # Simulated v1 extracted data
        extracted_v1 = {
            "backups": [{"backup_id": "test_v1", "backup_name": "Test V1"}],
            "exports": [{"pk": 1, "backup_id": "test_v1", "scope": "base"}],
            "channels": [{"pk": 1, "export_pk": 1, "discord_id": "111", "type": "GuildTextChat", "name": "c1", "position": 0, "path": "c1.json"}],
            "scenes": [
                {
                    "pk": 1,
                    "backup_id": "test_v1",
                    "scene_key": "1-1",
                    "channel_pk": 1,
                    "category_pk": 1,
                    "status": "closed",
                    "start_message_id": "m1",
                    "end_message_id": "m2",
                    "start_index": 0,
                    "end_index": 10,
                    "start_at": "2026-01-01T10:00:00Z",
                    "end_at": "2026-01-01T11:00:00Z",
                    "start_author_id": "1",
                    "end_author_id": "2",
                }
            ],
            "scene_issues": [
                {
                    "backup_id": "test_v1",
                    "scene_pk": 1,
                    "next_scene_pk": None,
                    "kind": "possible_split",
                    "reason": "start_tag_same_roster",
                    "candidate_message_id": "m5",
                    "candidate_index": 5,
                    "details": {"some_legacy": "data"},
                    "created_at": "2026-01-01T10:30:00Z",
                    "resolved_at": "2026-01-01T12:00:00Z",
                    "resolution": "accepted",
                },
                {
                    "backup_id": "test_v1",
                    "scene_pk": 1,
                    "next_scene_pk": None,
                    "kind": "auto_split",
                    "reason": "separate_roster",
                    "candidate_message_id": "m8",
                    "candidate_index": 8,
                    "details": {"another": "legacy"},
                    "created_at": "2026-01-01T10:45:00Z",
                    "resolved_at": "2026-01-01T12:00:00Z",
                    "resolution": "accepted",
                },
            ]
        }

        metrics = populate_schema(mem_engine, extracted_v1, "test_v1", 1, target_schema_version=CURRENT_SCHEMA_VERSION)
        self.assertEqual(get_db_schema_version(mem_engine), CURRENT_SCHEMA_VERSION)
        self.assertEqual(metrics["scene_issues"], 2)

        # Check on mem_engine
        from sqlalchemy.orm import Session
        with Session(mem_engine) as mem_session:
            issues = mem_session.query(SceneIssueModel).order_by(SceneIssueModel.pk).all()
            self.assertEqual(len(issues), 2)

            # possible_split -> soft_boundary, accepted -> merged
            iss1 = issues[0]
            self.assertEqual(iss1.kind, "soft_boundary")
            self.assertEqual(iss1.resolution, "merged")
            self.assertFalse(hasattr(iss1, "details") and getattr(iss1, "details") is not None)

            # auto_split: accepted -> split
            iss2 = issues[1]
            self.assertEqual(iss2.kind, "auto_split")
            self.assertEqual(iss2.resolution, "split")

        mem_engine.dispose()


if __name__ == "__main__":
    unittest.main()

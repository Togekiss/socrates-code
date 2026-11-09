import os
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

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

# pyrefly: ignore [missing-import]
from db.models import (
    Base,
    BackupModel,
    ExportModel,
    BackupStepModel,
    ChannelModel,
    WriterModel,
    WriterAliasModel,
    CharacterGroupModel,
    GroupNameModel,
    CharacterModel,
    CharacterNameModel,
    EventModel,
    SceneModel,
    SceneParticipantModel,
    SceneIssueModel,
    FlaggedResolution,
    FlaggedMessageModel,
    SchemaVersionModel,
    CURRENT_SCHEMA_VERSION,
    Scope,
    Step,
    Status,
    SceneStatus,
    SceneKind,
    IssueKind,
    IssueReason,
    FlaggedKind,
    VersionType,
    Origin,
    Activity,
)

# pyrefly: ignore [missing-import]
from db.session import init_db, get_db_schema_version
# pyrefly: ignore [missing-import]
from db.upgrade import extract_database_data, populate_schema
# pyrefly: ignore [missing-import]
from utils import exceptions as exc
# pyrefly: ignore [missing-import]
import utils.tricks as t


class TestDatabaseSchemaAndModels(unittest.TestCase):
    """Tests the SQLAlchemy schema creation and core ORM model operations in SQLite."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        init_db(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_sqlite_schema_creation_all_tables_present(self):
        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        expected_tables = {
            "backups",
            "exports",
            "backup_steps",
            "channels",
            "writers",
            "writer_aliases",
            "character_groups",
            "group_names",
            "characters",
            "character_names",
            "events",
            "scenes",
            "scene_participants",
            "scene_issues",
            "flagged_messages",
            "schema_version",
        }
        missing = expected_tables - tables
        self.assertEqual(len(missing), 0, f"Missing expected tables: {missing}")

    def test_backup_and_character_model_relationships(self):
        with self.Session() as session:
            backup = BackupModel(
                backup_id="test_backup_1",
                backup_name="Test Backup 1",
                server_id="123456789012345678",
                server_name="Test Server",
            )
            session.add(backup)
            session.flush()

            export = ExportModel(
                backup_id=backup.backup_id,
                scope=Scope.BASE,
            )
            session.add(export)
            session.flush()

            step = BackupStepModel(
                export_pk=export.pk,
                step=Step.DOWNLOAD,
                status=Status.SUCCESS,
            )
            session.add(step)

            writer = WriterModel(
                backup_id=backup.backup_id,
                display_name="TestWriter",
                discord_user_id="111222333444",
            )
            session.add(writer)
            session.flush()

            alias = WriterAliasModel(
                writer_pk=writer.pk,
                alias="TW",
            )
            session.add(alias)

            group = CharacterGroupModel(backup_id=backup.backup_id)
            session.add(group)
            session.flush()

            group_name = GroupNameModel(group_pk=group.pk, name="TestGroup", position=0)
            session.add(group_name)

            char = CharacterModel(
                backup_id=backup.backup_id,
                char_id=1,
                writer_pk=writer.pk,
                group_pk=group.pk,
                origin=Origin.CANON,
                activity=Activity.ACTIVE,
            )
            session.add(char)
            session.flush()

            char_name = CharacterNameModel(
                character_pk=char.pk,
                name="Protagonist",
                position=0,
            )
            session.add(char_name)
            session.commit()

        # Query back and verify in a new session
        with self.Session() as session:
            loaded_backup = session.query(BackupModel).filter_by(backup_id="test_backup_1").first()
            self.assertIsNotNone(loaded_backup)
            self.assertEqual(len(loaded_backup.exports), 1)

            loaded_char = session.query(CharacterModel).filter_by(char_id=1).first()
            self.assertIsNotNone(loaded_char)
            self.assertEqual(loaded_char.names[0].name, "Protagonist")
            self.assertEqual(loaded_char.writer.display_name, "TestWriter")
            self.assertEqual(loaded_char.group.names[0].name, "TestGroup")

    def test_scenes_and_flagged_messages(self):
        with self.Session() as session:
            backup = BackupModel(
                backup_id="test_backup_scenes",
                backup_name="Test Backup Scenes",
                server_id="100200300400500600",
                server_name="Test RP Server",
            )
            session.add(backup)
            session.flush()

            export = ExportModel(
                backup_id=backup.backup_id,
                scope=Scope.BASE,
            )
            session.add(export)
            session.flush()

            channel = ChannelModel(
                export_pk=export.pk,
                discord_id="100200300400",
                type="GuildTextChat",
                name="rp-general",
                position=1,
                path="Data/rp-general",
            )
            session.add(channel)
            session.flush()

            import datetime
            now = datetime.datetime.now(datetime.timezone.utc)
            scene = SceneModel(
                backup_id=backup.backup_id,
                scene_key="1-1-1",
                category_pk=channel.pk,
                channel_pk=channel.pk,
                status=SceneStatus.OPEN,
                start_message_id="111",
                end_message_id="222",
                start_index=0,
                end_index=9,
                start_at=now,
                end_at=now,
                start_author_id="123",
                end_author_id="456",
            )
            session.add(scene)
            session.flush()

            flagged = FlaggedMessageModel(
                backup_id=backup.backup_id,
                channel_pk=channel.pk,
                message_id="555666777888",
                kind=FlaggedKind.OOC_MESSAGE.value,
                content="Hello from non-tupper bot",
                author={"id": "555", "name": "BadBot"},
                flagged_at=now,
            )
            session.add(flagged)
            session.commit()

            loaded_scene = session.query(SceneModel).filter_by(scene_key="1-1-1").first()
            self.assertIsNotNone(loaded_scene)
            self.assertEqual(loaded_scene.start_message_id, "111")
            self.assertEqual(loaded_scene.channel.name, "rp-general")

            loaded_flag = session.query(FlaggedMessageModel).filter_by(message_id="555666777888").first()
            self.assertIsNotNone(loaded_flag)
            self.assertEqual(loaded_flag.kind, FlaggedKind.OOC_MESSAGE.value)
            self.assertEqual(loaded_flag.author["name"], "BadBot")

    def test_issue_kind_and_scene_status_enums(self):
        """Verifies that IssueKind and SceneStatus enums only contain active modern members."""
        expected_kinds = {"auto_split", "soft_boundary"}
        actual_kinds = {k.value for k in IssueKind}
        self.assertEqual(actual_kinds, expected_kinds)

        expected_statuses = {"open", "closed", "no_end_tag"}
        actual_statuses = {s.value for s in SceneStatus}
        self.assertEqual(actual_statuses, expected_statuses)

        expected_reasons = {"separate_roster", "start_tag_roster_change", "start_tag_same_roster", "roster_change", "manual", "inactivity_gap", "tupper_end_tag"}
        actual_reasons = {r.value for r in IssueReason}
        self.assertEqual(actual_reasons, expected_reasons)

    def test_schema_version_tracking(self):
        """Verifies that schema_version table correctly tracks CURRENT_SCHEMA_VERSION."""
        self.assertEqual(CURRENT_SCHEMA_VERSION, 5)
        current_ver = get_db_schema_version(self.engine)
        self.assertEqual(current_ver, 5)

        with self.Session() as session:
            record = session.query(SchemaVersionModel).filter_by(version=CURRENT_SCHEMA_VERSION).first()
            self.assertIsNotNone(record)
            self.assertIsNotNone(record.applied_at)

    def test_scene_kind_and_participant_details_schema(self):
        """Verifies SceneKind enum and columns on SceneModel, EventModel, and SceneParticipantModel."""
        expected_kinds = {"scene", "session", "event"}
        actual_kinds = {k.value for k in SceneKind}
        self.assertEqual(actual_kinds, expected_kinds)

        inspector = inspect(self.engine)
        scene_cols = {c["name"]: c for c in inspector.get_columns("scenes")}
        self.assertIn("kind", scene_cols)
        self.assertIn("event_pk", scene_cols)
        self.assertIn("custom_name", scene_cols)

        event_cols = {c["name"]: c for c in inspector.get_columns("events")}
        for col_name in ("pk", "backup_id", "event_key", "name", "status", "start_at", "end_at", "message_count", "character_movements"):
            self.assertIn(col_name, event_cols)

        part_cols = {c["name"]: c for c in inspector.get_columns("scene_participants")}
        for col_name in ("position", "first_message_id", "first_at", "last_message_id", "last_at"):
            self.assertIn(col_name, part_cols)

    def test_event_model_and_upgrade_roundtrip(self):
        """Verifies EventModel creation, SceneModel.event_pk relationship, and upgrade extraction/population."""
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        with self.Session() as session:
            backup = BackupModel(
                backup_id="test_ev_backup",
                backup_name="Test Event Backup",
                server_id="999",
                server_name="Event Server",
            )
            session.add(backup)
            session.flush()

            export = ExportModel(backup_id=backup.backup_id, scope=Scope.BASE)
            session.add(export)
            session.flush()

            channel = ChannelModel(
                export_pk=export.pk,
                discord_id="1008065639467982868",
                type="GuildTextChat",
                name="event-1",
                position=1,
                path="6# Events/1# event-1.json",
            )
            session.add(channel)
            session.flush()

            ev = EventModel(
                backup_id=backup.backup_id,
                event_key="ev-1",
                name="Summer Beach Festival",
                status="closed",
                start_at=now,
                end_at=now,
                message_count=42,
                character_movements={"1": [{"channel_id": "10", "channel_name": "event-1", "first_message_id": "100"}]},
            )
            session.add(ev)
            session.flush()

            scene = SceneModel(
                backup_id=backup.backup_id,
                scene_key="6-1-ev1",
                channel_pk=channel.pk,
                category_pk=channel.pk,
                kind=SceneKind.EVENT.value,
                event_pk=ev.pk,
                custom_name="beach-shore",
                status="closed",
                start_message_id="100",
                end_message_id="141",
                start_index=0,
                end_index=41,
                start_at=now,
                end_at=now,
                start_author_id="1",
                end_author_id="1",
            )
            session.add(scene)
            session.commit()

        # Extract and re-populate into a fresh engine to verify upgrade preservation
        data = extract_database_data(self.engine)
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(data["events"][0]["name"], "Summer Beach Festival")

        fresh_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(fresh_engine)
        counts = populate_schema(fresh_engine, data)
        self.assertEqual(counts["events"], 1)
        self.assertEqual(counts["scenes"], 1)

        FreshSession = sessionmaker(bind=fresh_engine)
        with FreshSession() as s2:
            loaded_ev = s2.query(EventModel).filter_by(event_key="ev-1").first()
            self.assertIsNotNone(loaded_ev)
            self.assertEqual(loaded_ev.name, "Summer Beach Festival")
            self.assertEqual(len(loaded_ev.scenes), 1)
            self.assertEqual(loaded_ev.scenes[0].custom_name, "beach-shore")
        fresh_engine.dispose()

    def test_schema_version_mismatch_raises_error(self):
        """Verifies that init_db raises DatabaseSchemaMismatchError when DB version < CURRENT_SCHEMA_VERSION."""
        with self.Session() as session:
            session.query(SchemaVersionModel).delete()
            session.commit()

        self.assertEqual(get_db_schema_version(self.engine), 0)

        with self.assertRaises(exc.DatabaseSchemaMismatchError) as ctx:
            init_db(self.engine, check_version=True)
        self.assertIn("older than required version", str(ctx.exception))


class TestAtomicUtilities(unittest.TestCase):
    """Tests atomic file persistence and path resolution helpers."""

    def test_save_json_atomic_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_file = Path(tmpdir) / "test_data.json"
            sample_data = {
                "name": "Socrates",
                "version": 1.0,
                "items": [1, 2, 3],
                "nested": {"status": "ok"},
            }
            t.save_json_atomic(sample_data, target_file)
            self.assertTrue(target_file.exists())

            loaded = t.load_from_json(target_file)
            self.assertEqual(loaded, sample_data)

    def test_get_backup_path_resolution(self):
        path_elysium = t.get_backup_path("1")
        self.assertIn("Elysium", path_elysium)
        self.assertTrue(Path(path_elysium).exists())

        path_meu_server = t.get_backup_path("1789899843")
        self.assertIn("el_meu_server", path_meu_server)
        self.assertTrue(Path(path_meu_server).exists())


if __name__ == "__main__":
    unittest.main()

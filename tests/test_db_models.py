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
    SceneModel,
    SceneParticipantModel,
    SceneIssueModel,
    MessageOverrideModel,
    FlaggedMessageModel,
    SchemaVersionModel,
    CURRENT_SCHEMA_VERSION,
    Scope,
    Step,
    Status,
    SceneStatus,
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
            "scenes",
            "scene_participants",
            "scene_issues",
            "message_overrides",
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
                kind=FlaggedKind.NON_TUPPER,
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
            self.assertEqual(loaded_flag.kind, FlaggedKind.NON_TUPPER)
            self.assertEqual(loaded_flag.author["name"], "BadBot")

    def test_issue_kind_and_scene_status_enums(self):
        """Verifies that IssueKind and SceneStatus enums only contain active modern members."""
        expected_kinds = {"auto_split", "soft_boundary"}
        actual_kinds = {k.value for k in IssueKind}
        self.assertEqual(actual_kinds, expected_kinds)

        expected_statuses = {"open", "closed", "no_end_tag"}
        actual_statuses = {s.value for s in SceneStatus}
        self.assertEqual(actual_statuses, expected_statuses)

        expected_reasons = {"separate_roster", "start_tag_roster_change", "start_tag_same_roster", "roster_change"}
        actual_reasons = {r.value for r in IssueReason}
        self.assertEqual(actual_reasons, expected_reasons)

    def test_schema_version_tracking(self):
        """Verifies that schema_version table correctly tracks CURRENT_SCHEMA_VERSION."""
        current_ver = get_db_schema_version(self.engine)
        self.assertEqual(current_ver, CURRENT_SCHEMA_VERSION)

        with self.Session() as session:
            record = session.query(SchemaVersionModel).filter_by(version=CURRENT_SCHEMA_VERSION).first()
            self.assertIsNotNone(record)
            self.assertIsNotNone(record.applied_at)

    def test_schema_version_mismatch_raises_error(self):
        """Verifies that init_db raises DatabaseSchemaMismatchError when DB version < CURRENT_SCHEMA_VERSION."""
        # Wipe schema_version table to simulate legacy v0 database with existing tables
        with self.Session() as session:
            session.query(SchemaVersionModel).delete()
            session.commit()

        self.assertEqual(get_db_schema_version(self.engine), 0)

        # Calling init_db with check_version=True should raise DatabaseSchemaMismatchError
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

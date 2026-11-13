import os
import shutil
import sqlite3
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
from db.session import init_db, get_db_schema_version, has_db, require_db, close_all_engines
# pyrefly: ignore [missing-import]
from db import status_service, character_service
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

    def test_central_database_url_without_local_sqlite_file(self):
        """Verifies services and db checks work via DATABASE_URL without a local backup.sqlite file."""
        from unittest.mock import patch

        close_all_engines()
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_folder = Path(tmpdir) / "empty_backup_dir"
            backup_folder.mkdir()
            central_db_path = Path(tmpdir) / "central_service.db"
            central_url = f"sqlite:///{central_db_path.as_posix()}"

            with patch.dict(os.environ, {"DATABASE_URL": central_url}):
                close_all_engines()
                try:
                    self.assertTrue(has_db(backup_folder.as_posix()))
                    require_db(backup_folder.as_posix())

                    status_service.init_backup_export(
                        backup_id="central_backup_1",
                        backup_path=backup_folder.as_posix(),
                        backup_name="Central DB Test Backup",
                        server_id="123456",
                        server_name="Central Test Server",
                    )
                    character_service.save_new_characters(
                        backup_id="central_backup_1",
                        base_path=backup_folder.as_posix(),
                        new_characters=[(101, "CentralHero")],
                        write_snapshot=False,
                    )
                    chars = character_service.get_characters(
                        backup_id="central_backup_1",
                        base_path=backup_folder.as_posix(),
                    )
                    self.assertEqual(len(chars), 1)
                    self.assertEqual(chars[0]["names"][0], "CentralHero")
                    self.assertFalse((backup_folder / "backup.sqlite").exists())
                finally:
                    close_all_engines()


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


class TestSqliteWalCheckpointing(unittest.TestCase):
    """Ensures SQLite commits checkpoint WAL back into backup.sqlite so standalone .sqlite files stay up to date."""

    def test_status_update_is_checkpointed_into_standalone_sqlite_file(self):
        from db import status_service
        from db.session import close_all_engines

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backup_wal_test"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_id = "wal_test_1"
            base_path = backup_dir.as_posix()

            try:
                status_service.init_backup_export(
                    backup_id=backup_id,
                    backup_path=base_path,
                    backup_name="WAL Test",
                )
                # Step 1: mark index_scenes running
                status_service.update_step_status(backup_id, base_path, "index_scenes", "running", write_snapshot=False)
                # Simulate an active read from the pooled engine (uvicorn polling)
                state_running = status_service.load_backup_state(backup_id, base_path)
                self.assertEqual(state_running["steps"]["index_scenes"], "running")

                # Step 2: update step to success WITHOUT calling close_all_engines() first
                status_service.update_step_status(backup_id, base_path, "index_scenes", "success", write_snapshot=False)

                # Copy ONLY backup.sqlite (intentionally omitting -wal and -shm) to verify self-contained state
                standalone_copy = Path(tmpdir) / "standalone.sqlite"
                shutil.copy2(backup_dir / "backup.sqlite", standalone_copy)

                conn = sqlite3.connect(standalone_copy.as_posix())
                try:
                    rows = conn.execute(
                        "SELECT step, status FROM backup_steps WHERE step = 'index_scenes'"
                    ).fetchall()
                finally:
                    conn.close()

                self.assertEqual(rows, [("index_scenes", "success")])
            finally:
                close_all_engines()


class TestSqliteTmpCacheAndSync(unittest.TestCase):
    """Tests Option B: local /tmp SQLite caching, dirty tracking, debounced GCS sync, and stale-cache refresh."""

    def test_activation_guard(self):
        from unittest.mock import patch
        from db.session import is_sqlite_tmp_cache_enabled

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOCRATES_SQLITE_TMP_CACHE", None)
            os.environ.pop("SOCRATES_DATA_DIR", None)
            os.environ.pop("DATABASE_URL", None)
            self.assertFalse(is_sqlite_tmp_cache_enabled())

        with patch.dict(os.environ, {"SOCRATES_DATA_DIR": "/mnt/socrates-data"}, clear=False):
            os.environ.pop("SOCRATES_SQLITE_TMP_CACHE", None)
            os.environ.pop("DATABASE_URL", None)
            self.assertTrue(is_sqlite_tmp_cache_enabled())

        with patch.dict(os.environ, {"SOCRATES_DATA_DIR": "/mnt/socrates-data", "SOCRATES_SQLITE_TMP_CACHE": "0"}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            self.assertFalse(is_sqlite_tmp_cache_enabled())

        with patch.dict(os.environ, {"SOCRATES_SQLITE_TMP_CACHE": "1", "DATABASE_URL": "postgresql://localhost/db"}, clear=False):
            self.assertFalse(is_sqlite_tmp_cache_enabled())

    def test_copy_on_load_debounced_sync_and_stale_refresh(self):
        from unittest.mock import patch
        from db import status_service
        from db.session import (
            close_all_engines,
            get_engine,
            get_tmp_sqlite_path,
            invalidate_sqlite_tmp_cache,
            sync_dirty_sqlite_dbs,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backup_gcs"
            tmp_cache_root = Path(tmpdir) / "tmp_cache"
            backup_dir.mkdir(parents=True, exist_ok=True)
            tmp_cache_root.mkdir(parents=True, exist_ok=True)

            backup_id = "tmp_sync_test_1"
            base_path = backup_dir.as_posix()
            source_sqlite = os.path.abspath((backup_dir / "backup.sqlite").as_posix()).replace("\\", "/")

            # 1. Local dev mode (disabled): opens source_sqlite directly, no /tmp copy created
            env_disabled = {
                "SOCRATES_SQLITE_TMP_CACHE": "0",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
            }
            with patch.dict(os.environ, env_disabled, clear=False):
                close_all_engines()
                status_service.init_backup_export(
                    backup_id=backup_id,
                    backup_path=base_path,
                    backup_name="Tmp Cache Test",
                )
                eng_local = get_engine(backup_id=backup_id, backup_path=base_path)
                self.assertEqual(
                    os.path.abspath(eng_local.url.database).replace("\\", "/"),
                    os.path.abspath(source_sqlite).replace("\\", "/"),
                )
                self.assertFalse(os.path.exists(get_tmp_sqlite_path(source_sqlite)))
                close_all_engines()

            # 2. Cloud/FUSE mode (enabled): copies source_sqlite to /tmp on load
            env_enabled = {
                "SOCRATES_SQLITE_TMP_CACHE": "1",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
                "SOCRATES_SQLITE_SYNC_TIMER": "0",
            }
            with patch.dict(os.environ, env_enabled, clear=False):
                try:
                    invalidate_sqlite_tmp_cache(backup_id=backup_id, backup_path=base_path)
                    eng_tmp = get_engine(backup_id=backup_id, backup_path=base_path)
                    expected_tmp = get_tmp_sqlite_path(source_sqlite)
                    self.assertEqual(
                        os.path.abspath(eng_tmp.url.database).replace("\\", "/"),
                        os.path.abspath(expected_tmp).replace("\\", "/"),
                    )
                    self.assertTrue(os.path.exists(expected_tmp))

                    # 3. Committed write marks dirty; first sync materializes standalone backup.sqlite
                    status_service.update_step_status(
                        backup_id, base_path, "index_scenes", "running", write_snapshot=False
                    )
                    synced = sync_dirty_sqlite_dbs(force=False, min_interval=10.0)
                    self.assertEqual(synced, [source_sqlite])

                    # Verify standalone source_sqlite has "running"
                    conn = sqlite3.connect(source_sqlite)
                    try:
                        rows = conn.execute(
                            "SELECT step, status FROM backup_steps WHERE step = 'index_scenes'"
                        ).fetchall()
                    finally:
                        conn.close()
                    self.assertEqual(rows, [("index_scenes", "running")])

                    # 4. Rapid second write within min_interval is debounced (skipped)
                    status_service.update_step_status(
                        backup_id, base_path, "index_scenes", "success", write_snapshot=False
                    )
                    skipped = sync_dirty_sqlite_dbs(force=False, min_interval=10.0)
                    self.assertEqual(skipped, [])

                    # Target source_sqlite still has "running" until forced or interval elapses
                    conn = sqlite3.connect(source_sqlite)
                    try:
                        rows = conn.execute(
                            "SELECT step, status FROM backup_steps WHERE step = 'index_scenes'"
                        ).fetchall()
                    finally:
                        conn.close()
                    self.assertEqual(rows, [("index_scenes", "running")])

                    # 5. close_all_engines() forces sync before disposing
                    close_all_engines()
                    conn = sqlite3.connect(source_sqlite)
                    try:
                        rows = conn.execute(
                            "SELECT step, status FROM backup_steps WHERE step = 'index_scenes'"
                        ).fetchall()
                    finally:
                        conn.close()
                    self.assertEqual(rows, [("index_scenes", "success")])

                    # 6. External replacement of source_sqlite is picked up on next open
                    ext_copy = Path(tmpdir) / "external_modified.sqlite"
                    shutil.copy2(source_sqlite, ext_copy)
                    ext_conn = sqlite3.connect(ext_copy.as_posix())
                    try:
                        ext_conn.execute(
                            "UPDATE backup_steps SET status = 'failed' WHERE step = 'index_scenes'"
                        )
                        ext_conn.commit()
                    finally:
                        ext_conn.close()
                    shutil.copy2(ext_copy, source_sqlite)

                    reloaded = status_service.load_backup_state(backup_id, base_path)
                    self.assertEqual(reloaded["steps"]["index_scenes"], "failed")
                finally:
                    close_all_engines()
                    invalidate_sqlite_tmp_cache(backup_id=backup_id, backup_path=base_path)

    def test_brand_new_backup_initialization_and_sync(self):
        from unittest.mock import patch
        from db import status_service
        from db.session import (
            close_all_engines,
            get_tmp_sqlite_path,
            has_db,
            require_db,
            sync_dirty_sqlite_dbs,
            invalidate_sqlite_tmp_cache,
            _stat_file,
            _read_source_meta,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "new_backup_gcs"
            tmp_cache_root = Path(tmpdir) / "tmp_cache"
            backup_dir.mkdir(parents=True, exist_ok=True)
            tmp_cache_root.mkdir(parents=True, exist_ok=True)

            backup_id = "brand_new_backup_1"
            base_path = backup_dir.as_posix()
            source_sqlite = os.path.abspath((backup_dir / "backup.sqlite").as_posix()).replace("\\", "/")

            env = {
                "SOCRATES_SQLITE_TMP_CACHE": "1",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
                "SOCRATES_SQLITE_SYNC_TIMER": "0",
            }
            with patch.dict(os.environ, env, clear=False):
                try:
                    close_all_engines()
                    self.assertFalse(has_db(backup_path=base_path))
                    with self.assertRaises(exc.DatabaseConnectionError):
                        require_db(backup_path=base_path)

                    # Initialize brand new backup in /tmp
                    status_service.init_backup_export(
                        backup_id=backup_id,
                        backup_path=base_path,
                        backup_name="Brand New Backup",
                    )
                    expected_tmp = get_tmp_sqlite_path(source_sqlite)
                    self.assertTrue(os.path.exists(expected_tmp))
                    # Source on GCS should not exist yet before sync
                    self.assertFalse(os.path.exists(source_sqlite))

                    # has_db() and require_db() recognize the /tmp cached DB
                    self.assertTrue(has_db(backup_path=base_path))
                    require_db(backup_path=base_path)

                    # Flush to GCS
                    synced = sync_dirty_sqlite_dbs(force=True)
                    self.assertEqual(synced, [source_sqlite])
                    self.assertTrue(os.path.exists(source_sqlite))

                    # Verify source_sqlite has valid tables and schema
                    conn = sqlite3.connect(source_sqlite)
                    try:
                        step_rows = conn.execute("SELECT step FROM backup_steps").fetchall()
                    finally:
                        conn.close()
                    self.assertGreater(len(step_rows), 0)

                    # Verify .source_meta.json matches source stat
                    source_stat = _stat_file(source_sqlite)
                    meta_stat = _read_source_meta(expected_tmp)
                    self.assertIsNotNone(source_stat)
                    self.assertEqual(source_stat, meta_stat)
                finally:
                    close_all_engines()
                    invalidate_sqlite_tmp_cache(backup_id=backup_id, backup_path=base_path)

    def test_cross_device_link_exdev_fallback(self):
        from unittest.mock import patch
        from db.session import (
            close_all_engines,
            get_tmp_sqlite_path,
            sync_dirty_sqlite_dbs,
            invalidate_sqlite_tmp_cache,
        )
        from db import status_service

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "exdev_backup"
            tmp_cache_root = Path(tmpdir) / "tmp_cache"
            backup_dir.mkdir(parents=True, exist_ok=True)
            tmp_cache_root.mkdir(parents=True, exist_ok=True)

            backup_id = "exdev_test_1"
            base_path = backup_dir.as_posix()
            source_sqlite = os.path.abspath((backup_dir / "backup.sqlite").as_posix()).replace("\\", "/")

            env = {
                "SOCRATES_SQLITE_TMP_CACHE": "1",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
                "SOCRATES_SQLITE_SYNC_TIMER": "0",
            }
            with patch.dict(os.environ, env, clear=False):
                try:
                    close_all_engines()
                    status_service.init_backup_export(
                        backup_id=backup_id,
                        backup_path=base_path,
                        backup_name="EXDEV Test",
                    )
                    expected_tmp = get_tmp_sqlite_path(source_sqlite)

                    real_replace = os.replace

                    # Simulate EXDEV on initial cross-device os.replace(staging_path, source_sqlite_path)
                    def mock_replace(src, dst):
                        if ".sync." in str(src) and str(dst) == source_sqlite and not str(src).startswith(str(backup_dir)):
                            raise OSError(18, "Invalid cross-device link")
                        return real_replace(src, dst)

                    with patch("os.replace", side_effect=mock_replace):
                        synced = sync_dirty_sqlite_dbs(force=True)
                        self.assertEqual(synced, [source_sqlite])
                        self.assertTrue(os.path.exists(source_sqlite))

                    # Verify database was copied cleanly despite simulated EXDEV
                    conn = sqlite3.connect(source_sqlite)
                    try:
                        step_rows = conn.execute("SELECT step FROM backup_steps").fetchall()
                    finally:
                        conn.close()
                    self.assertGreater(len(step_rows), 0)
                finally:
                    close_all_engines()
                    invalidate_sqlite_tmp_cache(backup_id=backup_id, backup_path=base_path)

    def test_middleware_opportunistic_get_sync(self):
        from unittest.mock import patch, MagicMock
        from db import status_service
        from db.session import (
            close_all_engines,
            sync_dirty_sqlite_dbs,
            invalidate_sqlite_tmp_cache,
            _last_sync_times,
        )
        from server import sqlite_tmp_sync_middleware

        def run_coro_sync(coro):
            try:
                while True:
                    coro.send(None)
            except StopIteration as stop:
                return stop.value

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "middleware_backup"
            tmp_cache_root = Path(tmpdir) / "tmp_cache"
            backup_dir.mkdir(parents=True, exist_ok=True)
            tmp_cache_root.mkdir(parents=True, exist_ok=True)

            backup_id = "middleware_test_1"
            base_path = backup_dir.as_posix()
            source_sqlite = os.path.abspath((backup_dir / "backup.sqlite").as_posix()).replace("\\", "/")

            env = {
                "SOCRATES_SQLITE_TMP_CACHE": "1",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
                "SOCRATES_SQLITE_SYNC_TIMER": "0",
                "SOCRATES_SQLITE_SYNC_INTERVAL": "5.0",
            }
            with patch.dict(os.environ, env, clear=False):
                try:
                    close_all_engines()
                    status_service.init_backup_export(
                        backup_id=backup_id,
                        backup_path=base_path,
                        backup_name="Middleware Test",
                    )
                    # Initial sync
                    sync_dirty_sqlite_dbs(force=True)

                    # Mutate DB in /tmp to mark dirty
                    status_service.update_step_status(
                        backup_id, base_path, "index_scenes", "running", write_snapshot=False
                    )

                    # Simulate that last sync was 10s ago (> 5s min_interval)
                    import time
                    _last_sync_times[source_sqlite] = time.monotonic() - 10.0

                    # Simulate incoming GET request through middleware
                    mock_request = MagicMock()
                    mock_request.method = "GET"

                    async def dummy_call_next(req):
                        return "ok_response"

                    res = run_coro_sync(sqlite_tmp_sync_middleware(mock_request, dummy_call_next))
                    self.assertEqual(res, "ok_response")

                    # Verify that source_sqlite on GCS was updated by the opportunistic GET sync
                    conn = sqlite3.connect(source_sqlite)
                    try:
                        rows = conn.execute(
                            "SELECT step, status FROM backup_steps WHERE step = 'index_scenes'"
                        ).fetchall()
                    finally:
                        conn.close()
                    self.assertEqual(rows, [("index_scenes", "running")])
                finally:
                    close_all_engines()
                    invalidate_sqlite_tmp_cache(backup_id=backup_id, backup_path=base_path)

    def test_upgrade_rollback_invalidates_cache_without_sync(self):
        from unittest.mock import patch
        from db import status_service
        from db.session import (
            close_all_engines,
            get_tmp_sqlite_path,
            sync_dirty_sqlite_dbs,
            invalidate_sqlite_tmp_cache,
        )
        from db.upgrade import upgrade_single_backup

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "upgrade_backup"
            tmp_cache_root = Path(tmpdir) / "tmp_cache"
            backup_dir.mkdir(parents=True, exist_ok=True)
            tmp_cache_root.mkdir(parents=True, exist_ok=True)

            backup_id = "upgrade_test_1"
            base_path = backup_dir.as_posix()
            source_sqlite = os.path.abspath((backup_dir / "backup.sqlite").as_posix()).replace("\\", "/")

            env = {
                "SOCRATES_SQLITE_TMP_CACHE": "1",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
                "SOCRATES_SQLITE_SYNC_TIMER": "0",
            }
            with patch.dict(os.environ, env, clear=False):
                try:
                    close_all_engines()
                    status_service.init_backup_export(
                        backup_id=backup_id,
                        backup_path=base_path,
                        backup_name="Upgrade Test",
                    )
                    status_service.update_step_status(
                        backup_id, base_path, "index_scenes", "success", write_snapshot=False
                    )
                    sync_dirty_sqlite_dbs(force=True)

                    backup_dict = {
                        "backup_id": backup_id,
                        "backup_name": "Upgrade Test",
                        "path": base_path,
                    }

                    # 1. Successful upgrade cleans up .bak and syncs
                    res = upgrade_single_backup(backup_dict, dry_run=False, reindex_scenes=False)
                    self.assertFalse(res["dry_run"])
                    self.assertFalse(os.path.exists(f"{source_sqlite}.bak"))

                    # 2. Failed upgrade rolls back safely, restores safety copy, and removes .bak
                    def fail_populate(*args, **kwargs):
                        raise RuntimeError("Simulated failure during table population")

                    with patch("db.upgrade.populate_schema", side_effect=fail_populate):
                        with self.assertRaises(exc.DatabaseUpgradeError):
                            upgrade_single_backup(backup_dict, dry_run=False, reindex_scenes=False)

                    # 3. Failed reindex_scenes during upgrade logs original error and raises DatabaseUpgradeError
                    with patch("index_scenes.index_scenes", side_effect=RuntimeError("Simulated reindex failure")):
                        with self.assertRaises(exc.DatabaseUpgradeError) as reindex_ctx:
                            upgrade_single_backup(backup_dict, dry_run=False, reindex_scenes=True)
                        self.assertIn("Simulated reindex failure", str(reindex_ctx.exception))

                    # Verify safety backup file was cleaned up and source_sqlite is still readable
                    self.assertFalse(os.path.exists(f"{source_sqlite}.bak"))
                    conn = sqlite3.connect(source_sqlite)
                    try:
                        rows = conn.execute(
                            "SELECT step, status FROM backup_steps WHERE step = 'index_scenes'"
                        ).fetchall()
                    finally:
                        conn.close()
                    self.assertEqual(rows, [("index_scenes", "success")])
                finally:
                    close_all_engines()
                    invalidate_sqlite_tmp_cache(backup_id=backup_id, backup_path=base_path)

    def test_reset_test_backup_invalidates_tmp_cache(self):
        from unittest.mock import patch
        from db import status_service
        from db.session import (
            close_all_engines,
            get_tmp_sqlite_path,
            has_db,
            invalidate_sqlite_tmp_cache,
        )
        import tests.reset_test_backup as rtb

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_root = Path(tmpdir)
            clean_dir = fake_root / "Backups" / "Elysium-sql-tests-clean"
            target_dir = fake_root / "Backups" / "Elysium-sql-tests"
            tmp_cache_root = fake_root / "tmp_cache"
            clean_dir.mkdir(parents=True, exist_ok=True)
            target_dir.mkdir(parents=True, exist_ok=True)
            tmp_cache_root.mkdir(parents=True, exist_ok=True)
            (clean_dir / "backup_config.json").write_text("{}", encoding="utf-8")

            base_path = target_dir.as_posix()
            source_sqlite = os.path.abspath((target_dir / "backup.sqlite").as_posix()).replace("\\", "/")

            env = {
                "SOCRATES_SQLITE_TMP_CACHE": "1",
                "SOCRATES_SQLITE_TMP_DIR": tmp_cache_root.as_posix(),
                "SOCRATES_SQLITE_SYNC_TIMER": "0",
            }
            with patch.dict(os.environ, env, clear=False), patch.object(rtb, "DATA_ROOT", fake_root):
                try:
                    close_all_engines()
                    status_service.init_backup_export(
                        backup_id="reset_tmp_test",
                        backup_path=base_path,
                        backup_name="Reset Tmp Test",
                    )
                    expected_tmp = get_tmp_sqlite_path(source_sqlite)
                    self.assertTrue(os.path.exists(expected_tmp))
                    self.assertTrue(has_db(backup_path=base_path))

                    self.assertTrue(rtb.reset_test_backup())
                    self.assertFalse(os.path.exists(source_sqlite))
                    self.assertFalse(os.path.exists(expected_tmp))
                    self.assertFalse(has_db(backup_path=base_path))
                finally:
                    close_all_engines()
                    invalidate_sqlite_tmp_cache(backup_path=base_path)


if __name__ == "__main__":
    unittest.main()

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import OperationalError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
for p in (SRC_DIR.as_posix(), PROJECT_ROOT.as_posix()):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("SOCRATES_ENV", "development")
os.environ.setdefault("JWT_SECRET", "a_very_strong_test_jwt_secret_key_with_more_than_32_bytes")

import download_channels  # noqa: E402
import find_character_scenes  # noqa: E402
import get_server_info  # noqa: E402
import index_sessions  # noqa: E402
import rbac  # noqa: E402
import server  # noqa: E402
import utils.exceptions as exc  # noqa: E402
import utils.tricks as t  # noqa: E402
from db import audit_service, curation_service, event_service, scene_service  # noqa: E402
from db.audit_models import AuditLog  # noqa: E402
from db.models import BackupModel, ChannelModel, EventModel, ExportModel, SceneModel  # noqa: E402
from db.session import (  # noqa: E402
    checkpoint_wal,
    close_all_engines,
    db_session,
    global_audit_db_session,
    init_db,
)
from models import SceneManager  # noqa: E402
from tests.test_security_phase1 import (  # noqa: E402
    INSTANCE_ADMIN_DISCORD_ID,
    STRONG_TEST_SECRET,
    _make_jwt,
    _make_test_client,
)
from utils.path_safety import (  # noqa: E402
    DISCORD_MSG_LINK_RE,
    ensure_safe_backup_path,
    escape_like,
    safe_join_within,
    sanitize_backup_slug,
    scrub_sensitive_env,
    validate_backup_id,
    validate_channel_ids,
    validate_snowflake,
)


TEST_BACKUP_ID = "4455667788"
TEST_GUILD_ID = "880011223344556611"
UID_ADMIN = "200000000000000011"
UID_CURATOR = "200000000000000012"
ROLE_ADMIN_ID = "100000000000000011"
ROLE_CURATOR_ID = "100000000000000012"


def _cookie_for(sub: str, guilds=None, csrf: str = "phase4-csrf") -> dict:
    tok = _make_jwt(
        {
            "sub": sub,
            "username": f"user_{sub}",
            "auth_method": "discord",
            "authorized_guilds": guilds or [],
            "jti": f"jti-{sub}",
            "csrf": csrf,
        }
    )
    return {"__session": tok}


class TestSubprocessAndCommandHardening(unittest.TestCase):
    """Tests shell=True elimination, ALLOWED_STEPS, channel_ids validation, and env scrubbing."""

    def test_run_command_rejects_string_and_uses_shell_false_list(self):
        with self.assertRaises(exc.ConsoleCommandError):
            t.run_command("echo pwned && whoami")

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["ok\n"])
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0

        with patch.dict(
            os.environ,
            {
                "JWT_SECRET": STRONG_TEST_SECRET,
                "DISCORD_CLIENT_SECRET": "client-secret-xyz",
                "DISCORD_TOKEN": "bot-token-xyz",
            },
            clear=False,
        ):
            with patch.object(t.subprocess, "Popen", return_value=mock_proc) as mock_popen:
                code, out = t.run_command(["echo", "hello"])
                self.assertEqual(code, 0)
                self.assertIn("ok", out)
                self.assertFalse(mock_popen.call_args.kwargs["shell"])
                self.assertEqual(mock_popen.call_args.args[0], ["echo", "hello"])
                child_env = mock_popen.call_args.kwargs["env"]
                self.assertNotIn("JWT_SECRET", child_env)
                self.assertNotIn("DISCORD_CLIENT_SECRET", child_env)
                self.assertEqual(child_env.get("DISCORD_TOKEN"), "bot-token-xyz")

    def test_dce_wrappers_pass_argv_lists_and_reject_invalid_ids(self):
        with self.assertRaises(exc.GetChannelListError) as ctx:
            get_server_info.get_categories("857848490683269161; rm -rf /")
        self.assertIsInstance(ctx.exception.__cause__, ValueError)

        with patch.object(t, "run_command", return_value=(0, "111 \\ 1# Cat\n")) as mock_rc:
            cats = get_server_info.get_categories("857848490683269161")
            self.assertEqual(cats, {"111": "1# Cat"})
            argv = mock_rc.call_args.args[0]
            self.assertIsInstance(argv, list)
            self.assertIn("channels", argv)
            self.assertIn("857848490683269161", argv)

        with self.assertRaises(exc.DownloadExportError):
            download_channels.download_full_category("General", "not-digits && calc", None)

        with patch.object(t, "run_command", return_value=(0, "done")) as mock_rc:
            download_channels.download_full_category("General", "857848490683269161", None)
            argv = mock_rc.call_args.args[0]
            self.assertIsInstance(argv, list)
            self.assertIn("export", argv)
            self.assertIn("857848490683269161", argv)

    def test_run_script_in_background_allowlist_and_secret_scrubbing(self):
        with patch.object(server.subprocess, "Popen") as mock_popen:
            server.run_script_in_background("../../evil.py", TEST_BACKUP_ID)
            mock_popen.assert_not_called()

            server.run_script_in_background("backup_server.py", "../traversal")
            mock_popen.assert_not_called()

        mock_proc = MagicMock()
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = 0
        mock_proc.returncode = 0

        with tempfile.TemporaryDirectory() as tmpdir:
            b_dir = Path(tmpdir) / "Backups" / "SafeBackup"
            b_dir.mkdir(parents=True)
            entries = [{"backup_id": TEST_BACKUP_ID, "path": "Backups/SafeBackup"}]

            with patch.dict(
                os.environ,
                {
                    "JWT_SECRET": STRONG_TEST_SECRET,
                    "DISCORD_CLIENT_SECRET": "oauth-secret",
                    "DISCORD_TOKEN": "bot-token",
                },
                clear=False,
            ):
                with patch.object(server, "get_data_root", return_value=tmpdir), patch.object(
                    t, "get_backups_index", return_value=entries
                ), patch.object(server.subprocess, "Popen", return_value=mock_proc) as mock_popen:
                    # Non-Discord step scrubs DISCORD_TOKEN, JWT_SECRET, DISCORD_CLIENT_SECRET
                    server.run_script_in_background("index_scenes.py", TEST_BACKUP_ID)
                    env_non_discord = mock_popen.call_args.kwargs["env"]
                    self.assertNotIn("DISCORD_TOKEN", env_non_discord)
                    self.assertNotIn("DISCORD_CLIENT_SECRET", env_non_discord)
                    self.assertNotIn("JWT_SECRET", env_non_discord)

                    # Pipeline fetch step keeps DISCORD_TOKEN, scrubs JWT_SECRET & DISCORD_CLIENT_SECRET
                    server.run_script_in_background("backup_server.py", TEST_BACKUP_ID)
                    env_pipeline = mock_popen.call_args.kwargs["env"]
                    self.assertEqual(env_pipeline.get("DISCORD_TOKEN"), "bot-token")
                    self.assertNotIn("DISCORD_CLIENT_SECRET", env_pipeline)
                    self.assertNotIn("JWT_SECRET", env_pipeline)


class TestPathSafetyAndValidationHelpers(unittest.TestCase):
    """Tests path containment, filename sanitization, WAL allowlist, LIKE escaping, and ReDoS."""

    def test_path_containment_and_identifiers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backups_dir = Path(tmpdir) / "Backups" / "MyServer"
            backups_dir.mkdir(parents=True)

            resolved = ensure_safe_backup_path("Backups/MyServer", tmpdir)
            self.assertEqual(resolved, backups_dir.resolve())

            for bad_path in ["../../etc/passwd", "Backups", "Backups/../../secret", "/etc/passwd", "C:/Windows/System32"]:
                with self.subTest(bad_path=bad_path):
                    with self.assertRaises(ValueError):
                        ensure_safe_backup_path(bad_path, tmpdir)

            with self.assertRaises(ValueError):
                safe_join_within(backups_dir, "..", "outside.txt")

        self.assertEqual(t.sanitize_filename(".."), "unnamed")
        self.assertEqual(t.sanitize_filename("."), "unnamed")
        self.assertEqual(sanitize_backup_slug("../../My Cool Server!"), "My_Cool_Server")
        self.assertEqual(validate_backup_id("1791895360"), "1791895360")
        with self.assertRaises(ValueError):
            validate_backup_id("../evil")
        with self.assertRaises(ValueError):
            validate_snowflake("123")
        self.assertEqual(validate_channel_ids(["12345", "67890"]), ["12345", "67890"])
        with self.assertRaises(ValueError):
            validate_channel_ids(["12345;whoami"])
        with self.assertRaises(ValueError):
            validate_channel_ids(["1"] * 101)

    def test_wal_mode_allowlist_and_scrub_env(self):
        with self.assertRaises(ValueError):
            checkpoint_wal(mode="TRUNCATE; ATTACH DATABASE '/tmp/pwn' AS pwn")
        env = scrub_sensitive_env({"JWT_SECRET": "a", "DISCORD_CLIENT_SECRET": "b", "DISCORD_TOKEN": "c", "PATH": "x"})
        self.assertEqual(env, {"PATH": "x"})

    def test_redos_patterns_complete_in_linear_time(self):
        # Adversarial inputs targeting historical catastrophic backtracking patterns
        evil_mentions = "@a " * 6000 + "!"
        evil_header = "@" * 3000 + "!"
        evil_end = "`end " + "a " * 6000
        evil_apology = "sorry " + ("word " * 4000)

        t0 = time.perf_counter()
        self.assertIsNone(find_character_scenes.MENTION_ONLY_PAT.match(evil_mentions))
        self.assertFalse(find_character_scenes.has_start_tag(evil_header))
        self.assertFalse(find_character_scenes.has_end_tag(evil_end))
        self.assertFalse(index_sessions.has_apology_continuation({"content": evil_apology}))
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertLess(elapsed_ms, 150.0)

        # Positive matches preserved
        self.assertIsNotNone(find_character_scenes.MENTION_ONLY_PAT.match("<@123456> @Role Name"))
        self.assertTrue(find_character_scenes.has_end_tag("Some roleplay text `[End]`"))
        self.assertTrue(index_sessions.has_apology_continuation({"content": "Sorry for the delay, back now!"}))

    def test_anchored_discord_link_regex(self):
        self.assertIsNotNone(
            DISCORD_MSG_LINK_RE.fullmatch(
                "https://discord.com/channels/857848490683269161/857848490683269162/857848490683269163"
            )
        )
        self.assertIsNone(
            DISCORD_MSG_LINK_RE.fullmatch(
                "https://evil.example/channels/857848490683269161/857848490683269162/857848490683269163"
            )
        )


class TestHttpHardeningPhase4(unittest.TestCase):
    """End-to-end HTTP tests for strict schemas, CSRF, CORS, query bounds, SSE limits, and sanitized 500s."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.data_root = Path(cls._tmpdir.name)
        cls.backup_dir = cls.data_root / "Backups" / "Phase4Backup"
        cls.backup_dir.mkdir(parents=True)
        (cls.data_root / "out").mkdir(parents=True)

        with open(cls.backup_dir / "backup_config.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "server_id": TEST_GUILD_ID,
                    "backup_id": TEST_BACKUP_ID,
                    "rbac": {
                        "adminRoleIds": [ROLE_ADMIN_ID],
                        "curatorRoleIds": [ROLE_CURATOR_ID],
                        "participantRoleIds": [],
                        "restrictedUserIds": [],
                        "blockedUserIds": [],
                    },
                },
                f,
            )
        with open(cls.backup_dir / "log.txt", "w", encoding="utf-8") as f:
            f.write("2026-01-01 INFO phase4 line 1\n")

        cls.index_entries = [
            {
                "backup_id": TEST_BACKUP_ID,
                "backup_name": "Phase4Backup",
                "server_id": TEST_GUILD_ID,
                "server_name": "Phase4 Guild",
                "path": "Backups/Phase4Backup",
            },
            {
                "backup_id": "99887766",
                "backup_name": "EscapeBackup",
                "server_id": TEST_GUILD_ID,
                "server_name": "Phase4 Guild",
                "path": "../../outside_dir",
            },
        ]

        init_db(backup_id=TEST_BACKUP_ID, backup_path=cls.backup_dir.as_posix())
        with db_session(backup_id=TEST_BACKUP_ID, backup_path=cls.backup_dir.as_posix()) as session:
            session.add(
                BackupModel(
                    backup_id=TEST_BACKUP_ID,
                    backup_name="Phase4Backup",
                    server_id=TEST_GUILD_ID,
                    server_name="Phase4 Guild",
                    created_at=datetime.now(timezone.utc),
                )
            )
            export = ExportModel(backup_id=TEST_BACKUP_ID, scope="base")
            session.add(export)
            session.flush()
            cat = ChannelModel(
                export_pk=export.pk,
                discord_id="444555666777888999",
                name="1# Cat",
                type="GuildCategory",
                position=1,
                path="Data/1# Cat",
            )
            session.add(cat)
            session.flush()
            ch = ChannelModel(
                export_pk=export.pk,
                discord_id="555666777888999000",
                name="general_chat",
                type="GuildTextChat",
                parent_pk=cat.pk,
                position=1,
                path="Data/1# Cat/1# general_chat.json",
            )
            session.add(ch)
            session.flush()
            session.add_all(
                [
                    SceneModel(
                        backup_id=TEST_BACKUP_ID,
                        scene_key="scene-1",
                        channel_pk=ch.pk,
                        category_pk=cat.pk,
                        custom_name="100% Real Scene",
                        kind="scene",
                        status="active",
                        start_message_id="100000000000000001",
                        end_message_id="100000000000000002",
                        start_index=0,
                        end_index=1,
                        start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        end_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                        start_author_id="111222333444555666",
                        end_author_id="111222333444555666",
                    ),
                    SceneModel(
                        backup_id=TEST_BACKUP_ID,
                        scene_key="scene-2",
                        channel_pk=ch.pk,
                        category_pk=cat.pk,
                        custom_name="Normal Tavern Scene",
                        kind="scene",
                        status="active",
                        start_message_id="100000000000000003",
                        end_message_id="100000000000000004",
                        start_index=2,
                        end_index=3,
                        start_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                        end_at=datetime(2026, 1, 2, 1, tzinfo=timezone.utc),
                        start_author_id="111222333444555666",
                        end_author_id="111222333444555666",
                    ),
                    EventModel(
                        backup_id=TEST_BACKUP_ID,
                        event_key="evt-1",
                        name="Winter_Ball 50%",
                        status="active",
                        start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        end_at=datetime(2026, 1, 1, 2, tzinfo=timezone.utc),
                    ),
                    EventModel(
                        backup_id=TEST_BACKUP_ID,
                        event_key="evt-2",
                        name="Summer Picnic",
                        status="active",
                        start_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                        end_at=datetime(2026, 1, 2, 2, tzinfo=timezone.utc),
                    ),
                ]
            )
        close_all_engines()

    @classmethod
    def tearDownClass(cls):
        SceneManager.clear_cache()
        close_all_engines()
        cls._tmpdir.cleanup()

    def setUp(self):
        server.clear_bot_guilds_cache()
        server.clear_revoked_jtis()
        rbac.clear_rbac_caches()
        with server._SSE_ACTIVE_STREAMS_LOCK:
            server._SSE_ACTIVE_STREAMS.clear()
        self.raw_client = _make_test_client(server.app, include_csrf_headers=False)
        self.ui_client = _make_test_client(server.app, include_csrf_headers=True)

        self.env_patcher = patch.dict(
            os.environ,
            {
                "SOCRATES_ENV": "development",
                "JWT_SECRET": STRONG_TEST_SECRET,
                "SOCRATES_INSTANCE_ADMINS": INSTANCE_ADMIN_DISCORD_ID,
                "DISCORD_TOKEN": "fake-bot-token",
            },
            clear=False,
        )
        self.env_patcher.start()

        def fake_httpx_get(url, headers=None, timeout=10.0):
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith(f"/members/{UID_ADMIN}"):
                resp.json.return_value = {"roles": [ROLE_ADMIN_ID]}
            elif url.endswith(f"/members/{UID_CURATOR}"):
                resp.json.return_value = {"roles": [ROLE_CURATOR_ID]}
            else:
                resp.json.return_value = {"roles": []}
            return resp

        self.patches = [
            patch.object(server, "get_data_root", return_value=self.data_root.as_posix()),
            patch.object(t, "get_backups_index", side_effect=lambda: list(self.index_entries)),
            patch.object(server, "get_live_bot_guilds", return_value={TEST_GUILD_ID}),
            patch.object(rbac.httpx, "get", side_effect=fake_httpx_get),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.env_patcher.stop()
        SceneManager.clear_cache()
        close_all_engines()

    def test_csrf_middleware_enforces_origin_x_requested_with_and_csrf_token_with_audit(self):
        admin_cookies = _cookie_for(UID_ADMIN, guilds=[{"id": TEST_GUILD_ID, "permissions": 8}], csrf="good-csrf")

        # 1. Missing X-Requested-With -> 403 + csrf.denied audit
        r_no_hdr = self.raw_client.put(
            f"/api/backups/{TEST_BACKUP_ID}/config",
            json={"timezone": "UTC"},
            cookies=admin_cookies,
            headers={"X-CSRF-Token": "good-csrf"},
        )
        self.assertEqual(r_no_hdr.status_code, 403)

        # 2. Untrusted Origin -> 403
        r_bad_origin = self.ui_client.put(
            f"/api/backups/{TEST_BACKUP_ID}/config",
            json={"timezone": "UTC"},
            cookies=admin_cookies,
            headers={"Origin": "https://evil.attacker.example", "X-CSRF-Token": "good-csrf"},
        )
        self.assertEqual(r_bad_origin.status_code, 403)

        # 3. Missing / wrong X-CSRF-Token on cookie-authenticated mutation -> 403
        r_no_csrf = self.ui_client.put(
            f"/api/backups/{TEST_BACKUP_ID}/config",
            json={"timezone": "UTC"},
            cookies=admin_cookies,
        )
        self.assertEqual(r_no_csrf.status_code, 403)

        r_bad_csrf = self.ui_client.put(
            f"/api/backups/{TEST_BACKUP_ID}/config",
            json={"timezone": "UTC"},
            cookies=admin_cookies,
            headers={"X-CSRF-Token": "wrong-csrf"},
        )
        self.assertEqual(r_bad_csrf.status_code, 403)

        # Verify csrf.denied was audited in global_audit.sqlite
        with global_audit_db_session(data_root=self.data_root.as_posix()) as session:
            denied_rows = session.query(AuditLog).filter_by(action="csrf.denied", status="denied").all()
            self.assertGreaterEqual(len(denied_rows), 4)

        # 4. Valid Origin + X-Requested-With + X-CSRF-Token -> 200
        r_ok = self.ui_client.put(
            f"/api/backups/{TEST_BACKUP_ID}/config",
            json={"timezone": "UTC"},
            cookies=admin_cookies,
            headers={"Origin": "http://localhost:5173", "X-CSRF-Token": "good-csrf"},
        )
        self.assertEqual(r_ok.status_code, 200)

    def test_production_cors_excludes_localhost_and_wildcards(self):
        with patch.dict(
            os.environ,
            {
                "SOCRATES_ENV": "production",
                "CORS_ORIGINS": "*,http://insecure.example,https://custom.example.com",
            },
            clear=False,
        ):
            cfg = server.build_cors_config()
            self.assertIsNone(cfg["allow_origin_regex"])
            self.assertNotIn("*", cfg["allow_origins"])
            self.assertNotIn("http://localhost:5173", cfg["allow_origins"])
            self.assertNotIn("http://insecure.example", cfg["allow_origins"])
            self.assertIn("https://socrates-backend-509220.web.app", cfg["allow_origins"])
            self.assertIn("https://custom.example.com", cfg["allow_origins"])
            self.assertEqual(cfg["allow_headers"], ["Content-Type", "X-CSRF-Token", "X-Requested-With"])
            self.assertEqual(cfg["allow_methods"], ["GET", "POST", "PUT", "DELETE", "OPTIONS"])
            self.assertFalse(server.is_origin_allowed("http://localhost:5173"))
            self.assertTrue(server.is_origin_allowed("https://socrates-backend-509220.web.app"))

    def test_strict_config_schemas_reject_dangerous_and_unknown_fields_with_422(self):
        inst_cookies = _cookie_for(INSTANCE_ADMIN_DISCORD_ID, guilds=[], csrf="inst-csrf")
        admin_cookies = _cookie_for(UID_ADMIN, guilds=[{"id": TEST_GUILD_ID, "permissions": 8}], csrf="adm-csrf")

        malicious_payloads = [
            {"script": "evil.py", "args": ["-c", "import os"]},
            {"command": "whoami", "shell": True},
            {"steps": {"download": {"enabled": True, "script": "calc.exe"}}},
            {"steps": {"download": {"channel_ids": ["123;rm -rf /"]}}},
            {"steps": {"download": {"channel_ids": ["1"] * 101}}},
            {"admin": {"path": "../../outside"}},
            {"discord_token": "steal-me", "jwt_secret": "x" * 40},
            {"unknown_key": "rejected"},
        ]

        for payload in malicious_payloads:
            with self.subTest(payload=payload):
                r_cfg = self.ui_client.put(
                    f"/api/backups/{TEST_BACKUP_ID}/config",
                    json=payload,
                    cookies=admin_cookies,
                    headers={"X-CSRF-Token": "adm-csrf"},
                )
                self.assertEqual(r_cfg.status_code, 422)

                r_run = self.ui_client.post(
                    f"/api/backups/{TEST_BACKUP_ID}/run",
                    json=payload,
                    cookies=admin_cookies,
                    headers={"X-CSRF-Token": "adm-csrf"},
                )
                self.assertEqual(r_run.status_code, 422)

                r_global = self.ui_client.put(
                    "/api/config/global",
                    json=payload,
                    cookies=inst_cookies,
                    headers={"X-CSRF-Token": "inst-csrf"},
                )
                self.assertEqual(r_global.status_code, 422)

                r_create = self.ui_client.post(
                    "/api/backups",
                    json=payload,
                    cookies=inst_cookies,
                    headers={"X-CSRF-Token": "inst-csrf"},
                )
                self.assertEqual(r_create.status_code, 422)

        # Valid step & admin config accepted
        r_valid = self.ui_client.put(
            f"/api/backups/{TEST_BACKUP_ID}/config",
            json={
                "server_id": TEST_GUILD_ID,
                "admin": {"serverId": TEST_GUILD_ID, "path": "Backups/Phase4Backup"},
                "steps": {"download": {"enabled": True, "channel_ids": ["123456789012345678"]}},
            },
            cookies=admin_cookies,
            headers={"X-CSRF-Token": "adm-csrf"},
        )
        self.assertEqual(r_valid.status_code, 200)

    def test_backup_path_traversal_and_server_id_validation(self):
        admin_cookies = _cookie_for(UID_ADMIN, guilds=[{"id": TEST_GUILD_ID, "permissions": 8}], csrf="adm-csrf")

        # Index entry with ../../outside_dir rejected with 400
        self.assertEqual(
            self.ui_client.get("/api/backups/99887766/config", cookies=admin_cookies).status_code,
            400,
        )
        self.assertEqual(
            self.ui_client.get("/api/backups/99887766/logs", cookies=admin_cookies).status_code,
            400,
        )
        # Traversal characters in backup_id rejected
        self.assertEqual(
            self.ui_client.get("/api/backups/bad..id/config", cookies=admin_cookies).status_code,
            400,
        )
        # Unauthorized server categories returns 403 and records rbac.denied
        r_cat_denied = self.ui_client.get(
            "/api/servers/999888777666555444/categories",
            cookies=admin_cookies,
        )
        self.assertEqual(r_cat_denied.status_code, 403)
        # Invalid server_id (as InstanceAdmin) returns 400
        inst_cookies = _cookie_for(INSTANCE_ADMIN_DISCORD_ID, guilds=[], csrf="inst-csrf")
        self.assertEqual(
            self.ui_client.get("/api/servers/not-a-snowflake/categories", cookies=inst_cookies).status_code,
            400,
        )

    def test_pagination_bounds_and_sql_like_escaping(self):
        admin_cookies = _cookie_for(UID_ADMIN, guilds=[{"id": TEST_GUILD_ID, "permissions": 8}], csrf="adm-csrf")
        inst_cookies = _cookie_for(INSTANCE_ADMIN_DISCORD_ID, guilds=[], csrf="inst-csrf")

        for path in [
            f"/api/backups/{TEST_BACKUP_ID}/scenes?per_page=9999",
            f"/api/backups/{TEST_BACKUP_ID}/scenes?page=0",
            f"/api/backups/{TEST_BACKUP_ID}/scenes?search={'a' * 501}",
            f"/api/backups/{TEST_BACKUP_ID}/sessions?per_page=201",
            f"/api/backups/{TEST_BACKUP_ID}/events?per_page=500",
            f"/api/backups/{TEST_BACKUP_ID}/scene-issues?per_page=250",
            f"/api/backups/{TEST_BACKUP_ID}/flagged-messages?per_page=300",
            f"/api/backups/{TEST_BACKUP_ID}/message-overrides?per_page=999",
            f"/api/backups/{TEST_BACKUP_ID}/logs?lines=5000",
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.ui_client.get(path, cookies=admin_cookies).status_code, 422)

        self.assertEqual(
            self.ui_client.get("/api/logs/global?lines=9999", cookies=inst_cookies).status_code,
            422,
        )

        # Wildcards '%' and '_' must match literally, not all rows
        self.assertEqual(escape_like(r"100%_test\x"), r"100\%\_test\\x")

        r_pct_scene = self.ui_client.get(
            f"/api/backups/{TEST_BACKUP_ID}/scenes",
            params={"search": "%"},
            cookies=admin_cookies,
        )
        self.assertEqual(r_pct_scene.status_code, 200)
        self.assertEqual(r_pct_scene.json()["total_items"], 1)
        self.assertEqual(r_pct_scene.json()["scenes"][0]["custom_name"], "100% Real Scene")

        r_pct_event = self.ui_client.get(
            f"/api/backups/{TEST_BACKUP_ID}/events",
            params={"search": "Ball 50%"},
            cookies=admin_cookies,
        )
        self.assertEqual(r_pct_event.status_code, 200)
        self.assertEqual(r_pct_event.json()["total_items"], 1)

        # Service layer also clamps oversized per_page <= 200 directly
        with db_session(backup_id=TEST_BACKUP_ID, backup_path=self.backup_dir.as_posix()) as session:
            ev_res = event_service.query_events(session, TEST_BACKUP_ID, page=1, per_page=5000)
            self.assertEqual(ev_res["per_page"], 200)
        sc_res = scene_service.query_scenes(TEST_BACKUP_ID, self.backup_dir.as_posix(), page=1, per_page=5000)
        self.assertEqual(sc_res["per_page"], 200)
        iss_res = curation_service.get_scene_issues(TEST_BACKUP_ID, self.backup_dir.as_posix(), page=1, per_page=5000)
        self.assertEqual(iss_res["per_page"], 200)

    def test_sse_stream_duration_and_concurrency_caps(self):
        admin_cookies = _cookie_for(UID_ADMIN, guilds=[{"id": TEST_GUILD_ID, "permissions": 8}], csrf="adm-csrf")

        # Stream duration cap terminates stream cleanly
        with patch.object(server, "SSE_MAX_DURATION_SECONDS", 0.05):
            with self.ui_client.stream(
                "GET", f"/api/backups/{TEST_BACKUP_ID}/logs/stream", cookies=admin_cookies
            ) as resp:
                self.assertEqual(resp.status_code, 200)
                body = "".join(resp.iter_text())
                self.assertIn("[Stream duration limit reached]", body)

        # Stream count cleaned up in finally
        with server._SSE_ACTIVE_STREAMS_LOCK:
            self.assertEqual(server._SSE_ACTIVE_STREAMS.get(UID_ADMIN, 0), 0)
            server._SSE_ACTIVE_STREAMS[UID_ADMIN] = server.SSE_MAX_CONCURRENT_STREAMS_PER_USER

        try:
            r_429 = self.ui_client.get(
                f"/api/backups/{TEST_BACKUP_ID}/logs/stream", cookies=admin_cookies
            )
            self.assertEqual(r_429.status_code, 429)
        finally:
            with server._SSE_ACTIVE_STREAMS_LOCK:
                server._SSE_ACTIVE_STREAMS.clear()

    def test_500_errors_sanitize_paths_sql_and_tracebacks(self):
        admin_cookies = _cookie_for(UID_ADMIN, guilds=[{"id": TEST_GUILD_ID, "permissions": 8}], csrf="adm-csrf")

        with patch.object(
            server.curation_service,
            "get_curation_summary",
            side_effect=RuntimeError(r"SELECT * FROM C:\secret\backup.sqlite failed"),
        ):
            r_err = self.ui_client.get(
                f"/api/backups/{TEST_BACKUP_ID}/curation/summary", cookies=admin_cookies
            )
            self.assertEqual(r_err.status_code, 500)
            detail = r_err.json()["detail"]
            self.assertIn("Internal server error (ref:", detail)
            self.assertNotIn("SELECT", detail)
            self.assertNotIn("backup.sqlite", detail)
            self.assertNotIn("C:\\", detail)

        with patch.object(
            scene_service,
            "query_scenes",
            side_effect=OperationalError("SELECT * FROM scenes", {}, Exception("/var/data/secret.sqlite")),
        ):
            r_db_err = self.ui_client.get(
                f"/api/backups/{TEST_BACKUP_ID}/scenes", cookies=admin_cookies
            )
            self.assertEqual(r_db_err.status_code, 500)
            body = r_db_err.json()
            self.assertEqual(body["error"], "database_error")
            self.assertIn("Internal database error (ref:", body["detail"])
            self.assertNotIn("SELECT", body["detail"])
            self.assertNotIn("secret.sqlite", body["detail"])


if __name__ == "__main__":
    unittest.main()

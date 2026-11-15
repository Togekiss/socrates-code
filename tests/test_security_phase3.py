import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
for p in (SRC_DIR.as_posix(), PROJECT_ROOT.as_posix()):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("SOCRATES_ENV", "development")
os.environ.setdefault("JWT_SECRET", "a_very_strong_test_jwt_secret_key_with_more_than_32_bytes")

import rbac  # noqa: E402
import server  # noqa: E402
import utils.tricks as t  # noqa: E402
from db import audit_service  # noqa: E402
from db.audit_models import AuditLog, ensure_utc_datetime, format_utc_iso  # noqa: E402
from db.models import (  # noqa: E402
    BackupModel,
    CURRENT_SCHEMA_VERSION,
    CharacterModel,
    CharacterNameModel,
    ExportModel,
    WriterAliasModel,
    WriterModel,
)
from db.session import (  # noqa: E402
    audit_db_session,
    close_all_engines,
    db_session,
    global_audit_db_session,
    init_db,
    resolve_backup_audit_db_path,
    resolve_global_audit_db_path,
)
from models import SceneManager  # noqa: E402
from tests.test_security_phase1 import (  # noqa: E402
    INSTANCE_ADMIN_DISCORD_ID,
    STRONG_TEST_SECRET,
    _make_jwt,
    _make_test_client,
)


ROLE_ADMIN_ID = "100000000000000001"
ROLE_CURATOR_ID = "100000000000000002"
ROLE_PARTICIPANT_ID = "100000000000000003"

UID_ADMIN = "200000000000000001"
UID_CURATOR = "200000000000000002"
UID_PARTICIPANT = "200000000000000003"
UID_VIEWER = "200000000000000005"
UID_STRANGER = "200000000000000099"

TEST_BACKUP_ID = "9900112255"
TEST_GUILD_ID = "880011223344556699"
OTHER_GUILD_ID = "880011223344556600"


def _session_cookie(
    sub: str,
    guilds=None,
    auth_method: str = "discord",
    dev_role: str | None = None,
    jti: str = "phase3-jti-1",
    csrf: str = "phase3-csrf-1",
) -> dict:
    payload = {
        "sub": sub,
        "username": f"user_{sub}",
        "auth_method": auth_method,
        "authorized_guilds": guilds if guilds is not None else [],
        "jti": jti,
        "csrf": csrf,
        "iss": "socrates",
        "typ": "session",
    }
    if dev_role is not None:
        payload["dev_role"] = dev_role
    return {"__session": _make_jwt(payload, STRONG_TEST_SECRET)}


class TestAuditDatabaseIsolationAndFormatting(unittest.TestCase):
    """Verifies dedicated audit.sqlite / global_audit.sqlite isolation, UTC format, and 16 KB payload caps."""

    def tearDown(self):
        close_all_engines()
        audit_service.clear_prune_throttle()

    def test_audit_dbs_isolated_from_backup_sqlite_v5(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            backup_dir = data_root / "Backups" / "TestBackup"
            backup_dir.mkdir(parents=True, exist_ok=True)

            # Create normal backup.sqlite at schema v5
            init_db(engine_or_backup_id=TEST_BACKUP_ID, backup_path=backup_dir.as_posix())
            with db_session(backup_id=TEST_BACKUP_ID, backup_path=backup_dir.as_posix()) as session:
                session.add(
                    BackupModel(
                        backup_id=TEST_BACKUP_ID,
                        backup_name="TestBackup",
                        server_id=TEST_GUILD_ID,
                        server_name="Test Guild",
                    )
                )

            # Write to per-backup audit.sqlite and global_audit.sqlite
            audit_service.record_audit_event(
                action="writer.update",
                target_type="writer",
                target_id="1",
                backup_id=TEST_BACKUP_ID,
                backup_dir=backup_dir.as_posix(),
                data_root=data_root.as_posix(),
                before={"display_name": "Old"},
                after={"display_name": "New"},
            )
            audit_service.record_audit_event(
                action="auth.login",
                target_type="auth",
                target_id=UID_ADMIN,
                data_root=data_root.as_posix(),
                write_global=True,
            )

            backup_sqlite_path = backup_dir / "backup.sqlite"
            audit_sqlite_path = Path(resolve_backup_audit_db_path(backup_dir.as_posix()))
            global_audit_path = Path(resolve_global_audit_db_path(data_root.as_posix()))

            self.assertTrue(backup_sqlite_path.exists())
            self.assertTrue(audit_sqlite_path.exists())
            self.assertTrue(global_audit_path.exists())
            self.assertEqual(audit_sqlite_path.name, "audit.sqlite")
            self.assertEqual(global_audit_path, data_root / "out" / "global_audit.sqlite")

            # Verify backup.sqlite has schema v5 and NO audit_logs table
            conn = sqlite3.connect(backup_sqlite_path.as_posix())
            try:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                self.assertNotIn("audit_logs", tables)
                version_row = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
                self.assertEqual(version_row[0], CURRENT_SCHEMA_VERSION)
                self.assertEqual(CURRENT_SCHEMA_VERSION, 5)
            finally:
                conn.close()

            close_all_engines()

    def test_unittest_default_global_audit_is_isolated_from_workspace_db(self):
        real_db_path = (PROJECT_ROOT / "out" / "global_audit.sqlite").resolve().as_posix().lower()
        resolved_default = Path(resolve_global_audit_db_path()).resolve().as_posix().lower()
        resolved_server_root = Path(resolve_global_audit_db_path(server.get_data_root())).resolve().as_posix().lower()
        self.assertNotEqual(resolved_default, real_db_path)
        self.assertEqual(resolved_default, resolved_server_root)

        before_mtime = os.path.getmtime(real_db_path) if os.path.exists(real_db_path) else None
        server._audit(
            action="test.isolation_check",
            target_type="admin",
            target_id="isolation",
            actor={"sub": UID_ADMIN, "username": "IsolationTester", "auth_method": "discord"},
            actor_role="instance_admin",
            write_global=True,
        )
        after_mtime = os.path.getmtime(real_db_path) if os.path.exists(real_db_path) else None
        self.assertEqual(before_mtime, after_mtime)
        with global_audit_db_session() as session:
            rows = session.query(AuditLog).filter(AuditLog.action == "test.isolation_check").all()
            self.assertGreaterEqual(len(rows), 1)
        close_all_engines()

    def test_utc_formatting_with_z_suffix(self):
        naive = datetime(2026, 11, 14, 15, 30, 5)
        aware = ensure_utc_datetime(naive)
        self.assertEqual(aware.tzinfo, timezone.utc)
        self.assertEqual(format_utc_iso(naive), "2026-11-14T15:30:05Z")

    def test_serialize_capped_json_list_and_16kb_truncation(self):
        # 1. List truncation > 50 items
        long_list_payload = {"items": list(range(120))}
        encoded_list = audit_service.serialize_capped_json(long_list_payload)
        self.assertIsNotNone(encoded_list)
        parsed_list = json.loads(encoded_list)
        self.assertTrue(parsed_list["items"]["_truncated"])
        self.assertEqual(parsed_list["items"]["count"], 120)
        self.assertEqual(len(parsed_list["items"]["sample"]), 50)

        # 2. Byte truncation > 16 KB (with multibyte characters)
        huge_payload = {"blob": "é" * 20000, "extra": "x" * 5000}
        encoded_huge = audit_service.serialize_capped_json(huge_payload)
        self.assertIsNotNone(encoded_huge)
        self.assertLessEqual(len(encoded_huge.encode("utf-8")), 16384)
        parsed_huge = json.loads(encoded_huge)
        self.assertTrue(parsed_huge.get("_truncated"))


class TestAuditRetentionPruning(unittest.TestCase):
    """Verifies 90-day denied, 365-day mutation retention, 100k row cap, and 1-hour throttling."""

    def tearDown(self):
        close_all_engines()
        audit_service.clear_prune_throttle()

    def test_retention_pruning_90d_365d_and_row_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                backup_dir = Path(tmpdir) / "Backups" / "RetentionTest"
                backup_dir.mkdir(parents=True, exist_ok=True)
                now = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)

                def _row(action: str, status: str, created_at: datetime) -> AuditLog:
                    return AuditLog(
                        actor_user_id="100",
                        actor_username="tester",
                        actor_role="curator",
                        auth_method="dev",
                        backup_id=TEST_BACKUP_ID,
                        action=action,
                        target_type="writer",
                        status=status,
                        created_at=created_at,
                    )

                with audit_db_session(backup_dir.as_posix()) as session:
                    session.add_all([
                        # Denied at 91 days -> PRUNE
                        _row("rbac.denied", "denied", now - timedelta(days=91)),
                        # Denied at 89 days -> KEEP
                        _row("rbac.denied", "denied", now - timedelta(days=89)),
                        # Mutation at 366 days -> PRUNE
                        _row("writer.update", "success", now - timedelta(days=366)),
                        # Mutation at 364 days -> KEEP
                        _row("writer.update", "success", now - timedelta(days=364)),
                        # Recent mutations -> KEEP
                        _row("character.update", "success", now - timedelta(days=2)),
                        _row("scene.update", "success", now - timedelta(days=1)),
                    ])

                with audit_db_session(backup_dir.as_posix()) as session:
                    stats = audit_service.prune_audit_logs(
                        session,
                        db_key=backup_dir.as_posix(),
                        now_utc=now,
                        max_rows=100_000,
                        force_prune=True,
                    )
                    self.assertFalse(stats["skipped"])
                    self.assertEqual(stats["deleted_denied"], 1)
                    self.assertEqual(stats["deleted_expired"], 1)
                    self.assertEqual(stats["deleted_overflow"], 0)
                    remaining = session.query(AuditLog).count()
                    self.assertEqual(remaining, 4)

                    # Throttle check: without force_prune within 3600s, does not re-prune even with small max_rows
                    throttled = audit_service.prune_audit_logs(
                        session,
                        db_key=backup_dir.as_posix(),
                        now_utc=now + timedelta(minutes=10),
                        max_rows=2,
                        force_prune=False,
                    )
                    self.assertTrue(throttled["skipped"])
                    self.assertEqual(throttled["deleted_overflow"], 0)

                    # With force_prune=True and max_rows=2, keeps only the 2 newest rows
                    capped = audit_service.prune_audit_logs(
                        session,
                        db_key=backup_dir.as_posix(),
                        now_utc=now + timedelta(minutes=10),
                        max_rows=2,
                        force_prune=True,
                    )
                    self.assertEqual(capped["deleted_overflow"], 2)
                    kept_actions = [r.action for r in session.query(AuditLog).order_by(AuditLog.created_at.asc()).all()]
                    self.assertEqual(kept_actions, ["character.update", "scene.update"])
            finally:
                close_all_engines()

    def test_request_ip_is_hmac_hashed_and_never_stored_raw(self):
        self.assertIsNone(audit_service.hash_ip_address(None))
        self.assertIsNone(audit_service.hash_ip_address("   "))

        h1 = audit_service.hash_ip_address("203.0.113.42")
        h2 = audit_service.hash_ip_address(" 203.0.113.42 ")
        h3 = audit_service.hash_ip_address("203.0.113.43")
        self.assertIsNotNone(h1)
        self.assertTrue(h1.startswith("ip:") and len(h1) == 19)
        self.assertEqual(h1, h2)
        self.assertNotEqual(h1, h3)
        self.assertNotIn("203.0.113", h1)
        # Idempotent if already hashed
        self.assertEqual(audit_service.hash_ip_address(h1), h1)
        # IPv6 normalization
        self.assertEqual(
            audit_service.hash_ip_address("2001:0db8:0000:0000:0000:0000:0000:0001"),
            audit_service.hash_ip_address("2001:db8::1"),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                backup_dir = Path(tmpdir) / "Backups" / "IpHashTest"
                backup_dir.mkdir(parents=True, exist_ok=True)
                audit_service.record_audit_event(
                    action="auth.login",
                    target_type="auth",
                    actor={"id": "100", "username": "tester"},
                    actor_role="viewer",
                    backup_dir=backup_dir.as_posix(),
                    write_global=False,
                    request_ip="203.0.113.42",
                )
                with audit_db_session(backup_dir.as_posix()) as session:
                    row = session.query(AuditLog).first()
                    self.assertIsNotNone(row)
                    self.assertEqual(row.request_ip, h1)
                    self.assertNotEqual(row.request_ip, "203.0.113.42")
            finally:
                close_all_engines()


class TestAuditEndpointsAndRecording(unittest.TestCase):
    """End-to-end HTTP tests for audit recording (auth, curation, admin, 403 denials) and query endpoints."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self._tmpdir.name)
        self.backups_dir = self.data_root / "Backups"
        self.backup_dir = self.backups_dir / "AuditTestBackup"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        (self.data_root / "out").mkdir(parents=True, exist_ok=True)

        self.index_entries = [
            {
                "backup_id": TEST_BACKUP_ID,
                "backup_name": "AuditTestBackup",
                "server_id": TEST_GUILD_ID,
                "server_name": "Audit Test Guild",
                "path": "Backups/AuditTestBackup",
            }
        ]
        (self.backups_dir / "backups_index.json").write_text(
            json.dumps(self.index_entries), encoding="utf-8"
        )

        # Seed v5 backup.sqlite with 1 writer and 1 character
        init_db(engine_or_backup_id=TEST_BACKUP_ID, backup_path=self.backup_dir.as_posix())
        with db_session(backup_id=TEST_BACKUP_ID, backup_path=self.backup_dir.as_posix()) as session:
            session.add(
                BackupModel(
                    backup_id=TEST_BACKUP_ID,
                    backup_name="AuditTestBackup",
                    server_id=TEST_GUILD_ID,
                    server_name="Audit Test Guild",
                )
            )
            session.add(
                ExportModel(
                    backup_id=TEST_BACKUP_ID,
                    scope="base",
                )
            )
            writer = WriterModel(
                pk=1,
                backup_id=TEST_BACKUP_ID,
                display_name="AliceWriter",
                discord_user_id=UID_PARTICIPANT,
            )
            session.add(writer)
            session.flush()
            session.add(WriterAliasModel(writer_pk=writer.pk, alias="Alice"))
            char = CharacterModel(
                char_id=101,
                backup_id=TEST_BACKUP_ID,
                writer_pk=writer.pk,
                version_type="canon",
            )
            session.add(char)
            session.flush()
            session.add(CharacterNameModel(character_pk=char.pk, name="Lyra", position=0))

        rbac.save_backup_rbac_config(
            self.backup_dir.as_posix(),
            {
                "adminRoleIds": [ROLE_ADMIN_ID],
                "curatorRoleIds": [ROLE_CURATOR_ID],
                "participantRoleIds": [ROLE_PARTICIPANT_ID],
                "restrictedUserIds": [],
                "blockedUserIds": [],
            },
            guild_id=TEST_GUILD_ID,
        )

        self.member_roles_map = {
            UID_ADMIN: {ROLE_ADMIN_ID},
            UID_CURATOR: {ROLE_CURATOR_ID},
            UID_PARTICIPANT: {ROLE_PARTICIPANT_ID},
            UID_VIEWER: set(),
        }

        server.clear_bot_guilds_cache()
        server.clear_revoked_jtis()
        rbac.clear_rbac_caches()
        audit_service.clear_prune_throttle()

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

        self.patches = [
            patch.object(server, "get_data_root", return_value=self.data_root.as_posix()),
            patch.object(t, "get_backups_index", side_effect=lambda: list(self.index_entries)),
            patch.object(server, "_get_effective_bot_guilds", return_value={TEST_GUILD_ID}),
            patch.object(
                rbac,
                "fetch_guild_member_roles",
                side_effect=lambda gid, uid, tok: self.member_roles_map.get(str(uid), set()),
            ),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.env_patcher.stop()
        SceneManager.clear_cache()
        close_all_engines()
        server.clear_bot_guilds_cache()
        server.clear_revoked_jtis()
        rbac.clear_rbac_caches()
        audit_service.clear_prune_throttle()
        self._tmpdir.cleanup()

    def test_auth_events_and_global_audit_query_rbac(self):
        from fastapi import FastAPI

        with patch.dict(
            os.environ,
            {
                "SOCRATES_ENABLE_DEV_LOGIN": "true",
                "SOCRATES_DEV_ROLE": "server_admin",
                "SOCRATES_DEV_ID": UID_ADMIN,
            },
        ):
            app_dev = FastAPI()
            self.assertTrue(server.register_dev_login_route(app_dev))
            app_dev.add_api_route("/api/auth/logout", server.logout, methods=["POST"])
            client = _make_test_client(app_dev)

            # 1. Proxied dev-login denied -> auth.denied in global_audit.sqlite
            denied_resp = client.post("/api/auth/dev-login", headers={"X-Forwarded-For": "203.0.113.5"})
            self.assertEqual(denied_resp.status_code, 403)

            # 2. Local dev-login success -> auth.dev_login
            login_resp = client.post("/api/auth/dev-login")
            self.assertEqual(login_resp.status_code, 200)
            csrf = login_resp.json()["csrf_token"]

            # 3. Logout -> auth.logout
            logout_resp = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
            self.assertEqual(logout_resp.status_code, 200)

        # Verify Non-InstanceAdmin gets 403 on GET /api/admin/audit-logs (and records rbac.denied)
        client_main = _make_test_client(server.app)
        client_main.cookies.update(_session_cookie(UID_ADMIN, guilds=[{"id": TEST_GUILD_ID}], jti="j-admin"))
        r_forbidden = client_main.get("/api/admin/audit-logs")
        self.assertEqual(r_forbidden.status_code, 403)

        # Verify InstanceAdmin gets 200 and sees auth.denied, auth.dev_login, auth.logout, rbac.denied
        client_main.cookies.clear()
        client_main.cookies.update(_session_cookie(INSTANCE_ADMIN_DISCORD_ID, guilds=[], jti="j-inst"))
        r_admin = client_main.get("/api/admin/audit-logs?per_page=50")
        self.assertEqual(r_admin.status_code, 200)
        body = r_admin.json()
        actions = [item["action"] for item in body["items"]]
        self.assertIn("auth.denied", actions)
        self.assertIn("auth.dev_login", actions)
        self.assertIn("auth.logout", actions)
        self.assertIn("rbac.denied", actions)
        for item in body["items"]:
            self.assertTrue(str(item["created_at"]).endswith("Z"))

    def test_curation_admin_and_denial_auditing_plus_backup_query_endpoint(self):
        client = _make_test_client(server.app)

        # 1. Curator updates writer -> writer.update with before/after in audit.sqlite
        client.cookies.update(_session_cookie(UID_CURATOR, guilds=[{"id": TEST_GUILD_ID}], jti="j-cur", csrf="c-cur"))
        res_writer = client.put(
            f"/api/backups/{TEST_BACKUP_ID}/writers/1",
            json={"display_name": "AliceRenamed", "aliases": ["Alice", "Ali"]},
            headers={"X-CSRF-Token": "c-cur"},
        )
        self.assertEqual(res_writer.status_code, 200)

        # 2. Curator updates character -> character.update with before/after in audit.sqlite
        res_char = client.put(
            f"/api/backups/{TEST_BACKUP_ID}/characters/101",
            json={"names": ["LyraRenamed"], "tags": ["canon"]},
            headers={"X-CSRF-Token": "c-cur"},
        )
        self.assertEqual(res_char.status_code, 200)

        # 3. ServerAdmin updates RBAC -> rbac.update in audit.sqlite
        client.cookies.clear()
        client.cookies.update(_session_cookie(UID_ADMIN, guilds=[{"id": TEST_GUILD_ID}], jti="j-adm", csrf="c-adm"))
        res_rbac = client.put(
            f"/api/backups/{TEST_BACKUP_ID}/rbac",
            json={
                "adminRoleIds": [ROLE_ADMIN_ID],
                "curatorRoleIds": [ROLE_CURATOR_ID],
                "participantRoleIds": [ROLE_PARTICIPANT_ID],
                "restrictedUserIds": [],
                "blockedUserIds": [],
            },
            headers={"X-CSRF-Token": "c-adm"},
        )
        self.assertEqual(res_rbac.status_code, 200)

        # 4. Viewer fails RBAC update -> 403 and rbac.denied in BOTH audit.sqlite & global_audit.sqlite
        client.cookies.clear()
        client.cookies.update(_session_cookie(UID_VIEWER, guilds=[{"id": TEST_GUILD_ID}], jti="j-view", csrf="c-view"))
        res_denied = client.put(
            f"/api/backups/{TEST_BACKUP_ID}/rbac",
            json={"adminRoleIds": []},
            headers={"X-CSRF-Token": "c-view"},
        )
        self.assertEqual(res_denied.status_code, 403)

        # 5. Cross-guild stranger BOLA -> 403 in global_audit.sqlite ONLY (not in victim's audit.sqlite)
        client.cookies.clear()
        client.cookies.update(_session_cookie(UID_STRANGER, guilds=[{"id": OTHER_GUILD_ID}], jti="j-str", csrf="c-str"))
        res_bola = client.get(f"/api/backups/{TEST_BACKUP_ID}/characters")
        self.assertEqual(res_bola.status_code, 403)

        # 6. Curator/Participant/Viewer get 403 on GET /api/backups/{id}/audit-logs
        for role_uid, jti in ((UID_CURATOR, "jc"), (UID_PARTICIPANT, "jp"), (UID_VIEWER, "jv")):
            client.cookies.clear()
            client.cookies.update(_session_cookie(role_uid, guilds=[{"id": TEST_GUILD_ID}], jti=jti))
            r_no = client.get(f"/api/backups/{TEST_BACKUP_ID}/audit-logs")
            self.assertEqual(r_no.status_code, 403)

        # 7. ServerAdmin reads backup audit-logs (pagination + filters)
        client.cookies.clear()
        client.cookies.update(_session_cookie(UID_ADMIN, guilds=[{"id": TEST_GUILD_ID}], jti="j-adm2"))
        r_all = client.get(f"/api/backups/{TEST_BACKUP_ID}/audit-logs?per_page=2&page=1")
        self.assertEqual(r_all.status_code, 200)
        data = r_all.json()
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["per_page"], 2)
        self.assertGreaterEqual(data["total"], 4)
        self.assertEqual(len(data["items"]), 2)
        self.assertGreaterEqual(data["total_pages"], 2)

        # Filter action=writer.update -> verify before/after snapshots
        r_writer = client.get(f"/api/backups/{TEST_BACKUP_ID}/audit-logs?action=writer.update")
        self.assertEqual(r_writer.status_code, 200)
        w_items = r_writer.json()["items"]
        self.assertEqual(len(w_items), 1)
        self.assertEqual(w_items[0]["before"]["display_name"], "AliceWriter")
        self.assertEqual(w_items[0]["after"]["display_name"], "AliceRenamed")
        self.assertTrue(w_items[0]["created_at"].endswith("Z"))

        # Verify stranger BOLA was NOT written into backup's audit.sqlite
        r_stranger_in_backup = client.get(
            f"/api/backups/{TEST_BACKUP_ID}/audit-logs?actor_user_id={UID_STRANGER}"
        )
        self.assertEqual(r_stranger_in_backup.status_code, 200)
        self.assertEqual(r_stranger_in_backup.json()["total"], 0)

        # Invalid from_ts returns 400
        r_bad_ts = client.get(f"/api/backups/{TEST_BACKUP_ID}/audit-logs?from_ts=not-a-timestamp")
        self.assertEqual(r_bad_ts.status_code, 400)

        # 8. InstanceAdmin executes POST /api/admin/tests/run (mocked subprocess) -> admin.tests_run in global_audit.sqlite
        mock_proc = MagicMock(returncode=0, stdout="Ran 1 test\nOK", stderr="")
        with patch.object(server.subprocess, "run", return_value=mock_proc):
            client.cookies.clear()
            client.cookies.update(_session_cookie(INSTANCE_ADMIN_DISCORD_ID, guilds=[], jti="j-ia", csrf="c-ia"))
            r_run = client.post("/api/admin/tests/run", headers={"X-CSRF-Token": "c-ia"})
            self.assertEqual(r_run.status_code, 200)

        # Verify global_audit.sqlite recorded admin.tests_run and stranger's rbac.denied
        r_global_tests = client.get("/api/admin/audit-logs?action=admin.tests_run")
        self.assertEqual(r_global_tests.status_code, 200)
        self.assertEqual(r_global_tests.json()["total"], 1)

        r_global_bola = client.get(f"/api/admin/audit-logs?actor_user_id={UID_STRANGER}&status=denied")
        self.assertEqual(r_global_bola.status_code, 200)
        self.assertGreaterEqual(r_global_bola.json()["total"], 1)


if __name__ == "__main__":
    unittest.main()

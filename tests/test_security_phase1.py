import asyncio
import json
import os
import selectors
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _WakeSelector(selectors.BaseSelector):
    """Socket-free selector for running TestClient in restricted environments."""

    def __init__(self):
        self._cond = threading.Condition()
        self._woken = False
        self._map = {}

    def register(self, fileobj, events, data=None):
        return selectors.SelectorKey(fileobj, 0, events, data)

    def unregister(self, fileobj):
        return None

    def modify(self, fileobj, events, data=None):
        return None

    def select(self, timeout=None):
        with self._cond:
            if not self._woken:
                self._cond.wait(timeout=timeout)
            self._woken = False
        return []

    def close(self):
        with self._cond:
            self._woken = True
            self._cond.notify_all()

    def get_map(self):
        return self._map


class _TestEventLoop(asyncio.SelectorEventLoop):
    """SelectorEventLoop without TCP self-pipe sockets for in-memory ASGI testing."""

    def __init__(self):
        self._wake_sel = _WakeSelector()
        super().__init__(selector=self._wake_sel)

    def _make_self_pipe(self):
        pass

    def _close_self_pipe(self):
        pass

    def _write_to_self(self):
        with self._wake_sel._cond:
            self._wake_sel._woken = True
            self._wake_sel._cond.notify_all()


def _make_test_client(app_obj: FastAPI, *, include_csrf_headers: bool = True) -> TestClient:
    headers = {"X-Requested-With": "Socrates-UI"} if include_csrf_headers else None
    return TestClient(app_obj, headers=headers, backend_options={"loop_factory": _TestEventLoop})

# Add src to sys.path so server and utils can be imported directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if SRC_DIR.as_posix() not in sys.path:
    sys.path.insert(0, SRC_DIR.as_posix())
if PROJECT_ROOT.as_posix() not in sys.path:
    sys.path.insert(0, PROJECT_ROOT.as_posix())

from tests.test_env import has_local_live_backup_fixture, has_local_test_backup_fixture
import server  # noqa: E402


STRONG_TEST_SECRET = "a_very_strong_test_jwt_secret_key_with_more_than_32_bytes"
GUILD_ELYSIUM = "857848490683269161"
GUILD_OTHER = "442481942794076161"
BACKUP_ELYSIUM = "1791895360"
BACKUP_OTHER = "1789899843"
INSTANCE_ADMIN_DISCORD_ID = "999000111222333444"
REGULAR_USER_DISCORD_ID = "111222333444555666"


def _make_jwt(payload: dict, secret: str = STRONG_TEST_SECRET) -> str:
    data = dict(payload)
    if "iss" not in data:
        data["iss"] = "socrates"
    if "typ" not in data:
        data["typ"] = "session"
    if "csrf" not in data:
        data["csrf"] = "phase1-csrf"
    if "exp" not in data:
        data["exp"] = datetime.now(timezone.utc) + timedelta(hours=1)
    return jwt.encode(data, secret, algorithm="HS256")


class TestStartupAndJWTConfig(unittest.TestCase):
    """Tests production JWT fail-fast, ephemeral non-prod fallback, /api/health, and disabled OpenAPI docs."""

    def test_health_endpoint_is_unauthenticated(self):
        client = _make_test_client(server.app)
        resp = client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_production_rejects_missing_weak_and_placeholder_jwt_secrets(self):
        bad_secrets = [
            "",
            "short_secret_under_32_chars",
            "dev_secret",
            "dev-secret-change-me",
            "your_random_secure_jwt_secret_here",
        ]
        for secret_val in bad_secrets:
            with self.subTest(secret=secret_val):
                with patch.dict(
                    os.environ,
                    {"SOCRATES_ENV": "production", "JWT_SECRET": secret_val},
                    clear=False,
                ):
                    with self.assertRaises(RuntimeError):
                        server.validate_startup_security()

    def test_k_service_implies_production_mode(self):
        with patch.dict(
            os.environ,
            {
                "SOCRATES_ENV": "development",
                "K_SERVICE": "socrates-cloud-run",
                "JWT_SECRET": "dev-secret-change-me",
            },
            clear=False,
        ):
            self.assertTrue(server.is_production_env())
            self.assertFalse(server.is_dev_login_enabled())
            with self.assertRaises(RuntimeError):
                server.validate_startup_security()

    def test_non_production_generates_process_wide_ephemeral_secret_when_unset(self):
        with patch.dict(
            os.environ,
            {"SOCRATES_ENV": "development", "K_SERVICE": "", "JWT_SECRET": ""},
            clear=False,
        ):
            with patch.object(server.t, "global_log") as mock_log:
                server._EPHEMERAL_DEV_JWT_SECRET = None
                server._EPHEMERAL_DEV_JWT_WARNED = False
                secret1 = server.resolve_jwt_secret()
                secret2 = server.resolve_jwt_secret()
                self.assertEqual(secret1, secret2)
                self.assertGreaterEqual(len(secret1), 32)
                self.assertNotIn(secret1.lower(), server.KNOWN_WEAK_JWT_SECRETS)
                mock_log.assert_called_once()

    def test_production_import_fails_fast_and_valid_prod_disables_docs_and_dev_login(self):
        base_env = os.environ.copy()
        base_env["PYTHONPATH"] = f"{SRC_DIR.as_posix()}{os.pathsep}{PROJECT_ROOT.as_posix()}"

        # 1) Missing/weak JWT_SECRET in production must crash startup import
        bad_env = dict(base_env)
        bad_env["SOCRATES_ENV"] = "production"
        bad_env["JWT_SECRET"] = "dev_secret"
        proc_fail = subprocess.run(
            [sys.executable, "-c", "import server"],
            cwd=PROJECT_ROOT.as_posix(),
            env=bad_env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc_fail.returncode, 0)
        self.assertIn("RuntimeError", proc_fail.stderr)

        # 2) Valid strong secret in production disables /docs, /redoc, /openapi.json and /api/auth/dev-login
        prod_env = dict(base_env)
        prod_env["SOCRATES_ENV"] = "production"
        prod_env["JWT_SECRET"] = STRONG_TEST_SECRET
        prod_env["SOCRATES_ENABLE_DEV_LOGIN"] = "true"
        prod_env["SOCRATES_DEV_ROLE"] = "instance_admin"
        script = (
            "import json, server; "
            "from tests.test_security_phase1 import _make_test_client; "
            "c = _make_test_client(server.app); "
            "out = {"
            "'health': c.get('/api/health').status_code, "
            "'docs': c.get('/docs').status_code, "
            "'redoc': c.get('/redoc').status_code, "
            "'openapi': c.get('/openapi.json').status_code, "
            "'dev_post': c.post('/api/auth/dev-login').status_code, "
            "'dev_get': c.get('/api/auth/dev-login').status_code"
            "}; "
            "print(json.dumps(out))"
        )
        proc_ok = subprocess.run(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT.as_posix(),
            env=prod_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc_ok.returncode, 0, proc_ok.stderr)
        statuses = json.loads(proc_ok.stdout.strip().splitlines()[-1])
        self.assertEqual(statuses["health"], 200)
        self.assertEqual(statuses["docs"], 404)
        self.assertEqual(statuses["redoc"], 404)
        self.assertEqual(statuses["openapi"], 404)
        self.assertEqual(statuses["dev_post"], 404)
        self.assertEqual(statuses["dev_get"], 404)


class TestDevLoginQuarantine(unittest.TestCase):
    """Tests strict opt-in gating, GET removal, proxy/IP rejections, claims, and TTL of /api/auth/dev-login."""

    def test_get_dev_login_route_does_not_exist(self):
        client = _make_test_client(server.app)
        resp = client.get("/api/auth/dev-login")
        self.assertIn(resp.status_code, {404, 405})

    def test_register_dev_login_requires_all_four_conditions(self):
        cases = [
            {
                "SOCRATES_ENV": "staging",
                "K_SERVICE": "",
                "SOCRATES_ENABLE_DEV_LOGIN": "true",
                "SOCRATES_DEV_ROLE": "instance_admin",
            },
            {
                "SOCRATES_ENV": "development",
                "K_SERVICE": "svc",
                "SOCRATES_ENABLE_DEV_LOGIN": "true",
                "SOCRATES_DEV_ROLE": "instance_admin",
            },
            {
                "SOCRATES_ENV": "development",
                "K_SERVICE": "",
                "SOCRATES_ENABLE_DEV_LOGIN": "false",
                "SOCRATES_DEV_ROLE": "instance_admin",
            },
            {
                "SOCRATES_ENV": "development",
                "K_SERVICE": "",
                "SOCRATES_ENABLE_DEV_LOGIN": "true",
                "SOCRATES_DEV_ROLE": "",
            },
            {
                "SOCRATES_ENV": "development",
                "K_SERVICE": "",
                "SOCRATES_ENABLE_DEV_LOGIN": "true",
                "SOCRATES_DEV_ROLE": "superuser",
            },
        ]
        for env_vals in cases:
            with self.subTest(env=env_vals):
                temp_app = FastAPI()
                with patch.dict(os.environ, env_vals, clear=False):
                    registered = server.register_dev_login_route(temp_app)
                self.assertFalse(registered)
                resp = _make_test_client(temp_app).post("/api/auth/dev-login")
                self.assertEqual(resp.status_code, 404)

    def test_dev_login_http_proxy_headers_non_loopback_and_claims(self):
        temp_app = FastAPI()
        env_vals = {
            "SOCRATES_ENV": "development",
            "K_SERVICE": "",
            "SOCRATES_ENABLE_DEV_LOGIN": "true",
            "SOCRATES_DEV_ROLE": "viewer",
            "SOCRATES_DEV_ID": INSTANCE_ADMIN_DISCORD_ID,
            "SOCRATES_INSTANCE_ADMINS": INSTANCE_ADMIN_DISCORD_ID,
            "JWT_SECRET": STRONG_TEST_SECRET,
        }
        with patch.dict(os.environ, env_vals, clear=False):
            self.assertTrue(server.register_dev_login_route(temp_app))
            client = _make_test_client(temp_app)

            # Proxy headers must be rejected with 403
            r_xff = client.post("/api/auth/dev-login", headers={"X-Forwarded-For": "8.8.8.8"})
            self.assertEqual(r_xff.status_code, 403)
            r_fwd = client.post("/api/auth/dev-login", headers={"Forwarded": "for=8.8.8.8"})
            self.assertEqual(r_fwd.status_code, 403)

            # Non-loopback client host must be rejected with 403
            mock_req = MagicMock()
            mock_req.headers = {}
            mock_req.client = MagicMock(host="198.51.100.10")
            from fastapi import HTTPException, Response
            with self.assertRaises(HTTPException) as ctx:
                server.dev_login(Response(), mock_req)
            self.assertEqual(ctx.exception.status_code, 403)

            # Valid local POST succeeds with viewer role (NOT instance_admin even though SOCRATES_DEV_ID is in SOCRATES_INSTANCE_ADMINS!)
            r_ok = client.post("/api/auth/dev-login")
            self.assertEqual(r_ok.status_code, 200)
            body = r_ok.json()
            self.assertEqual(body["user"]["id"], INSTANCE_ADMIN_DISCORD_ID)
            self.assertEqual(body["user"]["auth_method"], "dev")
            self.assertEqual(body["user"]["dev_role"], "viewer")
            self.assertFalse(body["user"]["is_instance_admin"])

            token = r_ok.cookies.get("__session")
            self.assertTrue(token)
            decoded = jwt.decode(token, STRONG_TEST_SECRET, algorithms=["HS256"])
            self.assertEqual(decoded["auth_method"], "dev")
            self.assertEqual(decoded["dev_role"], "viewer")
            self.assertEqual(decoded["sub"], INSTANCE_ADMIN_DISCORD_ID)
            ttl_seconds = decoded["exp"] - decoded["iat"] if "iat" in decoded else None
            # Verify 12h TTL
            now_ts = int(datetime.now(timezone.utc).timestamp())
            self.assertGreater(decoded["exp"] - now_ts, 11 * 3600)
            self.assertLessEqual(decoded["exp"] - now_ts, 12 * 3600 + 60)
            self.assertEqual(ttl_seconds, 12 * 3600)

            # Now test with SOCRATES_DEV_ROLE=instance_admin
            with patch.dict(os.environ, {"SOCRATES_DEV_ROLE": "instance_admin"}, clear=False):
                r_admin = client.post("/api/auth/dev-login")
                self.assertEqual(r_admin.status_code, 200)
                self.assertTrue(r_admin.json()["user"]["is_instance_admin"])


class TestOAuthAndGuildVerification(unittest.TestCase):
    """Tests Discord OAuth login guild verification without backups_index.json bypass and InstanceAdmin login."""

    def setUp(self):
        server.clear_bot_guilds_cache()

    def tearDown(self):
        server.clear_bot_guilds_cache()

    def test_auth_discord_does_not_trust_backups_index_when_bot_not_in_guild(self):
        class FakeResp:
            def __init__(self, status_code, data):
                self.status_code = status_code
                self._data = data
                self.text = json.dumps(data)

            def json(self):
                return self._data

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, data=None, headers=None):
                return FakeResp(200, {"access_token": "tok_123"})

            async def get(self, url, headers=None):
                auth = (headers or {}).get("Authorization", "")
                if url.endswith("/users/@me"):
                    return FakeResp(200, {"id": REGULAR_USER_DISCORD_ID, "username": "Alice", "avatar": None})
                if url.endswith("/users/@me/guilds") and auth == "Bearer tok_123":
                    # User is in GUILD_ELYSIUM, which exists in backups_index.json
                    return FakeResp(200, [{"id": GUILD_ELYSIUM, "name": "Elysium"}])
                if url.endswith("/users/@me/guilds") and auth == "Bot test_bot_token":
                    # Bot is NOT in GUILD_ELYSIUM (only in some unrelated guild)
                    return FakeResp(200, [{"id": "777777777777777777", "name": "OtherBotGuild"}])
                return FakeResp(404, {})

        with patch.dict(
            os.environ,
            {
                "DISCORD_CLIENT_ID": "cid",
                "DISCORD_CLIENT_SECRET": "csec",
                "DISCORD_REDIRECT_URI": "http://localhost:5173/callback",
                "SOCRATES_ALLOWED_REDIRECT_URIS": "http://localhost:5173/callback",
                "DISCORD_TOKEN": "test_bot_token",
                "JWT_SECRET": STRONG_TEST_SECRET,
                "SOCRATES_INSTANCE_ADMINS": INSTANCE_ADMIN_DISCORD_ID,
                "SOCRATES_ENV": "development",
                "K_SERVICE": "",
            },
            clear=False,
        ):
            with patch.object(server.httpx, "AsyncClient", FakeAsyncClient):
                client = _make_test_client(server.app)
                login_res = client.get("/api/auth/login-url")
                self.assertEqual(login_res.status_code, 200)
                state = login_res.json()["state"]
                resp = client.post("/api/auth/discord", json={"code": "oauth_code", "state": state})
                # Previously this succeeded because backups_index.json was unconditionally unioned into bot_guilds!
                self.assertEqual(resp.status_code, 403)

    def test_auth_discord_allows_instance_admin_with_no_guild_overlap(self):
        class FakeResp:
            def __init__(self, status_code, data):
                self.status_code = status_code
                self._data = data
                self.text = json.dumps(data)

            def json(self):
                return self._data

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, data=None, headers=None):
                return FakeResp(200, {"access_token": "tok_admin"})

            async def get(self, url, headers=None):
                auth = (headers or {}).get("Authorization", "")
                if url.endswith("/users/@me"):
                    return FakeResp(200, {"id": INSTANCE_ADMIN_DISCORD_ID, "username": "RootAdmin", "avatar": None})
                if url.endswith("/users/@me/guilds") and auth == "Bearer tok_admin":
                    return FakeResp(200, [])
                if url.endswith("/users/@me/guilds") and auth == "Bot test_bot_token":
                    return FakeResp(200, [{"id": GUILD_ELYSIUM, "name": "Elysium"}])
                return FakeResp(404, {})

        with patch.dict(
            os.environ,
            {
                "DISCORD_CLIENT_ID": "cid",
                "DISCORD_CLIENT_SECRET": "csec",
                "DISCORD_REDIRECT_URI": "http://localhost:5173/callback",
                "SOCRATES_ALLOWED_REDIRECT_URIS": "http://localhost:5173/callback",
                "DISCORD_TOKEN": "test_bot_token",
                "JWT_SECRET": STRONG_TEST_SECRET,
                "SOCRATES_INSTANCE_ADMINS": INSTANCE_ADMIN_DISCORD_ID,
                "SOCRATES_ENV": "development",
                "K_SERVICE": "",
            },
            clear=False,
        ):
            with patch.object(server.httpx, "AsyncClient", FakeAsyncClient):
                client = _make_test_client(server.app)
                login_res = client.get("/api/auth/login-url")
                self.assertEqual(login_res.status_code, 200)
                state = login_res.json()["state"]
                resp = client.post("/api/auth/discord", json={"code": "oauth_code", "state": state})
                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertEqual(body["user"]["id"], INSTANCE_ADMIN_DISCORD_ID)
                self.assertTrue(body["user"]["is_instance_admin"])
                self.assertEqual(body["user"]["authorized_guilds"], [])

                # /api/auth/me reflects enriched id and is_instance_admin
                me_resp = client.get("/api/auth/me")
                self.assertEqual(me_resp.status_code, 200)
                self.assertEqual(me_resp.json()["user"]["id"], INSTANCE_ADMIN_DISCORD_ID)
                self.assertTrue(me_resp.json()["user"]["is_instance_admin"])

    def test_live_bot_guilds_ttl_cache(self):
        calls = {"count": 0}

        class FakeResp:
            status_code = 200

            def json(self):
                return [{"id": GUILD_ELYSIUM}]

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None):
                calls["count"] += 1
                return FakeResp()

        with patch.dict(os.environ, {"DISCORD_TOKEN": "bot_tok_ttl"}, clear=False):
            with patch.object(server.httpx, "AsyncClient", FakeAsyncClient):
                g1 = asyncio.run(server.fetch_live_bot_guilds_async(), loop_factory=_TestEventLoop)
                g2 = asyncio.run(server.fetch_live_bot_guilds_async(), loop_factory=_TestEventLoop)
                self.assertEqual(g1, {GUILD_ELYSIUM})
                self.assertEqual(g2, {GUILD_ELYSIUM})
                self.assertEqual(calls["count"], 1)


class TestRouteAuthAndBOLA(unittest.TestCase):
    """Tests 401 unauthenticated denials, 403/404 BOLA across backups/guilds, and InstanceAdmin gates."""

    def setUp(self):
        server.clear_bot_guilds_cache()
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        (root / "out").mkdir(parents=True, exist_ok=True)
        (root / "Backups" / "Elysium-sql-tests-clean").mkdir(parents=True, exist_ok=True)
        (root / "Backups" / "Elysium-sql-tests").mkdir(parents=True, exist_ok=True)
        (root / "Backups" / "el_meu_server").mkdir(parents=True, exist_ok=True)
        (root / "Backups" / "Elysium-sql-tests-clean" / "backup_config.json").write_text(
            json.dumps({"name": "Elysium"}), encoding="utf-8"
        )
        (root / "Backups" / "Elysium-sql-tests" / "backup_config.json").write_text(
            json.dumps({"name": "Elysium"}), encoding="utf-8"
        )
        (root / "Backups" / "el_meu_server" / "backup_config.json").write_text(
            json.dumps({"name": "Other"}), encoding="utf-8"
        )
        self.index_entries = [
            {
                "backup_id": BACKUP_ELYSIUM,
                "backup_name": "Elysium-sql-tests",
                "server_id": GUILD_ELYSIUM,
                "server_name": "Elysium",
                "path": "Backups/Elysium-sql-tests",
            },
            {
                "backup_id": BACKUP_OTHER,
                "backup_name": "el_meu_server",
                "server_id": GUILD_OTHER,
                "server_name": "Other",
                "path": "Backups/el_meu_server",
            },
        ]
        self.data_root_patcher = patch.object(server, "get_data_root", return_value=self.tmpdir.name)
        self.index_patcher = patch.object(
            server.t,
            "get_backups_index",
            side_effect=lambda: [dict(entry) for entry in self.index_entries],
        )
        self.data_root_patcher.start()
        self.index_patcher.start()

        self.client = _make_test_client(server.app)
        self.env_patcher = patch.dict(
            os.environ,
            {
                "JWT_SECRET": STRONG_TEST_SECRET,
                "SOCRATES_INSTANCE_ADMINS": INSTANCE_ADMIN_DISCORD_ID,
                "SOCRATES_ENV": "development",
                "K_SERVICE": "",
                "DISCORD_TOKEN": "secret_bot_token_value",
                "DISCORD_CLIENT_SECRET": "secret_client_secret_value",
            },
            clear=False,
        )
        self.env_patcher.start()

    def tearDown(self):
        from db.session import close_all_engines
        self.env_patcher.stop()
        self.index_patcher.stop()
        self.data_root_patcher.stop()
        close_all_engines()
        self.tmpdir.cleanup()
        server.clear_bot_guilds_cache()

    def _cookies_for_regular_user(self, guild_ids=None, sub=REGULAR_USER_DISCORD_ID):
        guilds = [{"id": gid, "name": f"Guild {gid}"} for gid in (guild_ids or [GUILD_ELYSIUM])]
        token = _make_jwt(
            {
                "sub": sub,
                "username": "RegularUser",
                "auth_method": "discord",
                "authorized_guilds": guilds,
            }
        )
        return {"__session": token}

    def _cookies_for_instance_admin(self):
        token = _make_jwt(
            {
                "sub": INSTANCE_ADMIN_DISCORD_ID,
                "username": "InstanceAdmin",
                "auth_method": "discord",
                "authorized_guilds": [],
            }
        )
        return {"__session": token}

    def test_unauthenticated_requests_return_401(self):
        endpoints = [
            ("GET", "/api/backups"),
            ("GET", "/api/backups-paths"),
            ("POST", "/api/backups"),
            ("GET", f"/api/servers/{GUILD_ELYSIUM}/categories"),
            ("GET", "/api/config/global"),
            ("PUT", "/api/config/global"),
            ("GET", "/api/logs/global"),
            ("DELETE", "/api/logs/global"),
            ("POST", "/api/admin/test-backup/reset"),
            ("POST", "/api/admin/test-backup/migrate"),
            ("POST", "/api/admin/upgrade-all"),
            ("POST", "/api/admin/tests/run"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/config"),
            ("PUT", f"/api/backups/{BACKUP_ELYSIUM}/config"),
            ("POST", f"/api/backups/{BACKUP_ELYSIUM}/run"),
            ("POST", f"/api/backups/{BACKUP_ELYSIUM}/cancel"),
            ("POST", f"/api/backups/{BACKUP_ELYSIUM}/upgrade"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/characters"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/writers"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/scenes"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/sessions"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/events"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/groups"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/curation/summary"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/scene-issues"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/flagged-messages"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/message-overrides"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/me/writer"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/logs"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/logs/raw"),
            ("DELETE", f"/api/backups/{BACKUP_ELYSIUM}/logs"),
            ("GET", f"/api/backups/{BACKUP_ELYSIUM}/logs/stream"),
        ]
        for method, path in endpoints:
            with self.subTest(method=method, path=path):
                resp = self.client.request(method, path)
                self.assertEqual(resp.status_code, 401)

    def test_forged_cli_claims_in_jwt_are_rejected_with_401(self):
        forged_direct = _make_jwt({"sub": "0", "auth_method": "discord", "_direct_call": True})
        forged_cli = _make_jwt({"sub": "0", "auth_method": "cli"})
        forged_http = _make_jwt({"sub": "0", "auth_method": "discord", "_verified_http": True})
        for tok in (forged_direct, forged_cli, forged_http):
            resp = self.client.get("/api/config/global", cookies={"__session": tok})
            self.assertEqual(resp.status_code, 401)

    def test_get_backups_filtering_for_regular_user_vs_instance_admin(self):
        # Bot is in GUILD_ELYSIUM, NOT in GUILD_OTHER
        with patch.object(server, "get_live_bot_guilds", return_value={GUILD_ELYSIUM}):
            # Regular user has both guilds in JWT, but bot is only in GUILD_ELYSIUM
            reg_cookies = self._cookies_for_regular_user([GUILD_ELYSIUM, GUILD_OTHER])
            resp_reg = self.client.get("/api/backups", cookies=reg_cookies)
            self.assertEqual(resp_reg.status_code, 200)
            reg_items = resp_reg.json()
            self.assertTrue(len(reg_items) > 0)
            self.assertTrue(all(str(b["server_id"]) == GUILD_ELYSIUM for b in reg_items))
            self.assertTrue(all(b["bot_in_guild"] is True for b in reg_items))

            # InstanceAdmin sees ALL backups including GUILD_OTHER with accurate bot_in_guild flag
            admin_cookies = self._cookies_for_instance_admin()
            resp_admin = self.client.get("/api/backups", cookies=admin_cookies)
            self.assertEqual(resp_admin.status_code, 200)
            admin_items = resp_admin.json()
            by_id = {str(b["backup_id"]): b for b in admin_items}
            self.assertIn(BACKUP_ELYSIUM, by_id)
            self.assertIn(BACKUP_OTHER, by_id)
            self.assertTrue(by_id[BACKUP_ELYSIUM]["bot_in_guild"])
            self.assertFalse(by_id[BACKUP_OTHER]["bot_in_guild"])

    def test_backup_bola_and_archived_guild_access(self):
        # Bot is in BOTH guilds, regular user only belongs to GUILD_ELYSIUM
        with patch.object(server, "get_live_bot_guilds", return_value={GUILD_ELYSIUM, GUILD_OTHER}):
            reg_admin_tok = _make_jwt(
                {
                    "sub": REGULAR_USER_DISCORD_ID,
                    "username": "Alice",
                    "auth_method": "discord",
                    "authorized_guilds": [
                        {"id": GUILD_ELYSIUM, "name": "Elysium", "permissions": 0x8}
                    ],
                }
            )
            reg_cookies = {"__session": reg_admin_tok}

            # Allowed on own guild backup
            r_own = self.client.get(f"/api/backups/{BACKUP_ELYSIUM}/config", cookies=reg_cookies)
            self.assertEqual(r_own.status_code, 200)

            # Denied (403) on other guild backup across endpoints
            for method, path in [
                ("GET", f"/api/backups/{BACKUP_OTHER}"),
                ("GET", f"/api/backups/{BACKUP_OTHER}/config"),
                ("GET", f"/api/backups/{BACKUP_OTHER}/logs"),
                ("GET", f"/api/backups/{BACKUP_OTHER}/logs/stream"),
                ("GET", f"/api/backups/{BACKUP_OTHER}/scenes"),
                ("GET", f"/api/backups/{BACKUP_OTHER}/events"),
                ("GET", f"/api/backups/{BACKUP_OTHER}/curation/summary"),
                ("POST", f"/api/backups/{BACKUP_OTHER}/upgrade"),
                ("POST", f"/api/backups/{BACKUP_OTHER}/cancel"),
            ]:
                with self.subTest(method=method, path=path):
                    r = self.client.request(
                        method,
                        path,
                        cookies=reg_cookies,
                        headers={"X-CSRF-Token": "phase1-csrf"},
                    )
                    self.assertEqual(r.status_code, 403)

            # Nonexistent backup returns 404
            r_missing = self.client.get("/api/backups/999999999/config", cookies=reg_cookies)
            self.assertEqual(r_missing.status_code, 404)

        # Now bot leaves GUILD_OTHER (archived backup)
        with patch.object(server, "get_live_bot_guilds", return_value={GUILD_ELYSIUM}):
            reg_both = self._cookies_for_regular_user([GUILD_ELYSIUM, GUILD_OTHER])
            r_reg_archived = self.client.get(f"/api/backups/{BACKUP_OTHER}/config", cookies=reg_both)
            self.assertEqual(r_reg_archived.status_code, 403)

            admin_cookies = self._cookies_for_instance_admin()
            r_admin_archived = self.client.get(f"/api/backups/{BACKUP_OTHER}/config", cookies=admin_cookies)
            self.assertEqual(r_admin_archived.status_code, 200)

    def test_instance_admin_endpoints_reject_non_admin_and_scrub_test_runner_env(self):
        reg_cookies = self._cookies_for_regular_user([GUILD_ELYSIUM, GUILD_OTHER])
        admin_only_endpoints = [
            ("GET", "/api/config/global", None),
            ("PUT", "/api/config/global", {"admin": {}}),
            ("GET", "/api/logs/global", None),
            ("DELETE", "/api/logs/global", None),
            ("POST", "/api/backups", {"admin": {"serverId": GUILD_ELYSIUM, "serverName": "Elysium", "backupName": "Test"}}),
            ("POST", "/api/admin/test-backup/reset", None),
            ("POST", "/api/admin/test-backup/migrate", None),
            ("POST", "/api/admin/upgrade-all", None),
            ("POST", "/api/admin/tests/run", None),
        ]
        with patch.object(server, "get_live_bot_guilds", return_value={GUILD_ELYSIUM, GUILD_OTHER}):
            for method, path, payload in admin_only_endpoints:
                with self.subTest(method=method, path=path):
                    kwargs = {"cookies": reg_cookies, "headers": {"X-CSRF-Token": "phase1-csrf"}}
                    if payload is not None:
                        kwargs["json"] = payload
                    resp = self.client.request(method, path, **kwargs)
                    self.assertEqual(resp.status_code, 403)

        # InstanceAdmin can run /api/admin/tests/run even in production, staged in /tmp with secrets scrubbed
        admin_cookies = self._cookies_for_instance_admin()
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "OK"
        mock_proc.stderr = ""
        captured = {}

        def _fake_subprocess_run(*args, **kwargs):
            child_env = dict(kwargs.get("env") or {})
            data_dir = child_env.get("SOCRATES_DATA_DIR", "")
            captured["env"] = child_env
            captured["staged_exists"] = bool(data_dir) and Path(data_dir).exists()
            captured["staged_clean_exists"] = bool(data_dir) and (
                Path(data_dir) / "Backups" / "Elysium-sql-tests-clean" / "backup_config.json"
            ).exists()
            return mock_proc

        with patch.dict(os.environ, {"SOCRATES_ENV": "production"}, clear=False):
            with patch.object(server.subprocess, "run", side_effect=_fake_subprocess_run):
                resp = self.client.post(
                    "/api/admin/tests/run",
                    cookies=admin_cookies,
                    headers={"X-CSRF-Token": "phase1-csrf"},
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["status"], "success")
                called_env = captured["env"]
                self.assertNotIn("DISCORD_TOKEN", called_env)
                self.assertNotIn("DISCORD_CLIENT_SECRET", called_env)
                self.assertNotIn("JWT_SECRET", called_env)
                self.assertEqual(called_env.get("SOCRATES_PRODUCTION_TESTS_ONLY"), "1")
                self.assertEqual(called_env.get("SOCRATES_TEST_SUITE"), "1")
                self.assertEqual(called_env.get("SOCRATES_SQLITE_TMP_CACHE"), "0")
                self.assertEqual(called_env.get("SOCRATES_TEST_DATA_STAGE_DONE"), "1")
                staged_data_dir = called_env.get("SOCRATES_DATA_DIR", "")
                self.assertTrue(staged_data_dir)
                self.assertNotEqual(Path(staged_data_dir).resolve(), Path(self.tmpdir.name).resolve())
                self.assertTrue(captured["staged_exists"])
                self.assertTrue(captured["staged_clean_exists"])
                audit_db_path = called_env.get("SOCRATES_GLOBAL_AUDIT_DB_PATH", "")
                self.assertTrue(audit_db_path)
                self.assertTrue(
                    Path(audit_db_path).resolve().is_relative_to(Path(staged_data_dir).resolve())
                )

    def test_run_python_tests_lock_returns_409_when_already_running(self):
        admin_cookies = self._cookies_for_instance_admin()
        acquired = server._TEST_RUN_LOCK.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            resp = self.client.post(
                "/api/admin/tests/run",
                cookies=admin_cookies,
                headers={"X-CSRF-Token": "phase1-csrf"},
            )
            self.assertEqual(resp.status_code, 409)
        finally:
            server._TEST_RUN_LOCK.release()

    def test_fixture_helpers_depend_only_on_fixture_presence_even_in_production(self):
        with patch.dict(
            os.environ,
            {
                "SOCRATES_ENV": "production",
                "SOCRATES_PRODUCTION_TESTS_ONLY": "1",
                "SOCRATES_DATA_DIR": self.tmpdir.name,
            },
            clear=False,
        ):
            self.assertTrue(has_local_test_backup_fixture())
            self.assertFalse(has_local_live_backup_fixture())

            (Path(self.tmpdir.name) / "Backups" / "Elysium").mkdir(parents=True, exist_ok=True)
            self.assertTrue(has_local_live_backup_fixture())

        with tempfile.TemporaryDirectory() as empty_dir:
            with patch.dict(
                os.environ,
                {
                    "SOCRATES_ENV": "production",
                    "SOCRATES_PRODUCTION_TESTS_ONLY": "1",
                    "SOCRATES_DATA_DIR": empty_dir,
                },
                clear=False,
            ):
                self.assertFalse(has_local_test_backup_fixture())
                self.assertFalse(has_local_live_backup_fixture())


if __name__ == "__main__":
    unittest.main()

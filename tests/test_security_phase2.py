import base64
import concurrent.futures
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import jwt

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
from db.models import (  # noqa: E402
    BackupModel,
    CharacterModel,
    CharacterNameModel,
    WriterAliasModel,
    WriterModel,
)
from db.session import close_all_engines, db_session, init_db  # noqa: E402
from models import SceneManager  # noqa: E402
from tests.test_security_phase1 import (  # noqa: E402
    GUILD_ELYSIUM,
    GUILD_OTHER,
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
UID_OTHER_WRITER = "200000000000000004"
UID_VIEWER = "200000000000000005"

TEST_BACKUP_ID = "9900112233"
ARCHIVED_BACKUP_ID = "9900112244"
TEST_GUILD_ID = "880011223344556677"
ARCHIVED_GUILD_ID = "880011223344556688"


def _session_cookie(
    sub: str,
    guilds=None,
    auth_method: str = "discord",
    dev_role: str | None = None,
    jti: str = "test-jti-1",
    csrf: str = "test-csrf-1",
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


class TestOAuth2AndJWTHardening(unittest.TestCase):
    """Tests OAuth2 state/PKCE, redirect_uri allowlist, JWT iss/typ/jti revocation, and CSRF tokens."""

    def setUp(self):
        server.clear_bot_guilds_cache()
        server.clear_revoked_jtis()
        rbac.clear_rbac_caches()

    def tearDown(self):
        server.clear_bot_guilds_cache()
        server.clear_revoked_jtis()
        rbac.clear_rbac_caches()

    def test_redirect_uri_allowlist_and_login_url_pkce(self):
        with patch.dict(
            os.environ,
            {
                "DISCORD_CLIENT_ID": "cid_test",
                "DISCORD_CLIENT_SECRET": "csec_test",
                "DISCORD_REDIRECT_URI": "",
                "SOCRATES_ALLOWED_REDIRECT_URIS": "",
                "JWT_SECRET": STRONG_TEST_SECRET,
            },
            clear=False,
        ):
            client = _make_test_client(server.app)
            r_unconfigured = client.get("/api/auth/login-url")
            self.assertEqual(r_unconfigured.status_code, 500)

        with patch.dict(
            os.environ,
            {
                "DISCORD_CLIENT_ID": "cid_test",
                "DISCORD_CLIENT_SECRET": "csec_test",
                "DISCORD_REDIRECT_URI": "http://localhost:5173/callback",
                "SOCRATES_ALLOWED_REDIRECT_URIS": "http://localhost:5173/callback,https://app.example.com/auth/callback",
                "JWT_SECRET": STRONG_TEST_SECRET,
            },
            clear=False,
        ):
            client = _make_test_client(server.app)

            r_bad_uri = client.get(
                "/api/auth/login-url",
                params={"redirect_uri": "https://evil.example.com/steal"},
            )
            self.assertEqual(r_bad_uri.status_code, 400)

            r_ok = client.get(
                "/api/auth/login-url",
                params={"redirect_uri": "https://app.example.com/auth/callback"},
            )
            self.assertEqual(r_ok.status_code, 200)
            body = r_ok.json()
            self.assertIn("url", body)
            self.assertIn("state", body)

            parsed = urlparse(body["url"])
            qs = parse_qs(parsed.query)
            self.assertEqual(qs["state"][0], body["state"])
            self.assertEqual(qs["code_challenge_method"][0], "S256")
            self.assertEqual(qs["redirect_uri"][0], "https://app.example.com/auth/callback")

            preauth_token = r_ok.cookies.get("__session")
            self.assertTrue(preauth_token)
            preauth_claims = jwt.decode(
                preauth_token, STRONG_TEST_SECRET, algorithms=["HS256"]
            )
            self.assertEqual(preauth_claims["typ"], "oauth_preauth")
            self.assertEqual(preauth_claims["iss"], "socrates")
            self.assertEqual(preauth_claims["state"], body["state"])

            digest = hashlib.sha256(
                preauth_claims["code_verifier"].encode("ascii")
            ).digest()
            expected_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
            self.assertEqual(qs["code_challenge"][0], expected_challenge)

            # oauth_preauth cookie must NEVER grant API access
            r_me = client.get("/api/auth/me", cookies={"__session": preauth_token})
            self.assertEqual(r_me.status_code, 200)
            self.assertIsNone(r_me.json()["user"])

            r_backups = client.get("/api/backups", cookies={"__session": preauth_token})
            self.assertEqual(r_backups.status_code, 401)

    def test_auth_discord_validates_state_pkce_redirect_and_issues_hardened_session(self):
        captured_token_posts = []

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
                captured_token_posts.append((url, data))
                return FakeResp(200, {"access_token": "tok_hardened"})

            async def get(self, url, headers=None):
                auth = (headers or {}).get("Authorization", "")
                if url.endswith("/users/@me"):
                    return FakeResp(200, {"id": UID_VIEWER, "username": "ViewerOne"})
                if url.endswith("/users/@me/guilds") and auth == "Bearer tok_hardened":
                    return FakeResp(
                        200,
                        [
                            {
                                "id": GUILD_ELYSIUM,
                                "name": "Elysium",
                                "owner": True,
                                "permissions": "8",
                            }
                        ],
                    )
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
                "SOCRATES_ENV": "development",
                "K_SERVICE": "",
            },
            clear=False,
        ):
            with patch.object(server.httpx, "AsyncClient", FakeAsyncClient):
                client = _make_test_client(server.app)

                # Missing preauth cookie -> rejected
                r_no_cookie = client.post(
                    "/api/auth/discord", json={"code": "c1", "state": "s1"}
                )
                self.assertEqual(r_no_cookie.status_code, 400)

                # Get valid state + preauth cookie
                login_res = client.get("/api/auth/login-url")
                self.assertEqual(login_res.status_code, 200)
                state = login_res.json()["state"]

                # Mismatched state -> rejected
                r_bad_state = client.post(
                    "/api/auth/discord",
                    json={"code": "c1", "state": "wrong_state"},
                )
                self.assertEqual(r_bad_state.status_code, 403)

                # Disallowed redirect_uri -> rejected
                r_bad_redirect = client.post(
                    "/api/auth/discord",
                    json={
                        "code": "c1",
                        "state": state,
                        "redirect_uri": "https://evil.example.com/cb",
                    },
                )
                self.assertEqual(r_bad_redirect.status_code, 400)

                # Valid state & redirect_uri -> 200 + code_verifier sent + session JWT claims
                r_ok = client.post(
                    "/api/auth/discord",
                    json={"code": "c1", "state": state},
                )
                self.assertEqual(r_ok.status_code, 200)
                body = r_ok.json()
                self.assertTrue(body.get("csrf_token"))
                self.assertEqual(len(captured_token_posts), 1)
                self.assertTrue(captured_token_posts[0][1].get("code_verifier"))

                session_tok = r_ok.cookies.get("__session")
                claims = jwt.decode(
                    session_tok,
                    STRONG_TEST_SECRET,
                    algorithms=["HS256"],
                    issuer="socrates",
                )
                self.assertEqual(claims["typ"], "session")
                self.assertEqual(claims["iss"], "socrates")
                self.assertTrue(claims["jti"])
                self.assertEqual(claims["csrf"], body["csrf_token"])
                self.assertEqual(claims["exp"] - claims["iat"], 12 * 3600)
                self.assertEqual(
                    claims["authorized_guilds"],
                    [
                        {
                            "id": GUILD_ELYSIUM,
                            "name": "Elysium",
                            "owner": True,
                            "permissions": 8,
                        }
                    ],
                )

                # /api/auth/me exposes csrf_token
                me_res = client.get("/api/auth/me")
                self.assertEqual(me_res.status_code, 200)
                self.assertEqual(me_res.json()["csrf_token"], body["csrf_token"])

                # Logout revokes jti even before exp
                logout_res = client.post(
                    "/api/auth/logout",
                    headers={"X-CSRF-Token": body["csrf_token"]},
                )
                self.assertEqual(logout_res.status_code, 200)

                r_after_logout = client.get(
                    "/api/backups", cookies={"__session": session_tok}
                )
                self.assertEqual(r_after_logout.status_code, 401)
                r_me_after_logout = client.get(
                    "/api/auth/me", cookies={"__session": session_tok}
                )
                self.assertIsNone(r_me_after_logout.json()["user"])

    def test_jwt_rejects_wrong_issuer_or_typ_and_dev_login_includes_hardened_claims(self):
        with patch.dict(
            os.environ,
            {
                "SOCRATES_ENV": "development",
                "SOCRATES_ENABLE_DEV_LOGIN": "true",
                "SOCRATES_DEV_ROLE": "curator",
                "SOCRATES_DEV_ID": UID_CURATOR,
                "JWT_SECRET": STRONG_TEST_SECRET,
            },
            clear=False,
        ):
            app = server.FastAPI()
            server.register_dev_login_route(app)
            app.add_api_route("/api/auth/me", server.get_me, methods=["GET"])
            client = _make_test_client(app)

            r_dev = client.post("/api/auth/dev-login")
            self.assertEqual(r_dev.status_code, 200)
            body = r_dev.json()
            self.assertTrue(body.get("csrf_token"))
            tok = r_dev.cookies.get("__session")
            claims = jwt.decode(
                tok, STRONG_TEST_SECRET, algorithms=["HS256"], issuer="socrates"
            )
            self.assertEqual(claims["typ"], "session")
            self.assertEqual(claims["csrf"], body["csrf_token"])
            self.assertEqual(claims["exp"] - claims["iat"], 12 * 3600)
            self.assertTrue(claims["jti"])

        # Main app rejects wrong iss / typ on authenticated routes
        main_client = _make_test_client(server.app)
        with patch.dict(os.environ, {"JWT_SECRET": STRONG_TEST_SECRET}, clear=False):
            wrong_iss = _make_jwt({"sub": UID_VIEWER, "iss": "other-app", "typ": "session"})
            wrong_typ = _make_jwt({"sub": UID_VIEWER, "iss": "socrates", "typ": "oauth_preauth"})
            self.assertEqual(
                main_client.get("/api/backups", cookies={"__session": wrong_iss}).status_code,
                401,
            )
            self.assertEqual(
                main_client.get("/api/backups", cookies={"__session": wrong_typ}).status_code,
                401,
            )


class TestRBACResolutionAndConfig(unittest.TestCase):
    """Tests 5-tier RBAC role resolution, TTL caches, /discord-roles, and /rbac endpoints."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.backup_dir = Path(self.tmpdir.name) / "Backups" / "test_backup"
        self.archived_dir = Path(self.tmpdir.name) / "Backups" / "archived_backup"
        self.backup_dir.mkdir(parents=True)
        self.archived_dir.mkdir(parents=True)

        with open(self.backup_dir / "backup_config.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "server_id": TEST_GUILD_ID,
                    "backup_id": TEST_BACKUP_ID,
                    "rbac": {
                        "adminRoleIds": [ROLE_ADMIN_ID],
                        "curatorRoleIds": [ROLE_CURATOR_ID],
                        "participantRoleIds": [ROLE_PARTICIPANT_ID],
                        "restrictedUserIds": [],
                        "blockedUserIds": [],
                    },
                },
                f,
            )
        with open(self.archived_dir / "backup_config.json", "w", encoding="utf-8") as f:
            json.dump({"server_id": ARCHIVED_GUILD_ID, "backup_id": ARCHIVED_BACKUP_ID}, f)

        self.index_entries = [
            {
                "backup_id": TEST_BACKUP_ID,
                "backup_name": "TestGuild",
                "server_id": TEST_GUILD_ID,
                "server_name": "Test Guild",
                "path": "Backups/test_backup",
            },
            {
                "backup_id": ARCHIVED_BACKUP_ID,
                "backup_name": "ArchivedGuild",
                "server_id": ARCHIVED_GUILD_ID,
                "server_name": "Archived Guild",
                "path": self.archived_dir.as_posix(),
            },
        ]

        server.clear_bot_guilds_cache()
        server.clear_revoked_jtis()
        rbac.clear_rbac_caches()

    def tearDown(self):
        server.clear_bot_guilds_cache()
        server.clear_revoked_jtis()
        rbac.clear_rbac_caches()
        close_all_engines()
        self.tmpdir.cleanup()

    def test_role_resolution_hierarchy_offline_fallback_and_dev_roles(self):
        entry = self.index_entries[0]

        def resolve_for(actor, bot_token=None):
            return rbac.resolve_backup_role(
                backup_id=TEST_BACKUP_ID,
                entry=entry,
                base_path=self.backup_dir.as_posix(),
                actor=actor,
                is_instance_admin_fn=server.is_instance_admin_user,
                effective_bot_guilds_fn=server._get_effective_bot_guilds,
                extract_user_guild_ids_fn=server._extract_user_guild_ids,
                bot_token=bot_token,
                is_production=False,
                socrates_env="development",
            )

        # InstanceAdmin -> level 5
        with patch.dict(
            os.environ,
            {"SOCRATES_INSTANCE_ADMINS": INSTANCE_ADMIN_DISCORD_ID},
            clear=False,
        ):
            self.assertEqual(
                resolve_for({"sub": INSTANCE_ADMIN_DISCORD_ID, "auth_method": "discord"})[0],
                "instance_admin",
            )

        with patch.object(server, "get_live_bot_guilds", return_value={TEST_GUILD_ID}):
            # Guild owner -> server_admin (even offline without bot_token)
            self.assertEqual(
                resolve_for(
                    {
                        "sub": UID_VIEWER,
                        "auth_method": "discord",
                        "authorized_guilds": [{"id": TEST_GUILD_ID, "owner": True, "permissions": 0}],
                    },
                    bot_token=None,
                ),
                ("server_admin", 4),
            )

            # Administrator (0x8) or Manage Guild (0x20) -> server_admin
            self.assertEqual(
                resolve_for(
                    {
                        "sub": UID_VIEWER,
                        "auth_method": "discord",
                        "authorized_guilds": [{"id": TEST_GUILD_ID, "permissions": 0x8}],
                    }
                ),
                ("server_admin", 4),
            )
            self.assertEqual(
                resolve_for(
                    {
                        "sub": UID_VIEWER,
                        "auth_method": "discord",
                        "authorized_guilds": [{"id": TEST_GUILD_ID, "permissions": 0x20}],
                    }
                ),
                ("server_admin", 4),
            )

        # Discord role lookups for admin / curator / participant / viewer + cache
        api_calls = []

        def fake_httpx_get(url, headers=None, timeout=10.0):
            api_calls.append(url)
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith(f"/members/{UID_ADMIN}"):
                resp.json.return_value = {"roles": [ROLE_ADMIN_ID]}
            elif url.endswith(f"/members/{UID_CURATOR}"):
                resp.json.return_value = {"roles": [ROLE_CURATOR_ID, ROLE_PARTICIPANT_ID]}
            elif url.endswith(f"/members/{UID_PARTICIPANT}"):
                resp.json.return_value = {"roles": [ROLE_PARTICIPANT_ID]}
            else:
                resp.json.return_value = {"roles": []}
            return resp

        with patch.object(server, "get_live_bot_guilds", return_value={TEST_GUILD_ID}):
            with patch.object(rbac.httpx, "get", side_effect=fake_httpx_get):
                for uid, expected in [
                    (UID_ADMIN, ("server_admin", 4)),
                    (UID_CURATOR, ("curator", 3)),
                    (UID_PARTICIPANT, ("participant", 2)),
                    (UID_VIEWER, ("viewer", 1)),
                ]:
                    actor = {
                        "sub": uid,
                        "auth_method": "discord",
                        "authorized_guilds": [{"id": TEST_GUILD_ID, "permissions": 0}],
                    }
                    self.assertEqual(resolve_for(actor, bot_token="bot_tok"), expected)

                # Calling again hits 90s TTL cache (no additional HTTP call)
                before = len(api_calls)
                resolve_for(
                    {
                        "sub": UID_CURATOR,
                        "auth_method": "discord",
                        "authorized_guilds": [{"id": TEST_GUILD_ID, "permissions": 0}],
                    },
                    bot_token="bot_tok",
                )
                self.assertEqual(len(api_calls), before)

        # Offline fallback when bot_token is absent -> non-admin falls back to viewer
        with patch.object(server, "get_live_bot_guilds", return_value={TEST_GUILD_ID}):
            self.assertEqual(
                resolve_for(
                    {
                        "sub": UID_CURATOR,
                        "auth_method": "discord",
                        "authorized_guilds": [{"id": TEST_GUILD_ID, "permissions": 0}],
                    },
                    bot_token=None,
                ),
                ("viewer", 1),
            )

        # All dev_roles in local development mode
        with patch.object(server, "get_live_bot_guilds", return_value={TEST_GUILD_ID}):
            for dev_role, lvl in [
                ("server_admin", 4),
                ("curator", 3),
                ("participant", 2),
                ("viewer", 1),
            ]:
                self.assertEqual(
                    resolve_for(
                        {
                            "sub": UID_VIEWER,
                            "auth_method": "dev",
                            "dev_role": dev_role,
                            "authorized_guilds": [{"id": TEST_GUILD_ID}],
                        }
                    ),
                    (dev_role, lvl),
                )

    def test_rbac_endpoints_validation_cache_invalidation_and_config_preservation(self):
        client = _make_test_client(server.app)
        client.headers.update({"X-CSRF-Token": "test-csrf-1"})

        def fake_httpx_get(url, headers=None, timeout=10.0):
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith(f"/guilds/{TEST_GUILD_ID}/roles"):
                resp.json.return_value = [
                    {"id": TEST_GUILD_ID, "name": "@everyone", "position": 0, "color": 0},
                    {"id": ROLE_CURATOR_ID, "name": "Curator", "position": 5, "color": 255},
                ]
            elif "/members/" in url:
                uid = url.rsplit("/", 1)[-1]
                if uid == UID_CURATOR:
                    resp.json.return_value = {"roles": [ROLE_CURATOR_ID]}
                else:
                    resp.json.return_value = {"roles": []}
            return resp

        env_patch = {
            "JWT_SECRET": STRONG_TEST_SECRET,
            "DISCORD_TOKEN": "bot_tok",
            "SOCRATES_INSTANCE_ADMINS": INSTANCE_ADMIN_DISCORD_ID,
        }
        with patch.dict(os.environ, env_patch, clear=False):
            with patch.object(server, "get_data_root", return_value=self.tmpdir.name), patch.object(
                t, "get_backups_index", return_value=self.index_entries
            ):
                with patch.object(server, "get_live_bot_guilds", return_value={TEST_GUILD_ID}):
                    with patch.object(rbac.httpx, "get", side_effect=fake_httpx_get):
                        admin_cookies = _session_cookie(
                            UID_ADMIN,
                            guilds=[{"id": TEST_GUILD_ID, "owner": True, "permissions": 8}],
                            jti="jti-admin",
                        )
                        curator_cookies = _session_cookie(
                            UID_CURATOR,
                            guilds=[{"id": TEST_GUILD_ID, "owner": False, "permissions": 0}],
                            jti="jti-curator",
                        )

                        # GET /api/backups includes effective_role & role_level
                        r_list = client.get("/api/backups", cookies=curator_cookies)
                        self.assertEqual(r_list.status_code, 200)
                        self.assertEqual(len(r_list.json()), 1)
                        self.assertEqual(r_list.json()[0]["effective_role"], "curator")
                        self.assertEqual(r_list.json()[0]["role_level"], 3)

                        # Curator denied on /discord-roles and /rbac
                        self.assertEqual(
                            client.get(
                                f"/api/backups/{TEST_BACKUP_ID}/discord-roles",
                                cookies=curator_cookies,
                            ).status_code,
                            403,
                        )
                        self.assertEqual(
                            client.get(
                                f"/api/backups/{TEST_BACKUP_ID}/rbac",
                                cookies=curator_cookies,
                            ).status_code,
                            403,
                        )

                        # ServerAdmin can list discord roles (@everyone excluded)
                        r_roles = client.get(
                            f"/api/backups/{TEST_BACKUP_ID}/discord-roles",
                            cookies=admin_cookies,
                        )
                        self.assertEqual(r_roles.status_code, 200)
                        self.assertTrue(r_roles.json()["bot_available"])
                        self.assertEqual(len(r_roles.json()["roles"]), 1)
                        self.assertEqual(r_roles.json()["roles"][0]["id"], ROLE_CURATOR_ID)

                        # Validation rejects non-snowflake IDs and extra fields
                        r_bad = client.put(
                            f"/api/backups/{TEST_BACKUP_ID}/rbac",
                            json={
                                "adminRoleIds": ["not-a-snowflake"],
                                "curatorRoleIds": [],
                                "participantRoleIds": [],
                                "restrictedUserIds": [],
                                "blockedUserIds": [],
                            },
                            cookies=admin_cookies,
                        )
                        self.assertEqual(r_bad.status_code, 422)

                        r_extra = client.put(
                            f"/api/backups/{TEST_BACKUP_ID}/rbac",
                            json={"unknownField": []},
                            cookies=admin_cookies,
                        )
                        self.assertEqual(r_extra.status_code, 422)

                        # Put UID_CURATOR into restrictedUserIds -> invalidates member role cache -> downgraded to viewer
                        r_put = client.put(
                            f"/api/backups/{TEST_BACKUP_ID}/rbac",
                            json={
                                "adminRoleIds": [ROLE_ADMIN_ID],
                                "curatorRoleIds": [ROLE_CURATOR_ID],
                                "participantRoleIds": [ROLE_PARTICIPANT_ID],
                                "restrictedUserIds": [UID_CURATOR],
                                "blockedUserIds": [],
                            },
                            cookies=admin_cookies,
                        )
                        self.assertEqual(r_put.status_code, 200)

                        r_list_after = client.get("/api/backups", cookies=curator_cookies)
                        self.assertEqual(r_list_after.json()[0]["effective_role"], "viewer")
                        self.assertEqual(r_list_after.json()[0]["role_level"], 1)

                        # Block UID_CURATOR -> 403 on backup access
                        client.put(
                            f"/api/backups/{TEST_BACKUP_ID}/rbac",
                            json={
                                "adminRoleIds": [ROLE_ADMIN_ID],
                                "curatorRoleIds": [ROLE_CURATOR_ID],
                                "participantRoleIds": [ROLE_PARTICIPANT_ID],
                                "restrictedUserIds": [],
                                "blockedUserIds": [UID_CURATOR],
                            },
                            cookies=admin_cookies,
                        )
                        self.assertEqual(
                            client.get(
                                f"/api/backups/{TEST_BACKUP_ID}/curation/summary",
                                cookies=curator_cookies,
                            ).status_code,
                            403,
                        )
                        # Blocked user is also excluded from /api/backups and /api/backups-paths
                        self.assertEqual(
                            client.get("/api/backups", cookies=curator_cookies).json(),
                            [],
                        )
                        self.assertEqual(
                            client.get("/api/backups-paths", cookies=curator_cookies).json(),
                            [],
                        )

                        # PUT /config preserves rbac section
                        r_cfg_put = client.put(
                            f"/api/backups/{TEST_BACKUP_ID}/config",
                            json={
                                "server_id": TEST_GUILD_ID,
                                "categories": ["12345"],
                            },
                            cookies=admin_cookies,
                        )
                        self.assertEqual(r_cfg_put.status_code, 200)
                        preserved_rbac = rbac.load_backup_rbac_config(self.backup_dir.as_posix())
                        self.assertEqual(preserved_rbac["blockedUserIds"], [UID_CURATOR])


class TestRBACEndpointEnforcement(unittest.TestCase):
    """Tests 5-tier endpoint permissions, privacy masking, curation lockout, and participant self-service."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.backup_dir = Path(cls.tmpdir.name) / "Backups" / "rbac_backup"
        cls.archived_dir = Path(cls.tmpdir.name) / "Backups" / "archived_backup"
        cls.backup_dir.mkdir(parents=True)
        cls.archived_dir.mkdir(parents=True)

        with open(cls.backup_dir / "backup_config.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "server_id": TEST_GUILD_ID,
                    "backup_id": TEST_BACKUP_ID,
                    "rbac": {
                        "adminRoleIds": [ROLE_ADMIN_ID],
                        "curatorRoleIds": [ROLE_CURATOR_ID],
                        "participantRoleIds": [ROLE_PARTICIPANT_ID],
                        "restrictedUserIds": [],
                        "blockedUserIds": [],
                    },
                },
                f,
            )
        with open(cls.backup_dir / "log.txt", "w", encoding="utf-8") as f:
            f.write("2026-01-01 INFO test log line\n")

        with open(cls.archived_dir / "backup_config.json", "w", encoding="utf-8") as f:
            json.dump({"server_id": ARCHIVED_GUILD_ID, "backup_id": ARCHIVED_BACKUP_ID}, f)

        cls.index_entries = [
            {
                "backup_id": TEST_BACKUP_ID,
                "backup_name": "RbacBackup",
                "server_id": TEST_GUILD_ID,
                "server_name": "RBAC Guild",
                "path": "Backups/rbac_backup",
            },
            {
                "backup_id": ARCHIVED_BACKUP_ID,
                "backup_name": "ArchivedBackup",
                "server_id": ARCHIVED_GUILD_ID,
                "server_name": "Archived Guild",
                "path": "Backups/archived_backup",
            },
        ]

        # Initialize isolated SQLite backup DBs
        for b_id, b_dir, gid in [
            (TEST_BACKUP_ID, cls.backup_dir, TEST_GUILD_ID),
            (ARCHIVED_BACKUP_ID, cls.archived_dir, ARCHIVED_GUILD_ID),
        ]:
            init_db(backup_id=b_id, backup_path=b_dir.as_posix())
            with db_session(backup_id=b_id, backup_path=b_dir.as_posix()) as session:
                session.add(
                    BackupModel(
                        backup_id=b_id,
                        backup_name=f"Backup_{b_id}",
                        server_id=gid,
                        server_name="Guild",
                        created_at=datetime.now(timezone.utc),
                    )
                )

        with db_session(backup_id=TEST_BACKUP_ID, backup_path=cls.backup_dir.as_posix()) as session:
            w1 = WriterModel(
                backup_id=TEST_BACKUP_ID,
                display_name="ParticipantWriter",
                discord_user_id=UID_PARTICIPANT,
            )
            w2 = WriterModel(
                backup_id=TEST_BACKUP_ID,
                display_name="OtherWriter",
                discord_user_id=UID_OTHER_WRITER,
            )
            session.add_all([w1, w2])
            session.flush()
            session.add(WriterAliasModel(writer_pk=w1.pk, alias="P_Alias"))
            cls.w1_pk = w1.pk
            cls.w2_pk = w2.pk

            c_own_1 = CharacterModel(
                backup_id=TEST_BACKUP_ID,
                char_id=101,
                writer_pk=w1.pk,
                origin="oc",
                activity="active",
            )
            c_own_2 = CharacterModel(
                backup_id=TEST_BACKUP_ID,
                char_id=102,
                writer_pk=w1.pk,
                origin="oc",
                activity="active",
            )
            c_other = CharacterModel(
                backup_id=TEST_BACKUP_ID,
                char_id=201,
                writer_pk=w2.pk,
                origin="canon",
                activity="active",
            )
            c_unassigned = CharacterModel(
                backup_id=TEST_BACKUP_ID,
                char_id=301,
                writer_pk=None,
                origin="oc",
                activity="active",
            )
            session.add_all([c_own_1, c_own_2, c_other, c_unassigned])
            session.flush()
            session.add_all(
                [
                    CharacterNameModel(character_pk=c_own_1.pk, name="OwnOne", position=0),
                    CharacterNameModel(character_pk=c_own_2.pk, name="OwnTwo", position=0),
                    CharacterNameModel(character_pk=c_other.pk, name="OtherOne", position=0),
                    CharacterNameModel(character_pk=c_unassigned.pk, name="UnassignedOne", position=0),
                ]
            )

        close_all_engines()

    @classmethod
    def tearDownClass(cls):
        SceneManager.clear_cache()
        close_all_engines()
        cls.tmpdir.cleanup()

    def setUp(self):
        server.clear_bot_guilds_cache()
        server.clear_revoked_jtis()
        rbac.clear_rbac_caches()
        self.client = _make_test_client(server.app)
        self.client.headers.update({"X-CSRF-Token": "test-csrf-1"})

    def _run_with_env(self, fn):
        def fake_httpx_get(url, headers=None, timeout=10.0):
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith(f"/members/{UID_CURATOR}"):
                resp.json.return_value = {"roles": [ROLE_CURATOR_ID]}
            elif url.endswith(f"/members/{UID_PARTICIPANT}"):
                resp.json.return_value = {"roles": [ROLE_PARTICIPANT_ID]}
            elif url.endswith(f"/members/{UID_ADMIN}"):
                resp.json.return_value = {"roles": [ROLE_ADMIN_ID]}
            else:
                resp.json.return_value = {"roles": []}
            return resp

        env_patch = {
            "JWT_SECRET": STRONG_TEST_SECRET,
            "DISCORD_TOKEN": "bot_tok",
            "SOCRATES_INSTANCE_ADMINS": INSTANCE_ADMIN_DISCORD_ID,
        }
        with patch.dict(os.environ, env_patch, clear=False):
            with patch.object(server, "get_data_root", return_value=self.tmpdir.name), patch.object(
                t, "get_backups_index", return_value=self.index_entries
            ):
                    with patch.object(server, "get_live_bot_guilds", return_value={TEST_GUILD_ID}):
                        with patch.object(rbac.httpx, "get", side_effect=fake_httpx_get):
                            return fn()

    def test_viewer_masking_and_curation_lockout(self):
        viewer_cookies = _session_cookie(
            UID_VIEWER,
            guilds=[{"id": TEST_GUILD_ID, "permissions": 0}],
            jti="jti-v1",
        )

        def _checks():
            # Backup info includes effective_role & role_level
            r_info = self.client.get(f"/api/backups/{TEST_BACKUP_ID}", cookies=viewer_cookies)
            self.assertEqual(r_info.status_code, 200)
            self.assertEqual(r_info.json()["effective_role"], "viewer")
            self.assertEqual(r_info.json()["role_level"], 1)

            # Privacy masking on writers/detailed and characters?format=normalized|db
            r_wd = self.client.get(
                f"/api/backups/{TEST_BACKUP_ID}/writers/detailed", cookies=viewer_cookies
            )
            self.assertEqual(r_wd.status_code, 200)
            for w in r_wd.json():
                self.assertIsNone(w["discord_user_id"])
                self.assertFalse(w["is_self"])

            for fmt in ("normalized", "db"):
                r_chars = self.client.get(
                    f"/api/backups/{TEST_BACKUP_ID}/characters",
                    params={"format": fmt},
                    cookies=viewer_cookies,
                )
                self.assertEqual(r_chars.status_code, 200)
                for w in r_chars.json().get("writers", []):
                    self.assertIsNone(w.get("discord_user_id"))
                    self.assertFalse(w.get("is_self"))

            # Sanitized curation/summary
            r_sum = self.client.get(
                f"/api/backups/{TEST_BACKUP_ID}/curation/summary", cookies=viewer_cookies
            )
            self.assertEqual(r_sum.status_code, 200)
            self.assertEqual(
                r_sum.json(),
                {
                    "unresolved_issues": 0,
                    "unassigned_characters": 0,
                    "flagged_messages": 0,
                    "unlinked_writers": 0,
                    "link_suggestions": 0,
                },
            )

            # Curation lockout (403)
            for path in [
                f"/api/backups/{TEST_BACKUP_ID}/writers/link-suggestions",
                f"/api/backups/{TEST_BACKUP_ID}/characters/unassigned-writers",
                f"/api/backups/{TEST_BACKUP_ID}/scene-issues",
                f"/api/backups/{TEST_BACKUP_ID}/flagged-messages",
                f"/api/backups/{TEST_BACKUP_ID}/message-overrides",
            ]:
                with self.subTest(path=path):
                    self.assertEqual(
                        self.client.get(path, cookies=viewer_cookies).status_code, 403
                    )

            # Denied on participant mutations
            self.assertEqual(
                self.client.put(
                    f"/api/backups/{TEST_BACKUP_ID}/writers/{self.w1_pk}",
                    json={"display_name": "Hacked"},
                    cookies=viewer_cookies,
                ).status_code,
                403,
            )
            self.assertEqual(
                self.client.put(
                    f"/api/backups/{TEST_BACKUP_ID}/characters/101",
                    json={"names": ["HackedChar"]},
                    cookies=viewer_cookies,
                ).status_code,
                403,
            )

        self._run_with_env(_checks)

    def test_participant_self_service_ownership_and_boundaries(self):
        p_cookies = _session_cookie(
            UID_PARTICIPANT,
            guilds=[{"id": TEST_GUILD_ID, "permissions": 0}],
            jti="jti-p1",
        )

        def _checks():
            # Privacy masking shows own discord_user_id + is_self=True, masks others
            r_wd = self.client.get(
                f"/api/backups/{TEST_BACKUP_ID}/writers/detailed", cookies=p_cookies
            )
            self.assertEqual(r_wd.status_code, 200)
            by_pk = {w["id"]: w for w in r_wd.json()}
            self.assertTrue(by_pk[self.w1_pk]["is_self"])
            self.assertEqual(by_pk[self.w1_pk]["discord_user_id"], UID_PARTICIPANT)
            self.assertFalse(by_pk[self.w2_pk]["is_self"])
            self.assertIsNone(by_pk[self.w2_pk]["discord_user_id"])

            r_chars_norm = self.client.get(
                f"/api/backups/{TEST_BACKUP_ID}/characters",
                params={"format": "normalized"},
                cookies=p_cookies,
            )
            self.assertEqual(r_chars_norm.status_code, 200)
            norm_by_pk = {w["id"]: w for w in r_chars_norm.json().get("writers", [])}
            self.assertTrue(norm_by_pk[self.w1_pk]["is_self"])
            self.assertEqual(norm_by_pk[self.w1_pk]["discord_user_id"], UID_PARTICIPANT)
            self.assertFalse(norm_by_pk[self.w2_pk]["is_self"])
            self.assertIsNone(norm_by_pk[self.w2_pk]["discord_user_id"])

            # Default legacy /characters payload must also include writer_id so Participant UI shows Edit
            r_chars_legacy = self.client.get(
                f"/api/backups/{TEST_BACKUP_ID}/characters",
                cookies=p_cookies,
            )
            self.assertEqual(r_chars_legacy.status_code, 200)
            legacy_by_id = {c["id"]: c for c in r_chars_legacy.json()}
            self.assertEqual(legacy_by_id[101]["writer_id"], self.w1_pk)
            self.assertEqual(legacy_by_id[102]["writer_id"], self.w1_pk)
            self.assertEqual(legacy_by_id[201]["writer_id"], self.w2_pk)
            self.assertNotEqual(legacy_by_id[301]["writer_id"], self.w1_pk)

            # Curation lockout still applies to participant
            self.assertEqual(
                self.client.get(
                    f"/api/backups/{TEST_BACKUP_ID}/flagged-messages", cookies=p_cookies
                ).status_code,
                403,
            )

            # Self-service PUT /writers/{own} allowed without changing discord_user_id
            r_w_ok = self.client.put(
                f"/api/backups/{TEST_BACKUP_ID}/writers/{self.w1_pk}",
                json={"display_name": "ParticipantUpdated", "discord_user_id": UID_PARTICIPANT},
                cookies=p_cookies,
            )
            self.assertEqual(r_w_ok.status_code, 200)

            # Changing own writer's discord_user_id or updating other writer -> 403
            self.assertEqual(
                self.client.put(
                    f"/api/backups/{TEST_BACKUP_ID}/writers/{self.w1_pk}",
                    json={"discord_user_id": "999999999999999999"},
                    cookies=p_cookies,
                ).status_code,
                403,
            )
            self.assertEqual(
                self.client.put(
                    f"/api/backups/{TEST_BACKUP_ID}/writers/{self.w2_pk}",
                    json={"display_name": "Hijacked"},
                    cookies=p_cookies,
                ).status_code,
                403,
            )

            # Self-service PUT /characters/{own} allowed; writer reassignment -> 403
            self.assertEqual(
                self.client.put(
                    f"/api/backups/{TEST_BACKUP_ID}/characters/101",
                    json={"tags": ["oc", "active"]},
                    cookies=p_cookies,
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.put(
                    f"/api/backups/{TEST_BACKUP_ID}/characters/101",
                    json={"writer": ["OtherWriter"]},
                    cookies=p_cookies,
                ).status_code,
                403,
            )
            # Other user's character and unassigned character -> 403
            self.assertEqual(
                self.client.put(
                    f"/api/backups/{TEST_BACKUP_ID}/characters/201",
                    json={"tags": ["oc", "inactive"]},
                    cookies=p_cookies,
                ).status_code,
                403,
            )
            self.assertEqual(
                self.client.put(
                    f"/api/backups/{TEST_BACKUP_ID}/characters/301",
                    json={"tags": ["oc", "inactive"]},
                    cookies=p_cookies,
                ).status_code,
                403,
            )

            # Nest / unnest own characters -> 200; involving other's character -> 403
            self.assertEqual(
                self.client.post(
                    f"/api/backups/{TEST_BACKUP_ID}/characters/nest",
                    json={"child_id": 102, "parent_id": 101, "version_type": "alter_ego"},
                    cookies=p_cookies,
                ).status_code,
                200,
            )
            r_nested = self.client.get(
                f"/api/backups/{TEST_BACKUP_ID}/characters",
                cookies=p_cookies,
            )
            self.assertEqual(r_nested.status_code, 200)
            nested_parent = {c["id"]: c for c in r_nested.json()}[101]
            self.assertEqual(nested_parent["other_versions"][0]["writer_id"], self.w1_pk)
            self.assertEqual(
                self.client.post(
                    f"/api/backups/{TEST_BACKUP_ID}/characters/102/unnest",
                    cookies=p_cookies,
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.post(
                    f"/api/backups/{TEST_BACKUP_ID}/characters/nest",
                    json={"child_id": 201, "parent_id": 101, "version_type": "alter_ego"},
                    cookies=p_cookies,
                ).status_code,
                403,
            )

            # Curator+ routes denied (403)
            self.assertEqual(
                self.client.post(
                    f"/api/backups/{TEST_BACKUP_ID}/writers",
                    json={"display_name": "NewW"},
                    cookies=p_cookies,
                ).status_code,
                403,
            )
            self.assertEqual(
                self.client.get(
                    f"/api/backups/{TEST_BACKUP_ID}/config", cookies=p_cookies
                ).status_code,
                403,
            )

        self._run_with_env(_checks)

    def test_curator_server_admin_and_instance_admin_boundaries(self):
        curator_cookies = _session_cookie(
            UID_CURATOR,
            guilds=[{"id": TEST_GUILD_ID, "permissions": 0}],
            jti="jti-c1",
        )
        server_admin_cookies = _session_cookie(
            UID_ADMIN,
            guilds=[{"id": TEST_GUILD_ID, "permissions": 0}],
            jti="jti-sa1",
        )
        inst_admin_cookies = _session_cookie(
            INSTANCE_ADMIN_DISCORD_ID,
            guilds=[],
            jti="jti-ia1",
        )

        def _checks():
            # Curator sees unmasked discord_user_ids and curation routes
            r_wd = self.client.get(
                f"/api/backups/{TEST_BACKUP_ID}/writers/detailed", cookies=curator_cookies
            )
            self.assertEqual(r_wd.status_code, 200)
            by_pk = {w["id"]: w for w in r_wd.json()}
            self.assertEqual(by_pk[self.w2_pk]["discord_user_id"], UID_OTHER_WRITER)

            for path in [
                f"/api/backups/{TEST_BACKUP_ID}/curation/summary",
                f"/api/backups/{TEST_BACKUP_ID}/writers/link-suggestions",
                f"/api/backups/{TEST_BACKUP_ID}/characters/unassigned-writers",
                f"/api/backups/{TEST_BACKUP_ID}/scene-issues",
                f"/api/backups/{TEST_BACKUP_ID}/flagged-messages",
                f"/api/backups/{TEST_BACKUP_ID}/message-overrides",
            ]:
                with self.subTest(curator_path=path):
                    self.assertEqual(
                        self.client.get(path, cookies=curator_cookies).status_code, 200
                    )

            # Curator can assign character writer, but cannot access ServerAdmin routes
            self.assertEqual(
                self.client.put(
                    f"/api/backups/{TEST_BACKUP_ID}/characters/301/assign-writer",
                    json={"writer_id": self.w2_pk},
                    cookies=curator_cookies,
                ).status_code,
                200,
            )
            for method, path in [
                ("GET", f"/api/backups/{TEST_BACKUP_ID}/config"),
                ("GET", f"/api/backups/{TEST_BACKUP_ID}/logs"),
                ("GET", f"/api/backups/{TEST_BACKUP_ID}/discord-roles"),
                ("GET", f"/api/backups/{TEST_BACKUP_ID}/rbac"),
            ]:
                self.assertEqual(
                    self.client.request(method, path, cookies=curator_cookies).status_code,
                    403,
                )

            # ServerAdmin accesses config/logs/rbac, denied on InstanceAdmin & archived backups
            self.assertEqual(
                self.client.get(
                    f"/api/backups/{TEST_BACKUP_ID}/config", cookies=server_admin_cookies
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.get(
                    f"/api/backups/{TEST_BACKUP_ID}/logs", cookies=server_admin_cookies
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.get("/api/config/global", cookies=server_admin_cookies).status_code,
                403,
            )
            self.assertEqual(
                self.client.get(
                    f"/api/backups/{ARCHIVED_BACKUP_ID}", cookies=server_admin_cookies
                ).status_code,
                403,
            )

            # InstanceAdmin accesses global config and archived backups
            self.assertEqual(
                self.client.get("/api/config/global", cookies=inst_admin_cookies).status_code,
                200,
            )
            self.assertEqual(
                self.client.get(
                    f"/api/backups/{ARCHIVED_BACKUP_ID}", cookies=inst_admin_cookies
                ).status_code,
                200,
            )

        self._run_with_env(_checks)


class TestDiscordRateLimitHardening(unittest.TestCase):
    """Tests single-flight coalescing, Retry-After backoff, and stale fallback on HTTP 429."""

    def setUp(self):
        server.clear_bot_guilds_cache()
        rbac.clear_rbac_caches()

    def tearDown(self):
        server.clear_bot_guilds_cache()
        rbac.clear_rbac_caches()

    def test_get_live_bot_guilds_single_flight_and_429_stale_backoff(self):
        calls = {"count": 0}
        barrier = threading.Event()

        def fake_get(url, headers=None, timeout=10.0):
            calls["count"] += 1
            if calls["count"] == 1:
                barrier.wait(timeout=0.5)
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = [{"id": TEST_GUILD_ID}]
                return resp
            resp = MagicMock()
            resp.status_code = 429
            resp.headers = {"Retry-After": "12"}
            resp.json.return_value = {"retry_after": 12.0}
            return resp

        with patch.dict(os.environ, {"DISCORD_TOKEN": "bot_tok_sf"}, clear=False):
            with patch.object(server.httpx, "get", side_effect=fake_get):
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                    futures = [pool.submit(server.get_live_bot_guilds) for _ in range(4)]
                    barrier.set()
                    results = [f.result(timeout=2.0) for f in futures]
                self.assertEqual(calls["count"], 1)
                self.assertTrue(all(r == {TEST_GUILD_ID} for r in results))

                # Expire TTL so next call hits 429 -> must return stale guilds and enter backoff
                with server._BOT_GUILDS_CACHE_LOCK:
                    server._BOT_GUILDS_CACHE["expires_at"] = 0.0
                r_stale = server.get_live_bot_guilds()
                r_backoff = server.get_live_bot_guilds()
                self.assertEqual(r_stale, {TEST_GUILD_ID})
                self.assertEqual(r_backoff, {TEST_GUILD_ID})
                self.assertEqual(calls["count"], 2)

                # Cold cache 429 backoff avoids hammering on immediate follow-up
                server.clear_bot_guilds_cache()
                self.assertIsNone(server.get_live_bot_guilds())
                self.assertIsNone(server.get_live_bot_guilds())
                self.assertEqual(calls["count"], 3)

    def test_rbac_role_lookups_single_flight_and_429_stale_backoff(self):
        role_calls = {"count": 0}
        member_calls = {"count": 0}

        def fake_rbac_get(url, headers=None, timeout=10.0):
            resp = MagicMock()
            if url.endswith("/roles"):
                role_calls["count"] += 1
                if role_calls["count"] == 1:
                    time.sleep(0.05)
                    resp.status_code = 200
                    resp.json.return_value = [{"id": ROLE_ADMIN_ID, "name": "Admin", "position": 10, "color": 0}]
                    return resp
                resp.status_code = 429
                resp.headers = {"Retry-After": "10"}
                return resp

            member_calls["count"] += 1
            if member_calls["count"] == 1:
                time.sleep(0.05)
                resp.status_code = 200
                resp.json.return_value = {"roles": [ROLE_PARTICIPANT_ID]}
                return resp
            resp.status_code = 429
            resp.headers = {"Retry-After": "10"}
            return resp

        with patch.object(rbac.httpx, "get", side_effect=fake_rbac_get):
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                role_futs = [pool.submit(rbac.fetch_guild_roles, TEST_GUILD_ID, "tok_rbac") for _ in range(4)]
                mem_futs = [pool.submit(rbac.fetch_guild_member_roles, TEST_GUILD_ID, UID_PARTICIPANT, "tok_rbac") for _ in range(4)]
                role_res = [f.result(timeout=2.0) for f in role_futs]
                mem_res = [f.result(timeout=2.0) for f in mem_futs]
            self.assertEqual(role_calls["count"], 1)
            self.assertEqual(member_calls["count"], 1)
            self.assertTrue(all(ok and len(roles) == 1 for roles, ok in role_res))
            self.assertTrue(all(r == {ROLE_PARTICIPANT_ID} for r in mem_res))

            # Expire TTLs and trigger 429 -> returns stale values and suppresses immediate retry
            with rbac._RBAC_CACHE_LOCK:
                rbac._GUILD_ROLES_CACHE[TEST_GUILD_ID] = (0.0, "tok_rbac", rbac._GUILD_ROLES_CACHE[TEST_GUILD_ID][2])
                key = (TEST_GUILD_ID, UID_PARTICIPANT)
                rbac._MEMBER_ROLES_CACHE[key] = (0.0, "tok_rbac", rbac._MEMBER_ROLES_CACHE[key][2])

            roles_stale, ok_stale = rbac.fetch_guild_roles(TEST_GUILD_ID, "tok_rbac")
            roles_backoff, ok_backoff = rbac.fetch_guild_roles(TEST_GUILD_ID, "tok_rbac")
            mem_stale = rbac.fetch_guild_member_roles(TEST_GUILD_ID, UID_PARTICIPANT, "tok_rbac")
            mem_backoff = rbac.fetch_guild_member_roles(TEST_GUILD_ID, UID_PARTICIPANT, "tok_rbac")
            self.assertTrue(ok_stale and ok_backoff and len(roles_stale) == 1 and len(roles_backoff) == 1)
            self.assertEqual(mem_stale, {ROLE_PARTICIPANT_ID})
            self.assertEqual(mem_backoff, {ROLE_PARTICIPANT_ID})
            self.assertEqual(role_calls["count"], 2)
            self.assertEqual(member_calls["count"], 2)


if __name__ == "__main__":
    unittest.main()

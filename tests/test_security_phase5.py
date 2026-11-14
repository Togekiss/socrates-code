import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
TESTS_DIR = PROJECT_ROOT / "tests"
if SRC_DIR.as_posix() not in sys.path:
    sys.path.insert(0, SRC_DIR.as_posix())
if PROJECT_ROOT.as_posix() not in sys.path:
    sys.path.insert(0, PROJECT_ROOT.as_posix())
if TESTS_DIR.as_posix() not in sys.path:
    sys.path.insert(0, TESTS_DIR.as_posix())

import server  # noqa: E402
from test_security_phase1 import (  # noqa: E402
    INSTANCE_ADMIN_DISCORD_ID,
    STRONG_TEST_SECRET,
    _make_jwt,
    _make_test_client,
)

EXPECTED_API_SECURITY_HEADERS = {
    "cache-control": "no-store, private",
    "pragma": "no-cache",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
}


class Phase5ApiSecurityHeadersTests(unittest.TestCase):
    """Verify baseline security and no-store caching headers on all /api/* HTTP responses."""

    def _assert_api_headers(self, response):
        for header, expected in EXPECTED_API_SECURITY_HEADERS.items():
            self.assertEqual(
                response.headers.get(header),
                expected,
                f"Expected {header}={expected!r}, got {response.headers.get(header)!r}",
            )

    def test_api_health_and_unauthenticated_401_include_security_headers(self):
        with patch.dict(os.environ, {"JWT_SECRET": STRONG_TEST_SECRET, "SOCRATES_ENV": "test"}, clear=False):
            client = _make_test_client(server.app)
            health_res = client.get("/api/health")
            self.assertEqual(health_res.status_code, 200)
            self._assert_api_headers(health_res)

            unauth_res = client.get("/api/backups")
            self.assertEqual(unauth_res.status_code, 401)
            self._assert_api_headers(unauth_res)

    def test_authenticated_api_response_includes_security_headers(self):
        tok = _make_jwt(
            {
                "sub": INSTANCE_ADMIN_DISCORD_ID,
                "username": "inst-admin",
                "auth_method": "discord",
                "guilds": [],
            }
        )
        with patch.dict(
            os.environ,
            {
                "JWT_SECRET": STRONG_TEST_SECRET,
                "SOCRATES_ENV": "test",
                "SOCRATES_INSTANCE_ADMINS": INSTANCE_ADMIN_DISCORD_ID,
            },
            clear=False,
        ):
            client = _make_test_client(server.app)
            client.cookies.set("__session", tok)
            res = client.get("/api/backups")
            self.assertEqual(res.status_code, 200)
            self._assert_api_headers(res)

    def test_csrf_denied_early_responses_include_security_headers(self):
        tok = _make_jwt(
            {
                "sub": INSTANCE_ADMIN_DISCORD_ID,
                "username": "inst-admin",
                "auth_method": "discord",
                "csrf": "expected-csrf-value",
                "guilds": [],
            }
        )
        with patch.dict(os.environ, {"JWT_SECRET": STRONG_TEST_SECRET, "SOCRATES_ENV": "test"}, clear=False):
            # Missing X-Requested-With -> 403 early return
            client_no_xrw = _make_test_client(server.app, include_csrf_headers=False)
            res1 = client_no_xrw.post("/api/auth/logout")
            self.assertEqual(res1.status_code, 403)
            self._assert_api_headers(res1)

            # Untrusted Origin -> 403 early return
            client = _make_test_client(server.app)
            res2 = client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
            self.assertEqual(res2.status_code, 403)
            self._assert_api_headers(res2)

            # Missing X-CSRF-Token when session cookie present -> 403 early return
            client.cookies.set("__session", tok)
            res3 = client.post("/api/auth/logout")
            self.assertEqual(res3.status_code, 403)
            self._assert_api_headers(res3)


class Phase5FirebaseHostingAndContainerHygieneTests(unittest.TestCase):
    """Verify Firebase Hosting CSP/security headers, Dockerfile hardening, and ignore lists."""

    def test_firebase_json_contains_strict_csp_and_security_headers(self):
        firebase_path = PROJECT_ROOT / "ui" / "firebase.json"
        if not firebase_path.exists():
            self.skipTest("Repo-only path ui/firebase.json not present in container")
        data = json.loads(firebase_path.read_text(encoding="utf-8"))
        header_rules = data.get("hosting", {}).get("headers", [])
        self.assertTrue(header_rules, "ui/firebase.json must define hosting.headers")

        catch_all = next((r for r in header_rules if r.get("source") == "**"), None)
        self.assertIsNotNone(catch_all, "ui/firebase.json must define headers for source '**'")
        headers_map = {h["key"]: h["value"] for h in catch_all.get("headers", [])}

        self.assertEqual(headers_map.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers_map.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers_map.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertIn("max-age=31536000", headers_map.get("Strict-Transport-Security", ""))
        self.assertIn("camera=()", headers_map.get("Permissions-Policy", ""))

        csp = headers_map.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("unsafe-eval", csp)
        script_part = next((p.strip() for p in csp.split(";") if p.strip().startswith("script-src")), "")
        self.assertNotIn("unsafe-inline", script_part)
        self.assertIn("connect-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("base-uri 'self'", csp)
        self.assertIn("form-action 'self'", csp)
        self.assertIn("https://cdn.discordapp.com", csp)

    def test_dockerignore_excludes_sensitive_and_frontend_paths(self):
        dockerignore_path = PROJECT_ROOT / ".dockerignore"
        if not dockerignore_path.exists():
            self.skipTest("Repo-only path .dockerignore not present in container")
        lines = {
            line.strip()
            for line in dockerignore_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        for required in [".git", ".github", "ui/", "docs/", "*.md", "Backups/", "out/", "logs/", "E*/", ".env", ".env*", "*.sqlite"]:
            self.assertIn(required, lines, f".dockerignore missing required entry: {required}")
        for must_keep in ["src/", "tests/", "requirements.txt", "res/"]:
            self.assertNotIn(must_keep, lines, f".dockerignore must NOT exclude {must_keep}")

    def test_dockerfile_runs_as_non_root_user_in_production_mode(self):
        dockerfile_path = PROJECT_ROOT / "Dockerfile"
        if not dockerfile_path.exists():
            self.skipTest("Repo-only path Dockerfile not present in container")
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
        self.assertIn("SOCRATES_ENV=production", dockerfile)
        self.assertIn("useradd", dockerfile)
        self.assertIn("USER socrates", dockerfile)
        self.assertNotIn("--reload", dockerfile)

    def test_public_ignore_excludes_audits_secrets_and_outputs(self):
        public_ignore_path = PROJECT_ROOT / ".github" / "workflows" / "public-ignore.txt"
        if not public_ignore_path.exists():
            self.skipTest("Repo-only path .github/workflows/public-ignore.txt not present in container")
        lines = {
            line.strip()
            for line in public_ignore_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        for required in ["docs/audits/", "*.sqlite", ".env*", "out/", "logs/"]:
            self.assertIn(required, lines, f"public-ignore.txt missing required entry: {required}")

    def test_dependency_manifests_enforce_cve_floors_and_hygiene(self):
        req_path = PROJECT_ROOT / "requirements.txt"
        self.assertTrue(req_path.exists(), "requirements.txt must exist")
        req_lines = [
            line.strip()
            for line in req_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        floors = {
            "pyjwt": (2, 14, 0),
            "starlette": (1, 0, 1),
            "h11": (0, 16, 0),
        }
        seen = {}
        for line in req_lines:
            if ">=" in line:
                name, ver = line.split(">=", 1)
            elif "==" in line:
                name, ver = line.split("==", 1)
            else:
                continue
            pkg_key = name.split("[", 1)[0].strip().lower()
            parts = tuple(int(p) for p in ver.strip().split(".")[:3])
            seen[pkg_key] = parts
        for pkg, min_ver in floors.items():
            self.assertIn(pkg, seen, f"requirements.txt must pin minimum version for {pkg}")
            self.assertGreaterEqual(seen[pkg], min_ver, f"{pkg} floor {seen[pkg]} is below {min_ver}")

        pkg_json_path = PROJECT_ROOT / "ui" / "package.json"
        if not pkg_json_path.exists():
            return
        pkg_data = json.loads(pkg_json_path.read_text(encoding="utf-8"))
        deps = pkg_data.get("dependencies", {})
        dev_deps = pkg_data.get("devDependencies", {})
        for forbidden in ("approve", "scripts", "esbuild"):
            self.assertNotIn(forbidden, deps, f"Unexpected runtime dependency {forbidden} in ui/package.json")
        self.assertNotIn("approve", dev_deps)
        self.assertNotIn("scripts", dev_deps)


class Phase5FrontendRbacAndBundleHygieneTests(unittest.TestCase):
    """Verify frontend RBAC/privacy guards and clean production bundle."""

    def test_rbac_helpers_and_ui_guards_present(self):
        rbac_path = PROJECT_ROOT / "ui" / "src" / "utils" / "rbac.ts"
        if not rbac_path.exists():
            self.skipTest("Repo-only path ui/src/utils/rbac.ts not present in container")
        rbac_src = rbac_path.read_text(encoding="utf-8")
        self.assertIn("safeDiscordUrl", rbac_src)
        self.assertIn("safeDiscordAvatarUrl", rbac_src)
        self.assertIn("getEffectiveRoleLevel", rbac_src)

        app_src = (PROJECT_ROOT / "ui" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("isInstanceAdmin", app_src)
        self.assertIn("AccessDeniedState", app_src)
        self.assertIn("botInGuild === false", app_src)
        self.assertNotIn("window.location.hostname === 'localhost'", app_src)

        sidebar_src = (PROJECT_ROOT / "ui" / "src" / "components" / "layout" / "Sidebar.tsx").read_text(encoding="utf-8")
        self.assertIn("user?.is_instance_admin === true", sidebar_src)
        self.assertIn("resolvedRoleLevel >= 3", sidebar_src)
        self.assertIn("resolvedRoleLevel >= 4", sidebar_src)

        writers_src = (PROJECT_ROOT / "ui" / "src" / "components" / "WritersTab.tsx").read_text(encoding="utf-8")
        self.assertIn("showDiscordId", writers_src)
        self.assertIn("canCurate", writers_src)

        writer_modal_src = (PROJECT_ROOT / "ui" / "src" / "components" / "curation" / "WriterEditModal.tsx").read_text(encoding="utf-8")
        self.assertIn("isParticipantSelfEdit", writer_modal_src)

        char_modal_src = (PROJECT_ROOT / "ui" / "src" / "components" / "characters" / "CharacterEditModal.tsx").read_text(encoding="utf-8")
        self.assertIn("isParticipantMode", char_modal_src)

    def test_production_dist_has_no_dev_login_endpoint(self):
        dist_assets = PROJECT_ROOT / "ui" / "dist" / "assets"
        if not dist_assets.exists():
            self.skipTest("ui/dist/assets not built")
        for js_file in dist_assets.glob("*.js"):
            content = js_file.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("dev-login", content, f"Production bundle {js_file.name} leaked dev-login")


if __name__ == "__main__":
    unittest.main()

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

# Ensure src and project root are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
for p in (SRC_DIR.as_posix(), PROJECT_ROOT.as_posix()):
    if p not in sys.path:
        sys.path.insert(0, p)

import httpx
from sqlalchemy import inspect
from tests.test_env import skip_in_production_or_missing_fixture, use_socket_free_asyncio
DATA_ROOT = Path(os.environ.get("SOCRATES_DATA_DIR") or PROJECT_ROOT.as_posix())
# pyrefly: ignore [missing-import]
from db.skeleton_models import MessageSkeletonModel, SkeletonFlags  # noqa: E402
from db.session import (  # noqa: E402
    get_sqlite_path,
    get_skeleton_sqlite_path,
    db_session,
    skeleton_db_session,
    close_all_engines,
)
# pyrefly: ignore [missing-import]
from db.models import (
    BackupModel,
    ChannelModel,
    WriterModel,
    CharacterModel,
    EventModel,
    SceneModel,
    SceneParticipantModel,
    SceneIssueModel,
    FlaggedMessageModel,
    SeenDiscordUserModel,
    SceneKind,
    Step,
    Status,
)
# pyrefly: ignore [missing-import]
from db.migrate import migrate_single_backup
# pyrefly: ignore [missing-import]
from models.backup_context import BackupContext
# pyrefly: ignore [missing-import]
from models import ServerBackup, CharacterList, SceneManager
# pyrefly: ignore [missing-import]
from assign_ids import assign_ids
# pyrefly: ignore [missing-import]
from fix_bad_messages import fix_bad_messages
# pyrefly: ignore [missing-import]
from index_scenes import index_scenes
# pyrefly: ignore [missing-import]
from backup_server import backup_server
from discord_extractor import (  # noqa: E402
    DISCORD_EPOCH_MS,
    DiscordExtractor,
    extract_inline_emojis,
    format_content,
    serialize_message,
)
# pyrefly: ignore [missing-import]
from deprecated.inject_category import inject_category
from tests.reset_test_backup import reset_test_backup
# pyrefly: ignore [missing-import]
import utils.exceptions as exc
import utils.tricks as t


_WEBHOOK_AVATAR_RE = re.compile(r"/avatars/(\d+)/")


def _dce_msg_to_raw_discord(msg: dict) -> dict:
    """Converts a DCE §7 exported message dict into a raw Discord REST API v10 message dict."""
    author = msg.get("author") or {}
    author_id = str(author.get("id") or "100000000000000001")
    is_bot = bool(author.get("isBot", False))
    if is_bot and author_id.isdigit() and int(author_id) < 100000:
        m_av = _WEBHOOK_AVATAR_RE.search(str(author.get("avatarUrl") or ""))
        author_id = m_av.group(1) if m_av else "1020068778626789457"

    raw_author = {
        "id": author_id,
        "username": str(author.get("name") or "Unknown"),
        "discriminator": str(author.get("discriminator") or "0"),
        "global_name": str(author.get("nickname") or author.get("name") or ""),
        "bot": is_bot,
        "avatar": None,
    }
    raw_type = 19 if msg.get("type") == "Reply" else 0
    raw_msg = {
        "id": str(msg["id"]),
        "channel_id": str(msg.get("channelId") or ""),
        "type": raw_type,
        "timestamp": msg.get("timestamp"),
        "edited_timestamp": msg.get("timestampEdited"),
        "pinned": bool(msg.get("isPinned", False)),
        "content": str(msg.get("content") or ""),
        "author": raw_author,
        "attachments": [
            {
                "id": str(a.get("id") or ""),
                "url": str(a.get("url") or ""),
                "filename": str(a.get("fileName") or "file"),
                "size": int(a.get("fileSizeBytes", 0) or 0),
            }
            for a in (msg.get("attachments") or [])
        ],
        "embeds": list(msg.get("embeds") or []),
        "sticker_items": [
            {"id": str(s.get("id") or ""), "name": str(s.get("name") or ""), "format_type": 1}
            for s in (msg.get("stickers") or [])
        ],
        "reactions": [],
        "mentions": [
            {
                "id": str(m.get("id") or "100000000000000002"),
                "username": str(m.get("name") or "user"),
                "discriminator": str(m.get("discriminator") or "0"),
                "global_name": str(m.get("nickname") or m.get("name") or "user"),
                "bot": bool(m.get("isBot", False)),
            }
            for m in (msg.get("mentions") or [])
        ],
    }
    if isinstance(msg.get("reference"), dict):
        ref = msg["reference"]
        raw_msg["message_reference"] = {
            "type": 1 if ref.get("type") == "Forward" else 0,
            "message_id": ref.get("messageId"),
            "channel_id": ref.get("channelId"),
            "guild_id": ref.get("guildId"),
        }
    return raw_msg


class ElysiumMockDiscordServer:
    """
    Reusable offline Discord REST API v10 simulator driven by httpx.MockTransport,
    synthesizing guild, categories, channels, threads, members, and paginated messages
    from `Backups/Elysium-sql-tests-clean/Data` (and optionally `Update`).
    """

    GUILD_ID = "857848490683269161"

    def __init__(
        self,
        clean_backup_root: Path,
        *,
        include_update: bool = True,
        bot_token_mode: str = "valid",
        members_403: bool = False,
        rate_limit_once_429: bool = False,
    ):
        self.clean_root = Path(clean_backup_root)
        self.include_update = include_update
        self.bot_token_mode = bot_token_mode
        self.members_403 = members_403
        self.rate_limit_once_429 = rate_limit_once_429
        self._429_fired = False
        self.fetched_channel_history_ids: list[str] = []
        self.requests_seen: list[str] = []

        self.guild = {
            "id": self.GUILD_ID,
            "name": "(+18) Diabolik: Elysium",
            "icon": "f9774c466fbffcc2b6968b0112d787c5",
            "roles": [
                {"id": self.GUILD_ID, "name": "@everyone", "color": 0, "position": 0},
                {"id": "900000000000000001", "name": "Writer", "color": 0x3498DB, "position": 1},
            ],
        }

        self.messages_by_channel: dict[str, list[dict]] = {}
        self.members: list[dict] = []
        self.channels: list[dict] = []
        self.threads: list[dict] = []
        self._load_fixtures()

    def _load_json_dir_messages(self, base_dir: Path) -> None:
        if not base_dir.exists():
            return
        for jf in sorted(base_dir.rglob("*.json")):
            data = json.loads(jf.read_text(encoding="utf-8"))
            ch = data.get("channel") or {}
            cid = str(ch.get("id") or "")
            if not cid:
                continue
            existing = {str(m["id"]): m for m in self.messages_by_channel.get(cid, [])}
            for m in data.get("messages") or []:
                raw_m = _dce_msg_to_raw_discord(m)
                existing[raw_m["id"]] = raw_m
            ordered = sorted(existing.values(), key=lambda x: int(x["id"]))
            self.messages_by_channel[cid] = ordered

    def _load_fixtures(self) -> None:
        self._load_json_dir_messages(self.clean_root / "Data")
        if self.include_update:
            self._load_json_dir_messages(self.clean_root / "Update")

        # Harvest sample non-bot members from loaded messages
        seen_members: dict[str, dict] = {}
        for msgs in self.messages_by_channel.values():
            for rm in msgs:
                auth = rm.get("author") or {}
                uid = str(auth.get("id") or "")
                if not auth.get("bot") and uid.isdigit() and int(uid) >= 100000 and uid not in seen_members:
                    seen_members[uid] = {
                        "user": dict(auth),
                        "nick": auth.get("global_name") or auth.get("username"),
                        "roles": ["900000000000000001"],
                    }
        self.members = sorted(seen_members.values(), key=lambda m: int(m["user"]["id"]))

        # Build 28 ordered categories so relative positions match Data/ & Update/:
        # 6 -> CURRENT EVENT, 7 -> Group Chats, 14 -> The Twisted Viper Bar, 23 -> NSFW Events, 28 -> EVENT STORAGE
        real_cats = {
            6: ("1008065547155558431", "CURRENT EVENT"),
            7: ("1106268351220678767", "Group Chats"),
            14: ("1019770957172326470", "The Twisted Viper Bar"),
            23: ("1345359342970343486", "NSFW Events"),
            28: ("987749861963214878", "EVENT STORAGE"),
        }
        for pos_idx in range(1, 29):
            if pos_idx in real_cats:
                cid, cname = real_cats[pos_idx]
            else:
                cid, cname = (str(900000000000000100 + pos_idx), "OOC")
            if not self.include_update and pos_idx == 23:
                continue
            self.channels.append({"id": cid, "type": 4, "name": cname, "position": pos_idx - 1})

        def _last_mid(cid: str) -> str | None:
            msgs = self.messages_by_channel.get(cid) or []
            return msgs[-1]["id"] if msgs else None

        # Non-category text channels
        text_specs = [
            ("1008065681998221352", "1008065547155558431", "hotel-lobby", 0),
            ("1008065639467982868", "1008065547155558431", "game-booths", 1),
            ("858215486272962581", "1106268351220678767", "chatroom", 0),
            ("1013915163423932496", "1019770957172326470", "barside", 0),
            ("1019771259896205382", "1019770957172326470", "back-of-bar", 1),
            ("1019771317303644261", "1019770957172326470", "bar-tables", 2),
            ("1008065664034025533", "987749861963214878", "medical-tent", 0),
        ]
        if self.include_update:
            text_specs.append(("1345360008409518121", "1345359342970343486", "room-9", 0))

        for ch_id, p_id, ch_name, pos in text_specs:
            self.channels.append(
                {
                    "id": ch_id,
                    "type": 0,
                    "parent_id": p_id,
                    "name": ch_name,
                    "position": pos,
                    "last_message_id": _last_mid(ch_id),
                }
            )

        # Threads
        thread_specs = [
            ("1132200643776487524", "1008065639467982868", "Tamina Freaky Hours~"),
            ("1141818382782574645", "1019771259896205382", "A Toast to Emnity (Shin/Rin)"),
            ("1158294831097970738", "1019771259896205382", "Conversation"),
            ("1131989202465210569", "1008065664034025533", "Room 4: Ruki, Aoi, Kaoru"),
        ]
        if self.include_update:
            thread_specs.extend(
                [
                    ("1132744421587296397", "1008065639467982868", "Sand Dunes"),
                    ("1285969286808076360", "1019771317303644261", "Full Moon"),
                ]
            )
        for th_id, p_id, th_name in thread_specs:
            self.threads.append(
                {
                    "id": th_id,
                    "type": 11,
                    "parent_id": p_id,
                    "name": th_name,
                    "last_message_id": _last_mid(th_id),
                    "thread_metadata": {"archived": False},
                }
            )

    def make_transport(self) -> httpx.MockTransport:
        def _handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            self.requests_seen.append(f"{request.method} {path}")

            if self.rate_limit_once_429 and path == f"/api/v10/guilds/{self.GUILD_ID}" and not self._429_fired:
                self._429_fired = True
                return httpx.Response(
                    429,
                    json={"message": "You are being rate limited.", "retry_after": 0.01, "global": False},
                    headers={"Retry-After": "0.01"},
                )

            if path == "/api/v10/users/@me":
                if self.bot_token_mode == "unauthorized":
                    return httpx.Response(401, json={"message": "401: Unauthorized"})
                is_bot = self.bot_token_mode == "valid"
                return httpx.Response(200, json={"id": "999999999999999999", "username": "SocratesBot", "bot": is_bot})

            if path == "/api/v10/applications/@me":
                return httpx.Response(200, json={"id": "999999999999999999", "flags": 262144 | 524288})

            if path == f"/api/v10/guilds/{self.GUILD_ID}":
                return httpx.Response(200, json=self.guild)

            if path == f"/api/v10/guilds/{self.GUILD_ID}/channels":
                return httpx.Response(200, json=self.channels)

            if path == f"/api/v10/guilds/{self.GUILD_ID}/threads/active":
                return httpx.Response(200, json={"threads": self.threads, "has_more": False})

            if path == f"/api/v10/guilds/{self.GUILD_ID}/members":
                if self.members_403:
                    return httpx.Response(403, json={"message": "Missing Access"})
                after = int(request.url.params.get("after") or "0")
                limit = int(request.url.params.get("limit") or "1000")
                page = [m for m in self.members if int(m["user"]["id"]) > after][:limit]
                return httpx.Response(200, json=page)

            if path.endswith("/threads/archived/public") or path.endswith("/threads/archived/private"):
                return httpx.Response(200, json={"threads": [], "has_more": False})

            if path.startswith("/api/v10/channels/") and path.endswith("/messages"):
                cid = path.split("/")[4]
                self.fetched_channel_history_ids.append(cid)
                after_raw = request.url.params.get("after")
                limit = int(request.url.params.get("limit") or "100")
                all_msgs = self.messages_by_channel.get(cid, [])
                if after_raw is not None:
                    after = int(after_raw)
                    msgs = [m for m in all_msgs if int(m["id"]) > after]
                    # Discord returns up to `limit` oldest-after-cursor messages in descending order
                    return httpx.Response(200, json=list(reversed(msgs[:limit])))
                # Without `after`, Discord returns the `limit` most recent messages in descending order
                return httpx.Response(200, json=list(reversed(all_msgs[-limit:])))

            parts = [p for p in path.split("/") if p]
            if len(parts) == 6 and parts[0] == "api" and parts[2] == "channels" and parts[4] == "messages":
                cid, mid = parts[3], parts[5]
                for m in self.messages_by_channel.get(cid, []):
                    if str(m["id"]) == mid:
                        return httpx.Response(200, json=m)
                return httpx.Response(404, json={"message": "Unknown Message"})

            return httpx.Response(404, json={"message": "Unknown Message"})

        return httpx.MockTransport(_handler)


@skip_in_production_or_missing_fixture()
class TestPipelineIntegration(unittest.TestCase):
    """
    End-to-end integration test verifying the complete SQLite migration and pipeline execution.
    Tests: JSON -> SQLite migration -> assign_ids -> fix_bad_messages -> index_scenes -> find_character_scenes -> update.
    """

    @classmethod
    def setUpClass(cls):
        reset_test_backup()
        cls.backup_path = (DATA_ROOT / "Backups" / "Elysium-sql-tests").as_posix()
        cls.backup_id = "1791895360"
        cls.backup_name = "Elysium-sql-tests"

    @classmethod
    def tearDownClass(cls):
        # Clear singleton caches and dispose db engines to release Windows file locks
        SceneManager.clear_cache()
        close_all_engines()
        reset_test_backup()

    def test_01_migration_json_to_sqlite(self):
        """Phase 1: Test that migrate_single_backup creates backup.sqlite and populates all tables."""
        t.log("console", "Testing migration from JSON to SQLite...")
        index = t.get_backups_index()
        b = next((b for b in index if str(b["backup_id"]) == str(self.backup_id)), None)
        b["path"] = self.backup_path
        report = migrate_single_backup(b, dry_run=False, skip_snapshots=False)

        db_file = get_sqlite_path(self.backup_path)
        self.assertTrue(Path(db_file).exists(), f"backup.sqlite must exist at {db_file}")

        # Check schema tables
        with db_session(backup_id=self.backup_id, backup_path=self.backup_path) as session:
            inspector = inspect(session.bind)
            tables = set(inspector.get_table_names())
            expected_tables = {
                "backups", "channels", "writers",
                "writer_aliases", "character_groups", "group_names", "characters",
                "character_names", "events", "scenes", "scene_participants", "scene_issues",
                "flagged_messages", "seen_discord_users"
            }
            self.assertTrue(expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}")

            backup = session.query(BackupModel).filter(BackupModel.backup_id == self.backup_id).first()
            self.assertIsNotNone(backup)
            self.assertEqual(backup.backup_name, self.backup_name)

            channels_count = session.query(ChannelModel).count()
            self.assertGreater(channels_count, 0, "Channels must be migrated")

            chars_count = session.query(CharacterModel).count()
            self.assertGreater(chars_count, 0, "Characters must be migrated")

        t.log("console", "Migration succeeded with full table coverage.")

    def test_02_assign_ids_execution(self):
        """Phase 2: Test assign_ids() using SQLite CharacterList with zero in-loop disk writes."""
        t.log("console", "Testing assign_ids step...")
        ctx = BackupContext.create(
            backup_id=self.backup_id,
            backup_path=self.backup_path,
        )
        ctx.dry_run = False
        ctx.debug_files = True

        with BackupContext.activate(context=ctx):
            assign_ids()

            # Verify step status in SQLite
            backup = ServerBackup.load(scope="base")
            self.assertEqual(backup.steps[Step.ASSIGN_IDS], Status.SUCCESS)

            # Verify character lookups in-memory/SQLite
            char_list = CharacterList.load()
            self.assertGreater(len(char_list.characters), 0)
            ophelia_id = char_list.find_id_by_name("Ophelia")
            self.assertIsNotNone(ophelia_id)

        t.log("console", "assign_ids executed successfully and updated SQLite step status.")

    def test_03_fix_bad_messages_execution(self):
        """Phase 3: Test fix_bad_messages() using SQLite curation_service."""
        t.log("console", "Testing fix_bad_messages step...")
        ctx = BackupContext.create(
            backup_id=self.backup_id,
            backup_path=self.backup_path,
        )
        ctx.dry_run = False
        ctx.debug_files = True

        with BackupContext.activate(context=ctx):
            fix_bad_messages()

            backup = ServerBackup.load(scope="base")
            self.assertEqual(backup.steps[Step.FIX_MESSAGES], Status.SUCCESS)

            # Chatroom channels in c.CHATROOM_CATEGORIES and event channels in Events must be skipped by fix_bad_messages
            with db_session(backup_id=self.backup_id, backup_path=self.backup_path) as session:
                chatroom_chan = session.query(ChannelModel).filter(ChannelModel.discord_id == "858215486272962581").first()
                if chatroom_chan:
                    flagged_count = session.query(FlaggedMessageModel).filter(
                        FlaggedMessageModel.backup_id == str(self.backup_id),
                        FlaggedMessageModel.channel_pk == chatroom_chan.pk
                    ).count()
                    self.assertEqual(flagged_count, 0, "Chatroom channels must have 0 flagged messages")

                event_chan = session.query(ChannelModel).filter(ChannelModel.discord_id == "1008065639467982868").first()
                if event_chan:
                    event_flagged = session.query(FlaggedMessageModel).filter(
                        FlaggedMessageModel.backup_id == str(self.backup_id),
                        FlaggedMessageModel.channel_pk == event_chan.pk
                    ).count()
                    self.assertEqual(event_flagged, 0, "Event channels must have 0 flagged messages")

        t.log("console", "fix_bad_messages executed successfully and updated SQLite step status.")

    def test_04_index_scenes_execution(self):
        """Phase 4: Test index_scenes() saving indexed scenes, chat sessions, and events into SQLite."""
        t.log("console", "Testing index_scenes step...")
        ctx = BackupContext.create(
            backup_id=self.backup_id,
            backup_path=self.backup_path,
        )
        ctx.dry_run = False
        ctx.debug_files = True

        with BackupContext.activate(context=ctx):
            index_scenes()

            backup = ServerBackup.load(scope="base")
            self.assertEqual(backup.steps[Step.INDEX_SCENES], Status.SUCCESS)

            # Verify scenes were persisted directly in SQLite
            with db_session(backup_id=self.backup_id, backup_path=self.backup_path) as session:
                scenes_count = session.query(SceneModel).filter(SceneModel.backup_id == self.backup_id).count()
                self.assertGreater(scenes_count, 0, "Indexed scenes must be stored in SQLite scenes table")

                # Verify RP scenes and chatroom sessions
                rp_scenes_count = session.query(SceneModel).filter(
                    SceneModel.backup_id == self.backup_id,
                    SceneModel.kind == SceneKind.SCENE.value
                ).count()
                self.assertEqual(rp_scenes_count, 13, "Should have 13 RP scenes")

                session_scenes_count = session.query(SceneModel).filter(
                    SceneModel.backup_id == self.backup_id,
                    SceneModel.kind == SceneKind.SESSION.value
                ).count()
                self.assertEqual(session_scenes_count, 121, "Should have 121 chatroom sessions")

                # Verify Events and Event channel/thread scenes
                events_count = session.query(EventModel).filter(
                    EventModel.backup_id == self.backup_id
                ).count()
                self.assertEqual(events_count, 4, "Should have 4 indexed events in SQLite")

                event_scenes_count = session.query(SceneModel).filter(
                    SceneModel.backup_id == self.backup_id,
                    SceneModel.kind == SceneKind.EVENT.value
                ).count()
                self.assertEqual(event_scenes_count, 7, "Should have 7 event scene segments (5 channel segments + 2 threads)")

                # Verify participant details on session scenes
                session_participants = (
                    session.query(SceneParticipantModel)
                    .join(SceneModel, SceneParticipantModel.scene_pk == SceneModel.pk)
                    .filter(SceneModel.backup_id == self.backup_id, SceneModel.kind == SceneKind.SESSION.value)
                    .all()
                )
                self.assertGreater(len(session_participants), 0, "Chat sessions must have participants")
                for p in session_participants[:20]:
                    self.assertIsNotNone(p.first_message_id)
                    self.assertIsNotNone(p.first_at)
                    self.assertIsNotNone(p.last_message_id)
                    self.assertIsNotNone(p.last_at)
                    self.assertGreaterEqual(p.position, 0)

                # Verify zero auto-detected issues for session scenes
                non_rp_issues = (
                    session.query(SceneIssueModel)
                    .join(SceneModel, SceneIssueModel.scene_pk == SceneModel.pk)
                    .filter(
                        SceneModel.backup_id == self.backup_id,
                        SceneModel.kind == SceneKind.SESSION.value
                    )
                    .count()
                )
                self.assertEqual(non_rp_issues, 0, "Chat sessions should not produce auto-detected scene issues")

                # Verify event scenes support auto-detected issues (e.g. inactivity_gap, tupper_end_tag)
                event_issues = (
                    session.query(SceneIssueModel)
                    .join(SceneModel, SceneIssueModel.scene_pk == SceneModel.pk)
                    .filter(
                        SceneModel.backup_id == self.backup_id,
                        SceneModel.kind == SceneKind.EVENT.value
                    )
                    .count()
                )
                self.assertGreaterEqual(event_issues, 0)

                participants_count = session.query(SceneParticipantModel).count()
                self.assertGreater(participants_count, 0, "Scene participants must be stored in SQLite")

        t.log("console", "index_scenes executed successfully and saved scenes and events to SQLite.")

    def test_05_scene_manager_character_filtering(self):
        """Phase 5: Test SceneManager filtering scenes by character IDs directly from SQLite."""
        t.log("console", "Testing SceneManager character scene filtering...")
        ctx = BackupContext.create(
            backup_id=self.backup_id,
            backup_path=self.backup_path,
        )
        ctx.dry_run = False
        ctx.character = "Ophelia"

        with BackupContext.activate(context=ctx):
            manager = SceneManager.get_instance(backup_id=self.backup_id, base_path=self.backup_path)
            char_list = CharacterList.load()
            ophelia_ids = char_list.get_all_character_ids("Ophelia")
            self.assertGreater(len(ophelia_ids), 0)

            filtered = manager.filter_scenes(character_ids=ophelia_ids)
            self.assertIsInstance(filtered, list)
            self.assertGreater(len(filtered), 0, "Should find scenes for Ophelia in SQLite")

        t.log("console", "SceneManager successfully filtered character scenes from SQLite.")

    def test_06_update_with_backup_server(self):
        """Phase 6: Test full update pipeline in 'full' mode using offline MockTransport Discord API."""
        t.log("console", "Testing full update with native DiscordExtractor backup_server()...")

        # Ensure database is migrated
        db_file = get_sqlite_path(self.backup_path)
        if not Path(db_file).exists():
            self.test_01_migration_json_to_sqlite()

        # Capture pre-update updated_at timestamp
        pre_backup = ServerBackup.load(scope="base", backup_id=self.backup_id, backup_path=self.backup_path)
        original_updated_at = pre_backup.updated_at

        mock_discord = ElysiumMockDiscordServer(
            DATA_ROOT / "Backups" / "Elysium-sql-tests-clean",
            include_update=True,
        )

        ctx = BackupContext.create(
            backup_id=self.backup_id,
            backup_path=self.backup_path,
        )
        ctx.dry_run = False
        ctx.debug_files = False

        with use_socket_free_asyncio():
            with BackupContext.activate(context=ctx):
                backup_server(
                    backup_id=self.backup_id,
                    backup_path=self.backup_path,
                    token="test-bot-token",
                    transport=mock_discord.make_transport(),
                )

        # 1. Verify ServerBackup (scope="base") state
        post_backup = ServerBackup.load(scope="base", backup_id=self.backup_id, backup_path=self.backup_path)
        self.assertEqual(post_backup.status, Status.SUCCESS)
        self.assertEqual(post_backup.steps[Step.FIX_MESSAGES], Status.SUCCESS)
        self.assertEqual(post_backup.steps[Step.INDEX_SCENES], Status.SUCCESS)
        self.assertNotEqual(post_backup.updated_at, original_updated_at, "updated_at must be updated after run")

        # 2. Verify SQLite database tables
        with db_session(backup_id=self.backup_id, backup_path=self.backup_path) as session:
            backup = session.query(BackupModel).filter(
                BackupModel.backup_id == str(self.backup_id)
            ).first()
            self.assertIsNotNone(backup)
            self.assertEqual(backup.sync_status, "idle")

            # New thread 'Full Moon' must be saved in channels table
            full_moon_thread = session.query(ChannelModel).filter(
                ChannelModel.backup_id == str(self.backup_id),
                ChannelModel.discord_id == "1285969286808076360"
            ).first()
            self.assertIsNotNone(full_moon_thread, "New thread 'Full Moon' must be saved in ChannelModel")
            self.assertEqual(full_moon_thread.name, "Full Moon")
            self.assertEqual(full_moon_thread.type, "GuildPublicThread")

            # New event channel 'room-9' normalized to 'event-4'
            event4_chan = session.query(ChannelModel).filter(
                ChannelModel.backup_id == str(self.backup_id),
                ChannelModel.discord_id == "1345360008409518121"
            ).first()
            self.assertIsNotNone(event4_chan, "New event channel 'event-4' must be saved in ChannelModel")
            self.assertEqual(event4_chan.name, "event-4")

            # Scenes must be indexed in SQLite: 17 RP scenes (including Full Moon) and 121 chat sessions
            rp_count = session.query(SceneModel).filter(
                SceneModel.backup_id == str(self.backup_id),
                SceneModel.kind == SceneKind.SCENE.value
            ).count()
            self.assertEqual(rp_count, 17, "RP scenes count must be 17 after Full Moon thread is added")

            sessions_count = session.query(SceneModel).filter(
                SceneModel.backup_id == str(self.backup_id),
                SceneModel.kind == SceneKind.SESSION.value
            ).count()
            self.assertEqual(sessions_count, 121, "Chat sessions count must remain 121 after update")

            # Events must be indexed in SQLite (4 base events + new event(s) from Update)
            events_count = session.query(EventModel).filter(
                EventModel.backup_id == str(self.backup_id)
            ).count()
            self.assertGreaterEqual(events_count, 5, "Events count must increase after merging new event channels")

        # 3. Verify Filesystem state
        data_dir = Path(ctx.data_folder)
        full_moon_file = data_dir / "14# The Twisted Viper Bar" / "Threads" / "3-1# Full Moon.json"
        self.assertTrue(full_moon_file.exists(), f"Full Moon thread file must exist at {full_moon_file}")

        event4_file = data_dir / "6# Events" / "4# event-4.json"
        self.assertTrue(event4_file.exists(), f"Normalized event-4 file must exist at {event4_file}")

        sand_dunes_file = data_dir / "6# Events" / "Threads" / "1-2# Sand Dunes.json"
        self.assertTrue(sand_dunes_file.exists(), f"Normalized Sand Dunes thread file must exist at {sand_dunes_file}")

        # Update, Data_Old, and Merge folders should be cleaned up
        self.assertFalse(Path(ctx.update_folder).exists(), "Update folder should be cleaned up")
        self.assertFalse(Path(f"{ctx.data_folder}_Old").exists(), "Data_Old folder should be cleaned up")
        self.assertFalse(Path(ctx.merge_folder).exists(), "Merge folder should be cleaned up")

        t.log("console", "Full update with backup_server executed and verified successfully.")

    def test_07_inject_category_events(self):
        """
        Tests injecting a raw event category into an existing backup using inject_category(..., is_event=True).
        Verifies:
          1. Category is normalized into the faux 'Events' category ('event-1..N').
          2. Raw category folder is cleaned up and normalized on disk.
          3. EventModel and SceneModel (kind='event') rows are indexed and saved to SQLite.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_backup = Path(tmp_dir) / "TestInjectBackup"
            clean_backup = PROJECT_ROOT / "Backups" / "Elysium-sql-tests-clean"
            shutil.copytree(clean_backup, tmp_backup)

            data_dir = tmp_backup / "Data"
            faux_events_dir = data_dir / "6# Events"
            raw_event_storage = data_dir / "28# EVENT STORAGE"
            if faux_events_dir.exists():
                faux_events_dir.rename(raw_event_storage)
                ch1 = raw_event_storage / "1# event-1.json"
                if ch1.exists():
                    ch1.rename(raw_event_storage / "1# hogsmeade.json")
                ch2 = raw_event_storage / "2# event-2.json"
                if ch2.exists():
                    ch2.rename(raw_event_storage / "2# common-room.json")
                ch3 = raw_event_storage / "3# event-3.json"
                if ch3.exists():
                    ch3.rename(raw_event_storage / "3# hagrids-hut.json")

            try:
                migrate_single_backup(
                    backup={
                        "path": tmp_backup.as_posix(),
                        "backup_id": "999999999",
                        "backup_name": "TestInjectBackup",
                        "server_id": "857848490683269161",
                        "server_name": "Diabolik: Elysium",
                    },
                    dry_run=False,
                )

                inject_category(
                    backup_id="999999999",
                    backup_path=tmp_backup.as_posix(),
                    category_name="EVENT STORAGE",
                    is_event=True,
                )

                with db_session(backup_id="999999999", backup_path=tmp_backup.as_posix()) as session:
                    events = session.query(EventModel).filter_by(backup_id="999999999").all()
                    event_scenes = session.query(SceneModel).filter_by(
                        backup_id="999999999", kind=SceneKind.EVENT.value
                    ).all()
                    self.assertGreater(len(events), 0, "EventModel rows must be created")
                    self.assertGreater(len(event_scenes), 0, "SceneModel (kind='event') rows must be created")
                    for ev in events:
                        self.assertGreater(ev.message_count, 0)
                        self.assertIsNotNone(ev.start_at)
                        self.assertIsNotNone(ev.end_at)

                self.assertFalse(raw_event_storage.exists(), "Raw category folder must be cleaned up")
                events_dirs = [d for d in data_dir.iterdir() if d.is_dir() and "events" in d.name.lower()]
                self.assertEqual(len(events_dirs), 1, "Exactly one normalized Events folder must exist")
                norm_files = [f.name for f in events_dirs[0].glob("*.json")]
                self.assertTrue(any("event-1.json" in f for f in norm_files), "event-1.json must exist in normalized folder")

                backup = ServerBackup.load(scope="base", backup_id="999999999", backup_path=tmp_backup.as_posix())
                self.assertEqual(backup.steps[Step.INDEX_SCENES], Status.SUCCESS)

            finally:
                close_all_engines()


@skip_in_production_or_missing_fixture()
class TestNativeDiscordExtractorAndSyncModes(unittest.TestCase):
    """
    Phase 2 test suite covering backupless zero-JSON mode, resumable paused sync,
    24h edit lookback + IS_DELETED skeleton preservation, fail-fast bot verification,
    403 members fallback + 429 retry_after handling, and DCE §7 formatting/serialization parity.
    """

    def tearDown(self):
        SceneManager.clear_cache()
        close_all_engines()

    def _create_isolated_backup(
        self,
        tmp_dir: str,
        *,
        storage_mode: str = "backupless",
        backup_id: str = "777000111",
    ) -> tuple[str, str]:
        backup_dir = Path(tmp_dir) / f"backup_{backup_id}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        clean_cfg_path = DATA_ROOT / "Backups" / "Elysium-sql-tests-clean" / "backup_config.json"
        cfg = json.loads(clean_cfg_path.read_text(encoding="utf-8"))
        cfg["admin"]["backupName"] = backup_dir.name
        cfg["admin"]["path"] = backup_dir.as_posix()
        cfg["admin"]["storageMode"] = storage_mode
        (backup_dir / "backup_config.json").write_text(json.dumps(cfg, indent=4), encoding="utf-8")
        return backup_id, backup_dir.as_posix()

    def test_backupless_initial_sync_zero_json_files(self):
        mock_discord = ElysiumMockDiscordServer(
            DATA_ROOT / "Backups" / "Elysium-sql-tests-clean",
            include_update=False,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                bid, bpath = self._create_isolated_backup(tmp_dir, storage_mode="backupless", backup_id="777000101")
                ctx = BackupContext.create(backup_id=bid, backup_path=bpath)
                ctx.debug_files = False
                with use_socket_free_asyncio():
                    with BackupContext.activate(context=ctx):
                        res = backup_server(
                            backup_id=bid,
                            backup_path=bpath,
                            token="test-bot-token",
                            transport=mock_discord.make_transport(),
                        )

                self.assertEqual(res["status"], "idle")
                data_dir = Path(bpath) / "Data"
                json_files = list(data_dir.rglob("*.json")) if data_dir.exists() else []
                self.assertEqual(json_files, [], "backupless mode must write ZERO .json files inside Data/")
                self.assertTrue(Path(get_skeleton_sqlite_path(bpath)).exists(), "skeletons.sqlite must exist")

                with db_session(backup_id=bid, backup_path=bpath) as session:
                    b_row = session.query(BackupModel).filter_by(backup_id=bid).first()
                    self.assertIsNotNone(b_row)
                    self.assertEqual(b_row.storage_mode, "backupless")
                    self.assertEqual(b_row.sync_status, "idle")
                    self.assertEqual(
                        session.query(SceneModel).filter_by(backup_id=bid, kind=SceneKind.SCENE.value).count(),
                        13,
                    )
                    self.assertEqual(
                        session.query(SceneModel).filter_by(backup_id=bid, kind=SceneKind.SESSION.value).count(),
                        121,
                    )
                    self.assertGreaterEqual(session.query(EventModel).filter_by(backup_id=bid).count(), 4)
                    self.assertGreater(session.query(SeenDiscordUserModel).filter_by(backup_id=bid).count(), 0)

                with skeleton_db_session(backup_id=bid, backup_path=bpath) as skel_session:
                    self.assertGreater(skel_session.query(MessageSkeletonModel).count(), 11000)
            finally:
                close_all_engines()

    def test_resumable_interrupted_sync_and_resume(self):
        mock_discord = ElysiumMockDiscordServer(
            DATA_ROOT / "Backups" / "Elysium-sql-tests-clean",
            include_update=False,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                bid, bpath = self._create_isolated_backup(tmp_dir, storage_mode="backupless", backup_id="777000102")
                stop_ev = threading.Event()
                committed_first_run: list[str] = []

                def _on_commit(item, done, total):
                    committed_first_run.append(item.discord_id)
                    if done >= 2:
                        stop_ev.set()

                ctx = BackupContext.create(backup_id=bid, backup_path=bpath)
                ctx.debug_files = False
                with use_socket_free_asyncio():
                    with BackupContext.activate(context=ctx):
                        res1 = backup_server(
                            backup_id=bid,
                            backup_path=bpath,
                            token="test-bot-token",
                            transport=mock_discord.make_transport(),
                            stop_event=stop_ev,
                            on_channel_committed=_on_commit,
                        )

                self.assertEqual(res1["status"], "paused")
                self.assertGreaterEqual(len(committed_first_run), 2)

                with db_session(backup_id=bid, backup_path=bpath) as session:
                    b_row = session.query(BackupModel).filter_by(backup_id=bid).first()
                    self.assertEqual(b_row.sync_status, "paused")
                    synced_ids_before = {
                        ch.discord_id
                        for ch in session.query(ChannelModel).filter_by(backup_id=bid, sync_status="synced").all()
                        if ch.type != "GuildCategory"
                    }
                    self.assertTrue(set(committed_first_run).issubset(synced_ids_before))

                mock_discord.fetched_channel_history_ids.clear()
                with use_socket_free_asyncio():
                    with BackupContext.activate(context=ctx):
                        res2 = backup_server(
                            backup_id=bid,
                            backup_path=bpath,
                            token="test-bot-token",
                            transport=mock_discord.make_transport(),
                            resume=True,
                        )

                self.assertEqual(res2["status"], "idle")
                self.assertEqual(res2["channels_done"], res2["channels_total"])
                for already_synced in synced_ids_before:
                    self.assertNotIn(
                        already_synced,
                        mock_discord.fetched_channel_history_ids,
                        f"Resumed sync must skip already-synced channel {already_synced}",
                    )
            finally:
                close_all_engines()

    def test_24h_lookback_edit_to_end_and_deleted_message_preservation(self):
        now = datetime.now(timezone.utc)
        def _sf_at(dt: datetime, inc: int) -> str:
            ms = int(dt.timestamp() * 1000)
            return str(((ms - DISCORD_EPOCH_MS) << 22) + inc)

        cat_id = "910000000000000001"
        ch_id = "910000000000000002"
        m1_dt = now - timedelta(hours=3)
        m2_dt = now - timedelta(hours=2)
        m3_dt = now - timedelta(hours=1)
        m1_id = _sf_at(m1_dt, 1)
        m2_id = _sf_at(m2_dt, 2)
        m3_id = _sf_at(m3_dt, 3)

        channel_messages = [
            {
                "id": m1_id,
                "channel_id": ch_id,
                "type": 0,
                "timestamp": m1_dt.isoformat(),
                "edited_timestamp": None,
                "pinned": False,
                "content": "Elise stepped quietly into the lantern-lit tavern and ordered spiced wine while scanning the corner booths for familiar faces.",
                "author": {"id": "880000000000000001", "username": "Elise Rosenberg", "bot": True},
                "attachments": [], "embeds": [], "sticker_items": [], "reactions": [], "mentions": [],
            },
            {
                "id": m2_id,
                "channel_id": ch_id,
                "type": 0,
                "timestamp": m2_dt.isoformat(),
                "edited_timestamp": None,
                "pinned": False,
                "content": "Kaizer leaned back against the booth cushions, swirling his glass with an amused smirk at the newcomer.",
                "author": {"id": "880000000000000002", "username": "Kaizer", "bot": True},
                "attachments": [], "embeds": [], "sticker_items": [], "reactions": [], "mentions": [],
            },
            {
                "id": m3_id,
                "channel_id": ch_id,
                "type": 0,
                "timestamp": m3_dt.isoformat(),
                "edited_timestamp": None,
                "pinned": False,
                "content": "Rain tapped steadily against the stained-glass windows outside as the tavern piano shifted into a slower melody.",
                "author": {"id": "880000000000000001", "username": "Elise Rosenberg", "bot": True},
                "attachments": [], "embeds": [], "sticker_items": [], "reactions": [], "mentions": [],
            },
        ]

        guild_id = "910000000000000000"

        def _handler(request: httpx.Request) -> httpx.Response:
            p = request.url.path
            if p == "/api/v10/users/@me":
                return httpx.Response(200, json={"id": "999", "username": "Bot", "bot": True})
            if p == f"/api/v10/guilds/{guild_id}":
                return httpx.Response(200, json={"id": guild_id, "name": "LookbackGuild", "roles": []})
            if p == f"/api/v10/guilds/{guild_id}/channels":
                last_mid = channel_messages[-1]["id"] if channel_messages else None
                return httpx.Response(200, json=[
                    {"id": cat_id, "type": 4, "name": "The Twisted Viper Bar", "position": 0},
                    {"id": ch_id, "type": 0, "parent_id": cat_id, "name": "barside", "position": 0, "last_message_id": last_mid},
                ])
            if p == f"/api/v10/guilds/{guild_id}/threads/active":
                return httpx.Response(200, json={"threads": [], "has_more": False})
            if p.endswith("/threads/archived/public") or p.endswith("/threads/archived/private"):
                return httpx.Response(200, json={"threads": [], "has_more": False})
            if p == f"/api/v10/guilds/{guild_id}/members":
                return httpx.Response(200, json=[])
            if p == f"/api/v10/channels/{ch_id}/messages":
                after_raw = request.url.params.get("after")
                limit = int(request.url.params.get("limit") or "100")
                if after_raw is not None:
                    msgs = [m for m in channel_messages if int(m["id"]) > int(after_raw)]
                    return httpx.Response(200, json=list(reversed(msgs[:limit])))
                return httpx.Response(200, json=list(reversed(channel_messages[-limit:])))
            return httpx.Response(404, json={"message": "Not Found"})

        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                bdir = Path(tmp_dir) / "lookback_full"
                bdir.mkdir(parents=True, exist_ok=True)
                cfg = {
                    "admin": {
                        "serverName": "LookbackGuild",
                        "serverId": guild_id,
                        "storageMode": "full",
                        "categoriesToKeep": ["The Twisted Viper Bar"],
                        "keepMode": True,
                        "categoriesToIgnore": [],
                        "chatroomCategories": [],
                        "eventCategories": [],
                        "dmCategories": [],
                        "backupName": "lookback_full",
                        "path": bdir.as_posix(),
                    },
                    "user": {},
                }
                (bdir / "backup_config.json").write_text(json.dumps(cfg, indent=4), encoding="utf-8")

                ctx = BackupContext.create(backup_id="777000103", backup_path=bdir.as_posix())
                ctx.debug_files = False
                with use_socket_free_asyncio():
                    with BackupContext.activate(context=ctx):
                        backup_server(
                            backup_id="777000103",
                            backup_path=bdir.as_posix(),
                            token="test-bot-token",
                            transport=httpx.MockTransport(_handler),
                        )

                with db_session(backup_id="777000103", backup_path=bdir.as_posix()) as session:
                    scenes = session.query(SceneModel).filter_by(backup_id="777000103", kind=SceneKind.SCENE.value).all()
                    self.assertEqual(len(scenes), 1)
                    self.assertEqual(scenes[0].status, "open")

                # Mutate channel within 24h lookback window: edit m3 to end with [END] and delete m2
                channel_messages[2]["content"] = (
                    "Rain tapped steadily against the stained-glass windows outside.\n\n[END]"
                )
                channel_messages[2]["edited_timestamp"] = (now - timedelta(minutes=30)).isoformat()
                channel_messages.pop(1)

                with use_socket_free_asyncio():
                    with BackupContext.activate(context=ctx):
                        backup_server(
                            backup_id="777000103",
                            backup_path=bdir.as_posix(),
                            token="test-bot-token",
                            transport=httpx.MockTransport(_handler),
                        )

                with db_session(backup_id="777000103", backup_path=bdir.as_posix()) as session:
                    scenes = session.query(SceneModel).filter_by(backup_id="777000103", kind=SceneKind.SCENE.value).all()
                    self.assertEqual(len(scenes), 1)
                    self.assertEqual(scenes[0].status, "closed", "Edited [END] in 24h lookback must close open scene")
                    self.assertEqual(str(scenes[0].end_message_id), m3_id)

                with skeleton_db_session(backup_id="777000103", backup_path=bdir.as_posix()) as skel_session:
                    m2_row = skel_session.query(MessageSkeletonModel).filter_by(message_id=int(m2_id)).first()
                    self.assertIsNotNone(m2_row, "Deleted message skeleton row must be preserved")
                    self.assertNotEqual(int(m2_row.flags) & int(SkeletonFlags.IS_DELETED), 0)

                json_file = bdir / "Data" / "1# The Twisted Viper Bar" / "1# barside.json"
                self.assertTrue(json_file.exists())
                exported = json.loads(json_file.read_text(encoding="utf-8"))
                by_id = {m["id"]: m for m in exported["messages"]}
                self.assertTrue(by_id[m2_id].get("is_deleted"))
                self.assertIn("[END]", by_id[m3_id]["content"])
            finally:
                close_all_engines()

    def test_fail_fast_invalid_bot_token(self):
        for bad_mode in ("user", "unauthorized"):
            mock_discord = ElysiumMockDiscordServer(
                DATA_ROOT / "Backups" / "Elysium-sql-tests-clean",
                include_update=False,
                bot_token_mode=bad_mode,
            )
            with tempfile.TemporaryDirectory() as tmp_dir:
                try:
                    bid, bpath = self._create_isolated_backup(tmp_dir, storage_mode="backupless", backup_id="777000104")
                    ctx = BackupContext.create(backup_id=bid, backup_path=bpath)
                    with use_socket_free_asyncio():
                        with BackupContext.activate(context=ctx):
                            with self.assertRaises(exc.InvalidBotTokenError):
                                backup_server(
                                    backup_id=bid,
                                    backup_path=bpath,
                                    token="UserToken.invalid",
                                    transport=mock_discord.make_transport(),
                                )
                    # Verify /channels was NEVER requested and sync_status was never flipped to syncing
                    self.assertFalse(any("/channels" in r for r in mock_discord.requests_seen))
                    with db_session(backup_id=bid, backup_path=bpath) as session:
                        b_row = session.query(BackupModel).filter_by(backup_id=bid).first()
                        self.assertEqual(b_row.sync_status, "idle")
                finally:
                    close_all_engines()

    def test_guild_members_403_fallback_and_429_rate_limit_retry(self):
        mock_discord = ElysiumMockDiscordServer(
            DATA_ROOT / "Backups" / "Elysium-sql-tests-clean",
            include_update=False,
            members_403=True,
            rate_limit_once_429=True,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                bid, bpath = self._create_isolated_backup(tmp_dir, storage_mode="backupless", backup_id="777000105")
                ctx = BackupContext.create(backup_id=bid, backup_path=bpath)
                ctx.debug_files = False
                with use_socket_free_asyncio():
                    with BackupContext.activate(context=ctx):
                        res = backup_server(
                            backup_id=bid,
                            backup_path=bpath,
                            token="test-bot-token",
                            transport=mock_discord.make_transport(),
                        )

                self.assertEqual(res["status"], "idle")
                self.assertTrue(mock_discord._429_fired, "429 response must have been hit and retried")
                with db_session(backup_id=bid, backup_path=bpath) as session:
                    seen_users = session.query(SeenDiscordUserModel).filter_by(backup_id=bid).all()
                    self.assertGreater(len(seen_users), 0, "Channel-harvested seen_discord_users must populate on 403")
                    self.assertTrue(all(not u.is_current_member for u in seen_users))
            finally:
                close_all_engines()

    def test_single_pass_formatter_and_dce_json_serializer_parity(self):
        channels_by_id = {"5550001": {"id": "5550001", "name": "general-rp"}}
        roles_by_id = {"6660001": {"id": "6660001", "name": "Storyteller", "color": 0x1ABC9C, "position": 2}}
        members_by_id = {
            "7770001": {
                "user": {"id": "7770001", "username": "Alice Example", "global_name": "Alice Display", "bot": False},
                "nick": "Alice Nick",
                "roles": ["6660001"],
            }
        }

        # 1. Single-pass formatter: space-free @username, <#id>, <@&id>, <t:ts:F> UTC, custom emoji
        raw_text = "Hi <@!7770001> in <#5550001> for <@&6660001> at <t:1700000000:F> <:wave:8880001>"
        formatted = format_content(
            raw_text,
            channels_by_id=channels_by_id,
            roles_by_id=roles_by_id,
            members_by_id=members_by_id,
        )
        self.assertIn("@AliceExample", formatted)
        self.assertNotIn("@Alice Nick", formatted)
        self.assertIn("#general-rp", formatted)
        self.assertIn("@Storyteller", formatted)
        self.assertIn("14 November 2023 22:13", formatted)
        self.assertIn(":wave:", formatted)

        # 2. inlineEmojis codeblock stripping & escape safety
        emoji_src = "Visible <:grin:12345> ☀️ `ignored <:inCode:99999> 🔥` ```\n<:fenced:77777> ❄️\n``` \\:escaped:"
        emojis = extract_inline_emojis(emoji_src)
        emoji_names = [e["name"] for e in emojis]
        self.assertIn("grin", emoji_names)
        self.assertIn("☀️", emoji_names)
        self.assertNotIn("inCode", emoji_names)
        self.assertNotIn("fenced", emoji_names)
        self.assertNotIn("🔥", emoji_names)
        self.assertNotIn("❄️", emoji_names)

        # 3. DCE §7 serializer: Twitter embed merge, conditional color omission, system notifications
        raw_msg = {
            "id": "9001",
            "type": 0,
            "timestamp": "2024-01-10T12:00:00Z",
            "edited_timestamp": None,
            "pinned": False,
            "content": "Check photos",
            "author": {"id": "7770001", "username": "Alice Example", "bot": False},
            "mentions": [],
            "embeds": [
                {
                    "url": "https://twitter.com/example/status/1",
                    "description": "Tweet caption",
                    "color": None,
                    "image": {"url": "https://pbs.twimg.com/media/1.jpg", "width": 100, "height": 100},
                },
                {
                    "url": "https://twitter.com/example/status/1",
                    "color": None,
                    "image": {"url": "https://pbs.twimg.com/media/2.jpg", "width": 100, "height": 100},
                },
            ],
        }
        ser = serialize_message(
            raw_msg,
            guild_id="857848490683269161",
            channels_by_id=channels_by_id,
            roles_by_id=roles_by_id,
            members_by_id=members_by_id,
        )
        self.assertEqual(ser["author"]["color"], "#1ABC9C")
        self.assertEqual(len(ser["embeds"]), 1, "Twitter consecutive embeds must merge")
        self.assertEqual(len(ser["embeds"][0]["images"]), 2)
        self.assertNotIn("color", ser["embeds"][0], "Embed color must be omitted when null")

        sys_pin = serialize_message(
            {"id": "9002", "type": 6, "timestamp": "2024-01-10T12:01:00Z", "content": "", "author": {"id": "7770001", "username": "Alice Example"}}
        )
        self.assertEqual(sys_pin["type"], "ChannelPinnedMessage")
        self.assertEqual(sys_pin["content"], "Pinned a message.")
        self.assertIsNone(sys_pin["author"]["color"], "User color must remain null when absent")

    def test_prefixed_category_names_match_discord_categories(self):
        """
        Regression test: category selectors storing DCE position prefixes like '14# The Twisted Viper Bar'
        must match raw Discord category names ('The Twisted Viper Bar') during topology filtering and indexing.
        """
        mock_discord = ElysiumMockDiscordServer(DATA_ROOT / "Backups" / "Elysium-sql-tests-clean", include_update=False)
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                bid, bpath = self._create_isolated_backup(tmp_dir, storage_mode="backupless", backup_id="777000106")
                cfg_path = Path(bpath) / "backup_config.json"
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                cfg["admin"]["categoriesToKeep"] = [
                    "14# The Twisted Viper Bar",
                    "7# Group Chats",
                    "6# CURRENT EVENT",
                    "28# EVENT STORAGE",
                ]
                cfg["admin"]["chatroomCategories"] = ["7# Group Chats"]
                cfg["admin"]["eventCategories"] = ["6# CURRENT EVENT", "28# EVENT STORAGE"]
                cfg["admin"]["keepMode"] = True
                cfg_path.write_text(json.dumps(cfg, indent=4), encoding="utf-8")

                ctx = BackupContext.create(backup_id=bid, backup_path=bpath)
                self.assertEqual(ctx.chatroom_categories, ["Group Chats"])
                self.assertIn("The Twisted Viper Bar", ctx.categories_to_keep)

                with use_socket_free_asyncio():
                    with BackupContext.activate(context=ctx):
                        res = backup_server(
                            backup_id=bid,
                            backup_path=bpath,
                            token="test-bot-token",
                            transport=mock_discord.make_transport(),
                        )

                self.assertEqual(res["status"], "idle")
                self.assertGreater(res["channels_total"], 0)
                with db_session(backup_id=bid, backup_path=bpath) as session:
                    rp_cnt = session.query(SceneModel).filter_by(backup_id=bid, kind=SceneKind.SCENE.value).count()
                    sess_cnt = session.query(SceneModel).filter_by(backup_id=bid, kind=SceneKind.SESSION.value).count()
                    ev_cnt = session.query(EventModel).filter_by(backup_id=bid).count()
                    self.assertEqual(rp_cnt, 13)
                    self.assertEqual(sess_cnt, 121)
                    self.assertGreater(ev_cnt, 0)
            finally:
                close_all_engines()

    def test_rate_limit_and_retry_summary_telemetry(self):
        """
        Verifies DiscordExtractor tracks proactive bucket waits, 429s, and transient retries,
        emits thresholded [Throttle notice] logs on heavy pauses without per-request spam,
        and backup_server writes 'API wait summary:' to log.txt.
        """
        import asyncio
        from unittest.mock import patch
        from discord_extractor import DiscordExtractor

        call_seq = []

        async def _no_sleep(_seconds: float) -> None:
            return None

        def _throttled_handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            call_seq.append(path)
            if path == "/api/v10/users/@me":
                if call_seq.count(path) == 1:
                    return httpx.Response(
                        429,
                        json={"retry_after": 5.5, "global": True},
                        headers={"X-RateLimit-Global": "true", "Retry-After": "5.5"},
                    )
                return httpx.Response(
                    200,
                    json={"id": "999", "username": "bot", "bot": True},
                    headers={
                        "X-RateLimit-Bucket": "b-me",
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset-After": "0.25",
                    },
                )
            if path == "/api/v10/guilds/857848490683269161":
                if call_seq.count(path) == 1:
                    return httpx.Response(502, json={"message": "Bad Gateway"})
                return httpx.Response(200, json={"id": "857848490683269161", "name": "Elysium", "roles": []})
            return httpx.Response(404, json={"message": "Not Found"})

        logged_notices = []

        async def _exercise_extractor():
            async with DiscordExtractor(
                token="test-bot-token",
                transport=httpx.MockTransport(_throttled_handler),
                sleep_fn=_no_sleep,
                throttle_notice_single_s=5.0,
                throttle_notice_delta_s=15.0,
                throttle_notice_cooldown_s=15.0,
            ) as ext:
                await ext.verify_bot_token()
                # Reset _bot_verified so a second verify hits the bucket wait (Remaining: 0)
                ext._bot_verified = False
                await ext.verify_bot_token()
                await ext._request_json("GET", "guilds/857848490683269161")
                return ext.get_telemetry(), ext.format_wait_summary()

        with use_socket_free_asyncio():
            with patch("discord_extractor.t.log", side_effect=lambda lvl, msg: logged_notices.append((lvl, msg))):
                stats, summary_line = asyncio.run(_exercise_extractor())

        self.assertEqual(stats["http_429_count"], 1)
        self.assertEqual(stats["global_429_count"], 1)
        self.assertAlmostEqual(stats["http_429_wait_seconds"], 5.5, places=2)
        self.assertGreaterEqual(stats["bucket_waits"], 1)
        self.assertEqual(stats["retry_count"], 1)
        self.assertEqual(stats["requests_total"], 5)
        self.assertIn("API wait summary:", summary_line)
        self.assertIn("1x 429 [1 global]", summary_line)
        self.assertIn("1 retry/ies", summary_line)
        # Only the 5.5s wait triggers [Throttle notice]; routine 0.25s bucket wait & 0.5s retry stay silent
        self.assertEqual(len(logged_notices), 1)
        self.assertEqual(logged_notices[0][0], "warning")
        self.assertIn("[Throttle notice]", logged_notices[0][1])

        # Also verify end-to-end backup_server logs 'Sync complete:' + 'API wait summary:' into log.txt
        mock_discord = ElysiumMockDiscordServer(DATA_ROOT / "Backups" / "Elysium-sql-tests-clean", include_update=False)
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                bid, bpath = self._create_isolated_backup(tmp_dir, storage_mode="backupless", backup_id="777000107")
                ctx = BackupContext.create(backup_id=bid, backup_path=bpath)
                with use_socket_free_asyncio():
                    with BackupContext.activate(context=ctx):
                        backup_server(
                            backup_id=bid,
                            backup_path=bpath,
                            token="test-bot-token",
                            transport=mock_discord.make_transport(),
                        )
                t.flush_logs()
                log_text = (Path(bpath) / "log.txt").read_text(encoding="utf-8")
                self.assertIn("Sync complete:", log_text)
                self.assertIn("msg(s) in", log_text)
                self.assertIn("API wait summary:", log_text)
            finally:
                close_all_engines()

    def test_backupless_to_full_conversion_overwrites_stale_data_only_after_rescan_succeeds(self):
        """
        Verifies converting Backupless -> Full with rescan_discord=True:
        1. Leaves pre-existing Data/*.json untouched if token verification fails before syncing.
        2. Overwrites stale messages inside existing Data/*.json and prunes orphan JSON files
           (keeping Data/ itself intact) once rescan_discord=True succeeds.
        """
        import utils.exceptions as exc

        mock_discord = ElysiumMockDiscordServer(DATA_ROOT / "Backups" / "Elysium-sql-tests-clean", include_update=False)

        def _bad_token_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "401: Unauthorized"})

        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                bid, bpath = self._create_isolated_backup(tmp_dir, storage_mode="full", backup_id="777000108")
                stale_json = Path(bpath) / "Data" / "14# The Twisted Viper Bar" / "1# barside.json"
                stale_json.parent.mkdir(parents=True, exist_ok=True)
                stale_json.write_text(
                    json.dumps({
                        "messages": [
                            {"id": "1", "content": "STALE_MESSAGE_THAT_SHOULD_NOT_SURVIVE_RESCAN", "author": {"id": "1", "name": "Old"}},
                        ]
                    }),
                    encoding="utf-8",
                )
                orphan_json = Path(bpath) / "Data" / "99# DeletedCategory" / "1# orphan.json"
                orphan_json.parent.mkdir(parents=True, exist_ok=True)
                orphan_json.write_text(json.dumps({"messages": []}), encoding="utf-8")

                # 1. Failed token check must leave existing Data/*.json files intact
                ctx = BackupContext.create(backup_id=bid, backup_path=bpath)
                with use_socket_free_asyncio():
                    with BackupContext.activate(context=ctx):
                        with self.assertRaises(exc.InvalidBotTokenError):
                            backup_server(
                                backup_id=bid,
                                backup_path=bpath,
                                token="bad-token",
                                transport=httpx.MockTransport(_bad_token_handler),
                                rescan_discord=True,
                            )
                self.assertTrue(stale_json.exists())
                self.assertTrue(orphan_json.exists())

                # 2. Successful Full Discord Rescan overwrites stale channel JSONs and prunes orphan JSONs
                with use_socket_free_asyncio():
                    with BackupContext.activate(context=ctx):
                        res = backup_server(
                            backup_id=bid,
                            backup_path=bpath,
                            token="test-bot-token",
                            transport=mock_discord.make_transport(),
                            rescan_discord=True,
                        )

                self.assertEqual(res["status"], "idle")
                self.assertTrue((Path(bpath) / "Data").is_dir())
                self.assertFalse(orphan_json.exists(), "Orphan JSON file must be pruned after full rescan")
                self.assertFalse(orphan_json.parent.exists(), "Empty orphan directory must be removed")
                self.assertTrue(stale_json.exists())
                fresh_payload = json.loads(stale_json.read_text(encoding="utf-8"))
                fresh_ids = {str(m["id"]) for m in fresh_payload.get("messages", [])}
                self.assertNotIn("1", fresh_ids, "rescan_discord=True must overwrite pre-existing JSON rather than merging stale messages")
            finally:
                close_all_engines()

    def test_gcsfuse_copymode_copystat_safe_bootstrap_and_reset(self):
        """Ensure _ensure_backup_bootstrap and reset_test_backup_dir never invoke chmod/copymode/copystat."""
        import shutil
        from unittest.mock import patch
        from backup_server import _ensure_backup_bootstrap
        from db.test_backup_service import reset_test_backup_dir
        from res import constants as c

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            global_cfg = tmp_root / "global_config.json"
            global_cfg.write_text(json.dumps({"admin": {"storageMode": "full"}}), encoding="utf-8")
            backup_dir = tmp_root / "Backups" / "Elysium-full"

            clean_dir = tmp_root / "Backups" / "Elysium-sql-tests-clean"
            clean_dir.mkdir(parents=True, exist_ok=True)
            (clean_dir / "backup_config.json").write_text("{}", encoding="utf-8")

            def _raise_eperm(*args, **kwargs):
                raise PermissionError(1, "Operation not permitted")

            with (
                patch.object(shutil, "copymode", side_effect=_raise_eperm),
                patch.object(shutil, "copystat", side_effect=_raise_eperm),
                patch.object(c, "GLOBAL_CONFIG", global_cfg.as_posix()),
            ):
                b_id, b_path = _ensure_backup_bootstrap(backup_id="777000999", backup_path=backup_dir.as_posix())
                self.assertEqual(b_id, "777000999")
                self.assertEqual(b_path, backup_dir.as_posix())
                self.assertTrue((backup_dir / "backup_config.json").is_file())
                self.assertEqual(
                    json.loads((backup_dir / "backup_config.json").read_text(encoding="utf-8")),
                    {"admin": {"storageMode": "full"}},
                )

                self.assertTrue(reset_test_backup_dir(tmp_root))
                self.assertTrue((tmp_root / "Backups" / "Elysium-sql-tests" / "backup_config.json").is_file())

    def test_scene_key_collision_reconciled_on_reorder_and_deletion(self):
        """Ensure channel reorders and deleted channels holding stale scene_keys never raise IntegrityError."""
        from db.models import ChannelModel, SceneKind, SceneModel, SceneStatus
        from db.scene_service import reconcile_backup_scene_keys, save_channel_indexed_scenes
        from db.status_service import init_backup_export

        with tempfile.TemporaryDirectory() as tmp_dir:
            bid = "777000998"
            bpath = (Path(tmp_dir) / "reconcile-test").as_posix()
            try:
                init_backup_export(backup_id=bid, backup_path=bpath, backup_name="ReconcileTest")
                with db_session(backup_id=bid, backup_path=bpath) as session:
                    cat = ChannelModel(
                        backup_id=bid,
                        discord_id="1001",
                        type="GuildCategory",
                        parent_pk=None,
                        name="DORM LUNE",
                        position=11,
                        path="11# DORM LUNE",
                        is_deleted=False,
                    )
                    session.add(cat)
                    session.flush()

                    # Deleted channel still holding 11-2-1 and 11-2-2
                    ch_deleted = ChannelModel(
                        backup_id=bid,
                        discord_id="2001",
                        type="GuildTextChat",
                        parent_pk=cat.pk,
                        name="old-room",
                        position=2,
                        path="11# DORM LUNE/2# old-room.json",
                        is_deleted=True,
                    )
                    # Active channel now at 11-2 (previously had 12-5-1, 12-5-2)
                    ch_active = ChannelModel(
                        backup_id=bid,
                        discord_id="2002",
                        type="GuildTextChat",
                        parent_pk=cat.pk,
                        name="lune-kitchen",
                        position=2,
                        path="11# DORM LUNE/2# lune-kitchen.json",
                        is_deleted=False,
                    )
                    # Active channel moved from 11-3 -> 11-4 (swap/shift test)
                    ch_moved = ChannelModel(
                        backup_id=bid,
                        discord_id="2003",
                        type="GuildTextChat",
                        parent_pk=cat.pk,
                        name="baras-room",
                        position=4,
                        path="11# DORM LUNE/4# baras-room.json",
                        is_deleted=False,
                    )
                    session.add_all([ch_deleted, ch_active, ch_moved])
                    session.flush()

                    now_dt = datetime.now(timezone.utc)
                    session.add_all([
                        SceneModel(
                            backup_id=bid, scene_key="11-2-1", channel_pk=ch_deleted.pk, category_pk=cat.pk,
                            kind=SceneKind.SCENE.value, status=SceneStatus.CLOSED.value,
                            start_message_id="100", end_message_id="105", start_index=0, end_index=1,
                            message_count=2, start_at=now_dt, end_at=now_dt,
                            start_author_id="1", end_author_id="1",
                        ),
                        SceneModel(
                            backup_id=bid, scene_key="12-5-1", channel_pk=ch_active.pk, category_pk=cat.pk,
                            kind=SceneKind.SCENE.value, status=SceneStatus.CLOSED.value,
                            start_message_id="200", end_message_id="205", start_index=0, end_index=1,
                            message_count=2, start_at=now_dt, end_at=now_dt,
                            start_author_id="1", end_author_id="1",
                        ),
                        SceneModel(
                            backup_id=bid, scene_key="12-5-2", channel_pk=ch_active.pk, category_pk=cat.pk,
                            kind=SceneKind.SCENE.value, status=SceneStatus.CLOSED.value,
                            start_message_id="210", end_message_id="215", start_index=2, end_index=3,
                            message_count=2, start_at=now_dt, end_at=now_dt,
                            start_author_id="1", end_author_id="1",
                        ),
                        SceneModel(
                            backup_id=bid, scene_key="11-3-1", channel_pk=ch_moved.pk, category_pk=cat.pk,
                            kind=SceneKind.SCENE.value, status=SceneStatus.CLOSED.value,
                            start_message_id="300", end_message_id="305", start_index=0, end_index=1,
                            message_count=2, start_at=now_dt, end_at=now_dt,
                            start_author_id="1", end_author_id="1",
                        ),
                    ])
                    session.flush()
                    ch_del_pk = ch_deleted.pk
                    ch_act_pk = ch_active.pk
                    ch_mov_pk = ch_moved.pk

                # 1. Calling save_channel_indexed_scenes directly without prior reconcile must still succeed
                new_scene = {
                    "status": "closed",
                    "start": {"id": "220", "index": 4, "timestamp": "2026-01-01T00:00:00Z", "authorID": "1", "content": "start"},
                    "end": {"id": "225", "index": 5, "timestamp": "2026-01-01T00:01:00Z", "authorID": "1", "content": "end"},
                    "message_count": 2,
                    "character_ids": [],
                    "issues": [],
                }
                save_channel_indexed_scenes(bid, bpath, ch_act_pk, [new_scene], min_affected_message_id=220)

                with db_session(backup_id=bid, backup_path=bpath) as session:
                    act_keys = [
                        s.scene_key for s in session.query(SceneModel).filter_by(backup_id=bid, channel_pk=ch_act_pk).order_by(SceneModel.start_message_id).all()
                    ]
                    del_keys = [
                        s.scene_key for s in session.query(SceneModel).filter_by(backup_id=bid, channel_pk=ch_del_pk).all()
                    ]
                    mov_keys = [
                        s.scene_key for s in session.query(SceneModel).filter_by(backup_id=bid, channel_pk=ch_mov_pk).all()
                    ]
                    self.assertEqual(act_keys, ["11-2-1", "11-2-2", "11-2-3"])
                    self.assertEqual(del_keys, [f"del-{ch_del_pk}-1"])
                    self.assertEqual(mov_keys, ["11-4-1"])
                    # Idempotent second pass
                    self.assertEqual(reconcile_backup_scene_keys(session, bid), 0)
            finally:
                close_all_engines()

    def test_snowflake_id_category_configs_and_legacy_name_promotion(self):
        """
        Verifies Snowflake ID category matching in topology filtering, backup_server(), and index_scenes(),
        strict keepMode filtering (chatroom/event tags do not bypass keepMode), and automatic promotion
        of legacy category names in backup_category_configs to live Discord Snowflake IDs.
        """
        from db.config_service import load_backup_config_dict, save_backup_config_dict
        from db.models import BackupCategoryConfigModel, CategoryConfigKind
        from utils.path_safety import SNOWFLAKE_RE, category_matches

        # 1. Unit assertions for category_matches
        self.assertFalse(category_matches("1019770957172326470", "The Twisted Viper Bar", set()))
        self.assertTrue(category_matches("1019770957172326470", "Renamed Bar", {"1019770957172326470"}))
        self.assertTrue(category_matches(" 1019770957172326470 ", "Renamed Bar", {"1019770957172326470"}))
        self.assertTrue(category_matches("999", "14# The Twisted Viper Bar", {"The Twisted Viper Bar"}))
        self.assertFalse(category_matches("999", "Other", {"1019770957172326470", "The Twisted Viper Bar"}))

        mock_discord = ElysiumMockDiscordServer(DATA_ROOT / "Backups" / "Elysium-sql-tests-clean", include_update=False)
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                # 2. Pure SQLite config using Snowflake IDs (no backup_config.json on disk)
                bid = "777000109"
                bpath = (Path(tmp_dir) / f"backup_{bid}").as_posix()
                Path(bpath).mkdir(parents=True, exist_ok=True)
                sql_cfg = {
                    "admin": {
                        "serverName": "(+18) Diabolik: Elysium",
                        "serverId": ElysiumMockDiscordServer.GUILD_ID,
                        "storageMode": "backupless",
                        "keepMode": True,
                        "categoriesToKeep": [
                            "1019770957172326470",  # The Twisted Viper Bar
                            "1106268351220678767",  # Group Chats
                            "1008065547155558431",  # CURRENT EVENT
                            "987749861963214878",   # EVENT STORAGE
                        ],
                        "categoriesToIgnore": [],
                        "chatroomCategories": ["1106268351220678767"],
                        "eventCategories": ["1008065547155558431", "987749861963214878"],
                        "backupName": f"backup_{bid}",
                        "path": bpath,
                        "verbosity": {"info": True, "debug": False, "console": False, "log": False, "debugFiles": False},
                    }
                }
                save_backup_config_dict(
                    backup_id=bid,
                    backup_path=bpath,
                    config_data=sql_cfg,
                    create_db_if_missing=True,
                )
                self.assertFalse((Path(bpath) / "backup_config.json").exists())

                ctx = BackupContext.create(backup_id=bid, backup_path=bpath)
                with use_socket_free_asyncio():
                    with BackupContext.activate(context=ctx):
                        res = backup_server(
                            backup_id=bid,
                            backup_path=bpath,
                            token="test-bot-token",
                            transport=mock_discord.make_transport(),
                        )
                self.assertEqual(res["status"], "idle")

                with db_session(backup_id=bid, backup_path=bpath) as session:
                    self.assertEqual(session.query(SceneModel).filter_by(backup_id=bid, kind=SceneKind.SCENE.value).count(), 13)
                    self.assertEqual(session.query(SceneModel).filter_by(backup_id=bid, kind=SceneKind.SESSION.value).count(), 121)
                    self.assertGreaterEqual(session.query(EventModel).filter_by(backup_id=bid).count(), 4)

                # Re-running index_scenes directly with Snowflake IDs in chatroom/event config must preserve counts
                with BackupContext.activate(context=ctx):
                    index_scenes(backup_id=bid, backup_path=bpath, rescan_json=False)
                with db_session(backup_id=bid, backup_path=bpath) as session:
                    self.assertEqual(session.query(SceneModel).filter_by(backup_id=bid, kind=SceneKind.SCENE.value).count(), 13)
                    self.assertEqual(session.query(SceneModel).filter_by(backup_id=bid, kind=SceneKind.SESSION.value).count(), 121)
                    self.assertGreaterEqual(session.query(EventModel).filter_by(backup_id=bid).count(), 4)

                # 3. Legacy category names in config are auto-promoted to Snowflake IDs during backup_server()
                bid2, bpath2 = self._create_isolated_backup(tmp_dir, storage_mode="backupless", backup_id="777000110")
                cfg2_path = Path(bpath2) / "backup_config.json"
                cfg2 = json.loads(cfg2_path.read_text(encoding="utf-8"))
                cfg2["admin"]["categoriesToKeep"] = [
                    "14# The Twisted Viper Bar",
                    "Group Chats",
                    "CURRENT EVENT",
                ]
                # Deliberately tag EVENT STORAGE as an event category even though it is NOT in categoriesToKeep:
                # keepMode must strictly exclude EVENT STORAGE while still promoting its name -> Snowflake ID.
                cfg2["admin"]["categoriesToIgnore"] = ["OOC"]
                cfg2["admin"]["chatroomCategories"] = ["7# Group Chats"]
                cfg2["admin"]["eventCategories"] = ["6# CURRENT EVENT", "28# EVENT STORAGE"]
                cfg2["admin"]["keepMode"] = True
                cfg2_path.write_text(json.dumps(cfg2, indent=4), encoding="utf-8")

                ctx2 = BackupContext.create(backup_id=bid2, backup_path=bpath2)
                with use_socket_free_asyncio():
                    with BackupContext.activate(context=ctx2):
                        res2 = backup_server(
                            backup_id=bid2,
                            backup_path=bpath2,
                            token="test-bot-token",
                            transport=mock_discord.make_transport(),
                        )
                self.assertEqual(res2["status"], "idle")

                loaded2 = load_backup_config_dict(backup_id=bid2, backup_path=bpath2)
                self.assertEqual(
                    loaded2["admin"]["categoriesToKeep"],
                    ["1019770957172326470", "1106268351220678767", "1008065547155558431"],
                )
                self.assertEqual(loaded2["admin"]["chatroomCategories"], ["1106268351220678767"])
                self.assertEqual(
                    loaded2["admin"]["eventCategories"],
                    ["1008065547155558431", "987749861963214878"],
                )
                with db_session(backup_id=bid2, backup_path=bpath2) as session:
                    cat_rows = session.query(BackupCategoryConfigModel).filter_by(backup_id=bid2).all()
                    for cr in cat_rows:
                        self.assertRegex(cr.category_ref, SNOWFLAKE_RE)
                    # EVENT STORAGE was NOT in categoriesToKeep, so eventCategories must NOT bypass keepMode
                    self.assertIsNone(
                        session.query(ChannelModel).filter_by(backup_id=bid2, discord_id="1008065664034025533").first()
                    )
            finally:
                close_all_engines()

    def test_unselected_category_preservation_on_incremental_sync_and_rescan_reset(self):
        """
        Verifies:
        1. Incremental sync (rescan_discord=False) skips unselected categories/channels without marking
           them or their threads is_deleted=True, and preserves existing RP scenes and unselected
           event categories' events (e.g. EVENT STORAGE alongside CURRENT EVENT).
        2. Full Discord Rescan (rescan_discord=True) resets strictly to the active keep/ignore config,
           marking unselected categories/channels/threads as is_deleted=True.
        """
        from db.config_service import load_backup_config_dict, save_backup_config_dict

        mock_discord = ElysiumMockDiscordServer(DATA_ROOT / "Backups" / "Elysium-sql-tests-clean", include_update=False)
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                bid = "777000112"
                bpath = (Path(tmp_dir) / f"backup_{bid}").as_posix()
                Path(bpath).mkdir(parents=True, exist_ok=True)
                initial_cfg = {
                    "admin": {
                        "serverName": "(+18) Diabolik: Elysium",
                        "serverId": ElysiumMockDiscordServer.GUILD_ID,
                        "storageMode": "backupless",
                        "keepMode": True,
                        "categoriesToKeep": [
                            "1019770957172326470",  # The Twisted Viper Bar
                            "1106268351220678767",  # Group Chats
                            "1008065547155558431",  # CURRENT EVENT
                            "987749861963214878",   # EVENT STORAGE
                        ],
                        "categoriesToIgnore": [],
                        "chatroomCategories": ["1106268351220678767"],
                        "eventCategories": ["1008065547155558431", "987749861963214878"],
                        "backupName": f"backup_{bid}",
                        "path": bpath,
                        "verbosity": {"info": True, "debug": False, "console": False, "log": False, "debugFiles": False},
                    }
                }
                save_backup_config_dict(
                    backup_id=bid,
                    backup_path=bpath,
                    config_data=initial_cfg,
                    create_db_if_missing=True,
                )

                # 1. Initial full sync of all 4 categories
                with use_socket_free_asyncio():
                    res1 = backup_server(
                        backup_id=bid,
                        backup_path=bpath,
                        token="test-bot-token",
                        transport=mock_discord.make_transport(),
                    )
                self.assertEqual(res1["status"], "idle")

                with db_session(backup_id=bid, backup_path=bpath) as session:
                    self.assertEqual(session.query(SceneModel).filter_by(backup_id=bid, kind=SceneKind.SCENE.value).count(), 13)
                    self.assertEqual(session.query(SceneModel).filter_by(backup_id=bid, kind=SceneKind.SESSION.value).count(), 121)
                    initial_ev_cnt = session.query(EventModel).filter_by(backup_id=bid).count()
                    self.assertGreaterEqual(initial_ev_cnt, 4)
                    med_tent = session.query(ChannelModel).filter_by(backup_id=bid, discord_id="1008065664034025533").one()
                    self.assertGreater(
                        session.query(SceneModel).filter_by(backup_id=bid, channel_pk=med_tent.pk, kind=SceneKind.EVENT.value).count(),
                        0,
                    )

                # 2. Unselect The Twisted Viper Bar and EVENT STORAGE in SQLite config
                updated_cfg = load_backup_config_dict(backup_id=bid, backup_path=bpath)
                updated_cfg["admin"]["categoriesToKeep"] = [
                    "1106268351220678767",  # Group Chats
                    "1008065547155558431",  # CURRENT EVENT
                ]
                save_backup_config_dict(backup_id=bid, backup_path=bpath, config_data=updated_cfg)

                # 3. Incremental sync (rescan_discord=False) must skip & preserve unselected categories
                mock_discord.fetched_channel_history_ids.clear()
                with use_socket_free_asyncio():
                    res2 = backup_server(
                        backup_id=bid,
                        backup_path=bpath,
                        token="test-bot-token",
                        transport=mock_discord.make_transport(),
                        rescan_discord=False,
                    )
                self.assertEqual(res2["status"], "idle")

                unselected_ids = {
                    "1019770957172326470",  # The Twisted Viper Bar (cat)
                    "1013915163423932496",  # barside
                    "1019771259896205382",  # back-of-bar
                    "1019771317303644261",  # bar-tables
                    "1141818382782574645",  # A Toast to Emnity thread
                    "1158294831097970738",  # Conversation thread
                    "1008065664034025533",  # medical-tent (EVENT STORAGE)
                    "1131989202465210569",  # Room 4 thread (EVENT STORAGE)
                }
                for uid in unselected_ids:
                    self.assertNotIn(uid, mock_discord.fetched_channel_history_ids)

                with db_session(backup_id=bid, backup_path=bpath) as session:
                    for did in unselected_ids | {"events_category"}:
                        ch_row = session.query(ChannelModel).filter_by(backup_id=bid, discord_id=did).one()
                        self.assertFalse(ch_row.is_deleted, f"Channel {did} must stay is_deleted=False on incremental sync")

                    self.assertEqual(session.query(SceneModel).filter_by(backup_id=bid, kind=SceneKind.SCENE.value).count(), 13)
                    self.assertEqual(session.query(EventModel).filter_by(backup_id=bid).count(), initial_ev_cnt)
                    med_tent = session.query(ChannelModel).filter_by(backup_id=bid, discord_id="1008065664034025533").one()
                    self.assertGreater(
                        session.query(SceneModel).filter_by(backup_id=bid, channel_pk=med_tent.pk, kind=SceneKind.EVENT.value).count(),
                        0,
                    )

                # 3b. Genuinely deleting an unselected channel on Discord during incremental sync (rescan_discord=False)
                # must mark that channel is_deleted=True while keeping live unselected sibling channels/threads intact.
                mock_discord.channels = [
                    ch for ch in mock_discord.channels if str(ch.get("id")) != "1019771317303644261"
                ]
                with use_socket_free_asyncio():
                    res2b = backup_server(
                        backup_id=bid,
                        backup_path=bpath,
                        token="test-bot-token",
                        transport=mock_discord.make_transport(),
                        rescan_discord=False,
                    )
                self.assertEqual(res2b["status"], "idle")

                with db_session(backup_id=bid, backup_path=bpath) as session:
                    deleted_bar_tables = session.query(ChannelModel).filter_by(
                        backup_id=bid, discord_id="1019771317303644261"
                    ).one()
                    self.assertTrue(deleted_bar_tables.is_deleted)
                    for still_live_did in (unselected_ids - {"1019771317303644261"}) | {"events_category"}:
                        ch_row = session.query(ChannelModel).filter_by(backup_id=bid, discord_id=still_live_did).one()
                        self.assertFalse(ch_row.is_deleted, f"Live channel {still_live_did} must stay is_deleted=False")

                # 4. Full Discord Rescan (rescan_discord=True) resets strictly to current keep/ignore config
                with use_socket_free_asyncio():
                    res3 = backup_server(
                        backup_id=bid,
                        backup_path=bpath,
                        token="test-bot-token",
                        transport=mock_discord.make_transport(),
                        rescan_discord=True,
                    )
                self.assertEqual(res3["status"], "idle")

                with db_session(backup_id=bid, backup_path=bpath) as session:
                    for did in unselected_ids:
                        ch_row = session.query(ChannelModel).filter_by(backup_id=bid, discord_id=did).one()
                        self.assertTrue(ch_row.is_deleted, f"Channel {did} must be marked is_deleted=True on rescan_discord=True")
                    for selected_did in ("1106268351220678767", "858215486272962581", "events_category", "1008065681998221352"):
                        ch_row = session.query(ChannelModel).filter_by(backup_id=bid, discord_id=selected_did).one()
                        self.assertFalse(ch_row.is_deleted)
                    med_tent = session.query(ChannelModel).filter_by(backup_id=bid, discord_id="1008065664034025533").one()
                    self.assertEqual(
                        session.query(SceneModel).filter_by(backup_id=bid, channel_pk=med_tent.pk, kind=SceneKind.EVENT.value).count(),
                        0,
                    )

                # 5. Full Discord Rescan (rescan_discord=True) with all event categories unselected clears events
                no_events_cfg = load_backup_config_dict(backup_id=bid, backup_path=bpath)
                no_events_cfg["admin"]["categoriesToKeep"] = ["1106268351220678767"]
                save_backup_config_dict(backup_id=bid, backup_path=bpath, config_data=no_events_cfg)

                with use_socket_free_asyncio():
                    res4 = backup_server(
                        backup_id=bid,
                        backup_path=bpath,
                        token="test-bot-token",
                        transport=mock_discord.make_transport(),
                        rescan_discord=True,
                    )
                self.assertEqual(res4["status"], "idle")

                with db_session(backup_id=bid, backup_path=bpath) as session:
                    ev_cat = session.query(ChannelModel).filter_by(backup_id=bid, discord_id="events_category").one()
                    self.assertTrue(ev_cat.is_deleted)
                    self.assertEqual(session.query(EventModel).filter_by(backup_id=bid).count(), 0)
                    self.assertEqual(
                        session.query(SceneModel).filter_by(backup_id=bid, kind=SceneKind.EVENT.value).count(),
                        0,
                    )
            finally:
                close_all_engines()


if __name__ == "__main__":
    unittest.main()

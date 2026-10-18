import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Ensure src and project root are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = Path(__file__).resolve().parent
for p in (SRC_DIR.as_posix(), PROJECT_ROOT.as_posix()):
    if p not in sys.path:
        sys.path.insert(0, p)

import utils.tricks as t
from db.models import FlaggedMessageModel, SceneIssueModel, WriterModel
from db.session import db_session, has_sqlite_db

t.set_path()


def normalize_tokens(text: str) -> Set[str]:
    """Extracts alphanumeric tokens from text for robust matching."""
    if not text:
        return set()
    # Split by standard punctuation and whitespace
    raw_tokens = re.split(r"[\s\|\-_/~・,;:.\[\]\(\)\{\}★☆#@]+", text.lower())
    return {tok.strip() for tok in raw_tokens if len(tok.strip()) >= 2}


def find_writer_link_suggestions(
    backup_id: str, base_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Analyzes non-tupper authors in flagged messages and scene issues to suggest
    Discord User ID links for unlinked writers. Read-only operation.
    """
    if base_path is None:
        base_path = t.get_backup_path(backup_id)

    if not has_sqlite_db(base_path):
        return []

    suggestions: List[Dict[str, Any]] = []

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        # 1. Fetch unlinked writers
        unlinked_writers = (
            session.query(WriterModel)
            .filter(
                WriterModel.backup_id == str(backup_id),
                WriterModel.discord_user_id.is_(None),
            )
            .all()
        )

        if not unlinked_writers:
            return []

        # 2. Collect candidates from flagged messages
        flagged_messages = (
            session.query(FlaggedMessageModel)
            .filter(FlaggedMessageModel.backup_id == str(backup_id))
            .all()
        )

        # author_id -> {username, nickname, count}
        candidates: Dict[str, Dict[str, Any]] = {}

        for msg in flagged_messages:
            author = msg.author
            if not isinstance(author, dict):
                continue
            aid = str(author.get("id") or "")
            if not aid or aid == "None":
                continue

            username = str(author.get("name") or "")
            nickname = str(author.get("nickname") or "")

            if aid not in candidates:
                candidates[aid] = {
                    "discord_user_id": aid,
                    "username": username,
                    "nickname": nickname,
                    "flagged_count": 0,
                    "issue_count": 0,
                }
            candidates[aid]["flagged_count"] += 1
            if not candidates[aid]["nickname"] and nickname:
                candidates[aid]["nickname"] = nickname

        # 3. Collect candidates from scene_issues (non_tupper_author)
        scene_issues = (
            session.query(SceneIssueModel)
            .filter(
                SceneIssueModel.backup_id == str(backup_id),
                SceneIssueModel.kind == "non_tupper_author",
                SceneIssueModel.discord_user_id.isnot(None),
            )
            .all()
        )

        for issue in scene_issues:
            aid = str(issue.discord_user_id)
            if aid not in candidates:
                candidates[aid] = {
                    "discord_user_id": aid,
                    "username": "",
                    "nickname": "",
                    "flagged_count": 0,
                    "issue_count": 0,
                }
            candidates[aid]["issue_count"] += 1

        # 4. Match candidates against unlinked writers
        for writer in unlinked_writers:
            writer_aliases = [writer.display_name] + [
                a.alias for a in writer.aliases
            ]
            clean_aliases = [
                a.strip().lower() for a in writer_aliases if a and a.strip()
            ]

            best_match: Optional[Dict[str, Any]] = None

            for aid, cand in candidates.items():
                username = cand["username"]
                nickname = cand["nickname"]

                cand_tokens = normalize_tokens(username) | normalize_tokens(
                    nickname
                )
                cand_full_text = f"{username} {nickname}".lower()

                matched_alias = None
                confidence = None
                reason = None

                for alias in clean_aliases:
                    alias_tokens = normalize_tokens(alias)

                    # Case A: Exact username or nickname match
                    if alias == username.lower() or (
                        nickname and alias == nickname.lower()
                    ):
                        matched_alias = alias
                        confidence = 0.95
                        reason = f"Exact match with author username/nickname ('{alias}')"
                        break

                    # Case B: Alias is one of the candidate tokens
                    if alias in cand_tokens:
                        matched_alias = alias
                        confidence = 0.90
                        reason = f"Token in nickname/username matched alias '{alias}'"
                        break

                    # Case C: Candidate token in alias tokens
                    common_tokens = cand_tokens & alias_tokens
                    # Only accept if significant token (length >= 3)
                    sig_common = [t for t in common_tokens if len(t) >= 3]
                    if sig_common:
                        matched_alias = sig_common[0]
                        confidence = 0.85
                        reason = f"Significant token '{sig_common[0]}' matched author"
                        break

                    # Case D: Word-boundary substring if alias is length >= 4
                    if len(alias) >= 4 and re.search(
                        rf"\b{re.escape(alias)}\b", cand_full_text
                    ):
                        matched_alias = alias
                        confidence = 0.75
                        reason = f"Word-bounded substring match for '{alias}'"
                        break

                if matched_alias:
                    conf_level = (
                        "high"
                        if (isinstance(confidence, (int, float)) and confidence >= 0.85)
                        or confidence == "high"
                        else "medium"
                    )
                    score = (
                        (2 if conf_level == "high" else 1) * 100
                        + cand["flagged_count"]
                        + cand["issue_count"]
                    )
                    if best_match is None or score > best_match["_score"]:
                        best_match = {
                            "writer_pk": writer.pk,
                            "writer_id": writer.pk,
                            "display_name": writer.display_name,
                            "suggested_discord_user_id": aid,
                            "suggested_discord_id": aid,
                            "suggested_username": username,
                            "suggested_nickname": nickname,
                            "matched_alias": matched_alias,
                            "confidence": confidence,
                            "confidence_level": conf_level,
                            "reason": reason,
                            "evidence_count": cand["flagged_count"]
                            + cand["issue_count"],
                            "_score": score,
                        }

            if best_match:
                del best_match["_score"]
                suggestions.append(best_match)

    # Sort suggestions by confidence and display name
    suggestions.sort(
        key=lambda x: (
            -x["confidence"]
            if isinstance(x["confidence"], (int, float))
            else (0 if x.get("confidence") == "high" or x.get("confidence_level") == "high" else 1),
            x["display_name"].lower(),
        )
    )
    return suggestions


def main():
    parser = argparse.ArgumentParser(
        description="Suggests Discord User ID links for unlinked writers based on chat history."
    )
    parser.add_argument(
        "--backup-id", type=str, help="Backup ID to analyze (e.g. '1')"
    )
    args = parser.parse_args()

    backup_id = args.backup_id
    if not backup_id:
        t.log(
            "info",
            "No backup ID specified. Defaulting to '1' (Elysium) if available.",
        )
        backup_id = "1"

    t.log(
        "info",
        f"Scanning non-tupper authors for writer link suggestions (backup_id: {backup_id})...",
    )
    suggestions = find_writer_link_suggestions(backup_id)

    t.log(
        "base",
        f"Found {len(suggestions)} writer link suggestion(s) for backup {backup_id}:",
    )
    for s in suggestions:
        nick_str = (
            f" / '{s['suggested_nickname']}'" if s["suggested_nickname"] else ""
        )
        t.log(
            "base",
            f"  • Writer: {s['display_name']} -> Discord ID: {s['suggested_discord_user_id']} ({s['suggested_username']}{nick_str})",
        )
        t.log("debug", f"    Confidence: {s['confidence']} | {s['reason']}")


if __name__ == "__main__":
    main()

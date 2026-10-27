import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import func, case
from sqlalchemy.orm import selectinload, joinedload

from db.models import (
    BackupModel,
    ChannelModel,
    CharacterGroupModel,
    CharacterModel,
    ExportModel,
    FlaggedMessageModel,
    IssueKind,
    IssueReason,
    IssueResolution,
    MessageOverrideModel,
    SceneIssueModel,
    SceneModel,
    SceneParticipantModel,
    SceneStatus,
    Scope,
    WriterAliasModel,
    WriterModel,
    get_default_resolution,
    is_action_performed,
)
from db.session import db_session, require_sqlite_db, init_db
from db.snapshots import export_character_list_snapshot, export_curation_snapshots
from find_character_scenes import MENTION_ONLY_PAT, EXCERPT_MAX_LEN
from utils import exceptions as exc
import utils.tricks as t


_parse_dt = t.parse_datetime


# --- WRITERS MANAGEMENT ---


def get_writers_detailed(backup_id: str, base_path: str) -> List[Dict[str, Any]]:
    """Retrieves all writers with their aliases, discord_user_id, and written characters."""
    require_sqlite_db(base_path)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        writers = (
            session.query(WriterModel)
            .filter(WriterModel.backup_id == str(backup_id))
            .order_by(WriterModel.display_name)
            .all()
        )

        result = []
        for w in writers:
            aliases = [a.alias for a in sorted(w.aliases, key=lambda x: x.pk)]
            chars = []
            for c in w.characters:
                c_names = [n.name for n in sorted(c.names, key=lambda x: x.position)]
                chars.append({
                    "id": c.char_id,
                    "name": c_names[0] if c_names else f"Character #{c.char_id}",
                    "names": c_names,
                    "origin": c.origin,
                    "activity": c.activity,
                })
            result.append({
                "id": w.pk,
                "display_name": w.display_name,
                "discord_user_id": w.discord_user_id,
                "aliases": aliases,
                "character_count": len(chars),
                "characters": chars,
            })
        return result


def create_writer(
    backup_id: str,
    base_path: str,
    display_name: str,
    aliases: Optional[List[str]] = None,
    discord_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates a new writer and associated aliases."""
    if not display_name or not display_name.strip():
        raise ValueError("Writer display name cannot be empty.")

    clean_name = display_name.strip()
    clean_uid = discord_user_id.strip() if discord_user_id and discord_user_id.strip() else None

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        # Check duplicate display name
        existing = (
            session.query(WriterModel)
            .filter(
                WriterModel.backup_id == str(backup_id),
                func.lower(WriterModel.display_name) == clean_name.lower(),
            )
            .first()
        )
        if existing:
            raise ValueError(f"Writer '{clean_name}' already exists.")

        writer = WriterModel(
            backup_id=str(backup_id),
            display_name=clean_name,
            discord_user_id=clean_uid,
        )
        session.add(writer)
        session.flush()

        alias_set = {clean_name}
        if aliases:
            for a in aliases:
                if a and a.strip():
                    alias_set.add(a.strip())

        for a in alias_set:
            session.add(WriterAliasModel(writer_pk=writer.pk, alias=a))

        session.flush()
        export_character_list_snapshot(session, backup_id, write_to_disk=True)

        return {
            "id": writer.pk,
            "display_name": writer.display_name,
            "discord_user_id": writer.discord_user_id,
            "aliases": sorted(list(alias_set)),
            "character_count": 0,
            "characters": [],
        }


def update_writer(
    backup_id: str,
    base_path: str,
    writer_id: int,
    display_name: Optional[str] = None,
    aliases: Optional[List[str]] = None,
    discord_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Updates a writer's display name, aliases, or discord_user_id."""
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        writer = (
            session.query(WriterModel)
            .filter(
                WriterModel.pk == writer_id,
                WriterModel.backup_id == str(backup_id),
            )
            .first()
        )
        if not writer:
            raise ValueError(f"Writer #{writer_id} not found.")

        if display_name is not None and display_name.strip():
            writer.display_name = display_name.strip()

        if discord_user_id is not None:
            clean_uid = discord_user_id.strip() if discord_user_id.strip() else None
            # Check unique constraint on discord_user_id
            if clean_uid:
                clash = (
                    session.query(WriterModel)
                    .filter(
                        WriterModel.backup_id == str(backup_id),
                        WriterModel.discord_user_id == clean_uid,
                        WriterModel.pk != writer_id,
                    )
                    .first()
                )
                if clash:
                    raise ValueError(
                        f"Discord ID '{clean_uid}' is already linked to writer '{clash.display_name}'."
                    )
            writer.discord_user_id = clean_uid

        if aliases is not None:
            session.query(WriterAliasModel).filter(
                WriterAliasModel.writer_pk == writer.pk
            ).delete()
            alias_set = {writer.display_name}
            for a in aliases:
                if a and a.strip():
                    alias_set.add(a.strip())
            for a in alias_set:
                session.add(WriterAliasModel(writer_pk=writer.pk, alias=a))

        session.flush()
        export_character_list_snapshot(session, backup_id, write_to_disk=True)

        res_aliases = [a.alias for a in sorted(writer.aliases, key=lambda x: x.pk)]
        return {
            "id": writer.pk,
            "display_name": writer.display_name,
            "discord_user_id": writer.discord_user_id,
            "aliases": res_aliases,
            "character_count": len(writer.characters),
        }


def delete_writer(backup_id: str, base_path: str, writer_id: int) -> Dict[str, Any]:
    """Deletes a writer and disassociates its characters."""
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        writer = (
            session.query(WriterModel)
            .filter(
                WriterModel.pk == writer_id,
                WriterModel.backup_id == str(backup_id),
            )
            .first()
        )
        if not writer:
            raise ValueError(f"Writer #{writer_id} not found.")

        # Disassociate characters
        session.query(CharacterModel).filter(
            CharacterModel.writer_pk == writer.pk
        ).update({"writer_pk": None})

        session.delete(writer)
        session.flush()
        export_character_list_snapshot(session, backup_id, write_to_disk=True)

        return {"status": "success", "deleted_writer_id": writer_id}


def get_writer_link_suggestions(backup_id: str, base_path: str) -> List[Dict[str, Any]]:
    """Returns heuristic suggestions for linking Discord user IDs to unlinked writers."""
    try:
        from find_writer_links import find_writer_link_suggestions
        return find_writer_link_suggestions(backup_id, base_path)
    except ImportError:
        return []


# --- UNASSIGNED CHARACTERS QUEUE ---


def get_unassigned_characters(backup_id: str, base_path: str) -> List[Dict[str, Any]]:
    """Retrieves characters that currently have no writer assigned (writer_pk IS NULL)."""
    require_sqlite_db(base_path)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        chars = (
            session.query(CharacterModel)
            .filter(
                CharacterModel.backup_id == str(backup_id),
                CharacterModel.writer_pk.is_(None),
            )
            .order_by(CharacterModel.char_id)
            .all()
        )

        result = []
        for c in chars:
            c_names = [n.name for n in sorted(c.names, key=lambda x: x.position)]
            result.append({
                "id": c.char_id,
                "names": c_names,
                "origin": c.origin,
                "activity": c.activity,
                "version_type": c.version_type,
                "group_id": c.group_pk,
                "parent_id": c.parent.char_id if c.parent else None,
            })
        return result


def assign_character_writer(
    backup_id: str, base_path: str, char_id: int, writer_id: int
) -> Dict[str, Any]:
    """Assigns an unassigned character to a writer."""
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        char = (
            session.query(CharacterModel)
            .filter(
                CharacterModel.backup_id == str(backup_id),
                CharacterModel.char_id == char_id,
            )
            .first()
        )
        if not char:
            raise ValueError(f"Character #{char_id} not found.")

        writer = (
            session.query(WriterModel)
            .filter(
                WriterModel.backup_id == str(backup_id),
                WriterModel.pk == writer_id,
            )
            .first()
        )
        if not writer:
            raise ValueError(f"Writer #{writer_id} not found.")

        char.writer_pk = writer.pk
        session.flush()
        export_character_list_snapshot(session, backup_id, write_to_disk=True)

        return {
            "status": "success",
            "char_id": char.char_id,
            "writer_id": writer.pk,
            "writer_display_name": writer.display_name,
        }


# --- CHARACTER GROUPS MANAGEMENT ---


def delete_group(backup_id: str, base_path: str, group_id: int) -> Dict[str, Any]:
    """Deletes a character group and disassociates member characters."""
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        group = (
            session.query(CharacterGroupModel)
            .filter(
                CharacterGroupModel.pk == group_id,
                CharacterGroupModel.backup_id == str(backup_id),
            )
            .first()
        )
        if not group:
            raise ValueError(f"Character group #{group_id} not found.")

        # Disassociate characters
        session.query(CharacterModel).filter(
            CharacterModel.group_pk == group.pk
        ).update({"group_pk": None})

        session.delete(group)
        session.flush()
        export_character_list_snapshot(session, backup_id, write_to_disk=True)

        return {"status": "success", "deleted_group_id": group_id}


# --- SCENE ISSUES REVIEW QUEUE ---


def get_scene_issues(
    backup_id: str,
    base_path: str,
    kind: Optional[str] = None,
    reason: Optional[str] = None,
    status: Optional[str] = "unresolved",
    channel_id: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> Dict[str, Any]:
    """Queries scene issues with filtering by kind, resolution status, and channel."""
    if not isinstance(kind, str):
        kind = None
    if not isinstance(reason, str):
        reason = None
    if not isinstance(status, str):
        status = "unresolved"
    if not isinstance(channel_id, str):
        channel_id = None
    if not isinstance(page, int):
        page = 1
    if not isinstance(per_page, int):
        per_page = 50

    require_sqlite_db(base_path)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
        server_id = backup.server_id if backup else ""

        query = (
            session.query(SceneIssueModel)
            .outerjoin(SceneModel, SceneIssueModel.scene_pk == SceneModel.pk)
            .options(
                joinedload(SceneIssueModel.scene).joinedload(SceneModel.channel),
                joinedload(SceneIssueModel.next_scene),
            )
        )
        query = query.filter(SceneIssueModel.backup_id == str(backup_id))

        # TODO: Should not happen after migration
        if kind == "possible_split":
            kind = IssueKind.SOFT_BOUNDARY.value
        if kind:
            query = query.filter(SceneIssueModel.kind == kind)
        if reason:
            query = query.filter(SceneIssueModel.reason == reason)

        if status == "unresolved":
            query = query.filter(SceneIssueModel.resolved_at.is_(None))
        elif status == "resolved":
            query = query.filter(SceneIssueModel.resolved_at.isnot(None))

        if channel_id:
            query = query.join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
            query = query.filter(ChannelModel.discord_id == str(channel_id))

        total_items = query.count()

        # Compute status counts for the review queue
        counts_query = session.query(
            func.count(SceneIssueModel.pk).label("total"),
            func.coalesce(func.sum(case((SceneIssueModel.resolved_at.is_(None), 1), else_=0)), 0).label("unresolved"),
            func.coalesce(func.sum(case((SceneIssueModel.resolved_at.isnot(None), 1), else_=0)), 0).label("resolved"),
        ).filter(SceneIssueModel.backup_id == str(backup_id))

        if kind:
            counts_query = counts_query.filter(SceneIssueModel.kind == kind)
        if reason:
            counts_query = counts_query.filter(SceneIssueModel.reason == reason)
        if channel_id:
            counts_query = counts_query.join(SceneModel, SceneIssueModel.scene_pk == SceneModel.pk)
            counts_query = counts_query.join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
            counts_query = counts_query.filter(ChannelModel.discord_id == str(channel_id))

        counts_row = counts_query.first()
        status_counts = {
            "all": int(counts_row.total) if counts_row and counts_row.total is not None else 0,
            "unresolved": int(counts_row.unresolved) if counts_row and counts_row.unresolved is not None else 0,
            "resolved": int(counts_row.resolved) if counts_row and counts_row.resolved is not None else 0,
        }

        query = query.order_by(SceneIssueModel.created_at.desc(), SceneIssueModel.pk.desc())
        offset = (page - 1) * per_page
        issues_raw = query.offset(offset).limit(per_page).all()

        # Collect character IDs to resolve display names
        char_ids = set()
        for iss in issues_raw:
            if iss.previous_chars:
                for cid in iss.previous_chars:
                    if isinstance(cid, int):
                        char_ids.add(cid)
            if iss.next_chars:
                for cid in iss.next_chars:
                    if isinstance(cid, int):
                        char_ids.add(cid)

        char_name_map: Dict[int, str] = {}
        if char_ids:
            chars = (
                session.query(CharacterModel)
                .options(joinedload(CharacterModel.names))
                .filter(
                    CharacterModel.backup_id == str(backup_id),
                    CharacterModel.char_id.in_(char_ids),
                )
                .all()
            )
            for ch in chars:
                sorted_names = sorted(ch.names, key=lambda n: n.position)
                if sorted_names and sorted_names[0].name:
                    char_name_map[ch.char_id] = sorted_names[0].name
                else:
                    char_name_map[ch.char_id] = f"Character #{ch.char_id}"

        formatted = []
        for iss in issues_raw:
            scene = iss.scene
            channel = scene.channel if scene else None
            chan_id = channel.discord_id if channel else ""
            chan_name = channel.name if channel else ""
            start_msg_id = scene.start_message_id if scene else ""

            discord_link = ""
            if server_id and chan_id and start_msg_id:
                discord_link = f"https://discord.com/channels/{server_id}/{chan_id}/{start_msg_id}"

            candidate_discord_link = ""
            if server_id and chan_id and iss.candidate_message_id:
                candidate_discord_link = f"https://discord.com/channels/{server_id}/{chan_id}/{iss.candidate_message_id}"

            prev_ids = iss.previous_chars or []
            next_ids = iss.next_chars or []
            prev_names = [char_name_map.get(cid, f"#{cid}") for cid in prev_ids]
            next_names = [char_name_map.get(cid, f"#{cid}") for cid in next_ids]

            formatted.append({
                "id": iss.pk,
                "kind": iss.kind,
                "reason": iss.reason,
                "scene_pk": scene.pk if scene else None,
                "scene_key": scene.scene_key if scene else "",
                "channel_name": chan_name,
                "channel_discord_id": chan_id,
                "next_scene_pk": iss.next_scene_pk,
                "next_scene_key": iss.next_scene.scene_key if iss.next_scene else None,
                "candidate_message_id": iss.candidate_message_id,
                "candidate_index": iss.candidate_index,
                "candidate_excerpt": iss.candidate_excerpt,
                "previous_chars": prev_ids,
                "next_chars": next_ids,
                "previous_char_names": prev_names,
                "next_char_names": next_names,
                "action_performed": is_action_performed(iss.kind, iss.resolution),
                "discord_link": discord_link,
                "candidate_discord_link": candidate_discord_link,
                "created_at": iss.created_at.isoformat() if iss.created_at else None,
                "resolved_at": iss.resolved_at.isoformat() if iss.resolved_at else None,
                "resolved_note": iss.resolved_note,
                "resolution": iss.resolution,
            })

        total_pages = math.ceil(total_items / per_page) if per_page > 0 else 1
        return {
            "total_items": total_items,
            "current_page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "status_counts": status_counts,
            "issues": formatted,
        }


def _extract_scene_participants(
    messages: List[Dict[str, Any]],
    start_index: int,
    end_index: int,
    char_id_to_pk: Dict[int, int],
) -> Set[int]:
    """
    Extracts Tupperbox character bot IDs from messages in range [start_index, end_index],
    filtering out non-tuppers and mention-only posts. Returns set of character primary keys.
    """
    char_pks = set()
    for i in range(start_index, end_index + 1):
        if i < len(messages):
            m = messages[i]
            if m.get("type") == "Default":
                content = str(m.get("content", "") or "")
                if MENTION_ONLY_PAT.match(content.strip()):
                    continue
                aid = t.get_author_id(m)
                if t.is_tupper(aid) and aid in char_id_to_pk:
                    char_pks.add(char_id_to_pk[aid])
    return char_pks


def _merge_scenes(
    session,
    backup_id: str,
    base_path: str,
    s1: SceneModel,
    s2: SceneModel,
) -> SceneModel:
    """
    Merges adjacent scenes s1 and s2 in the same channel.
    s1 absorbs s2's end bounds, status and participants; s2 is deleted;
    channel scene keys are renumbered tmp- then 1..N.
    """
    if s1.channel_pk != s2.channel_pk:
        raise exc.ValidationError("Cannot merge scenes belonging to different channels.")

    if s2.start_index <= s1.end_index:
        raise exc.ValidationError(
            f"Scene 2 (start={s2.start_index}) must start after Scene 1 (end={s1.end_index})."
        )

    # Adjacency check: verify no other scene in this channel starts between s1 and s2
    intervening = (
        session.query(SceneModel)
        .filter(
            SceneModel.backup_id == str(backup_id),
            SceneModel.channel_pk == s1.channel_pk,
            SceneModel.start_index > s1.end_index,
            SceneModel.start_index < s2.start_index,
        )
        .first()
    )
    if intervening:
        raise exc.ValidationError(
            f"Cannot merge non-adjacent scenes: Scene #{intervening.pk} ({intervening.scene_key}) "
            f"starts between Scene {s1.scene_key} and Scene {s2.scene_key}."
        )

    s1_key = s1.scene_key
    s2_key = s2.scene_key

    # Extend s1 bounds and status to cover s2
    s1.end_message_id = s2.end_message_id
    s1.end_index = s2.end_index
    s1.end_at = s2.end_at
    s1.end_author_id = s2.end_author_id
    s1.end_excerpt = s2.end_excerpt
    s1.status = s2.status

    # Combine participants
    s1_char_pks = {p.character_pk for p in s1.participants}
    for p2 in s2.participants:
        if p2.character_pk not in s1_char_pks:
            session.add(SceneParticipantModel(scene_pk=s1.pk, character_pk=p2.character_pk))
            s1_char_pks.add(p2.character_pk)

    # Re-link any other issues that were associated with s2 to s1
    session.query(SceneIssueModel).filter(
        SceneIssueModel.backup_id == str(backup_id),
        SceneIssueModel.scene_pk == s2.pk,
    ).update({"scene_pk": s1.pk}, synchronize_session="fetch")

    session.query(SceneIssueModel).filter(
        SceneIssueModel.backup_id == str(backup_id),
        SceneIssueModel.next_scene_pk == s2.pk,
    ).update({"next_scene_pk": s1.pk}, synchronize_session="fetch")

    # Delete s2
    session.delete(s2)
    session.flush()

    # Renumber channel scene keys
    channel_scenes = (
        session.query(SceneModel)
        .filter(
            SceneModel.channel_pk == s1.channel_pk,
            SceneModel.backup_id == str(backup_id),
        )
        .order_by(SceneModel.start_index)
        .all()
    )
    key_prefix = s1_key.rsplit("-", 1)[0]
    for sc in channel_scenes:
        sc.scene_key = f"tmp-{sc.pk}"
    session.flush()
    for idx, sc in enumerate(channel_scenes):
        sc.scene_key = f"{key_prefix}-{idx + 1}"
    session.flush()

    # Clear SceneManager cache
    try:
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
    except Exception as e:
        t.log("error", f"SceneManager clear_cache error: {e}")

    return s1


def _split_scene_at(
    session,
    backup_id: str,
    base_path: str,
    scene: SceneModel,
    candidate_message_id: Optional[str] = None,
    candidate_index: Optional[int] = None,
    exclude_issue_pk: Optional[int] = None,
) -> Tuple[SceneModel, SceneModel]:
    """
    Splits scene into two scenes at candidate_message_id / candidate_index.
    The left half (scene) always receives status "no_end_tag".
    The right half (scene2) inherits the original scene's end bounds and status.
    Participants are partitioned, other issues re-linked, and channel keys renumbered.
    Returns (scene, scene2).
    """
    channel = scene.channel
    if not channel:
        raise exc.NotFoundError(f"Channel for scene #{scene.pk} not found in database.")

    # Locate channel JSON
    c_path = Path(channel.path)
    if (Path(base_path) / c_path).exists():
        file_path = Path(base_path) / c_path
    elif (Path(base_path) / "Data" / c_path).exists():
        file_path = Path(base_path) / "Data" / c_path
    else:
        raise exc.NotFoundError(f"Channel data file not found at {channel.path}")

    channel_data = t.load_from_json(file_path.as_posix())
    messages = channel_data.get("messages", [])

    cand_idx = None
    cand_msg = None

    if candidate_index is not None and 0 <= candidate_index < len(messages):
        if not candidate_message_id or str(messages[candidate_index].get("id")) == str(candidate_message_id):
            cand_idx = candidate_index
            cand_msg = messages[cand_idx]

    if cand_idx is None and candidate_message_id:
        for idx, m in enumerate(messages):
            if str(m.get("id")) == str(candidate_message_id):
                cand_idx = idx
                cand_msg = m
                break

    if cand_msg is None or cand_idx is None:
        raise exc.NotFoundError(
            f"Candidate message {candidate_message_id or candidate_index} not found in channel messages."
        )

    if cand_idx <= scene.start_index or cand_idx > scene.end_index:
        raise exc.ValidationError(
            f"Candidate split point index {cand_idx} is outside Scene boundaries ({scene.start_index}..{scene.end_index})."
        )

    # Find prev_msg: last Default text message before cand_idx within scene.start_index..cand_idx-1
    prev_msg = None
    prev_idx = None
    for i in range(cand_idx - 1, scene.start_index - 1, -1):
        m = messages[i]
        if m.get("type") == "Default":
            prev_msg = m
            prev_idx = i
            break
    if not prev_msg:
        prev_idx = cand_idx - 1
        prev_msg = messages[prev_idx]

    orig_end_msg_id = scene.end_message_id
    orig_end_index = scene.end_index
    orig_end_at = scene.end_at
    orig_end_author_id = scene.end_author_id
    orig_end_excerpt = scene.end_excerpt
    orig_status = scene.status
    orig_scene_key = scene.scene_key

    # Truncate Scene 1 (left half is ALWAYS "no_end_tag")
    prev_content = str(prev_msg.get("content", ""))
    scene.end_message_id = str(prev_msg.get("id", ""))
    scene.end_index = prev_idx
    scene.end_at = t.parse_datetime(prev_msg.get("timestamp")) or scene.end_at
    scene.end_author_id = str(t.get_author_id(prev_msg) or prev_msg.get("author", {}).get("id", ""))
    scene.end_excerpt = prev_content if len(prev_content) <= EXCERPT_MAX_LEN else "..." + prev_content[-(EXCERPT_MAX_LEN-3):]
    scene.status = SceneStatus.NO_END_TAG.value

    # Insert Scene 2 (right half)
    cand_content = str(cand_msg.get("content", ""))
    cand_author_id = str(t.get_author_id(cand_msg) or cand_msg.get("author", {}).get("id", ""))
    cand_at = t.parse_datetime(cand_msg.get("timestamp")) or scene.start_at
    scene2 = SceneModel(
        backup_id=str(backup_id),
        scene_key="tmp-split-new",
        channel_pk=scene.channel_pk,
        category_pk=scene.category_pk,
        status=orig_status,
        start_message_id=str(cand_msg.get("id", "")),
        end_message_id=orig_end_msg_id,
        start_index=cand_idx,
        end_index=orig_end_index,
        start_at=cand_at,
        end_at=orig_end_at,
        start_author_id=cand_author_id,
        end_author_id=orig_end_author_id,
        start_excerpt=cand_content if len(cand_content) <= EXCERPT_MAX_LEN else cand_content[:(EXCERPT_MAX_LEN-3)] + "...",
        end_excerpt=orig_end_excerpt,
    )
    session.add(scene2)
    session.flush()

    # Partition / recompute participants
    chars = session.query(CharacterModel).filter_by(backup_id=str(backup_id)).all()
    char_id_to_pk = {c.char_id: c.pk for c in chars}

    part1_pks = _extract_scene_participants(messages, scene.start_index, prev_idx, char_id_to_pk)
    part2_pks = _extract_scene_participants(messages, cand_idx, orig_end_index, char_id_to_pk)

    session.query(SceneParticipantModel).filter_by(scene_pk=scene.pk).delete()
    session.flush()

    for cpk in part1_pks:
        session.add(SceneParticipantModel(scene_pk=scene.pk, character_pk=cpk))

    for cpk in part2_pks:
        session.add(SceneParticipantModel(scene_pk=scene2.pk, character_pk=cpk))

    # Renumber scenes in channel
    channel_scenes = (
        session.query(SceneModel)
        .filter(SceneModel.channel_pk == scene.channel_pk, SceneModel.backup_id == str(backup_id))
        .order_by(SceneModel.start_index)
        .all()
    )
    key_prefix = orig_scene_key.rsplit("-", 1)[0]
    for sc in channel_scenes:
        sc.scene_key = f"tmp-{sc.pk}"
    session.flush()
    for idx, sc in enumerate(channel_scenes):
        sc.scene_key = f"{key_prefix}-{idx + 1}"
    session.flush()

    # Re-link other issues that were on Scene 1 at or after cand_idx to Scene 2
    relink_q = session.query(SceneIssueModel).filter(
        SceneIssueModel.backup_id == str(backup_id),
        SceneIssueModel.scene_pk == scene.pk,
        SceneIssueModel.candidate_index >= cand_idx,
    )
    if exclude_issue_pk is not None:
        relink_q = relink_q.filter(SceneIssueModel.pk != exclude_issue_pk)
    relink_q.update({"scene_pk": scene2.pk}, synchronize_session="fetch")

    try:
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
    except Exception as e:
        t.log("error", f"SceneManager clear_cache error: {e}")

    return scene, scene2


def get_resolved_boundary_decisions(backup_id: str, base_path: str) -> Dict[str, str]:
    """
    Returns a dictionary mapping candidate_message_id -> resolution ("merged" | "split")
    for all resolved scene issues in SQLite for this backup.
    If two decisions share a candidate id, the latest resolved_at wins.
    """
    require_sqlite_db(base_path)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        issues = (
            session.query(SceneIssueModel)
            .filter(
                SceneIssueModel.backup_id == str(backup_id),
                SceneIssueModel.resolved_at.isnot(None),
                SceneIssueModel.candidate_message_id.isnot(None),
            )
            .order_by(SceneIssueModel.resolved_at.asc())
            .all()
        )
        decisions: Dict[str, str] = {}
        for iss in issues:
            if iss.candidate_message_id and iss.resolution:
                decisions[str(iss.candidate_message_id)] = str(iss.resolution)
        return decisions


def resolve_scene_issue(
    backup_id: str,
    base_path: str,
    issue_id: int,
    resolution: str,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolves a scene issue with 'split' or 'merged'.
    If resolution equals the kind default: marks resolved.
    If resolution is the opposite: executes merge or split via helpers.
    """
    if resolution not in (IssueResolution.SPLIT.value, IssueResolution.MERGED.value):
        raise exc.ValidationError(
            f"Invalid resolution '{resolution}'. Must be 'split' or 'merged'."
        )

    require_sqlite_db(base_path)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        issue = (
            session.query(SceneIssueModel)
            .filter(
                SceneIssueModel.pk == issue_id,
                SceneIssueModel.backup_id == str(backup_id),
            )
            .first()
        )
        if not issue:
            raise exc.NotFoundError(f"Scene issue #{issue_id} not found.")

        if issue.resolved_at is not None:
            raise exc.ValidationError(
                f"Issue #{issue_id} is already resolved. Reopen it first before applying a different resolution."
            )

        default_res = get_default_resolution(issue.kind)

        # 1. No action needed: mark resolved
        if resolution == default_res:
            issue.resolved_at = datetime.now(timezone.utc)
            issue.resolution = resolution
            default_note = "Accepted split" if issue.kind == IssueKind.AUTO_SPLIT.value else "Accepted merge"
            issue.resolved_note = note.strip() if note and note.strip() else default_note
            session.flush()
            return {
                "status": "success",
                "issue_id": issue.pk,
                "resolved_at": issue.resolved_at.isoformat(),
                "resolved_note": issue.resolved_note,
                "resolution": issue.resolution,
                "action_performed": False,
            }

        # 2. Action needed: Auto-Split + Merged (merge Scene 1 and Scene 2)
        if issue.kind == IssueKind.AUTO_SPLIT.value and resolution == IssueResolution.MERGED.value:
            if not issue.scene_pk or not issue.next_scene_pk:
                raise exc.ValidationError(
                    f"Issue #{issue_id} is missing scene references (scene_pk={issue.scene_pk}, next_scene_pk={issue.next_scene_pk})."
                )
            s1 = session.query(SceneModel).filter_by(pk=issue.scene_pk, backup_id=str(backup_id)).first()
            s2 = session.query(SceneModel).filter_by(pk=issue.next_scene_pk, backup_id=str(backup_id)).first()
            if not s1 or not s2:
                raise exc.NotFoundError(f"Target scenes to merge (Scene 1 #{issue.scene_pk}, Scene 2 #{issue.next_scene_pk}) not found in database.")

            s2_key = s2.scene_key
            _merge_scenes(session, backup_id, base_path, s1, s2)

            issue.next_scene_pk = None
            issue.resolved_at = datetime.now(timezone.utc)
            issue.resolution = IssueResolution.MERGED.value
            issue.resolved_note = note.strip() if note and note.strip() else f"Merged Scene {s1.scene_key} and {s2_key} by reviewer"
            session.flush()

            return {
                "status": "success",
                "action": "merge",
                "issue_id": issue.pk,
                "scene_pk": s1.pk,
                "scene_key": s1.scene_key,
                "merged_scene_key": s2_key,
                "resolution": issue.resolution,
                "resolved_at": issue.resolved_at.isoformat(),
                "resolved_note": issue.resolved_note,
                "action_performed": True,
            }

        # 3. Action needed: Soft-Boundary + Split (split Scene 1 at candidate point)
        if issue.kind == IssueKind.SOFT_BOUNDARY.value and resolution == IssueResolution.SPLIT.value:
            if not issue.scene_pk:
                raise exc.ValidationError(f"Issue #{issue_id} is missing scene reference (scene_pk is None).")
            scene = session.query(SceneModel).filter_by(pk=issue.scene_pk, backup_id=str(backup_id)).first()
            if not scene:
                raise exc.NotFoundError(f"Target scene #{issue.scene_pk} not found in database.")

            s1, s2 = _split_scene_at(
                session,
                backup_id,
                base_path,
                scene,
                candidate_message_id=issue.candidate_message_id,
                candidate_index=issue.candidate_index,
                exclude_issue_pk=issue.pk,
            )

            issue.next_scene_pk = s2.pk
            issue.resolved_at = datetime.now(timezone.utc)
            issue.resolution = IssueResolution.SPLIT.value
            issue.resolved_note = note.strip() if note and note.strip() else f"Split at message {issue.candidate_message_id} by reviewer"
            session.flush()

            return {
                "status": "success",
                "action": "split",
                "issue_id": issue.pk,
                "scene_pk": s1.pk,
                "scene_key": s1.scene_key,
                "next_scene_pk": s2.pk,
                "next_scene_key": s2.scene_key,
                "resolution": issue.resolution,
                "resolved_at": issue.resolved_at.isoformat(),
                "resolved_note": issue.resolved_note,
                "action_performed": True,
            }

        raise exc.ValidationError(f"Invalid resolution '{resolution}' for issue kind '{issue.kind}'.")


def reopen_scene_issue(backup_id: str, base_path: str, issue_id: int) -> Dict[str, Any]:
    """
    Reopens a previously resolved scene issue.
    If an action was performed (merge or split), undoes the action:
      - auto_split + merged: splits scene_pk at candidate point and restores next_scene_pk
      - soft_boundary + split: merges scene_pk and next_scene_pk and clears next_scene_pk
    If no action was performed: only clears resolution fields.
    """
    require_sqlite_db(base_path)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        issue = (
            session.query(SceneIssueModel)
            .filter(
                SceneIssueModel.pk == issue_id,
                SceneIssueModel.backup_id == str(backup_id),
            )
            .first()
        )
        if not issue:
            raise exc.NotFoundError(f"Scene issue #{issue_id} not found.")

        if is_action_performed(issue.kind, issue.resolution):
            if issue.kind == IssueKind.AUTO_SPLIT.value:
                # Was merged, undo by splitting at candidate point
                if not issue.scene_pk:
                    raise exc.ValidationError(f"Issue #{issue_id} is missing scene_pk for undoing merge.")
                s1 = session.query(SceneModel).filter_by(pk=issue.scene_pk, backup_id=str(backup_id)).first()
                if not s1:
                    raise exc.NotFoundError(f"Scene #{issue.scene_pk} not found in database.")
                s1, new_s2 = _split_scene_at(
                    session,
                    backup_id,
                    base_path,
                    s1,
                    candidate_message_id=issue.candidate_message_id,
                    candidate_index=issue.candidate_index,
                    exclude_issue_pk=issue.pk,
                )
                issue.next_scene_pk = new_s2.pk

            elif issue.kind == IssueKind.SOFT_BOUNDARY.value:
                # Was split, undo by merging scene_pk and next_scene_pk
                if not issue.scene_pk or not issue.next_scene_pk:
                    raise exc.ValidationError(
                        f"Issue #{issue_id} missing scene references for undoing split: scene_pk={issue.scene_pk}, next_scene_pk={issue.next_scene_pk}."
                    )
                s1 = session.query(SceneModel).filter_by(pk=issue.scene_pk, backup_id=str(backup_id)).first()
                s2 = session.query(SceneModel).filter_by(pk=issue.next_scene_pk, backup_id=str(backup_id)).first()
                if not s1 or not s2:
                    raise exc.NotFoundError(f"Target scenes to merge for undo not found (Scene 1 #{issue.scene_pk}, Scene 2 #{issue.next_scene_pk}).")
                _merge_scenes(session, backup_id, base_path, s1, s2)
                issue.next_scene_pk = None

        issue.resolved_at = None
        issue.resolved_note = None
        issue.resolution = None
        session.flush()

        return {
            "status": "success",
            "issue_id": issue.pk,
            "reopened": True,
        }


def merge_auto_split_scenes(backup_id: str, base_path: str, issue_id: int, note: Optional[str] = None) -> Dict[str, Any]:
    return resolve_scene_issue(backup_id, base_path, issue_id, resolution=IssueResolution.MERGED.value, note=note)


def split_possible_split_scene(backup_id: str, base_path: str, issue_id: int, note: Optional[str] = None) -> Dict[str, Any]:
    return resolve_scene_issue(backup_id, base_path, issue_id, resolution=IssueResolution.SPLIT.value, note=note)


# --- FLAGGED MESSAGES & OVERRIDES ---


def suggest_character_for_non_tupper(
    session,
    backup_id: str,
    discord_user_id: Optional[str],
    content: Optional[str] = "",
    scene_tupper_char_ids: Optional[List[int]] = None,
    writer_cache: Optional[Dict[str, Any]] = None,
    all_chars_cache: Optional[List[Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Resolves a suggested tupper character for a non-tupper message posted by discord_user_id.
    Heuristics:
      1. Priority 1 (name_prefix): content starts with '<CharName>:' (writer's characters, or any if unlinked).
      2. Priority 2 (active_in_scene): intersect writer's characters with scene's tupper characters.
      3. Priority 3 (only_character): if writer only owns 1 top-level character.
    """
    clean_uid = str(discord_user_id).strip() if discord_user_id else None
    content_clean = (content or "").lstrip()

    writer = None
    if clean_uid:
        if writer_cache is not None:
            writer = writer_cache.get(clean_uid)
        else:
            writer = (
                session.query(WriterModel)
                .options(
                    selectinload(WriterModel.characters).selectinload(CharacterModel.names)
                )
                .filter(
                    WriterModel.backup_id == str(backup_id),
                    WriterModel.discord_user_id == clean_uid,
                )
                .first()
            )

    writer_characters = list(writer.characters) if writer else []

    # Priority 1: name_prefix
    if content_clean:
        if writer:
            for c in writer_characters:
                c_names = [n.name for n in sorted(c.names, key=lambda x: x.position)]
                primary_name = c_names[0] if c_names else f"Character #{c.char_id}"
                for name in c_names:
                    if name and content_clean.lower().startswith(f"{name.lower()}:"):
                        return {
                            "char_id": c.char_id,
                            "name": primary_name,
                            "writer_name": writer.display_name,
                            "reason": "name_prefix",
                        }
        else:
            if all_chars_cache is not None:
                all_chars = all_chars_cache
            else:
                all_chars = (
                    session.query(CharacterModel)
                    .options(
                        selectinload(CharacterModel.names),
                        joinedload(CharacterModel.writer),
                    )
                    .filter(CharacterModel.backup_id == str(backup_id))
                    .all()
                )
            for c in all_chars:
                c_names = [n.name for n in sorted(c.names, key=lambda x: x.position)]
                primary_name = c_names[0] if c_names else f"Character #{c.char_id}"
                for name in c_names:
                    if name and content_clean.lower().startswith(f"{name.lower()}:"):
                        w_name = c.writer.display_name if c.writer else None
                        return {
                            "char_id": c.char_id,
                            "name": primary_name,
                            "writer_name": w_name,
                            "reason": "name_prefix",
                        }

    # Priority 2: active_in_scene
    if writer and scene_tupper_char_ids:
        active = [c for c in writer_characters if c.char_id in scene_tupper_char_ids]
        if active:
            chosen = active[0]
            c_names = [n.name for n in sorted(chosen.names, key=lambda x: x.position)]
            primary_name = c_names[0] if c_names else f"Character #{chosen.char_id}"
            return {
                "char_id": chosen.char_id,
                "name": primary_name,
                "writer_name": writer.display_name,
                "reason": "active_in_scene",
            }

    # Priority 3: only_character
    if writer:
        top_level = [c for c in writer_characters if c.parent_pk is None]
        chosen = None
        if len(top_level) == 1:
            chosen = top_level[0]
        elif len(writer_characters) == 1:
            chosen = writer_characters[0]

        if chosen:
            c_names = [n.name for n in sorted(chosen.names, key=lambda x: x.position)]
            primary_name = c_names[0] if c_names else f"Character #{chosen.char_id}"
            return {
                "char_id": chosen.char_id,
                "name": primary_name,
                "writer_name": writer.display_name,
                "reason": "only_character",
            }

    return None


def get_flagged_messages(
    backup_id: str,
    base_path: str,
    kind: Optional[str] = None,
    channel_id: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> Dict[str, Any]:
    """Queries flagged messages awaiting curation review."""
    if not isinstance(kind, str):
        kind = None
    if not isinstance(channel_id, str):
        channel_id = None
    if not isinstance(page, int):
        page = 1
    if not isinstance(per_page, int):
        per_page = 50

    require_sqlite_db(base_path)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
        server_id = backup.server_id if backup else ""

        query = session.query(FlaggedMessageModel).filter(FlaggedMessageModel.backup_id == str(backup_id))

        if kind:
            query = query.filter(FlaggedMessageModel.kind == kind)

        if channel_id:
            query = query.join(ChannelModel, FlaggedMessageModel.channel_pk == ChannelModel.pk)
            query = query.filter(ChannelModel.discord_id == str(channel_id))

        total_items = query.count()

        query = query.order_by(FlaggedMessageModel.flagged_at.desc(), FlaggedMessageModel.pk.desc())
        offset = (page - 1) * per_page
        msgs_raw = query.offset(offset).limit(per_page).all()

        # Batch-fetch scenes and writers to prevent N+1 queries
        chan_pks = {f.channel_pk for f in msgs_raw if f.channel_pk}
        chan_scenes_map: Dict[int, List[SceneModel]] = {}
        if chan_pks:
            fetched_scenes = (
                session.query(SceneModel)
                .options(
                    selectinload(SceneModel.participants).joinedload(SceneParticipantModel.character)
                )
                .filter(SceneModel.channel_pk.in_(chan_pks))
                .all()
            )
            for sc in fetched_scenes:
                chan_scenes_map.setdefault(sc.channel_pk, []).append(sc)

        page_author_ids = {
            str(f.author.get("id")).strip()
            for f in msgs_raw
            if isinstance(f.author, dict) and f.author.get("id")
        }
        page_writers = (
            session.query(WriterModel)
            .options(
                selectinload(WriterModel.characters).selectinload(CharacterModel.names)
            )
            .filter(
                WriterModel.backup_id == str(backup_id),
                WriterModel.discord_user_id.in_(page_author_ids),
            )
            .all()
        ) if page_author_ids else []
        writer_cache = {str(w.discord_user_id).strip(): w for w in page_writers if w.discord_user_id}

        formatted = []
        for f in msgs_raw:
            channel = f.channel
            chan_id = channel.discord_id if channel else ""
            chan_name = channel.name if channel else ""

            discord_link = ""
            if server_id and chan_id and f.message_id:
                discord_link = f"https://discord.com/channels/{server_id}/{chan_id}/{f.message_id}"

            # Suggest character
            author_id = f.author.get("id") if isinstance(f.author, dict) else None
            scene_tupper_char_ids = None
            if f.channel_pk:
                chan_scenes = chan_scenes_map.get(f.channel_pk, [])
                if chan_scenes:
                    chosen_scene = None
                    try:
                        f_mid = int(f.message_id)
                        for sc in chan_scenes:
                            s_mid = int(sc.start_message_id) if sc.start_message_id and str(sc.start_message_id).isdigit() else 0
                            e_mid = int(sc.end_message_id) if sc.end_message_id and str(sc.end_message_id).isdigit() else 0
                            if s_mid <= f_mid <= e_mid:
                                chosen_scene = sc
                                break
                        if not chosen_scene:
                            chosen_scene = min(
                                chan_scenes,
                                key=lambda sc: min(
                                    abs(f_mid - (int(sc.start_message_id) if sc.start_message_id and str(sc.start_message_id).isdigit() else 0)),
                                    abs(f_mid - (int(sc.end_message_id) if sc.end_message_id and str(sc.end_message_id).isdigit() else 0))
                                )
                            )
                    except (ValueError, TypeError):
                        chosen_scene = chan_scenes[0]

                    if chosen_scene:
                        scene_tupper_char_ids = [
                            p.character.char_id
                            for p in chosen_scene.participants
                            if p.character and t.is_tupper(p.character.char_id)
                        ]

            suggested = suggest_character_for_non_tupper(
                session=session,
                backup_id=str(backup_id),
                discord_user_id=author_id,
                content=f.content,
                scene_tupper_char_ids=scene_tupper_char_ids,
                writer_cache=writer_cache,
            )

            formatted.append({
                "id": f.pk,
                "message_id": f.message_id,
                "kind": f.kind,
                "channel_name": chan_name,
                "channel_discord_id": chan_id,
                "content": f.content,
                "author": f.author,
                "discord_link": discord_link,
                "flagged_at": f.flagged_at.isoformat() if f.flagged_at else None,
                "suggested_character": suggested,
            })

        total_pages = math.ceil(total_items / per_page) if per_page > 0 else 1
        return {
            "total_items": total_items,
            "current_page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "messages": formatted,
        }

def promote_flagged_message(
    backup_id: str,
    base_path: str,
    message_id: str,
    content: Optional[str] = None,
    author: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Promotes a flagged message into a permanent message override and removes it from the flagged queue."""
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        flagged = (
            session.query(FlaggedMessageModel)
            .filter(
                FlaggedMessageModel.backup_id == str(backup_id),
                FlaggedMessageModel.message_id == str(message_id),
            )
            .first()
        )
        if not flagged:
            raise ValueError(f"Flagged message #{message_id} not found.")

        # Check existing override or insert
        override = (
            session.query(MessageOverrideModel)
            .filter(
                MessageOverrideModel.backup_id == str(backup_id),
                MessageOverrideModel.message_id == str(message_id),
            )
            .first()
        )

        now_utc = datetime.now(timezone.utc)
        target_content = content if content is not None else flagged.content
        target_author = author if author is not None else flagged.author

        if isinstance(target_author, dict) and "id" in target_author:
            target_author = dict(target_author)
            clean_id = str(target_author["id"]).strip()
            target_author["id"] = clean_id
            if clean_id.isdigit() and t.is_tupper(int(clean_id)) and "isBot" not in target_author:
                target_author["isBot"] = True

        if override:
            override.content = target_content
            override.author = target_author
            override.channel_pk = flagged.channel_pk
        else:
            override = MessageOverrideModel(
                backup_id=str(backup_id),
                message_id=str(message_id),
                channel_pk=flagged.channel_pk,
                content=target_content,
                author=target_author,
                created_at=now_utc,
            )
            session.add(override)

        # Remove from flagged messages
        session.delete(flagged)
        session.flush()

        return {
            "status": "success",
            "message_id": message_id,
            "override_id": override.pk,
            "promoted_at": now_utc.isoformat(),
        }


def get_message_overrides(
    backup_id: str, base_path: str, page: int = 1, per_page: int = 50
) -> Dict[str, Any]:
    """Retrieves all active message overrides for the backup."""
    if not isinstance(page, int):
        page = 1
    if not isinstance(per_page, int):
        per_page = 50

    require_sqlite_db(base_path)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
        server_id = backup.server_id if backup else ""

        query = session.query(MessageOverrideModel).filter(MessageOverrideModel.backup_id == str(backup_id))
        total_items = query.count()

        query = query.order_by(MessageOverrideModel.created_at.desc(), MessageOverrideModel.pk.desc())
        offset = (page - 1) * per_page
        overrides_raw = query.offset(offset).limit(per_page).all()

        formatted = []
        for o in overrides_raw:
            channel = o.channel
            chan_id = channel.discord_id if channel else ""
            chan_name = channel.name if channel else ""

            discord_link = ""
            if server_id and chan_id and o.message_id:
                discord_link = f"https://discord.com/channels/{server_id}/{chan_id}/{o.message_id}"

            formatted.append({
                "id": o.pk,
                "message_id": o.message_id,
                "channel_name": chan_name,
                "channel_discord_id": chan_id,
                "content": o.content,
                "author": o.author,
                "discord_link": discord_link,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            })

        total_pages = math.ceil(total_items / per_page) if per_page > 0 else 1
        return {
            "total_items": total_items,
            "current_page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "overrides": formatted,
        }


def delete_message_override(backup_id: str, base_path: str, message_id: str) -> Dict[str, Any]:
    """Deletes an active message override."""
    require_sqlite_db(base_path)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        override = (
            session.query(MessageOverrideModel)
            .filter(
                MessageOverrideModel.backup_id == str(backup_id),
                MessageOverrideModel.message_id == str(message_id),
            )
            .first()
        )
        if not override:
            raise ValueError(f"Message override #{message_id} not found.")

        session.delete(override)
        session.flush()

        return {"status": "success", "deleted_override_message_id": message_id}


def get_overrides_map(backup_id: str, base_path: str) -> Dict[str, Dict[str, Any]]:
    """
    Returns a dictionary mapping message_id -> {"content": ..., "author": ...}
    for all active message overrides in SQLite.
    """
    require_sqlite_db(base_path)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        overrides = session.query(MessageOverrideModel).filter(
            MessageOverrideModel.backup_id == str(backup_id)
        ).all()
        return {
            str(o.message_id): {
                "content": o.content,
                "author": o.author,
            }
            for o in overrides
        }


def save_flagged_messages(
    backup_id: str,
    base_path: str,
    flagged_items: List[Dict[str, Any]],
    debug_files: bool = False
) -> None:
    """
    Replaces FlaggedMessageModel rows in SQLite with newly discovered flagged messages from fix_bad_messages.
    Optionally exports debug JSON snapshots (bad_messages.json, bad_end_messages.json, fixed_messages.json).
    """
    require_sqlite_db(base_path)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    now_utc = datetime.now(timezone.utc)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        # Clear previous flagged messages
        session.query(FlaggedMessageModel).filter(
            FlaggedMessageModel.backup_id == str(backup_id)
        ).delete()

        # Build discord_id -> channel_pk map
        channels = session.query(ChannelModel).join(ExportModel).filter(
            ExportModel.backup_id == str(backup_id),
            ExportModel.scope == Scope.BASE.value
        ).all()
        chan_map = {ch.discord_id: ch.pk for ch in channels}

        for item in flagged_items:
            chan_discord_id = str(item.get("channel_discord_id") or "")
            flagged = FlaggedMessageModel(
                backup_id=str(backup_id),
                message_id=str(item["message_id"]),
                channel_pk=chan_map.get(chan_discord_id),
                kind=str(item.get("kind", "non_tupper")),
                content=str(item.get("content", "")),
                author=item.get("author", {}),
                flagged_at=item.get("flagged_at") or now_utc,
            )
            session.add(flagged)

        session.flush()

        if debug_files:
            export_curation_snapshots(session, backup_id, base_path)


# --- 'BY ME' USER LINKING ---


def get_my_writer(
    backup_id: str, base_path: str, discord_user_id: str
) -> Optional[Dict[str, Any]]:
    """Resolves the writer associated with the current user's Discord snowflake."""
    if not discord_user_id:
        return None
    require_sqlite_db(base_path)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        writer = (
            session.query(WriterModel)
            .filter(
                WriterModel.backup_id == str(backup_id),
                WriterModel.discord_user_id == str(discord_user_id),
            )
            .first()
        )
        if not writer:
            return None

        char_ids = [c.char_id for c in writer.characters]
        aliases = [a.alias for a in writer.aliases]
        return {
            "id": writer.pk,
            "display_name": writer.display_name,
            "discord_user_id": writer.discord_user_id,
            "aliases": aliases,
            "character_ids": char_ids,
        }


def get_curation_summary(backup_id: str, base_path: str) -> Dict[str, int]:
    """Returns real-time badge counts for curation review queues and unassigned data."""
    require_sqlite_db(base_path)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)
    suggestions = get_writer_link_suggestions(backup_id, base_path)
    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        return {
            "unresolved_issues": session.query(func.count(SceneIssueModel.pk)).filter(
                SceneIssueModel.backup_id == str(backup_id),
                SceneIssueModel.resolved_at.is_(None)
            ).scalar() or 0,
            "unassigned_characters": session.query(func.count(CharacterModel.pk)).filter(
                CharacterModel.backup_id == str(backup_id),
                CharacterModel.writer_pk.is_(None)
            ).scalar() or 0,
            "flagged_messages": session.query(func.count(FlaggedMessageModel.pk)).filter(
                FlaggedMessageModel.backup_id == str(backup_id)
            ).scalar() or 0,
            "unlinked_writers": session.query(func.count(WriterModel.pk)).filter(
                WriterModel.backup_id == str(backup_id),
                WriterModel.discord_user_id.is_(None)
            ).scalar() or 0,
            "link_suggestions": len(suggestions),
        }



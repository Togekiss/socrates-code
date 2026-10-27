from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload, joinedload

from db.session import db_session, require_sqlite_db, init_db
from db.models import (
    SceneModel,
    SceneParticipantModel,
    SceneIssueModel,
    ChannelModel,
    CharacterModel,
    WriterModel,
    WriterAliasModel,
    BackupModel,
    ExportModel,
    Scope,
    SceneStatus,
    IssueKind,
)
from find_character_scenes import EXCERPT_MAX_LEN
import utils.tricks as t

_parse_dt = t.parse_datetime


def save_indexed_scenes(
    backup_id: str,
    base_path: str,
    scenes: List[Dict[str, Any]],
    debug_files: bool = False
) -> None:
    """
    Persists indexed scenes, participants, and detected issues into SQLite.
    Preserves existing resolved issue notes (resolved_at, resolved_note) across re-indexing runs.
    Optionally exports debug JSON snapshots (_scenes.json) if debug_files is True.
    """
    require_sqlite_db(base_path)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        # 1. Delete unresolved issues and capture surviving resolved issues across re-indexing runs
        session.query(SceneIssueModel).filter(
            SceneIssueModel.backup_id == str(backup_id),
            SceneIssueModel.resolved_at.is_(None),
        ).delete()
        session.flush()

        existing_resolved = (
            session.query(SceneIssueModel)
            .filter(
                SceneIssueModel.backup_id == str(backup_id),
                SceneIssueModel.resolved_at.isnot(None),
            )
            .order_by(SceneIssueModel.resolved_at.asc())
            .all()
        )
        resolved_by_candidate: Dict[str, SceneIssueModel] = {
            str(iss.candidate_message_id): iss for iss in existing_resolved if iss.candidate_message_id
        }

        # Detach surviving resolved issues from scene foreign keys so re-linking can attach them cleanly
        session.query(SceneIssueModel).filter(
            SceneIssueModel.backup_id == str(backup_id),
            SceneIssueModel.resolved_at.isnot(None),
        ).update({"scene_pk": None, "next_scene_pk": None}, synchronize_session="fetch")
        session.flush()

        # 2. Delete existing scene participants for this backup explicitly
        old_scene_pks = session.query(SceneModel.pk).filter(SceneModel.backup_id == str(backup_id))
        session.query(SceneParticipantModel).filter(
            SceneParticipantModel.scene_pk.in_(old_scene_pks)
        ).delete(synchronize_session=False)

        # Delete existing scenes for this backup
        session.query(SceneModel).filter(SceneModel.backup_id == str(backup_id)).delete()
        session.flush()

        # 3. Cache channels and characters for fast lookups
        export = (
            session.query(ExportModel)
            .filter(
                ExportModel.backup_id == str(backup_id),
                ExportModel.scope == Scope.BASE.value,
            )
            .first()
        )
        export_pk = export.pk if export else None

        channels = (
            session.query(ChannelModel)
            .filter(ChannelModel.export_pk == export_pk)
            .all()
        ) if export_pk else []
        chan_by_discord_id = {ch.discord_id: ch for ch in channels}
        chan_by_pk = {ch.pk: ch for ch in channels}

        chars = (
            session.query(CharacterModel)
            .options(
                selectinload(CharacterModel.names),
                joinedload(CharacterModel.writer)
            )
            .filter(CharacterModel.backup_id == str(backup_id))
            .all()
        )
        char_id_to_pk = {c.char_id: c.pk for c in chars}

        # 4. Group scenes by channelId to build accurate hierarchical keys
        scenes_by_channel: Dict[str, List[Dict[str, Any]]] = {}
        for s in scenes:
            chan_id = str(s.get("channelId") or s.get("channel", {}).get("id", ""))
            scenes_by_channel.setdefault(chan_id, []).append(s)

        all_created_scene_models: List[SceneModel] = []
        channel_scenes_map: Dict[int, List[Tuple[SceneModel, Dict[str, Any]]]] = {}

        for chan_discord_id, chan_scenes in scenes_by_channel.items():
            chan_scenes.sort(key=lambda x: x.get("start", {}).get("index", 0))
            chan_model = chan_by_discord_id.get(chan_discord_id)
            if not chan_model:
                continue

            if chan_model.type == "GuildPublicThread" and chan_model.parent_pk:
                parent_chan = chan_by_pk.get(chan_model.parent_pk)
                cat_chan = chan_by_pk.get(parent_chan.parent_pk) if parent_chan and parent_chan.parent_pk else parent_chan
                category_pk = cat_chan.pk if cat_chan else chan_model.pk
                key_prefix = f"{cat_chan.position if cat_chan else 0}-{parent_chan.position if parent_chan else 0}-{chan_model.position}"
            else:
                cat_chan = chan_by_pk.get(chan_model.parent_pk) if chan_model.parent_pk else chan_model
                category_pk = cat_chan.pk if cat_chan else chan_model.pk
                key_prefix = f"{cat_chan.position if cat_chan else 0}-{chan_model.position}"

            created_scenes: List[Tuple[SceneModel, Dict[str, Any]]] = []
            for idx, s in enumerate(chan_scenes):
                scene_key = f"{key_prefix}-{idx + 1}"
                lifecycle_status = s.get("status", SceneStatus.CLOSED.value)

                start_at = _parse_dt(s.get("start", {}).get("timestamp")) or datetime.now(timezone.utc)
                end_at = _parse_dt(s.get("end", {}).get("timestamp")) or datetime.now(timezone.utc)
                start_msg_id = str(s.get("start", {}).get("id", ""))
                end_msg_id = str(s.get("end", {}).get("id", ""))
                start_message = str(s.get("start", {}).get("content", ""))
                start_excerpt = start_message if len(start_message) <= EXCERPT_MAX_LEN else start_message[:EXCERPT_MAX_LEN-3] + "..."
                end_message = str(s.get("end", {}).get("content", ""))
                end_excerpt = end_message if len(end_message) <= EXCERPT_MAX_LEN else "..." + end_message[-(EXCERPT_MAX_LEN-3):]

                scene_model = SceneModel(
                    backup_id=str(backup_id),
                    scene_key=scene_key,
                    channel_pk=chan_model.pk,
                    category_pk=category_pk,
                    status=lifecycle_status,
                    start_message_id=start_msg_id,
                    end_message_id=end_msg_id,
                    start_index=int(s.get("start", {}).get("index", 0)),
                    end_index=int(s.get("end", {}).get("index", 0)),
                    start_at=start_at,
                    end_at=end_at,
                    start_author_id=str(s.get("start", {}).get("authorID") or s.get("start", {}).get("author", {}).get("id", "")),
                    end_author_id=str(s.get("end", {}).get("authorID") or s.get("end", {}).get("author", {}).get("id", "")),
                    start_excerpt=start_excerpt,
                    end_excerpt=end_excerpt,
                )
                session.add(scene_model)
                created_scenes.append((scene_model, s))
                all_created_scene_models.append(scene_model)
                channel_scenes_map.setdefault(chan_model.pk, []).append((scene_model, s))

            session.flush()

            for idx, (scene_model, s) in enumerate(created_scenes):
                # Add participants (deduplicating to prevent unique constraint collisions)
                seen_char_pks = set()
                for participant_id in s.get("characters", []):
                    try:
                        p_int = int(participant_id)
                    except (ValueError, TypeError):
                        continue

                    if p_int in char_id_to_pk:
                        char_pk = char_id_to_pk[p_int]
                        if char_pk not in seen_char_pks:
                            seen_char_pks.add(char_pk)
                            session.add(SceneParticipantModel(
                                scene_pk=scene_model.pk,
                                character_pk=char_pk
                            ))

                # Identify next scene in channel if this scene was auto-split
                next_scene_model = created_scenes[idx + 1][0] if idx + 1 < len(created_scenes) else None
                next_scene_pk = next_scene_model.pk if next_scene_model else None

                # Persist auto_split and soft_boundary issues that haven't been resolved yet
                for iss in s.get("issues", []):
                    ikind = iss.get("kind")
                    # TODO: Should not happen after migration
                    if ikind == "possible_split":
                        ikind = IssueKind.SOFT_BOUNDARY.value

                    if ikind in (IssueKind.AUTO_SPLIT.value, IssueKind.SOFT_BOUNDARY.value):
                        cand_id = iss.get("candidate_id")
                        cand_id_str = str(cand_id) if cand_id else None
                        cand_idx = iss.get("candidate_index")

                        # If this candidate point has already been resolved by reviewer, skip inserting duplicate
                        if not cand_id_str or cand_id_str in resolved_by_candidate:
                            continue

                        cand_excerpt = iss.get("candidate_excerpt")
                        if cand_excerpt:
                            cand_excerpt = str(cand_excerpt) if len(str(cand_excerpt)) <= EXCERPT_MAX_LEN else str(cand_excerpt)[:(EXCERPT_MAX_LEN-3)] + "..."
                        prev_chars = iss.get("previous_chars") or []
                        nxt_chars = iss.get("next_chars") or []
                        reason = iss.get("reason") or ""

                        session.add(SceneIssueModel(
                            backup_id=str(backup_id),
                            scene_pk=scene_model.pk,
                            next_scene_pk=next_scene_pk if ikind == IssueKind.AUTO_SPLIT.value else None,
                            kind=ikind,
                            reason=reason,
                            candidate_message_id=cand_id_str,
                            candidate_index=int(cand_idx) if cand_idx is not None else None,
                            candidate_excerpt=cand_excerpt,
                            previous_chars=prev_chars,
                            next_chars=nxt_chars,
                            created_at=scene_model.start_at,
                            resolved_at=None,
                            resolved_note=None,
                            resolution=None,
                        ))

        # 5. Re-link surviving resolved issues to newly generated scenes using indexer-reported tags
        applied_cand_ids = set()
        for chan_pk, chan_scenes in channel_scenes_map.items():
            for sc_idx, (sc_model, s_dict) in enumerate(chan_scenes):
                # Role 'start': forced cut on split decision
                res_start = s_dict.get("resolved_start")
                if res_start and str(res_start) in resolved_by_candidate:
                    iss = resolved_by_candidate[str(res_start)]
                    prev_sc = chan_scenes[sc_idx - 1][0] if sc_idx > 0 else None
                    iss.scene_pk = prev_sc.pk if prev_sc else None
                    iss.next_scene_pk = sc_model.pk
                    applied_cand_ids.add(str(res_start))

                # Role 'inside': candidate(s) inside this scene suppressed by a 'merged' decision
                res_inside = s_dict.get("resolved_inside", [])
                for cand_id in res_inside:
                    cand_id_str = str(cand_id)
                    if cand_id_str in resolved_by_candidate:
                        iss = resolved_by_candidate[cand_id_str]
                        iss.scene_pk = sc_model.pk
                        iss.next_scene_pk = None
                        applied_cand_ids.add(cand_id_str)

        unapplied_count = len(resolved_by_candidate) - len(applied_cand_ids)
        if unapplied_count > 0:
            t.log("info", f"{unapplied_count} resolved curation decision(s) were unapplied/orphaned during re-indexing.")

        session.flush()

    # 5. Optionally export debug snapshots
    if debug_files:
        data_dir = Path(base_path) / "Data"
        data_dir.mkdir(parents=True, exist_ok=True)
        t.save_json_atomic(scenes, (data_dir / "_scenes.json").as_posix())


def query_scenes(
    backup_id: str,
    base_path: str,
    categories: Optional[List[str]] = None,
    statuses: Optional[List[str]] = None,
    status: str = "all",
    types: Optional[List[str]] = None,
    character_ids: Optional[List[int]] = None,
    character_logic: str = "OR",
    writer_names: Optional[List[str]] = None,
    writer_logic: str = "OR",
    include_alter_egos: bool = False,
    include_familiars: bool = False,
    include_npcs: bool = False,
    search_folder: str = "",
    before: Optional[str] = None,
    after: Optional[str] = None,
    page: Optional[int] = None,
    per_page: int = 50,
    **kwargs
) -> Any:
    """
    Queries scenes from SQLite.
    Supports both unpaginated filtering (when page is None) and paginated responses (when page is int).
    """
    require_sqlite_db(base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
        server_id = backup.server_id if backup and backup.server_id else ""

        query = session.query(SceneModel).filter(SceneModel.backup_id == str(backup_id))

        # Filter by status
        if statuses and isinstance(statuses, (list, tuple, set)):
            query = query.filter(SceneModel.status.in_(statuses))
        elif status and status != "all":
            query = query.filter(SceneModel.status == status)

        # Filter by categories
        if categories and isinstance(categories, (list, tuple, set)):
            cat_subquery = session.query(ChannelModel.pk).filter(
                ChannelModel.name.in_(categories)
            )
            query = query.filter(SceneModel.category_pk.in_(cat_subquery))

        # Filter by types (channel vs thread)
        if types and isinstance(types, (list, tuple, set)):
            is_chan = "channel" in types
            is_thread = "thread" in types
            if is_chan and not is_thread:
                chan_subquery = session.query(ChannelModel.pk).filter(ChannelModel.type != "GuildPublicThread")
                query = query.filter(SceneModel.channel_pk.in_(chan_subquery))
            elif is_thread and not is_chan:
                chan_subquery = session.query(ChannelModel.pk).filter(ChannelModel.type == "GuildPublicThread")
                query = query.filter(SceneModel.channel_pk.in_(chan_subquery))
            elif not is_chan and not is_thread:
                chan_subquery = session.query(ChannelModel.pk).filter(ChannelModel.type.in_(types))
                query = query.filter(SceneModel.channel_pk.in_(chan_subquery))

        # Filter by search_folder
        if search_folder:
            clean_sf = search_folder.strip("/\\").lower()
            query = query.join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
            query = query.filter(func.lower(ChannelModel.path).contains(clean_sf))

        # Filter by before/after dates
        if before:
            before_dt = _parse_dt(before)
            if before_dt:
                query = query.filter(SceneModel.start_at < before_dt)
        if after:
            after_dt = _parse_dt(after)
            if after_dt:
                query = query.filter(SceneModel.start_at > after_dt)

        # Filter by character_ids
        if character_ids and isinstance(character_ids, (list, tuple, set)):
            resolved_clusters = []
            for cid in character_ids:
                family_pks = set()
                char = session.query(CharacterModel).filter(
                    CharacterModel.backup_id == str(backup_id),
                    CharacterModel.char_id == cid
                ).first()
                if char:
                    family_pks.add(char.pk)
                    for child in char.children:
                        vt = child.version_type
                        if include_alter_egos and vt == "alter_ego":
                            family_pks.add(child.pk)
                        if include_familiars and vt == "familiar":
                            family_pks.add(child.pk)
                        if include_npcs and vt == "npc":
                            family_pks.add(child.pk)
                resolved_clusters.append(family_pks)

            if character_logic == "AND":
                for cluster in resolved_clusters:
                    if cluster:
                        query = query.filter(
                            SceneModel.participants.any(SceneParticipantModel.character_pk.in_(cluster))
                        )
                    else:
                        return {"total_items": 0, "current_page": page or 1, "per_page": per_page, "total_pages": 0, "scenes": []} if page is not None else []
            else:
                all_target_pks = set().union(*resolved_clusters)
                if all_target_pks:
                    query = query.filter(
                        SceneModel.participants.any(SceneParticipantModel.character_pk.in_(all_target_pks))
                    )
                else:
                    return {"total_items": 0, "current_page": page or 1, "per_page": per_page, "total_pages": 0, "scenes": []} if page is not None else []

        # Filter by writers
        if writer_names and isinstance(writer_names, (list, tuple, set)):
            w_lower = [w.strip().lower() for w in writer_names if isinstance(w, str) and w.strip()]
            if w_lower:
                matched_writers = session.query(WriterModel).outerjoin(WriterAliasModel).filter(
                    WriterModel.backup_id == str(backup_id),
                    or_(
                        func.lower(WriterModel.display_name).in_(w_lower),
                        func.lower(WriterAliasModel.alias).in_(w_lower)
                    )
                ).all()

                if not matched_writers:
                    return {"total_items": 0, "current_page": page or 1, "per_page": per_page, "total_pages": 0, "scenes": []} if page is not None else []

                if writer_logic == "AND":
                    for w in matched_writers:
                        w_pks = set()
                        for c in w.characters:
                            w_pks.add(c.pk)
                            for child in c.children:
                                w_pks.add(child.pk)
                        if w_pks:
                            query = query.filter(
                                SceneModel.participants.any(SceneParticipantModel.character_pk.in_(w_pks))
                            )
                        else:
                            return {"total_items": 0, "current_page": page or 1, "per_page": per_page, "total_pages": 0, "scenes": []} if page is not None else []
                else:
                    all_w_char_pks = set()
                    for w in matched_writers:
                        for c in w.characters:
                            all_w_char_pks.add(c.pk)
                            for child in c.children:
                                all_w_char_pks.add(child.pk)
                    if all_w_char_pks:
                        query = query.filter(
                            SceneModel.participants.any(SceneParticipantModel.character_pk.in_(all_w_char_pks))
                        )
                    else:
                        return {"total_items": 0, "current_page": page or 1, "per_page": per_page, "total_pages": 0, "scenes": []} if page is not None else []

        total_items = query.count()
        query = query.order_by(SceneModel.start_at.asc(), SceneModel.pk.asc()).options(selectinload(SceneModel.issues))

        if page is not None:
            total_pages = math.ceil(total_items / per_page) if per_page > 0 else 1
            page = max(1, min(page, max(1, total_pages)))
            offset = (page - 1) * per_page
            scenes_raw = query.offset(offset).limit(per_page).all()
        else:
            offset = 0
            scenes_raw = query.all()

        formatted_scenes = []
        for idx, s in enumerate(scenes_raw):
            channel = s.channel
            category = s.category

            chan_discord_id = channel.discord_id if channel else ""
            chan_name = channel.name if channel else ""
            is_thread = channel.type == "GuildPublicThread" if channel else False
            chan_type = "thread" if is_thread else "channel"
            cat_name = category.name if category else ""
            thread_name = chan_name if is_thread else None

            start_link = f"https://discord.com/channels/{server_id}/{chan_discord_id}/{s.start_message_id}" if server_id and chan_discord_id and s.start_message_id else ""
            end_link = f"https://discord.com/channels/{server_id}/{chan_discord_id}/{s.end_message_id}" if server_id and chan_discord_id and s.end_message_id else ""

            participants = [p.character.char_id for p in s.participants if p.character]

            formatted_scenes.append({
                "id": s.scene_key,
                "index": (offset + idx + 1) if page is not None else (idx + 1),
                "scene_key": s.scene_key,
                "channelId": chan_discord_id,
                "channel": chan_name,
                "category": cat_name,
                "type": chan_type,
                "thread_name": thread_name,
                "status": s.status,
                "characters": participants,
                "issues": [
                    {
                        "id": iss.pk,
                        "kind": iss.kind,
                        "reason": iss.reason,
                        "candidate_message_id": iss.candidate_message_id,
                        "candidate_index": iss.candidate_index,
                        "resolved": iss.resolved_at is not None,
                        "resolved_at": iss.resolved_at.isoformat() if iss.resolved_at else None,
                        "resolved_note": iss.resolved_note,
                        "resolution": iss.resolution,
                    }
                    for iss in s.issues
                ],
                "start": {
                    "id": s.start_message_id,
                    "timestamp": s.start_at.isoformat() if s.start_at else "",
                    "index": s.start_index,
                    "authorID": s.start_author_id,
                    "content": s.start_excerpt or "",
                    "link": start_link,
                },
                "end": {
                    "id": s.end_message_id,
                    "timestamp": s.end_at.isoformat() if s.end_at else "",
                    "index": s.end_index,
                    "authorID": s.end_author_id,
                    "content": s.end_excerpt or "",
                    "link": end_link,
                },
            })

        if page is not None:
            return {
                "total_items": total_items,
                "current_page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "scenes": formatted_scenes,
            }

        return formatted_scenes

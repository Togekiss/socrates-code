from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import func, or_, and_

from db.session import db_session, require_sqlite_db
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
    Status,
    SceneStatus,
    IssueKind,
)
import utils.tricks as t


def _parse_dt(dt_val: Any) -> Optional[datetime]:
    if not dt_val:
        return None
    if isinstance(dt_val, datetime):
        return dt_val
    try:
        dt = datetime.fromisoformat(str(dt_val))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def save_indexed_scenes(
    backup_id: str,
    base_path: str,
    scenes: List[Dict[str, Any]],
    bad_scenes: Optional[List[Dict[str, Any]]] = None,
    debug_files: bool = False
) -> None:
    """
    Persists indexed scenes, participants, and detected issues into SQLite.
    Preserves existing resolved issue notes (resolved_at, resolved_note) across re-indexing runs.
    Optionally exports debug JSON snapshots (_scenes.json, _bad_scenes.json) if debug_files is True.
    """
    require_sqlite_db(base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        # 1. Capture previously resolved issues to preserve manual curation across re-runs
        existing_resolved = (
            session.query(SceneIssueModel)
            .join(SceneModel, SceneIssueModel.scene_pk == SceneModel.pk)
            .filter(
                SceneIssueModel.backup_id == str(backup_id),
                SceneIssueModel.resolved_at.isnot(None),
            )
            .all()
        )
        resolved_map: Dict[Tuple[str, str], Tuple[Optional[datetime], Optional[str]]] = {}
        for issue in existing_resolved:
            resolved_map[(issue.scene.start_message_id, issue.kind)] = (
                issue.resolved_at,
                issue.resolved_note,
            )

        # 2. Delete existing scenes for this backup (cascades to participants & issues)
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

        chars = session.query(CharacterModel).filter(
            CharacterModel.backup_id == str(backup_id)
        ).all()
        char_id_to_pk = {c.char_id: c.pk for c in chars}

        # 4. Group scenes by channelId to build accurate hierarchical keys
        scenes_by_channel: Dict[str, List[Dict[str, Any]]] = {}
        for s in scenes:
            chan_id = str(s.get("channelId") or s.get("channel", {}).get("id", ""))
            scenes_by_channel.setdefault(chan_id, []).append(s)

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

            for idx, s in enumerate(chan_scenes):
                scene_key = f"{key_prefix}-{idx + 1}"
                raw_status = s.get("status", "closed")
                lifecycle_status = "closed" if raw_status in ["gap", "consecutive"] else raw_status

                start_at = _parse_dt(s.get("start", {}).get("timestamp")) or datetime.now(timezone.utc)
                end_at = _parse_dt(s.get("end", {}).get("timestamp")) or datetime.now(timezone.utc)
                start_msg_id = str(s.get("start", {}).get("id", ""))
                end_msg_id = str(s.get("end", {}).get("id", ""))

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
                    start_excerpt=str(s.get("start", {}).get("content", ""))[:250],
                    end_excerpt=str(s.get("end", {}).get("content", ""))[:250],
                )
                session.add(scene_model)
                session.flush()

                # Add participants and detect non-tupper authors
                for participant_id in s.get("characters", []):
                    try:
                        p_int = int(participant_id)
                    except (ValueError, TypeError):
                        continue

                    if p_int in char_id_to_pk:
                        session.add(SceneParticipantModel(
                            scene_pk=scene_model.pk,
                            character_pk=char_id_to_pk[p_int]
                        ))
                    elif p_int >= 10000:
                        res_info = resolved_map.get((start_msg_id, "non_tupper_author"))
                        session.add(SceneIssueModel(
                            backup_id=str(backup_id),
                            scene_pk=scene_model.pk,
                            kind="non_tupper_author",
                            discord_user_id=str(p_int),
                            details={"author_id": p_int},
                            created_at=start_at,
                            resolved_at=res_info[0] if res_info else None,
                            resolved_note=res_info[1] if res_info else None,
                        ))

                # Record gap / consecutive issues
                if raw_status in ["gap", "consecutive"]:
                    res_info = resolved_map.get((start_msg_id, raw_status))
                    session.add(SceneIssueModel(
                        backup_id=str(backup_id),
                        scene_pk=scene_model.pk,
                        kind=raw_status,
                        discord_user_id=None,
                        details={"original_status": raw_status},
                        created_at=start_at,
                        resolved_at=res_info[0] if res_info else None,
                        resolved_note=res_info[1] if res_info else None,
                    ))

        session.commit()

    # 5. Optionally export debug snapshots
    if debug_files:
        data_dir = Path(base_path) / "Data"
        data_dir.mkdir(parents=True, exist_ok=True)
        t.save_json_atomic(scenes, (data_dir / "_scenes.json").as_posix())
        if bad_scenes is not None:
            t.save_json_atomic(bad_scenes, (data_dir / "_bad_scenes.json").as_posix())


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
        query = query.order_by(SceneModel.start_at.asc(), SceneModel.pk.asc())

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

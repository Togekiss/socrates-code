import os
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload, joinedload

from db.session import db_session, require_db, init_db
from db.models import (
    BackupModel,
    ChannelModel,
    CharacterModel,
    CharacterNameModel,
    EventModel,
    ExportModel,
    SceneIssueModel,
    SceneKind,
    SceneModel,
    SceneParticipantModel,
    SceneStatus,
    Scope,
    WriterAliasModel,
    WriterModel,
)
from find_character_scenes import EXCERPT_MAX_LEN
from index_events import compute_event_movements, _smooth_runs
from utils import exceptions as exc
import utils.tricks as t

_parse_dt = t.parse_datetime


def _is_sa_session(obj: Any) -> bool:
    return hasattr(obj, "query") and hasattr(obj, "add") and hasattr(obj, "flush")


def _seg_key(s: Dict[str, Any]) -> Tuple[str, str]:
    chan_id = str(s.get("channelId") or s.get("channel", {}).get("id", ""))
    start_mid = str(s.get("start", {}).get("id", ""))
    return (chan_id, start_mid)


def _recompute_cluster_metadata(
    cl: Dict[str, Any],
    ev_idx: int,
    custom_name_by_chan_start: Dict[Tuple[str, str], str],
    custom_name_by_chan_end: Dict[Tuple[str, str], str],
) -> Dict[str, Any]:
    scenes = list(cl.get("scenes", []))
    scenes.sort(
        key=lambda s: (
            s.get("start", {}).get("timestamp", ""),
            int(s.get("start", {}).get("id", 0)) if str(s.get("start", {}).get("id", "")).isdigit() else 0,
        )
    )
    ev_key = f"ev-{ev_idx}"
    cl["id"] = ev_key

    custom_name_by_scene_key: Dict[str, Optional[str]] = {}
    custom_name_by_channel_id: Dict[str, Optional[str]] = {}
    old_key_to_new_key: Dict[str, str] = {}
    for s_idx, s in enumerate(scenes, start=1):
        old_key = str(s.get("scene_key") or s.get("id") or "")
        s_key = f"{ev_key}-{s_idx}"
        if old_key:
            old_key_to_new_key[old_key] = s_key
        s["id"] = s_key
        s["scene_key"] = s_key
        s["index"] = s_idx
        chan_id = str(s.get("channelId") or s.get("channel", {}).get("id", ""))
        start_mid = str(s.get("start", {}).get("id", ""))
        end_mid = str(s.get("end", {}).get("id", ""))
        c_name = (
            custom_name_by_chan_start.get((chan_id, start_mid))
            or custom_name_by_chan_end.get((chan_id, end_mid))
            or s.get("custom_name")
        )
        s["custom_name"] = c_name
        custom_name_by_scene_key[s_key] = c_name
        if chan_id and c_name:
            custom_name_by_channel_id[chan_id] = c_name

    cl["scenes"] = scenes

    text_scenes = [s for s in scenes if s.get("type") != "thread"]
    bound_scenes = text_scenes if text_scenes else scenes

    if bound_scenes:
        start_timestamps = [s.get("start", {}).get("timestamp", "") for s in bound_scenes if s.get("start", {}).get("timestamp")]
        end_timestamps = [s.get("end", {}).get("timestamp", "") for s in bound_scenes if s.get("end", {}).get("timestamp")]
        cl["start_at"] = min(start_timestamps) if start_timestamps else cl.get("start_at", "")
        cl["end_at"] = max(end_timestamps) if end_timestamps else cl.get("end_at", "")
        # Aggregate status: closed if any member text segment is closed, else open
        if any(s.get("status") == SceneStatus.CLOSED.value for s in bound_scenes):
            cl["status"] = SceneStatus.CLOSED.value
        else:
            cl["status"] = SceneStatus.OPEN.value
    else:
        cl["status"] = cl.get("status", SceneStatus.CLOSED.value)

    cl["message_count"] = sum(
        int(s.get("message_count") or max(0, int(s.get("end", {}).get("index", 0)) - int(s.get("start", {}).get("index", 0)) + 1))
        for s in scenes
    )

    if any("_tupper_msgs" in s for s in scenes):
        movements = compute_event_movements(cl)
    else:
        movements = cl.get("character_movements", {}) or {}

    for cid_str, hops in movements.items():
        for hop in hops:
            raw_s_id = str(hop.get("scene_id") or hop.get("scene_key") or "")
            s_id = old_key_to_new_key.get(raw_s_id, raw_s_id)
            if s_id:
                hop["scene_id"] = s_id
                hop["scene_key"] = s_id
            ch_id = str(hop.get("channel_id") or "")
            if s_id and s_id in custom_name_by_scene_key:
                hop["custom_name"] = custom_name_by_scene_key[s_id]
            elif ch_id and ch_id in custom_name_by_channel_id:
                hop["custom_name"] = custom_name_by_channel_id[ch_id]

    cl["character_movements"] = movements
    return cl


def _reconcile_curated_clusters(
    event_clusters: List[Dict[str, Any]],
    snap_events: List[Dict[str, Any]],
    custom_name_by_chan_start: Dict[Tuple[str, str], str],
    custom_name_by_chan_end: Dict[Tuple[str, str], str],
) -> List[Dict[str, Any]]:
    if not event_clusters:
        return []

    curated_snaps = [se for se in snap_events if se.get("is_curated") and se.get("member_keys")]

    # Step 1: Handle curated splits (when one auto-detected cluster was previously split into >= 2 curated events)
    split_adjusted: List[Dict[str, Any]] = []
    for cl in event_clusters:
        scenes = cl.get("scenes", [])
        cl_keys = {_seg_key(s) for s in scenes}
        overlapping_curated = [se for se in curated_snaps if se["member_keys"] & cl_keys]

        if len(overlapping_curated) >= 2:
            # Partition scenes across the overlapping curated events
            partitions: Dict[int, List[Dict[str, Any]]] = {i: [] for i in range(len(overlapping_curated))}
            unassigned: List[Dict[str, Any]] = []
            for s in scenes:
                sk = _seg_key(s)
                placed = False
                for idx, se in enumerate(overlapping_curated):
                    if sk in se["member_keys"]:
                        partitions[idx].append(s)
                        placed = True
                        break
                if not placed:
                    unassigned.append(s)

            non_empty_indices = [idx for idx, plist in partitions.items() if plist]
            if len(non_empty_indices) >= 2:
                # Attach any unassigned scenes (e.g. newly added thread) to the first non-empty partition
                if unassigned:
                    partitions[non_empty_indices[0]].extend(unassigned)
                for idx in non_empty_indices:
                    se = overlapping_curated[idx]
                    new_cl = dict(cl)
                    new_cl["scenes"] = partitions[idx]
                    new_cl["name"] = se.get("name")
                    new_cl["is_curated"] = True
                    split_adjusted.append(new_cl)
                continue

        split_adjusted.append(dict(cl))

    # Step 2: Handle curated merges (when one curated event spans scenes across >= 2 clusters)
    clusters = split_adjusted
    for se in curated_snaps:
        target_keys = se["member_keys"]
        matching_indices = []
        for idx, cl in enumerate(clusters):
            cl_keys = {_seg_key(s) for s in cl.get("scenes", [])}
            if cl_keys & target_keys:
                matching_indices.append(idx)

        if len(matching_indices) >= 2:
            primary_idx = matching_indices[0]
            merged_scenes: List[Dict[str, Any]] = []
            merged_movements: Dict[str, List[Dict[str, Any]]] = {}
            for idx in matching_indices:
                merged_scenes.extend(clusters[idx].get("scenes", []))
                for cid_str, hops in (clusters[idx].get("character_movements") or {}).items():
                    merged_movements.setdefault(cid_str, []).extend(hops)

            primary_cl = dict(clusters[primary_idx])
            primary_cl["scenes"] = merged_scenes
            primary_cl["name"] = se.get("name") or primary_cl.get("name")
            primary_cl["is_curated"] = True
            primary_cl["character_movements"] = merged_movements

            new_clusters = []
            for idx, cl in enumerate(clusters):
                if idx == primary_idx:
                    new_clusters.append(primary_cl)
                elif idx not in matching_indices:
                    new_clusters.append(cl)
            clusters = new_clusters

    # Step 3: Restore name & is_curated for 1-to-1 matching clusters
    for cl in clusters:
        cl_keys = {_seg_key(s) for s in cl.get("scenes", [])}
        best_snap = None
        best_overlap = 0
        for se in snap_events:
            overlap = len(se["member_keys"] & cl_keys)
            if overlap > best_overlap:
                best_overlap = overlap
                best_snap = se
        if best_snap and best_overlap > 0:
            if not cl.get("name") and best_snap.get("name"):
                cl["name"] = best_snap["name"]
            if best_snap.get("is_curated"):
                cl["is_curated"] = True

    # Sort clusters chronologically and recompute metadata/keys
    clusters.sort(
        key=lambda c: min(
            (s.get("start", {}).get("timestamp", "") for s in c.get("scenes", [])),
            default=c.get("start_at", ""),
        )
    )

    final_clusters = []
    for idx, cl in enumerate(clusters, start=1):
        if not cl.get("scenes"):
            continue
        final_clusters.append(
            _recompute_cluster_metadata(cl, idx, custom_name_by_chan_start, custom_name_by_chan_end)
        )
    return final_clusters


def _save_indexed_events_in_session(
    session,
    backup_id: str,
    event_clusters: List[Dict[str, Any]],
) -> None:
    # 1. Snapshot existing event scenes and events to preserve curation across re-indexing
    existing_event_scenes = (
        session.query(SceneModel)
        .options(joinedload(SceneModel.channel))
        .filter(
            SceneModel.backup_id == str(backup_id),
            SceneModel.kind == SceneKind.EVENT.value,
        )
        .all()
    )

    custom_name_by_chan_start: Dict[Tuple[str, str], str] = {}
    custom_name_by_chan_end: Dict[Tuple[str, str], str] = {}
    scenes_by_event_pk: Dict[int, List[SceneModel]] = {}

    for sc in existing_event_scenes:
        chan_discord_id = sc.channel.discord_id if sc.channel else str(sc.channel_pk)
        if sc.custom_name:
            if sc.start_message_id:
                custom_name_by_chan_start[(chan_discord_id, str(sc.start_message_id))] = sc.custom_name
            if sc.end_message_id:
                custom_name_by_chan_end[(chan_discord_id, str(sc.end_message_id))] = sc.custom_name
        if sc.event_pk is not None:
            scenes_by_event_pk.setdefault(sc.event_pk, []).append(sc)

    existing_events = (
        session.query(EventModel)
        .filter(EventModel.backup_id == str(backup_id))
        .order_by(EventModel.start_at.asc(), EventModel.pk.asc())
        .all()
    )

    snap_events: List[Dict[str, Any]] = []
    for ev in existing_events:
        ev_scenes = scenes_by_event_pk.get(ev.pk, [])
        member_keys = {
            (sc.channel.discord_id if sc.channel else str(sc.channel_pk), str(sc.start_message_id))
            for sc in ev_scenes
        }
        snap_events.append({
            "pk": ev.pk,
            "event_key": ev.event_key,
            "name": ev.name,
            "is_curated": bool(ev.is_curated),
            "member_keys": member_keys,
        })

    # 2. Reconcile clusters with snapshotted curated state
    reconciled_clusters = _reconcile_curated_clusters(
        event_clusters=event_clusters or [],
        snap_events=snap_events,
        custom_name_by_chan_start=custom_name_by_chan_start,
        custom_name_by_chan_end=custom_name_by_chan_end,
    )

    # 3. Preserve resolved issues on event scenes, then delete existing event participants, unresolved issues, scenes, and events
    event_scene_pk_to_chan_pk = {sc.pk: sc.channel_pk for sc in existing_event_scenes}
    event_scene_pks_subquery = session.query(SceneModel.pk).filter(
        SceneModel.backup_id == str(backup_id),
        SceneModel.kind == SceneKind.EVENT.value,
    )

    resolved_event_issues = (
        session.query(SceneIssueModel)
        .filter(
            SceneIssueModel.backup_id == str(backup_id),
            SceneIssueModel.resolved_at.isnot(None),
            SceneIssueModel.scene_pk.in_(event_scene_pks_subquery),
        )
        .all()
    )
    resolved_issues_by_chan: Dict[int, List[SceneIssueModel]] = {}
    for r_iss in resolved_event_issues:
        c_pk = event_scene_pk_to_chan_pk.get(r_iss.scene_pk) if r_iss.scene_pk else None
        if c_pk is not None:
            resolved_issues_by_chan.setdefault(c_pk, []).append(r_iss)
        r_iss.scene_pk = None
        r_iss.next_scene_pk = None

    session.query(SceneIssueModel).filter(
        SceneIssueModel.backup_id == str(backup_id),
        SceneIssueModel.resolved_at.is_(None),
        SceneIssueModel.scene_pk.in_(event_scene_pks_subquery),
    ).delete(synchronize_session=False)

    session.query(SceneParticipantModel).filter(
        SceneParticipantModel.scene_pk.in_(event_scene_pks_subquery)
    ).delete(synchronize_session=False)

    session.query(SceneModel).filter(
        SceneModel.backup_id == str(backup_id),
        SceneModel.kind == SceneKind.EVENT.value,
    ).delete(synchronize_session="fetch")

    session.query(EventModel).filter(
        EventModel.backup_id == str(backup_id)
    ).delete(synchronize_session="fetch")
    session.flush()

    if not reconciled_clusters:
        return

    # 4. Lookup channels and characters
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
        .filter(CharacterModel.backup_id == str(backup_id))
        .all()
    )
    char_id_to_pk = {c.char_id: c.pk for c in chars}

    # Build lookup of surviving resolved issues by candidate message ID
    resolved_by_candidate: Dict[str, SceneIssueModel] = {
        str(iss.candidate_message_id): iss
        for iss in resolved_event_issues
        if iss.candidate_message_id
    }

    # 5. Insert EventModel, SceneModel, and SceneParticipantModel rows
    channel_scenes_map: Dict[int, List[Tuple[SceneModel, Dict[str, Any]]]] = {}

    for cl in reconciled_clusters:
        start_dt = _parse_dt(cl.get("start_at")) or datetime.now(timezone.utc)
        end_dt = _parse_dt(cl.get("end_at")) or datetime.now(timezone.utc)

        ev_model = EventModel(
            backup_id=str(backup_id),
            event_key=str(cl["id"]),
            name=cl.get("name"),
            status=str(cl.get("status", SceneStatus.CLOSED.value)),
            start_at=start_dt,
            end_at=end_dt,
            message_count=int(cl.get("message_count", 0)),
            is_curated=bool(cl.get("is_curated", False)),
            character_movements=cl.get("character_movements", {}),
        )
        session.add(ev_model)
        session.flush()

        for s in cl.get("scenes", []):
            chan_discord_id = str(s.get("channelId") or s.get("channel", {}).get("id", ""))
            chan_model = chan_by_discord_id.get(chan_discord_id)
            if not chan_model:
                continue

            if chan_model.type == "GuildPublicThread" and chan_model.parent_pk:
                parent_chan = chan_by_pk.get(chan_model.parent_pk)
                cat_chan = chan_by_pk.get(parent_chan.parent_pk) if parent_chan and parent_chan.parent_pk else parent_chan
                category_pk = cat_chan.pk if cat_chan else chan_model.pk
            else:
                cat_chan = chan_by_pk.get(chan_model.parent_pk) if chan_model.parent_pk else chan_model
                category_pk = cat_chan.pk if cat_chan else chan_model.pk

            s_start_at = _parse_dt(s.get("start", {}).get("timestamp")) or start_dt
            s_end_at = _parse_dt(s.get("end", {}).get("timestamp")) or end_dt
            start_msg_id = str(s.get("start", {}).get("id", ""))
            end_msg_id = str(s.get("end", {}).get("id", ""))
            start_message = str(s.get("start", {}).get("content", ""))
            start_excerpt = start_message if len(start_message) <= EXCERPT_MAX_LEN else start_message[:EXCERPT_MAX_LEN - 3] + "..."
            end_message = str(s.get("end", {}).get("content", ""))
            end_excerpt = end_message if len(end_message) <= EXCERPT_MAX_LEN else "..." + end_message[-(EXCERPT_MAX_LEN - 3):]

            start_idx = int(s.get("start", {}).get("index", 0))
            msg_count = int(s.get("message_count", 0))
            end_idx = int(s.get("end", {}).get("index", max(0, start_idx + msg_count - 1)))
            if msg_count > 0:
                end_idx = start_idx + msg_count - 1

            scene_model = SceneModel(
                backup_id=str(backup_id),
                scene_key=str(s.get("scene_key") or s.get("id")),
                channel_pk=chan_model.pk,
                category_pk=category_pk,
                event_pk=ev_model.pk,
                custom_name=s.get("custom_name"),
                kind=SceneKind.EVENT.value,
                status=str(s.get("status", SceneStatus.CLOSED.value)),
                start_message_id=start_msg_id,
                end_message_id=end_msg_id,
                start_index=start_idx,
                end_index=end_idx,
                start_at=s_start_at,
                end_at=s_end_at,
                start_author_id=str(s.get("start", {}).get("authorID") or s.get("start", {}).get("author", {}).get("id", "")),
                end_author_id=str(s.get("end", {}).get("authorID") or s.get("end", {}).get("author", {}).get("id", "")),
                start_excerpt=start_excerpt,
                end_excerpt=end_excerpt,
            )
            session.add(scene_model)
            session.flush()
            channel_scenes_map.setdefault(chan_model.pk, []).append((scene_model, s))

            seen_char_pks = set()
            p_details = s.get("participant_details")
            if p_details:
                for p_info in p_details:
                    cid = p_info.get("char_id")
                    if cid in char_id_to_pk:
                        char_pk = char_id_to_pk[cid]
                        if char_pk not in seen_char_pks:
                            seen_char_pks.add(char_pk)
                            session.add(SceneParticipantModel(
                                scene_pk=scene_model.pk,
                                character_pk=char_pk,
                                position=int(p_info.get("position", 0)),
                                first_message_id=str(p_info.get("first_message_id")) if p_info.get("first_message_id") else None,
                                first_at=_parse_dt(p_info.get("first_at")),
                                last_message_id=str(p_info.get("last_message_id")) if p_info.get("last_message_id") else None,
                                last_at=_parse_dt(p_info.get("last_at")),
                            ))
            else:
                for pos, participant_id in enumerate(s.get("characters", [])):
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
                                character_pk=char_pk,
                                position=pos,
                            ))

    session.flush()

    # Persist newly detected auto_split and soft_boundary issues for event scenes
    from db.models import IssueKind
    for c_pk, chan_scenes in channel_scenes_map.items():
        chan_scenes.sort(key=lambda x: (x[0].start_index, x[0].start_at))
        for idx_sc, (scene_model, s) in enumerate(chan_scenes):
            next_scene_model = chan_scenes[idx_sc + 1][0] if idx_sc + 1 < len(chan_scenes) else None
            next_scene_pk = next_scene_model.pk if next_scene_model else None

            for iss in s.get("issues", []):
                ikind = iss.get("kind")
                if ikind == "possible_split":
                    ikind = IssueKind.SOFT_BOUNDARY.value

                if ikind in (IssueKind.AUTO_SPLIT.value, IssueKind.SOFT_BOUNDARY.value):
                    cand_id = iss.get("candidate_id")
                    cand_id_str = str(cand_id) if cand_id else None
                    cand_idx = iss.get("candidate_index")

                    if not cand_id_str or cand_id_str in resolved_by_candidate:
                        continue

                    cand_excerpt = iss.get("candidate_excerpt")
                    if cand_excerpt:
                        cand_excerpt = (
                            str(cand_excerpt)
                            if len(str(cand_excerpt)) <= EXCERPT_MAX_LEN
                            else str(cand_excerpt)[:EXCERPT_MAX_LEN - 3] + "..."
                        )
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

    session.flush()

    # 6. Relink any preserved resolved issues using resolved_by_candidate
    applied_cand_ids = set()
    for c_pk, chan_scenes in channel_scenes_map.items():
        for sc_idx, (sc_model, s_dict) in enumerate(chan_scenes):
            # Role 'start': forced cut on split decision
            res_start = s_dict.get("resolved_start")
            if res_start and str(res_start) in resolved_by_candidate:
                r_iss = resolved_by_candidate[str(res_start)]
                prev_sc = chan_scenes[sc_idx - 1][0] if sc_idx > 0 else None
                r_iss.scene_pk = prev_sc.pk if prev_sc else None
                r_iss.next_scene_pk = sc_model.pk
                applied_cand_ids.add(str(res_start))

            # Role 'inside': candidate(s) inside this scene suppressed by a 'merged' decision
            res_inside = s_dict.get("resolved_inside", [])
            for cand_id in res_inside:
                cand_id_str = str(cand_id)
                if cand_id_str in resolved_by_candidate:
                    r_iss = resolved_by_candidate[cand_id_str]
                    r_iss.scene_pk = sc_model.pk
                    r_iss.next_scene_pk = None
                    applied_cand_ids.add(cand_id_str)

    # Fallback re-linking for any resolved issues not explicitly matched by tags
    for r_iss in resolved_event_issues:
        cand_mid = str(r_iss.candidate_message_id or "")
        if cand_mid in applied_cand_ids:
            continue
        cand_idx = r_iss.candidate_index
        for c_pk, chan_scenes in channel_scenes_map.items():
            for idx_s, (n_sc, _) in enumerate(chan_scenes):
                if cand_mid and str(n_sc.start_message_id) == cand_mid and idx_s > 0:
                    r_iss.scene_pk = chan_scenes[idx_s - 1][0].pk
                    r_iss.next_scene_pk = n_sc.pk
                    applied_cand_ids.add(cand_mid)
                    break
                elif cand_idx is not None and n_sc.start_index <= cand_idx <= n_sc.end_index:
                    r_iss.scene_pk = n_sc.pk
                    r_iss.next_scene_pk = None
                    if cand_mid:
                        applied_cand_ids.add(cand_mid)
                    break
            if cand_mid in applied_cand_ids:
                break

    session.flush()


def save_indexed_events(
    session_or_backup_id: Any = None,
    backup_id_or_base_path: Any = None,
    event_clusters: Optional[List[Dict[str, Any]]] = None,
    *,
    backup_id: Optional[str] = None,
    base_path: Optional[str] = None,
) -> None:
    """
    Persists indexed events, event channel segments, and participants into SQLite.
    Supports both:
      - save_indexed_events(session, backup_id, event_clusters)
      - save_indexed_events(backup_id, base_path, event_clusters)
    """
    if _is_sa_session(session_or_backup_id):
        session = session_or_backup_id
        b_id = str(backup_id or backup_id_or_base_path)
        _save_indexed_events_in_session(session, b_id, event_clusters or [])
        return

    b_id = str(backup_id or session_or_backup_id)
    b_path = str(base_path or backup_id_or_base_path)
    require_db(b_path, backup_id=b_id)
    init_db(engine_or_backup_id=b_id, backup_path=b_path)

    with db_session(backup_id=b_id, backup_path=b_path) as session:
        _save_indexed_events_in_session(session, b_id, event_clusters or [])


def _format_scene_entry(
    s: SceneModel,
    server_id: str,
    threads: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    channel = s.channel
    chan_discord_id = channel.discord_id if channel else ""
    chan_name = channel.name if channel else ""

    start_link = f"https://discord.com/channels/{server_id}/{chan_discord_id}/{s.start_message_id}" if server_id and chan_discord_id and s.start_message_id else ""
    end_link = f"https://discord.com/channels/{server_id}/{chan_discord_id}/{s.end_message_id}" if server_id and chan_discord_id and s.end_message_id else ""

    sorted_participants = sorted(
        s.participants,
        key=lambda p: (
            p.first_at or datetime.max.replace(tzinfo=timezone.utc),
            p.position if p.position is not None else 0,
            p.character_pk,
        ),
    )

    participants_list = []
    for pos_idx, p in enumerate(sorted_participants):
        if not p.character:
            continue
        cid = p.character.char_id
        c_names = sorted(p.character.names, key=lambda n: n.position)
        cname = c_names[0].name if c_names else f"Character #{cid}"
        f_mid = p.first_message_id
        l_mid = p.last_message_id
        f_iso = p.first_at.isoformat() if p.first_at else None
        l_iso = p.last_at.isoformat() if p.last_at else None
        f_link = f"https://discord.com/channels/{server_id}/{chan_discord_id}/{f_mid}" if server_id and chan_discord_id and f_mid else ""
        l_link = f"https://discord.com/channels/{server_id}/{chan_discord_id}/{l_mid}" if server_id and chan_discord_id and l_mid else ""

        participants_list.append({
            "id": cid,
            "char_id": cid,
            "name": cname,
            "position": p.position if p.position is not None else pos_idx,
            "first_message_id": f_mid,
            "first_at": f_iso,
            "first_timestamp": f_iso,
            "first_link": f_link,
            "last_message_id": l_mid,
            "last_at": l_iso,
            "last_timestamp": l_iso,
            "last_link": l_link,
        })

    entry: Dict[str, Any] = {
        "id": s.scene_key,
        "scene_key": s.scene_key,
        "pk": s.pk,
        "scene_pk": s.pk,
        "type": "thread" if (s.channel and s.channel.type == "GuildPublicThread") else "channel",
        "channel_id": chan_discord_id,
        "channel_name": chan_name,
        "custom_name": s.custom_name,
        "status": s.status,
        "message_count": s.message_count,
        "start": {
            "id": s.start_message_id,
            "message_id": s.start_message_id,
            "timestamp": s.start_at.isoformat() if s.start_at else "",
            "link": start_link,
        },
        "end": {
            "id": s.end_message_id,
            "message_id": s.end_message_id,
            "timestamp": s.end_at.isoformat() if s.end_at else "",
            "link": end_link,
        },
        "participants": participants_list,
    }
    if threads is not None:
        entry["threads"] = threads
    return entry


def format_event_model(session, ev: EventModel, server_id: str) -> Dict[str, Any]:
    ev_scenes = sorted(
        ev.scenes,
        key=lambda s: (
            s.channel.position if s.channel and s.channel.position is not None else 999,
            s.start_at or datetime.min.replace(tzinfo=timezone.utc),
            s.pk or 0,
        ),
    )

    text_scenes: List[SceneModel] = []
    thread_scenes: List[SceneModel] = []
    custom_name_by_scene_key: Dict[str, Optional[str]] = {}
    custom_name_by_channel_id: Dict[str, Optional[str]] = {}

    for s in ev_scenes:
        custom_name_by_scene_key[s.scene_key] = s.custom_name
        if s.channel and s.custom_name:
            custom_name_by_channel_id[s.channel.discord_id] = s.custom_name
        if s.channel and s.channel.type == "GuildPublicThread":
            thread_scenes.append(s)
        else:
            text_scenes.append(s)

    # Group threads by parent channel_pk
    threads_by_parent_pk: Dict[int, List[SceneModel]] = {}
    for th in thread_scenes:
        parent_pk = th.channel.parent_pk if th.channel and th.channel.parent_pk else -1
        threads_by_parent_pk.setdefault(parent_pk, []).append(th)

    # Group text_scenes by channel_pk
    attached_parent_pks: Set[int] = set()
    channels_formatted: List[Dict[str, Any]] = []

    for s in text_scenes:
        ch_pk = s.channel_pk
        th_entries = []
        if ch_pk not in attached_parent_pks and ch_pk in threads_by_parent_pk:
            attached_parent_pks.add(ch_pk)
            for th_s in threads_by_parent_pk[ch_pk]:
                th_entries.append(_format_scene_entry(th_s, server_id))
        channels_formatted.append(_format_scene_entry(s, server_id, threads=th_entries))

    # Any threads whose parent channel had no text scene in this event (e.g. parent channel only had a banner)
    for parent_pk, orphan_threads in threads_by_parent_pk.items():
        if parent_pk in attached_parent_pks:
            continue
        parent_chan = session.get(ChannelModel, parent_pk) if parent_pk > 0 else None
        th_entries = [_format_scene_entry(th_s, server_id) for th_s in orphan_threads]
        if parent_chan and th_entries:
            first_th = orphan_threads[0]
            last_th = orphan_threads[-1]
            p_discord_id = parent_chan.discord_id
            f_link = th_entries[0]["start"]["link"]
            l_link = th_entries[-1]["end"]["link"]
            channels_formatted.append({
                "id": f"{ev.event_key}-parent-{parent_chan.position}",
                "scene_key": f"{ev.event_key}-parent-{parent_chan.position}",
                "pk": first_th.pk,
                "scene_pk": first_th.pk,
                "type": "channel",
                "channel_id": p_discord_id,
                "channel_name": parent_chan.name,
                "custom_name": custom_name_by_channel_id.get(p_discord_id),
                "status": first_th.status,
                "message_count": 0,
                "start": {
                    "id": first_th.start_message_id,
                    "message_id": first_th.start_message_id,
                    "timestamp": first_th.start_at.isoformat() if first_th.start_at else "",
                    "link": f_link,
                },
                "end": {
                    "id": last_th.end_message_id,
                    "message_id": last_th.end_message_id,
                    "timestamp": last_th.end_at.isoformat() if last_th.end_at else "",
                    "link": l_link,
                },
                "participants": [],
                "threads": th_entries,
            })

    # Condensed participants across all scenes in the event ordered by earliest first_at
    agg_participants: Dict[int, Dict[str, Any]] = {}
    for s in ev_scenes:
        chan_discord_id = s.channel.discord_id if s.channel else ""
        for p in s.participants:
            if not p.character:
                continue
            cid = p.character.char_id
            c_names = sorted(p.character.names, key=lambda n: n.position)
            cname = c_names[0].name if c_names else f"Character #{cid}"
            f_at = p.first_at
            l_at = p.last_at
            f_mid = p.first_message_id
            l_mid = p.last_message_id
            f_link = f"https://discord.com/channels/{server_id}/{chan_discord_id}/{f_mid}" if server_id and chan_discord_id and f_mid else ""
            l_link = f"https://discord.com/channels/{server_id}/{chan_discord_id}/{l_mid}" if server_id and chan_discord_id and l_mid else ""

            if cid not in agg_participants:
                agg_participants[cid] = {
                    "id": cid,
                    "char_id": cid,
                    "name": cname,
                    "_first_dt": f_at or datetime.max.replace(tzinfo=timezone.utc),
                    "_last_dt": l_at or datetime.min.replace(tzinfo=timezone.utc),
                    "first_at": f_at.isoformat() if f_at else None,
                    "first_timestamp": f_at.isoformat() if f_at else None,
                    "first_message_id": f_mid,
                    "first_link": f_link,
                    "last_at": l_at.isoformat() if l_at else None,
                    "last_timestamp": l_at.isoformat() if l_at else None,
                    "last_message_id": l_mid,
                    "last_link": l_link,
                }
            else:
                cur = agg_participants[cid]
                if f_at and f_at < cur["_first_dt"]:
                    cur["_first_dt"] = f_at
                    cur["first_at"] = f_at.isoformat()
                    cur["first_timestamp"] = f_at.isoformat()
                    cur["first_message_id"] = f_mid
                    cur["first_link"] = f_link
                if l_at and l_at >= cur["_last_dt"]:
                    cur["_last_dt"] = l_at
                    cur["last_at"] = l_at.isoformat()
                    cur["last_timestamp"] = l_at.isoformat()
                    cur["last_message_id"] = l_mid
                    cur["last_link"] = l_link

    sorted_agg_parts = sorted(
        agg_participants.values(),
        key=lambda item: (item["_first_dt"], item["id"]),
    )
    participants_condensed = []
    for pos_idx, item in enumerate(sorted_agg_parts):
        clean_item = {k: v for k, v in item.items() if not k.startswith("_")}
        clean_item["position"] = pos_idx
        participants_condensed.append(clean_item)

    # Enrich character_movements with custom_name and first_link
    raw_movements = ev.character_movements or {}
    formatted_movements: Dict[str, List[Dict[str, Any]]] = {}
    for cid_str, hops in raw_movements.items():
        enriched_hops = []
        for hop in hops:
            s_id = hop.get("scene_id") or hop.get("scene_key") or ""
            ch_id = str(hop.get("channel_id") or "")
            f_mid = str(hop.get("first_message_id") or "")
            c_name = (
                custom_name_by_scene_key.get(s_id)
                if s_id in custom_name_by_scene_key
                else (custom_name_by_channel_id.get(ch_id) or hop.get("custom_name"))
            )
            f_link = (
                f"https://discord.com/channels/{server_id}/{ch_id}/{f_mid}"
                if server_id and ch_id and f_mid
                else (hop.get("first_link") or "")
            )
            enriched_hops.append({
                "scene_id": s_id,
                "scene_key": s_id,
                "channel_id": ch_id,
                "channel_name": hop.get("channel_name", ""),
                "custom_name": c_name,
                "first_message_id": f_mid,
                "first_link": f_link,
                "first_at": hop.get("first_at"),
                "first_timestamp": hop.get("first_at") or hop.get("first_timestamp"),
                "last_message_id": hop.get("last_message_id"),
                "last_at": hop.get("last_at"),
                "last_timestamp": hop.get("last_at") or hop.get("last_timestamp"),
                "message_count": int(hop.get("message_count", 0)),
            })
        formatted_movements[str(cid_str)] = enriched_hops

    start_iso = ev.start_at.isoformat() if ev.start_at else ""
    end_iso = ev.end_at.isoformat() if ev.end_at else ""
    first_ch = channels_formatted[0] if channels_formatted else None
    last_ch = channels_formatted[-1] if channels_formatted else None

    return {
        "id": ev.event_key,
        "event_key": ev.event_key,
        "pk": ev.pk,
        "name": ev.name,
        "status": ev.status,
        "start_at": start_iso,
        "end_at": end_iso,
        "start_timestamp": start_iso,
        "end_timestamp": end_iso,
        "start": {
            "timestamp": start_iso,
            "message_id": first_ch["start"].get("message_id") if first_ch else None,
            "link": first_ch["start"].get("link", "") if first_ch else "",
        },
        "end": {
            "timestamp": end_iso,
            "message_id": last_ch["end"].get("message_id") if last_ch else None,
            "link": last_ch["end"].get("link", "") if last_ch else "",
        },
        "message_count": ev.message_count,
        "is_curated": bool(ev.is_curated),
        "characters": [p["id"] for p in participants_condensed],
        "participants": participants_condensed,
        "character_movements": formatted_movements,
        "channels": channels_formatted,
    }


def _query_events_in_session(
    session,
    backup_id: str,
    channels: Optional[List[str]] = None,
    statuses: Optional[List[str]] = None,
    status: str = "all",
    character_ids: Optional[List[int]] = None,
    characters: Optional[List[int]] = None,
    character_logic: str = "AND",
    character_name: Optional[str] = None,
    writer_names: Optional[List[str]] = None,
    writers: Optional[List[str]] = None,
    writer_logic: str = "AND",
    include_alter_egos: bool = True,
    include_familiars: bool = True,
    include_npcs: bool = True,
    before: Optional[str] = None,
    after: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "asc",
    page: Optional[int] = 1,
    per_page: int = 50,
    **kwargs,
) -> Any:
    backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
    server_id = backup.server_id if backup and backup.server_id else ""

    query = session.query(EventModel).filter(EventModel.backup_id == str(backup_id))

    # Filter by status
    if statuses and isinstance(statuses, (list, tuple, set)):
        query = query.filter(EventModel.status.in_(statuses))
    elif status and status != "all":
        query = query.filter(EventModel.status == status)

    # Filter by channels
    if channels and isinstance(channels, (list, tuple, set)):
        chan_subquery = session.query(ChannelModel.pk).filter(ChannelModel.name.in_(channels))
        query = query.filter(EventModel.scenes.any(SceneModel.channel_pk.in_(chan_subquery)))

    # Filter by dates
    eff_before = before or end_date
    eff_after = after or start_date
    if eff_before:
        before_dt = _parse_dt(eff_before)
        if before_dt:
            query = query.filter(EventModel.start_at < before_dt)
    if eff_after:
        after_dt = _parse_dt(eff_after)
        if after_dt:
            query = query.filter(EventModel.start_at > after_dt)

    # Filter by search query
    if search and isinstance(search, str) and search.strip():
        s_term = search.strip().lower()
        matching_chan_pks = session.query(ChannelModel.pk).filter(
            func.lower(ChannelModel.name).contains(s_term)
        )
        query = query.filter(
            or_(
                func.lower(EventModel.name).contains(s_term),
                func.lower(EventModel.event_key).contains(s_term),
                EventModel.scenes.any(func.lower(SceneModel.custom_name).contains(s_term)),
                EventModel.scenes.any(SceneModel.channel_pk.in_(matching_chan_pks)),
            )
        )

    # Filter by characters
    eff_char_ids = list(character_ids or characters or [])
    if character_name and isinstance(character_name, str) and character_name.strip():
        cname_lower = character_name.strip().lower()
        matched_chars = (
            session.query(CharacterModel)
            .join(CharacterNameModel, CharacterModel.pk == CharacterNameModel.character_pk)
            .filter(
                CharacterModel.backup_id == str(backup_id),
                func.lower(CharacterNameModel.name) == cname_lower,
            )
            .all()
        )
        for mc in matched_chars:
            if mc.char_id not in eff_char_ids:
                eff_char_ids.append(mc.char_id)

    if eff_char_ids:
        resolved_clusters = []
        for cid in eff_char_ids:
            family_pks = set()
            char = session.query(CharacterModel).filter(
                CharacterModel.backup_id == str(backup_id),
                CharacterModel.char_id == cid,
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

        empty_res = {
            "total_items": 0,
            "current_page": page or 1,
            "per_page": per_page,
            "total_pages": 0,
            "events": [],
            "scenes": [],
        } if page is not None else []

        if character_logic == "AND":
            for cluster in resolved_clusters:
                if cluster:
                    query = query.filter(
                        EventModel.scenes.any(
                            SceneModel.participants.any(SceneParticipantModel.character_pk.in_(cluster))
                        )
                    )
                else:
                    return empty_res
        else:
            all_target_pks = set().union(*resolved_clusters)
            if all_target_pks:
                query = query.filter(
                    EventModel.scenes.any(
                        SceneModel.participants.any(SceneParticipantModel.character_pk.in_(all_target_pks))
                    )
                )
            else:
                return empty_res

    # Filter by writers
    eff_writers = writer_names or writers
    if eff_writers and isinstance(eff_writers, (list, tuple, set)):
        w_lower = [w.strip().lower() for w in eff_writers if isinstance(w, str) and w.strip()]
        if w_lower:
            matched_writers = session.query(WriterModel).outerjoin(WriterAliasModel).filter(
                WriterModel.backup_id == str(backup_id),
                or_(
                    func.lower(WriterModel.display_name).in_(w_lower),
                    func.lower(WriterAliasModel.alias).in_(w_lower),
                ),
            ).all()

            empty_res = {
                "total_items": 0,
                "current_page": page or 1,
                "per_page": per_page,
                "total_pages": 0,
                "events": [],
                "scenes": [],
            } if page is not None else []

            if not matched_writers:
                return empty_res

            if writer_logic == "AND":
                for w in matched_writers:
                    w_pks = set()
                    for c in w.characters:
                        w_pks.add(c.pk)
                        for child in c.children:
                            w_pks.add(child.pk)
                    if w_pks:
                        query = query.filter(
                            EventModel.scenes.any(
                                SceneModel.participants.any(SceneParticipantModel.character_pk.in_(w_pks))
                            )
                        )
                    else:
                        return empty_res
            else:
                all_w_char_pks = set()
                for w in matched_writers:
                    for c in w.characters:
                        all_w_char_pks.add(c.pk)
                        for child in c.children:
                            all_w_char_pks.add(child.pk)
                if all_w_char_pks:
                    query = query.filter(
                        EventModel.scenes.any(
                            SceneModel.participants.any(SceneParticipantModel.character_pk.in_(all_w_char_pks))
                        )
                    )
                else:
                    return empty_res

    total_items = query.count()

    if str(sort).lower() in ("desc", "start_desc", "newest"):
        query = query.order_by(EventModel.start_at.desc(), EventModel.pk.desc())
    else:
        query = query.order_by(EventModel.start_at.asc(), EventModel.pk.asc())

    query = query.options(
        selectinload(EventModel.scenes).selectinload(SceneModel.channel),
        selectinload(EventModel.scenes)
        .selectinload(SceneModel.participants)
        .selectinload(SceneParticipantModel.character)
        .selectinload(CharacterModel.names),
    )

    if page is not None:
        total_pages = math.ceil(total_items / per_page) if per_page > 0 else 1
        page = max(1, min(page, max(1, total_pages)))
        offset = (page - 1) * per_page
        events_raw = query.offset(offset).limit(per_page).all()
    else:
        events_raw = query.all()

    formatted_events = [format_event_model(session, ev, server_id) for ev in events_raw]

    if page is not None:
        return {
            "total_items": total_items,
            "current_page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "events": formatted_events,
            "scenes": formatted_events,
        }

    return formatted_events


def query_events(
    session_or_backup_id: Any = None,
    backup_id_or_base_path: Any = None,
    *,
    backup_id: Optional[str] = None,
    base_path: Optional[str] = None,
    **kwargs,
) -> Any:
    """
    Queries events from SQLite with pagination and filters.
    Supports both:
      - query_events(session, backup_id, ...)
      - query_events(backup_id, base_path, ...)
    """
    if _is_sa_session(session_or_backup_id):
        session = session_or_backup_id
        b_id = str(backup_id or backup_id_or_base_path)
        return _query_events_in_session(session, b_id, **kwargs)

    b_id = str(backup_id or session_or_backup_id)
    b_path = str(base_path or backup_id_or_base_path)
    require_db(b_path, backup_id=b_id)

    with db_session(backup_id=b_id, backup_path=b_path) as session:
        return _query_events_in_session(session, b_id, **kwargs)


# --- EVENT CURATION OPERATIONS ---


def _update_event_metadata_in_session(
    session,
    backup_id: str,
    event_pk: int,
    name: Optional[str] = None,
    channel_names: Optional[Dict[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    ev = (
        session.query(EventModel)
        .filter(
            EventModel.backup_id == str(backup_id),
            EventModel.pk == int(event_pk),
        )
        .first()
    )
    if not ev:
        raise exc.NotFoundError(f"Event #{event_pk} not found.")

    ev.name = name.strip() if isinstance(name, str) and name.strip() else None
    ev.is_curated = True

    if isinstance(channel_names, dict):
        norm_names = {str(k): v for k, v in channel_names.items()}
        for sc in ev.scenes:
            matched_key = None
            if str(sc.pk) in norm_names:
                matched_key = str(sc.pk)
            elif sc.scene_key in norm_names:
                matched_key = sc.scene_key
            elif sc.channel and str(sc.channel.discord_id) in norm_names:
                matched_key = str(sc.channel.discord_id)
            elif sc.channel and sc.channel.name in norm_names:
                matched_key = sc.channel.name

            if matched_key is not None:
                raw_val = norm_names[matched_key]
                sc.custom_name = raw_val.strip() if isinstance(raw_val, str) and raw_val.strip() else None

    # Sync custom_name into character_movements JSON
    custom_by_key = {sc.scene_key: sc.custom_name for sc in ev.scenes}
    custom_by_chan = {sc.channel.discord_id: sc.custom_name for sc in ev.scenes if sc.channel and sc.custom_name}
    if ev.character_movements:
        new_movements = {}
        for cid_str, hops in ev.character_movements.items():
            updated_hops = []
            for hop in hops:
                h_copy = dict(hop)
                s_id = h_copy.get("scene_id") or h_copy.get("scene_key")
                ch_id = str(h_copy.get("channel_id") or "")
                if s_id in custom_by_key:
                    h_copy["custom_name"] = custom_by_key[s_id]
                elif ch_id in custom_by_chan:
                    h_copy["custom_name"] = custom_by_chan[ch_id]
                updated_hops.append(h_copy)
            new_movements[str(cid_str)] = updated_hops
        ev.character_movements = new_movements

    session.flush()
    backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
    server_id = backup.server_id if backup and backup.server_id else ""
    formatted = format_event_model(session, ev, server_id)
    res = dict(formatted)
    res["status"] = "success"
    res["event"] = formatted
    return res


def update_event_metadata(
    session_or_backup_id: Any,
    backup_id_or_base_path: Any,
    event_pk: int,
    name: Optional[str] = None,
    channel_names: Optional[Dict[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    if _is_sa_session(session_or_backup_id):
        return _update_event_metadata_in_session(
            session_or_backup_id,
            str(backup_id_or_base_path),
            event_pk,
            name=name,
            channel_names=channel_names,
        )

    b_id = str(session_or_backup_id)
    b_path = str(backup_id_or_base_path)
    require_db(b_path, backup_id=b_id)
    init_db(engine_or_backup_id=b_id, backup_path=b_path)
    with db_session(backup_id=b_id, backup_path=b_path) as session:
        return _update_event_metadata_in_session(
            session,
            b_id,
            event_pk,
            name=name,
            channel_names=channel_names,
        )


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _recompute_event_from_scenes(ev: EventModel, scenes: List[SceneModel]) -> None:
    text_scenes = [s for s in scenes if not s.channel or s.channel.type != "GuildPublicThread"]
    bound_scenes = text_scenes if text_scenes else scenes
    if bound_scenes:
        ev.start_at = min(_ensure_utc(s.start_at) for s in bound_scenes if s.start_at)
        ev.end_at = max(_ensure_utc(s.end_at) for s in bound_scenes if s.end_at)
        if any(s.status == SceneStatus.CLOSED.value for s in bound_scenes):
            ev.status = SceneStatus.CLOSED.value
        else:
            ev.status = SceneStatus.OPEN.value
    ev.message_count = sum(s.message_count for s in scenes)


def _merge_events_in_session(
    session,
    backup_id: str,
    event_pks: List[int],
    target_name: Optional[str] = None,
    base_path: Optional[str] = None,
) -> Dict[str, Any]:
    from pathlib import Path
    from index_events import is_tupper_Id

    if not base_path:
        db_file = None
        if (
            hasattr(session, "bind")
            and session.bind
            and getattr(session.bind.dialect, "name", None) == "sqlite"
            and hasattr(session.bind, "url")
            and session.bind.url
            and session.bind.url.database
            and session.bind.url.database != ":memory:"
            and os.path.exists(session.bind.url.database)
        ):
            db_file = session.bind.url.database
        if db_file:
            base_path = Path(db_file).parent.as_posix()
        else:
            try:
                base_path = t.get_backup_path(backup_id)
            except Exception:
                base_path = ""

    if not event_pks or len(set(event_pks)) < 2:
        raise exc.ValidationError("At least 2 distinct event IDs are required to merge.")

    events = (
        session.query(EventModel)
        .filter(
            EventModel.backup_id == str(backup_id),
            EventModel.pk.in_([int(x) for x in event_pks]),
        )
        .all()
    )
    if len(events) < 2:
        raise exc.NotFoundError("Could not find at least 2 matching events to merge.")

    events.sort(key=lambda e: (e.start_at or datetime.min.replace(tzinfo=timezone.utc), e.pk))
    primary_event = events[0]
    secondary_events = events[1:]

    if target_name is not None and str(target_name).strip():
        primary_event.name = str(target_name).strip()
    elif not primary_event.name:
        for sec in secondary_events:
            if sec.name:
                primary_event.name = sec.name
                break

    # Step A: Validate channel contiguity across all merging events BEFORE mutating or deleting anything
    all_candidate_scenes = list(primary_event.scenes)
    for sec in secondary_events:
        all_candidate_scenes.extend(list(sec.scenes))

    scenes_by_chan_check: Dict[int, List[SceneModel]] = {}
    for sc in all_candidate_scenes:
        scenes_by_chan_check.setdefault(sc.channel_pk, []).append(sc)

    for chan_pk, ch_scenes in scenes_by_chan_check.items():
        if len(ch_scenes) <= 1:
            continue

        ch_scenes.sort(key=lambda s: (s.start_index, s.start_at or datetime.min.replace(tzinfo=timezone.utc)))
        chan_model = ch_scenes[0].channel
        chan_name = chan_model.name if chan_model else f"channel-{chan_pk}"

        c_path = Path(chan_model.path) if chan_model else None
        messages = []
        if c_path and base_path:
            fp = Path(base_path) / c_path
            if not fp.exists():
                fp = Path(base_path) / "Data" / c_path
            if fp.exists():
                channel_data = t.load_from_json(fp.as_posix())
                messages = channel_data.get("messages", [])

        for i in range(len(ch_scenes) - 1):
            s1_chk = ch_scenes[i]
            s2_chk = ch_scenes[i + 1]

            # 1. s2.start_index > s1.end_index
            if s2_chk.start_index <= s1_chk.end_index:
                raise exc.ValidationError(
                    f"Cannot merge events: Channel '#{chan_name}' has scenes that cannot be merged because another scene intervenes between them."
                )

            # 2. No intervening scene in that channel exists between s1 and s2 in the database
            intervening = (
                session.query(SceneModel)
                .filter(
                    SceneModel.backup_id == str(backup_id),
                    SceneModel.channel_pk == chan_pk,
                    SceneModel.start_index > s1_chk.end_index,
                    SceneModel.start_index < s2_chk.start_index,
                )
                .first()
            )
            if intervening:
                raise exc.ValidationError(
                    f"Cannot merge events: Channel '#{chan_name}' has scenes that cannot be merged because another scene intervenes between them."
                )

            # 3. No intervening roleplay/tupper message exists between s1 and s2 in the channel chatlog
            # (ignore Discord system notifications like ThreadCreated)
            if messages:
                for m in messages[s1_chk.end_index + 1 : s2_chk.start_index]:
                    if m.get("type", "Default") == "Default":
                        aid = t.get_author_id(m)
                        if is_tupper_Id(aid):
                            raise exc.ValidationError(
                                f"Cannot merge events: Channel '#{chan_name}' has scenes that cannot be merged because another scene intervenes between them."
                            )

    # Step B: Validation passed! Reassign scenes from secondary events to primary_event and collect movements
    combined_movements: Dict[str, List[Dict[str, Any]]] = {}
    for cid_str, hops in (primary_event.character_movements or {}).items():
        combined_movements.setdefault(str(cid_str), []).extend([dict(h) for h in hops])

    for sec in secondary_events:
        for sc in list(sec.scenes):
            sc.event = primary_event
            sc.event_pk = primary_event.pk
        for cid_str, hops in (sec.character_movements or {}).items():
            combined_movements.setdefault(str(cid_str), []).extend([dict(h) for h in hops])

    session.flush()

    # Delete secondary events
    for sec in secondary_events:
        session.query(EventModel).filter(EventModel.pk == sec.pk).delete(synchronize_session="fetch")
    session.flush()

    # Step C: Merge contiguous channel scenes within primary_event
    from db.curation_service import _merge_scenes

    all_scenes_current = (
        session.query(SceneModel)
        .options(joinedload(SceneModel.channel))
        .filter(SceneModel.event_pk == primary_event.pk, SceneModel.backup_id == str(backup_id))
        .all()
    )
    scenes_by_chan: Dict[int, List[SceneModel]] = {}
    for sc in all_scenes_current:
        scenes_by_chan.setdefault(sc.channel_pk, []).append(sc)

    for chan_pk, ch_scenes in scenes_by_chan.items():
        if len(ch_scenes) <= 1:
            continue

        ch_scenes.sort(key=lambda s: (s.start_index, s.start_at or datetime.min.replace(tzinfo=timezone.utc)))

        while len(ch_scenes) > 1:
            s1 = ch_scenes[0]
            s2 = ch_scenes[1]

            s2_start_mid = str(s2.start_message_id)
            s2_start_idx = s2.start_index
            s2_start_excerpt = s2.start_excerpt
            s1_participants = list(s1.participants)
            s2_participants = list(s2.participants)

            # Resolve character char_id (Tupperbox/Discord ID) for participants, not character_pk
            all_ev_pks = {p.character_pk for p in s1_participants} | {p.character_pk for p in s2_participants}
            ev_pk_to_cid = {}
            if all_ev_pks:
                ev_char_rows = session.query(CharacterModel.pk, CharacterModel.char_id).filter(CharacterModel.pk.in_(all_ev_pks)).all()
                ev_pk_to_cid = {r.pk: r.char_id for r in ev_char_rows}
            ev_prev_cids = sorted(list({ev_pk_to_cid[p.character_pk] for p in s1_participants if p.character_pk in ev_pk_to_cid}))
            ev_next_cids = sorted(list({ev_pk_to_cid[p.character_pk] for p in s2_participants if p.character_pk in ev_pk_to_cid}))

            merged_s1 = _merge_scenes(session, backup_id, base_path, s1, s2)

            existing_issue = (
                session.query(SceneIssueModel)
                .filter(
                    SceneIssueModel.backup_id == str(backup_id),
                    or_(
                        (SceneIssueModel.scene_pk == merged_s1.pk) & (SceneIssueModel.candidate_message_id == s2_start_mid),
                        SceneIssueModel.candidate_message_id == s2_start_mid,
                    ),
                )
                .first()
            )
            resolved_note = f"Merged during event merge: {primary_event.name or primary_event.event_key}"
            if existing_issue:
                existing_issue.resolution = "merged"
                existing_issue.resolved_at = datetime.now(timezone.utc)
                existing_issue.resolved_note = resolved_note
                existing_issue.scene_pk = merged_s1.pk
                existing_issue.next_scene_pk = None
            else:
                from db.models import IssueKind
                session.add(SceneIssueModel(
                    backup_id=str(backup_id),
                    scene_pk=merged_s1.pk,
                    next_scene_pk=None,
                    kind=IssueKind.AUTO_SPLIT.value,
                    reason="inactivity_gap",
                    candidate_message_id=s2_start_mid,
                    candidate_index=s2_start_idx,
                    candidate_excerpt=s2_start_excerpt,
                    previous_chars=ev_prev_cids,
                    next_chars=ev_next_cids,
                    created_at=merged_s1.start_at,
                    resolved_at=datetime.now(timezone.utc),
                    resolved_note=resolved_note,
                    resolution="merged",
                ))

            ch_scenes = [merged_s1] + ch_scenes[2:]

    # Fetch surviving scenes and renumber
    surviving_scenes = (
        session.query(SceneModel)
        .options(joinedload(SceneModel.channel))
        .filter(SceneModel.event_pk == primary_event.pk, SceneModel.backup_id == str(backup_id))
        .order_by(SceneModel.start_at.asc(), SceneModel.pk.asc())
        .all()
    )

    for sc in surviving_scenes:
        sc.scene_key = f"tmp-ev-{sc.pk}"
    session.flush()

    for idx, sc in enumerate(surviving_scenes, start=1):
        sc.scene_key = f"{primary_event.event_key}-{idx}"
    session.flush()

    scene_key_by_chan_id = {
        sc.channel.discord_id: sc.scene_key
        for sc in surviving_scenes
        if sc.channel and sc.channel.type != "GuildPublicThread"
    }
    custom_name_by_chan_id = {
        sc.channel.discord_id: sc.custom_name
        for sc in surviving_scenes
        if sc.channel and sc.custom_name
    }

    # Merge and smooth character movements per character
    merged_movements_final: Dict[str, List[Dict[str, Any]]] = {}
    for cid_str, hops in combined_movements.items():
        hops.sort(key=lambda h: (_parse_dt(h.get("first_at")) or datetime.min.replace(tzinfo=timezone.utc), str(h.get("first_message_id") or "")))
        compressed: List[Dict[str, Any]] = []
        for h in hops:
            ch_id = str(h.get("channel_id") or "")
            h_copy = dict(h)
            if ch_id in scene_key_by_chan_id:
                h_copy["scene_id"] = scene_key_by_chan_id[ch_id]
                h_copy["scene_key"] = scene_key_by_chan_id[ch_id]
            if ch_id in custom_name_by_chan_id:
                h_copy["custom_name"] = custom_name_by_chan_id[ch_id]
            h_copy["_first_dt"] = _parse_dt(h_copy.get("first_at")) or datetime.min.replace(tzinfo=timezone.utc)
            h_copy["_last_dt"] = _parse_dt(h_copy.get("last_at")) or datetime.min.replace(tzinfo=timezone.utc)

            if compressed and compressed[-1]["channel_id"] == ch_id:
                prev = compressed[-1]
                prev["last_message_id"] = h_copy.get("last_message_id") or h_copy.get("first_message_id")
                prev["last_at"] = h_copy.get("last_at")
                prev["_last_dt"] = h_copy["_last_dt"]
                prev["message_count"] = int(prev.get("message_count", 0)) + int(h_copy.get("message_count", 0))
            else:
                compressed.append(h_copy)

        smoothed = _smooth_runs(compressed)
        merged_movements_final[str(cid_str)] = [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in smoothed
        ]

    primary_event.is_curated = True
    primary_event.character_movements = merged_movements_final
    _recompute_event_from_scenes(primary_event, surviving_scenes)
    session.flush()
    session.refresh(primary_event)

    backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
    server_id = backup.server_id if backup and backup.server_id else ""
    formatted = format_event_model(session, primary_event, server_id)
    res = dict(formatted)
    res["status"] = "success"
    res["event"] = formatted
    return res


def merge_events(
    session_or_backup_id: Any,
    backup_id_or_base_path: Any = None,
    event_pks_or_req: Any = None,
    target_name: Optional[str] = None,
    *,
    backup_id: Optional[str] = None,
    base_path: Optional[str] = None,
    event_pks: Optional[List[int]] = None,
) -> Dict[str, Any]:
    if _is_sa_session(session_or_backup_id):
        session = session_or_backup_id
        b_id = str(backup_id or backup_id_or_base_path)
        pks = event_pks
        t_name = target_name
        if pks is None and isinstance(event_pks_or_req, list):
            pks = event_pks_or_req
        elif pks is None and hasattr(event_pks_or_req, "event_pks"):
            pks = list(event_pks_or_req.event_pks or [])
            if not pks and getattr(event_pks_or_req, "target_event_pk", None) and getattr(event_pks_or_req, "source_event_pk", None):
                pks = [event_pks_or_req.target_event_pk, event_pks_or_req.source_event_pk]
            t_name = getattr(event_pks_or_req, "name", None) or getattr(event_pks_or_req, "merged_name", None)
        return _merge_events_in_session(
            session,
            b_id,
            pks or [],
            target_name=t_name,
            base_path=base_path,
        )

    b_id = str(backup_id or session_or_backup_id)
    b_path = str(base_path or backup_id_or_base_path)
    pks = event_pks
    t_name = target_name

    # Handle if second arg is a request object: merge_events(backup_id, req)
    if hasattr(backup_id_or_base_path, "event_pks") or hasattr(backup_id_or_base_path, "target_event_pk"):
        req = backup_id_or_base_path
        if hasattr(req, "event_pks") and req.event_pks:
            pks = list(req.event_pks)
        elif getattr(req, "target_event_pk", None) and getattr(req, "source_event_pk", None):
            pks = [req.target_event_pk, req.source_event_pk]
        t_name = getattr(req, "name", None) or getattr(req, "merged_name", None)
        b_path = base_path or t.get_backup_path(b_id)
    elif hasattr(event_pks_or_req, "event_pks") or hasattr(event_pks_or_req, "target_event_pk"):
        req = event_pks_or_req
        if hasattr(req, "event_pks") and req.event_pks:
            pks = list(req.event_pks)
        elif getattr(req, "target_event_pk", None) and getattr(req, "source_event_pk", None):
            pks = [req.target_event_pk, req.source_event_pk]
        t_name = getattr(req, "name", None) or getattr(req, "merged_name", None)
    elif isinstance(event_pks_or_req, list):
        pks = event_pks_or_req

    require_db(b_path, backup_id=b_id)
    init_db(engine_or_backup_id=b_id, backup_path=b_path)
    with db_session(backup_id=b_id, backup_path=b_path) as session:
        return _merge_events_in_session(
            session,
            b_id,
            pks or [],
            target_name=t_name,
            base_path=b_path,
        )


def _split_event_in_session(
    session,
    backup_id: str,
    event_pk: int,
    scene_ids_to_extract: List[str],
    new_event_name: Optional[str] = None,
) -> Dict[str, Any]:
    ev = (
        session.query(EventModel)
        .filter(
            EventModel.backup_id == str(backup_id),
            EventModel.pk == int(event_pk),
        )
        .first()
    )
    if not ev:
        raise exc.NotFoundError(f"Event #{event_pk} not found.")

    if not scene_ids_to_extract:
        raise exc.ValidationError("No scenes/channels specified for splitting.")

    target_set = {str(x) for x in scene_ids_to_extract}
    all_scenes = list(ev.scenes)

    extracted_scenes: List[SceneModel] = []
    for sc in all_scenes:
        if (
            sc.scene_key in target_set
            or str(sc.pk) in target_set
            or (sc.channel and sc.channel.discord_id in target_set)
            or (sc.channel and sc.channel.name in target_set)
        ):
            extracted_scenes.append(sc)

    # Also include threads whose parent channel was extracted (unless remaining scenes still have that parent channel)
    extracted_chan_pks = {sc.channel_pk for sc in extracted_scenes}
    remaining_chan_pks = {sc.channel_pk for sc in all_scenes if sc not in extracted_scenes}
    for sc in all_scenes:
        if sc not in extracted_scenes and sc.channel and sc.channel.type == "GuildPublicThread":
            if sc.channel.parent_pk in extracted_chan_pks and sc.channel.parent_pk not in remaining_chan_pks:
                extracted_scenes.append(sc)

    if not extracted_scenes or len(extracted_scenes) >= len(all_scenes):
        raise exc.ValidationError("Must select a non-empty proper subset of scenes/channels to split.")

    remaining_scenes = [sc for sc in all_scenes if sc not in extracted_scenes]

    # Determine next available event_key
    existing_keys = [
        r[0]
        for r in session.query(EventModel.event_key).filter(EventModel.backup_id == str(backup_id)).all()
    ]
    max_num = 0
    for k in existing_keys:
        if k and k.startswith("ev-") and k[3:].isdigit():
            max_num = max(max_num, int(k[3:]))
    new_event_key = f"ev-{max_num + 1}"

    extracted_old_keys = {sc.scene_key for sc in extracted_scenes}
    extracted_chan_ids = {sc.channel.discord_id for sc in extracted_scenes if sc.channel}
    remaining_old_keys = {sc.scene_key for sc in remaining_scenes}
    remaining_chan_ids = {sc.channel.discord_id for sc in remaining_scenes if sc.channel}

    new_ev = EventModel(
        backup_id=str(backup_id),
        event_key=new_event_key,
        name=new_event_name.strip() if isinstance(new_event_name, str) and new_event_name.strip() else None,
        status=SceneStatus.OPEN.value,
        start_at=ev.start_at,
        end_at=ev.end_at,
        message_count=0,
        is_curated=True,
        character_movements={},
    )
    session.add(new_ev)
    session.flush()

    for sc in extracted_scenes:
        sc.event = new_ev
        sc.event_pk = new_ev.pk
    ev.is_curated = True
    session.flush()

    # Renumber scene keys in both events
    remaining_scenes.sort(key=lambda s: (s.start_at or datetime.min.replace(tzinfo=timezone.utc), s.pk))
    extracted_scenes.sort(key=lambda s: (s.start_at or datetime.min.replace(tzinfo=timezone.utc), s.pk))

    old_to_new_rem: Dict[str, str] = {}
    old_to_new_ext: Dict[str, str] = {}

    for sc in remaining_scenes + extracted_scenes:
        sc.scene_key = f"tmp-split-{sc.pk}"
    session.flush()

    for idx, sc in enumerate(remaining_scenes, start=1):
        nk = f"{ev.event_key}-{idx}"
        if sc.channel:
            old_to_new_rem[sc.channel.discord_id] = nk
        sc.scene_key = nk

    for idx, sc in enumerate(extracted_scenes, start=1):
        nk = f"{new_ev.event_key}-{idx}"
        if sc.channel:
            old_to_new_ext[sc.channel.discord_id] = nk
        sc.scene_key = nk
    session.flush()

    # Partition character_movements between original and new event
    orig_movements: Dict[str, List[Dict[str, Any]]] = {}
    new_movements: Dict[str, List[Dict[str, Any]]] = {}

    for cid_str, hops in (ev.character_movements or {}).items():
        rem_hops = []
        ext_hops = []
        for hop in hops:
            s_id = hop.get("scene_id") or hop.get("scene_key")
            ch_id = str(hop.get("channel_id") or "")
            if s_id in extracted_old_keys or (s_id not in remaining_old_keys and ch_id in extracted_chan_ids):
                h_copy = dict(hop)
                if ch_id in old_to_new_ext:
                    h_copy["scene_id"] = old_to_new_ext[ch_id]
                    h_copy["scene_key"] = old_to_new_ext[ch_id]
                ext_hops.append(h_copy)
            elif s_id in remaining_old_keys or ch_id in remaining_chan_ids:
                h_copy = dict(hop)
                if ch_id in old_to_new_rem:
                    h_copy["scene_id"] = old_to_new_rem[ch_id]
                    h_copy["scene_key"] = old_to_new_rem[ch_id]
                rem_hops.append(h_copy)

        if rem_hops:
            orig_movements[str(cid_str)] = rem_hops
        if ext_hops:
            new_movements[str(cid_str)] = ext_hops

    ev.character_movements = orig_movements
    new_ev.character_movements = new_movements

    _recompute_event_from_scenes(ev, remaining_scenes)
    _recompute_event_from_scenes(new_ev, extracted_scenes)
    session.flush()
    session.refresh(ev)
    session.refresh(new_ev)

    backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
    server_id = backup.server_id if backup and backup.server_id else ""
    fmt_orig = format_event_model(session, ev, server_id)
    fmt_new = format_event_model(session, new_ev, server_id)

    res = dict(fmt_new)
    res["status"] = "success"
    res["original_event"] = fmt_orig
    res["remaining_event"] = fmt_orig
    res["new_event"] = fmt_new
    res["event"] = fmt_new
    return res


def split_event(
    session_or_backup_id: Any,
    backup_id_or_base_path: Any,
    event_pk: int,
    scene_ids_to_extract: List[str],
    new_event_name: Optional[str] = None,
) -> Dict[str, Any]:
    if _is_sa_session(session_or_backup_id):
        return _split_event_in_session(
            session_or_backup_id,
            str(backup_id_or_base_path),
            event_pk,
            scene_ids_to_extract,
            new_event_name=new_event_name,
        )

    b_id = str(session_or_backup_id)
    b_path = str(backup_id_or_base_path)
    require_db(b_path, backup_id=b_id)
    init_db(engine_or_backup_id=b_id, backup_path=b_path)
    with db_session(backup_id=b_id, backup_path=b_path) as session:
        return _split_event_in_session(
            session,
            b_id,
            event_pk,
            scene_ids_to_extract,
            new_event_name=new_event_name,
        )

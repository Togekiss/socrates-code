from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import utils.tricks as t
import utils.exceptions as exc
from find_character_scenes import EXCERPT_MAX_LEN

t.set_path()
from res import constants as c

EVENT_CHANNEL_GAP_HOURS = 36.0
EVENT_BANNER_GAP_HOURS = 12.0
EVENT_SETUP_MERGE_HOURS = 72.0
EVENT_CLUSTER_PROXIMITY_HOURS = 18.0

STRICT_EVENT_END_PAT = re.compile(r"(?:`{1,3}\s*EVENT\s+END\b|\[\s*EVENT\s+END\b)", re.IGNORECASE)
MOD_END_PAT = re.compile(r"(?:`{1,3}\s*(?:EVENT\s+END|END)\b|\[\s*(?:EVENT\s+END|END)\b)", re.IGNORECASE)


def is_tupper_Id(author_id: Any) -> bool:
    """Returns True if author_id represents a Tupperbox character ID (< 10000)."""
    return t.is_tupper(author_id)


def is_event_end_tag(msg: Dict[str, Any]) -> bool:
    """
    Detects whether a message is a moderator/Janitor event end marker.
    Ignores standard [END] tags posted by Tupperbox characters.
    """
    if not isinstance(msg, dict):
        return False
    content = str(msg.get("content", "") or "").strip()
    if not content:
        return False

    if len(content) <= 120 and STRICT_EVENT_END_PAT.search(content):
        return True

    author = msg.get("author") or {}
    author_id = author.get("id")
    author_name = str(author.get("name", "") or "").strip()

    if (not is_tupper_Id(author_id) or author_name == "Janitor") and len(content) <= 80:
        if MOD_END_PAT.search(content):
            return True

    return False


def is_banner_message(msg: Dict[str, Any]) -> bool:
    """Returns True if msg is a non-tupper image/attachment banner message."""
    if not isinstance(msg, dict):
        return False
    author = msg.get("author") or {}
    author_id = author.get("id")
    if is_tupper_Id(author_id):
        return False
    if is_event_end_tag(msg):
        return False
    attachments = msg.get("attachments") or []
    embeds = msg.get("embeds") or []
    return len(attachments) > 0 or len(embeds) > 0


class EventDictObject(dict):
    """Dictionary subclass supporting attribute-style access for segments, clusters, and runs."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


class EventSegment(EventDictObject):
    """Represents a single channel or thread segment belonging to an Event."""
    pass


class EventCluster(EventDictObject):
    """Represents a multi-channel Event cluster with attached threads and character movements."""
    pass


def _build_segment_from_messages(
    msgs_with_idx: List[Tuple[int, Dict[str, Any]]],
    status: str,
    channel_id: str,
    channel_name: str,
    channel_type: str,
    parent_channel_id: Optional[str],
    category_name: str,
    seg_index: int,
) -> Optional[EventSegment]:
    if not msgs_with_idx:
        return None

    participant_map: Dict[int, Dict[str, Any]] = {}
    for _, m in msgs_with_idx:
        aid = t.get_author_id(m)
        if not is_tupper_Id(aid):
            continue
        cid = int(aid)
        msg_id_str = str(m.get("id", ""))
        msg_dt = t.parse_datetime(m.get("timestamp"))
        author_name = str((m.get("author") or {}).get("name") or f"Character #{cid}")
        if cid not in participant_map:
            participant_map[cid] = EventDictObject({
                "char_id": cid,
                "id": cid,
                "name": author_name,
                "position": len(participant_map),
                "first_message_id": msg_id_str,
                "first_at": msg_dt,
                "last_message_id": msg_id_str,
                "last_at": msg_dt,
                "message_count": 1,
            })
        else:
            p_entry = participant_map[cid]
            p_entry["last_message_id"] = msg_id_str
            p_entry["last_at"] = msg_dt
            p_entry["message_count"] += 1

    if not participant_map:
        return None

    first_raw_idx, first_msg = msgs_with_idx[0]
    _, last_msg = msgs_with_idx[-1]
    msg_count = len(msgs_with_idx)
    start_idx = int(first_msg.get("raw_index", first_raw_idx))
    end_idx = start_idx + msg_count - 1

    start_dt = t.parse_datetime(first_msg.get("timestamp")) or datetime.now(timezone.utc)
    end_dt = t.parse_datetime(last_msg.get("timestamp")) or start_dt

    first_content = str(first_msg.get("content", "") or "")
    last_content = str(last_msg.get("content", "") or "")
    start_excerpt = first_content if len(first_content) <= EXCERPT_MAX_LEN else first_content[:EXCERPT_MAX_LEN - 3] + "..."
    end_excerpt = last_content if len(last_content) <= EXCERPT_MAX_LEN else "..." + last_content[-(EXCERPT_MAX_LEN - 3):]

    is_thread = channel_type != "GuildTextChat"
    participant_details = list(participant_map.values())
    characters = [p["char_id"] for p in participant_details]
    seg_id = f"ev-seg-{channel_id}-{seg_index}"

    return EventSegment({
        "id": seg_id,
        "scene_key": seg_id,
        "kind": "event",
        "channel_id": channel_id,
        "channelId": channel_id,
        "channel_name": channel_name,
        "channel": channel_name,
        "category": category_name,
        "channel_type": channel_type,
        "type": "thread" if is_thread else "channel",
        "is_thread": is_thread,
        "parent_channel_id": parent_channel_id,
        "status": status,
        "start_at": start_dt,
        "end_at": end_dt,
        "start_message_id": str(first_msg.get("id", "")),
        "end_message_id": str(last_msg.get("id", "")),
        "start_index": start_idx,
        "end_index": end_idx,
        "start_author_id": str((first_msg.get("author") or {}).get("id", "")),
        "end_author_id": str((last_msg.get("author") or {}).get("id", "")),
        "start_excerpt": start_excerpt,
        "end_excerpt": end_excerpt,
        "message_count": msg_count,
        "characters": characters,
        "participants": participant_details,
        "participant_details": participant_details,
        "messages": [m for _, m in msgs_with_idx],
        "start": {
            "id": str(first_msg.get("id", "")),
            "timestamp": start_dt.isoformat(),
            "index": start_idx,
            "authorID": str((first_msg.get("author") or {}).get("id", "")),
            "content": start_excerpt,
        },
        "end": {
            "id": str(last_msg.get("id", "")),
            "timestamp": end_dt.isoformat(),
            "index": end_idx,
            "authorID": str((last_msg.get("author") or {}).get("id", "")),
            "content": end_excerpt,
        },
    })


def find_all_event_segments_in_channel(
    channel_data: Dict[str, Any],
    manual_split_after_ids: Optional[Set[str]] = None,
    resolved_decisions: Optional[Dict[str, str]] = None,
) -> List[EventSegment]:
    """
    Stage 1: Segments a single event channel or thread JSON dictionary into EventSegment objects.
    """
    chan_info = channel_data.get("channel") or {}
    channel_id = str(chan_info.get("id") or channel_data.get("id") or "")
    channel_name = str(chan_info.get("name") or channel_data.get("name") or "")
    channel_type = str(chan_info.get("type") or channel_data.get("type") or "GuildTextChat")
    is_thread = channel_type != "GuildTextChat"
    parent_channel_id = str(chan_info.get("categoryId") or channel_data.get("parent_channel_id") or "") if is_thread else None
    category_name = str(chan_info.get("category") or "Events")

    raw_messages = channel_data.get("messages") or []
    manual_splits = {str(x) for x in (manual_split_after_ids or set())}
    resolved_decisions = resolved_decisions or {}

    default_msgs: List[Tuple[int, Dict[str, Any]]] = [
        (idx, msg)
        for idx, msg in enumerate(raw_messages)
        if isinstance(msg, dict) and msg.get("type", "Default") == "Default"
    ]
    if not default_msgs:
        return []

    if is_thread:
        raw_thread_chunks: List[Tuple[List[Tuple[int, Dict[str, Any]]], str]] = []
        cur_chunk: List[Tuple[int, Dict[str, Any]]] = []
        for idx, msg in default_msgs:
            m_id = str(msg.get("id", ""))
            if cur_chunk and resolved_decisions.get(m_id) == "split":
                raw_thread_chunks.append((cur_chunk, "closed"))
                cur_chunk = []
            cur_chunk.append((idx, msg))
            if m_id in manual_splits:
                raw_thread_chunks.append((cur_chunk, "closed"))
                cur_chunk = []
        if cur_chunk:
            raw_thread_chunks.append((cur_chunk, "open"))

        segments: List[EventSegment] = []
        for seg_idx, (chunk_msgs, st) in enumerate(raw_thread_chunks, start=1):
            seg = _build_segment_from_messages(
                msgs_with_idx=chunk_msgs,
                status=st,
                channel_id=channel_id,
                channel_name=channel_name,
                channel_type=channel_type,
                parent_channel_id=parent_channel_id,
                category_name=category_name,
                seg_index=seg_idx,
            )
            if seg is not None:
                segments.append(seg)
        return segments

    # GuildTextChat segmentation
    raw_segments: List[Dict[str, Any]] = []
    current_msgs: List[Tuple[int, Dict[str, Any]]] = []

    for idx, msg in default_msgs:
        msg_id = str(msg.get("id", ""))
        msg_dt = t.parse_datetime(msg.get("timestamp"))

        if current_msgs:
            if resolved_decisions.get(msg_id) == "split":
                raw_segments.append({
                    "msgs": current_msgs,
                    "status": "closed",
                    "closed_by_manual": True,
                })
                current_msgs = []
            else:
                prev_dt = t.parse_datetime(current_msgs[-1][1].get("timestamp"))
                gap_hours = ((msg_dt - prev_dt).total_seconds() / 3600.0) if (msg_dt and prev_dt) else 0.0
                if gap_hours >= EVENT_CHANNEL_GAP_HOURS or (
                    gap_hours >= EVENT_BANNER_GAP_HOURS and is_banner_message(msg)
                ):
                    raw_segments.append({
                        "msgs": current_msgs,
                        "status": "open",
                        "closed_by_manual": False,
                    })
                    current_msgs = []

        if not current_msgs and is_event_end_tag(msg):
            # Delayed cleanup end tag closes the previous finalized segment in this channel
            if raw_segments:
                raw_segments[-1]["status"] = "closed"
            continue

        current_msgs.append((idx, msg))

        if is_event_end_tag(msg) or msg_id in manual_splits:
            raw_segments.append({
                "msgs": current_msgs,
                "status": "closed",
                "closed_by_manual": msg_id in manual_splits,
            })
            current_msgs = []

    if current_msgs:
        raw_segments.append({
            "msgs": current_msgs,
            "status": "open",
            "closed_by_manual": False,
        })

    # 1-Message Setup Banner Merge Post-Pass
    merged_raw_segments: List[Dict[str, Any]] = []
    i = 0
    while i < len(raw_segments):
        cur = raw_segments[i]
        if (
            len(cur["msgs"]) == 1
            and not cur.get("closed_by_manual")
            and i + 1 < len(raw_segments)
        ):
            cur_dt = t.parse_datetime(cur["msgs"][0][1].get("timestamp"))
            nxt_dt = t.parse_datetime(raw_segments[i + 1]["msgs"][0][1].get("timestamp"))
            if cur_dt and nxt_dt:
                setup_gap_hours = (nxt_dt - cur_dt).total_seconds() / 3600.0
                if 0.0 <= setup_gap_hours <= EVENT_SETUP_MERGE_HOURS:
                    raw_segments[i + 1]["msgs"] = cur["msgs"] + raw_segments[i + 1]["msgs"]
                    i += 1
                    continue
        merged_raw_segments.append(cur)
        i += 1

    finalized_segments: List[EventSegment] = []
    for seg_idx, raw_seg in enumerate(merged_raw_segments, start=1):
        seg = _build_segment_from_messages(
            msgs_with_idx=raw_seg["msgs"],
            status=raw_seg["status"],
            channel_id=channel_id,
            channel_name=channel_name,
            channel_type=channel_type,
            parent_channel_id=None,
            category_name=category_name,
            seg_index=seg_idx,
        )
        if seg is not None:
            finalized_segments.append(seg)

    return finalized_segments


detect_event_channel_segments = find_all_event_segments_in_channel


def _recompute_cluster_aggregates(ev: EventCluster) -> None:
    text_segs: List[EventSegment] = ev.get("text_segments") or []
    thread_segs: List[EventSegment] = ev.get("thread_segments") or []
    all_segs = text_segs + thread_segs
    ev["scenes"] = all_segs

    if text_segs:
        ev["start_at"] = min(s["start_at"] for s in text_segs)
        ev["end_at"] = max(s["end_at"] for s in text_segs)
        ev["status"] = "closed" if any(s.get("status") == "closed" for s in text_segs) else "open"
    elif thread_segs:
        ev["start_at"] = min(s["start_at"] for s in thread_segs)
        ev["end_at"] = max(s["end_at"] for s in thread_segs)
        ev["status"] = "closed" if any(s.get("status") == "closed" for s in thread_segs) else "open"

    ev["message_count"] = sum(int(s.get("message_count", 0)) for s in all_segs)

    # Aggregate participants across all member segments (text + threads) ordered by earliest first_at
    agg_participants: Dict[int, Dict[str, Any]] = {}
    for seg in all_segs:
        for p in seg.get("participants", []):
            cid = int(p.get("char_id") if p.get("char_id") is not None else p.get("id"))
            p_first_at = t.parse_datetime(p.get("first_at"))
            p_last_at = t.parse_datetime(p.get("last_at"))
            if cid not in agg_participants:
                agg_participants[cid] = EventDictObject({
                    "id": cid,
                    "char_id": cid,
                    "name": p.get("name") or f"Character #{cid}",
                    "first_at": p_first_at,
                    "last_at": p_last_at,
                    "first_message_id": p.get("first_message_id"),
                    "last_message_id": p.get("last_message_id"),
                })
            else:
                existing = agg_participants[cid]
                if p_first_at and (not existing["first_at"] or p_first_at < existing["first_at"]):
                    existing["first_at"] = p_first_at
                    existing["first_message_id"] = p.get("first_message_id")
                if p_last_at and (not existing["last_at"] or p_last_at > existing["last_at"]):
                    existing["last_at"] = p_last_at
                    existing["last_message_id"] = p.get("last_message_id")

    sorted_parts = sorted(
        agg_participants.values(),
        key=lambda x: (x["first_at"] or datetime.max.replace(tzinfo=timezone.utc), x["id"]),
    )
    ev["participants"] = sorted_parts


def group_segments_into_events(
    text_segments: List[EventSegment],
    thread_segments: Optional[List[EventSegment]] = None,
) -> List[EventCluster]:
    """
    Stage 2: Groups per-channel GuildTextChat segments into chronological EventCluster objects,
    then attaches thread segments without expanding the event's GuildTextChat start_at/end_at bounds.
    """
    thread_segments = thread_segments or []
    sorted_text = sorted(
        text_segments,
        key=lambda s: (
            t.parse_datetime(s["start_at"]) or datetime.min.replace(tzinfo=timezone.utc),
            t.parse_datetime(s["end_at"]) or datetime.min.replace(tzinfo=timezone.utc),
            str(s.get("channel_id", "")),
        ),
    )

    clusters: List[EventCluster] = []

    for seg in sorted_text:
        seg_start = t.parse_datetime(seg["start_at"])
        seg_end = t.parse_datetime(seg["end_at"])
        seg["start_at"] = seg_start
        seg["end_at"] = seg_end
        seg_chan_id = str(seg.get("channel_id", ""))

        if not clusters:
            ev = EventCluster({
                "id": "ev-1",
                "event_key": "ev-1",
                "name": None,
                "status": seg.get("status", "open"),
                "start_at": seg_start,
                "end_at": seg_end,
                "message_count": int(seg.get("message_count", 0)),
                "is_curated": False,
                "text_segments": [seg],
                "thread_segments": [],
                "scenes": [seg],
                "participants": [],
                "character_movements": {},
            })
            _recompute_cluster_aggregates(ev)
            clusters.append(ev)
            continue

        cur_ev = clusters[-1]
        ev_end = cur_ev["end_at"]
        has_closed_same_chan = any(
            str(s.get("channel_id", "")) == seg_chan_id and s.get("status") == "closed"
            for s in cur_ev["text_segments"]
        )
        all_closed_in_ev = all(s.get("status") == "closed" for s in cur_ev["text_segments"])
        gap_hours = (seg_start - ev_end).total_seconds() / 3600.0

        joins_current = False
        if not has_closed_same_chan:
            if seg_start <= ev_end:
                joins_current = True
            elif gap_hours <= EVENT_CLUSTER_PROXIMITY_HOURS and not all_closed_in_ev:
                joins_current = True

        if joins_current:
            cur_ev["text_segments"].append(seg)
            _recompute_cluster_aggregates(cur_ev)
        else:
            ev_idx = len(clusters) + 1
            new_ev = EventCluster({
                "id": f"ev-{ev_idx}",
                "event_key": f"ev-{ev_idx}",
                "name": None,
                "status": seg.get("status", "open"),
                "start_at": seg_start,
                "end_at": seg_end,
                "message_count": int(seg.get("message_count", 0)),
                "is_curated": False,
                "text_segments": [seg],
                "thread_segments": [],
                "scenes": [seg],
                "participants": [],
                "character_movements": {},
            })
            _recompute_cluster_aggregates(new_ev)
            clusters.append(new_ev)

    # Attach threads
    for th_seg in thread_segments:
        th_start = t.parse_datetime(th_seg["start_at"])
        th_end = t.parse_datetime(th_seg["end_at"])
        th_seg["start_at"] = th_start
        th_seg["end_at"] = th_end
        parent_cid = str(th_seg.get("parent_channel_id") or "")

        target_ev: Optional[EventCluster] = None

        # Priority 1: EventCluster containing a text segment in parent_channel_id whose [start_at - 2h, end_at + 48h] covers th_start
        for ev in clusters:
            has_parent = any(str(s.get("channel_id", "")) == parent_cid for s in ev["text_segments"])
            if has_parent:
                win_start = ev["start_at"] - timedelta(hours=2)
                win_end = ev["end_at"] + timedelta(hours=48)
                if win_start <= th_start <= win_end:
                    target_ev = ev
                    break

        # Priority 2: Any EventCluster whose [start_at - 2h, end_at + 48h] covers th_start
        if target_ev is None:
            for ev in clusters:
                win_start = ev["start_at"] - timedelta(hours=2)
                win_end = ev["end_at"] + timedelta(hours=48)
                if win_start <= th_start <= win_end:
                    target_ev = ev
                    break

        # Priority 3: Closest preceding event in parent_channel_id, or closest preceding event overall
        if target_ev is None and clusters:
            preceding_parent = [
                ev for ev in clusters
                if any(str(s.get("channel_id", "")) == parent_cid for s in ev["text_segments"])
                and ev["start_at"] <= th_start + timedelta(hours=2)
            ]
            if preceding_parent:
                target_ev = preceding_parent[-1]
            else:
                preceding_any = [ev for ev in clusters if ev["start_at"] <= th_start + timedelta(hours=2)]
                target_ev = preceding_any[-1] if preceding_any else clusters[0]

        if target_ev is not None:
            target_ev["thread_segments"].append(th_seg)
            _recompute_cluster_aggregates(target_ev)

    # Assign deterministic scene keys within each cluster and compute movements
    global_seg_counter = 1
    for ev_idx, ev in enumerate(clusters, start=1):
        ev["id"] = f"ev-{ev_idx}"
        ev["event_key"] = f"ev-{ev_idx}"
        for seg in ev["text_segments"] + ev["thread_segments"]:
            s_key = f"ev-{ev_idx}-{global_seg_counter}"
            seg["id"] = s_key
            seg["scene_key"] = s_key
            global_seg_counter += 1
        ev["character_movements"] = compute_event_movements(ev)

    return clusters


def _merge_adjacent_same_channel_runs(runs: List[EventDictObject]) -> List[EventDictObject]:
    if not runs:
        return []
    merged: List[EventDictObject] = [runs[0]]
    for r in runs[1:]:
        prev = merged[-1]
        if prev["channel_id"] == r["channel_id"]:
            prev["last_message_id"] = r["last_message_id"]
            prev["last_at"] = r["last_at"]
            prev["message_count"] += r["message_count"]
        else:
            merged.append(r)
    return merged


def _smooth_character_runs(runs: List[EventDictObject]) -> List[EventDictObject]:
    runs = _merge_adjacent_same_channel_runs(runs)
    changed = True
    while changed:
        changed = False
        # Pattern 1: A(N) -> B(1) -> A(1) -> B(M)
        if len(runs) >= 4:
            for i in range(len(runs) - 3):
                r0, r1, r2, r3 = runs[i], runs[i + 1], runs[i + 2], runs[i + 3]
                if (
                    r0["channel_id"] == r2["channel_id"]
                    and r1["channel_id"] == r3["channel_id"]
                    and r1["message_count"] == 1
                    and r2["message_count"] == 1
                ):
                    r0["last_message_id"] = r2["last_message_id"]
                    r0["last_at"] = r2["last_at"]
                    r0["message_count"] += r2["message_count"]

                    r3["first_message_id"] = r1["first_message_id"]
                    r3["first_at"] = r1["first_at"]
                    r3["message_count"] += r1["message_count"]

                    runs = _merge_adjacent_same_channel_runs(runs[:i + 1] + [r3] + runs[i + 4:])
                    changed = True
                    break
        if changed:
            continue

        # Pattern 2: A(N) -> B(M) -> A(1) where N >= 2 and (M == 1 or A(1) is within 15 minutes of A(N).last_at)
        if len(runs) >= 3:
            for i in range(len(runs) - 2):
                r0, r1, r2 = runs[i], runs[i + 1], runs[i + 2]
                if (
                    r0["channel_id"] == r2["channel_id"]
                    and r0["message_count"] >= 2
                    and r2["message_count"] == 1
                ):
                    dt0 = t.parse_datetime(r0["last_at"])
                    dt2 = t.parse_datetime(r2["last_at"])
                    within_15m = bool(dt0 and dt2 and (dt2 - dt0).total_seconds() <= 900.0)
                    if r1["message_count"] == 1 or within_15m:
                        r0["last_message_id"] = r2["last_message_id"]
                        r0["last_at"] = r2["last_at"]
                        r0["message_count"] += r2["message_count"]
                        runs = _merge_adjacent_same_channel_runs(runs[:i + 2] + runs[i + 3:])
                        changed = True
                        break

    return runs


_smooth_runs = _smooth_character_runs


def compute_event_movements(event_cluster: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Stage 3: Computes per-character movement hop chains across GuildTextChat segments in event_cluster
    (excluding threads), applying ping-pong overlap smoothing.
    """
    text_segs = event_cluster.get("text_segments")
    if text_segs is None:
        all_scenes = event_cluster.get("scenes") or []
        text_segs = [
            s for s in all_scenes
            if not s.get("is_thread") and s.get("type", "channel") != "thread" and s.get("channel_type", "GuildTextChat") == "GuildTextChat"
        ]

    char_messages: Dict[str, List[Tuple[datetime, int, str, str, str, str, str]]] = {}

    for seg in text_segs:
        seg_key = str(seg.get("scene_key") or seg.get("id") or "")
        chan_id = str(seg.get("channel_id") or seg.get("channelId") or "")
        chan_name = str(seg.get("channel_name") or seg.get("channel") or "")
        msgs = seg.get("messages") or []

        for m in msgs:
            aid = t.get_author_id(m)
            if not is_tupper_Id(aid):
                continue
            char_key = str(int(aid))
            msg_id_str = str(m.get("id", ""))
            try:
                msg_id_int = int(msg_id_str)
            except (ValueError, TypeError):
                msg_id_int = 0
            dt = t.parse_datetime(m.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)
            dt_iso = dt.isoformat()
            char_messages.setdefault(char_key, []).append(
                (dt, msg_id_int, msg_id_str, dt_iso, seg_key, chan_id, chan_name)
            )

    movements: Dict[str, List[Dict[str, Any]]] = {}
    for char_key, m_list in char_messages.items():
        m_list.sort(key=lambda x: (x[0], x[1]))
        runs: List[EventDictObject] = []
        for dt, _, msg_id_str, dt_iso, seg_key, chan_id, chan_name in m_list:
            if runs and runs[-1]["channel_id"] == chan_id:
                runs[-1]["last_message_id"] = msg_id_str
                runs[-1]["last_at"] = dt_iso
                runs[-1]["message_count"] += 1
            else:
                runs.append(EventDictObject({
                    "scene_key": seg_key,
                    "scene_id": seg_key,
                    "channel_id": chan_id,
                    "channel_name": chan_name,
                    "first_message_id": msg_id_str,
                    "first_at": dt_iso,
                    "last_message_id": msg_id_str,
                    "last_at": dt_iso,
                    "message_count": 1,
                }))

        smoothed = _smooth_character_runs(runs)
        movements[char_key] = smoothed

    return movements


def index_event_categories(
    event_categories: List[Any],
    data_folder: Optional[str] = None,
    resolved_flags_map: Optional[Dict[str, Any]] = None,
    manual_splits_by_channel: Optional[Dict[str, Set[str]]] = None,
    resolved_decisions: Optional[Dict[str, str]] = None,
    folder: Optional[str] = None,
) -> List[EventCluster]:
    """
    Loads all channel and thread JSON files across event_categories, runs Stage 1 segmentation,
    Stage 2 multi-channel clustering & thread attachment, and Stage 3 character movement calculation.
    """
    from fix_bad_messages import prepare_channel_messages

    data_folder = data_folder or folder or c.DATA_FOLDER

    resolved_flags_map = resolved_flags_map or {}
    manual_splits_by_channel = manual_splits_by_channel or {}
    resolved_decisions = resolved_decisions or {}

    all_text_segments: List[EventSegment] = []
    all_thread_segments: List[EventSegment] = []

    for cat in event_categories:
        for ch in cat.channels:
            ch_file = (Path(data_folder) / ch.path).as_posix()
            if not Path(ch_file).exists():
                continue
            raw_ch_data = t.load_from_json(ch_file)
            prepared_msgs = prepare_channel_messages(raw_ch_data.get("messages", []), resolved_flags_map)
            ch_data = dict(raw_ch_data)
            ch_data["messages"] = prepared_msgs
            if "channel" in ch_data and isinstance(ch_data["channel"], dict):
                ch_data["channel"] = dict(ch_data["channel"])
                ch_data["channel"]["id"] = str(ch.id)
                ch_data["channel"]["name"] = str(ch.name)
                ch_data["channel"]["category"] = str(cat.name)

            ch_splits = manual_splits_by_channel.get(str(ch.id), set())
            segs = find_all_event_segments_in_channel(
                ch_data,
                manual_split_after_ids=ch_splits,
                resolved_decisions=resolved_decisions,
            )
            all_text_segments.extend(segs)

            for th in ch.threads:
                th_file = (Path(data_folder) / th.path).as_posix()
                if not Path(th_file).exists():
                    continue
                raw_th_data = t.load_from_json(th_file)
                prepared_th_msgs = prepare_channel_messages(raw_th_data.get("messages", []), resolved_flags_map)
                th_data = dict(raw_th_data)
                th_data["messages"] = prepared_th_msgs
                if "channel" in th_data and isinstance(th_data["channel"], dict):
                    th_data["channel"] = dict(th_data["channel"])
                    th_data["channel"]["id"] = str(th.id)
                    th_data["channel"]["name"] = str(th.name)
                    th_data["channel"]["categoryId"] = str(ch.id)
                    th_data["channel"]["category"] = str(ch.name)

                th_splits = manual_splits_by_channel.get(str(th.id), set())
                th_segs = find_all_event_segments_in_channel(
                    th_data,
                    manual_split_after_ids=th_splits,
                    resolved_decisions=resolved_decisions,
                )
                all_thread_segments.extend(th_segs)

    return group_segments_into_events(all_text_segments, all_thread_segments)

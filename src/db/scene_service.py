from datetime import datetime, timezone
import math
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from sqlalchemy import BigInteger, cast, func, or_
from sqlalchemy.orm import selectinload, joinedload

from db.session import db_session, require_db, init_db, skeleton_db_session, has_skeleton_db
from db.models import (
    SceneModel,
    SceneParticipantModel,
    SceneIssueModel,
    ChannelModel,
    CharacterModel,
    WriterModel,
    WriterAliasModel,
    BackupModel,
    FlaggedResolution,
    SceneStatus,
    SceneKind,
    IssueKind,
)
from db.skeleton_models import (
    MessageSkeletonModel,
    SkeletonFlags,
    TUPPER_ID_MAX,
    compute_skeleton_flags,
)
from find_character_scenes import EXCERPT_MAX_LEN
import utils.tricks as t

_parse_dt = t.parse_datetime

def _default_discord_excerpt_provider(backup_id: str, channel_discord_id: str, message_id: str) -> Optional[str]:
    """Lightweight wrapper delegating targeted excerpt hydration to DiscordExtractor when DISCORD_TOKEN is set."""
    if not os.environ.get("DISCORD_TOKEN", "").strip():
        return None
    try:
        from discord_extractor import fetch_message_content_sync
        return fetch_message_content_sync(backup_id, channel_discord_id, message_id)
    except Exception:
        return None


# Extensible single-message excerpt provider hook (wired to DiscordExtractor)
_EXTENSIBLE_EXCERPT_PROVIDER: Optional[Callable[[str, str, str], Optional[str]]] = _default_discord_excerpt_provider


def snowflake_int(val: Any, default: int = 0) -> int:
    """Safely converts a Discord Snowflake string/int to int."""
    if val is None:
        return default
    s = str(val).strip()
    if s.isdigit():
        return int(s)
    return default


def resolve_effective_skeleton(
    sk: Any,
    resolved_flags_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Overlays FlaggedMessageModel decisions in memory on top of a MessageSkeletonModel row
    without ever mutating skeletons.sqlite. Returns None when resolved as 'ignored'.
    """
    mid_str = str(sk.message_id)
    eff_author_id = int(sk.author_id)
    eff_flags = int(sk.flags)

    if resolved_flags_map and mid_str in resolved_flags_map:
        flag = resolved_flags_map[mid_str]
        res = flag.get("resolution") if isinstance(flag, dict) else getattr(flag, "resolution", None)
        if res == FlaggedResolution.IGNORED.value:
            return None
        if res == FlaggedResolution.OVERRIDE.value:
            o_author = flag.get("override_author") if isinstance(flag, dict) else getattr(flag, "override_author", None)
            if isinstance(o_author, dict) and o_author.get("id") is not None:
                o_aid_str = str(o_author["id"]).strip()
                if o_aid_str.isdigit():
                    eff_author_id = int(o_aid_str)

            o_flags = flag.get("override_flags") if isinstance(flag, dict) else getattr(flag, "override_flags", None)
            o_content = flag.get("override_content") if isinstance(flag, dict) else getattr(flag, "override_content", None)
            if o_flags is not None:
                eff_flags = int(o_flags)
                if eff_author_id < TUPPER_ID_MAX:
                    eff_flags |= int(SkeletonFlags.IS_TUPPER)
                    eff_flags &= ~int(SkeletonFlags.IS_BANNER)
                else:
                    eff_flags &= ~int(SkeletonFlags.IS_TUPPER)
            elif o_content is not None:
                eff_flags = compute_skeleton_flags(
                    {
                        "type": "Default",
                        "content": o_content,
                        "author": {"id": str(eff_author_id)},
                    },
                    author_id=eff_author_id,
                )
            else:
                if eff_author_id < TUPPER_ID_MAX:
                    eff_flags |= int(SkeletonFlags.IS_TUPPER)
                    eff_flags &= ~int(SkeletonFlags.IS_BANNER)
                else:
                    eff_flags &= ~int(SkeletonFlags.IS_TUPPER)

    is_valid = bool(eff_flags & SkeletonFlags.IS_DEFAULT) and not bool(eff_flags & SkeletonFlags.IS_MENTION_ONLY)
    ts_unix = int(sk.timestamp_unix or 0)
    return {
        "message_id": int(sk.message_id),
        "message_id_str": mid_str,
        "author_id": eff_author_id,
        "timestamp_unix": ts_unix,
        "timestamp_dt": datetime.fromtimestamp(ts_unix, tz=timezone.utc) if ts_unix > 0 else None,
        "flags": eff_flags,
        "is_valid": is_valid,
    }


def load_channel_skeletons(
    backup_id: str,
    base_path: str,
    channel_discord_id: Any,
    start_message_id: Optional[Any] = None,
    end_message_id: Optional[Any] = None,
) -> List[MessageSkeletonModel]:
    """Loads MessageSkeletonModel rows for a channel (optionally bounded by Snowflakes) ordered ASC."""
    if not str(channel_discord_id).isdigit():
        return []
    if not has_skeleton_db(base_path, backup_id=backup_id):
        return []
    chan_id_int = int(channel_discord_id)
    with skeleton_db_session(backup_id=backup_id, backup_path=base_path) as skel_session:
        q = skel_session.query(MessageSkeletonModel).filter(
            MessageSkeletonModel.channel_discord_id == chan_id_int
        )
        if start_message_id is not None and str(start_message_id).isdigit():
            q = q.filter(MessageSkeletonModel.message_id >= int(start_message_id))
        if end_message_id is not None and str(end_message_id).isdigit():
            q = q.filter(MessageSkeletonModel.message_id <= int(end_message_id))
        rows = q.order_by(MessageSkeletonModel.message_id.asc()).all()
        skel_session.expunge_all()
        return rows


def compute_scene_counts_from_skeletons(
    skeletons: List[Any],
    char_id_to_pk: Dict[int, int],
    resolved_flags_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Computes (scene_message_count, participant_details) from skeleton rows + resolved_flags_map.
    Each participant dict contains character_pk, position, first_message_id, first_at,
    last_message_id, last_at, and message_count.
    """
    ordered_cpks: List[int] = []
    details_by_cpk: Dict[int, Dict[str, Any]] = {}
    valid_count = 0

    for sk in skeletons:
        eff = resolve_effective_skeleton(sk, resolved_flags_map=resolved_flags_map)
        if not eff or not eff["is_valid"]:
            continue
        valid_count += 1
        aid = eff["author_id"]
        if t.is_tupper(aid) and aid in char_id_to_pk:
            cpk = char_id_to_pk[aid]
            mid_str = eff["message_id_str"]
            ts_dt = eff["timestamp_dt"]
            if cpk not in details_by_cpk:
                ordered_cpks.append(cpk)
                details_by_cpk[cpk] = {
                    "character_pk": cpk,
                    "position": len(ordered_cpks) - 1,
                    "first_message_id": mid_str,
                    "first_at": ts_dt,
                    "last_message_id": mid_str,
                    "last_at": ts_dt,
                    "message_count": 1,
                }
            else:
                entry = details_by_cpk[cpk]
                entry["last_message_id"] = mid_str
                entry["last_at"] = ts_dt
                entry["message_count"] += 1

    return valid_count, [details_by_cpk[cpk] for cpk in ordered_cpks]


def fetch_message_excerpt(
    backup_id: str,
    base_path: str,
    channel: Optional[ChannelModel],
    message_id: str,
    flagged_content_map: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """
    Resolves a boundary message excerpt during curation:
    1. Cached flagged/override content if provided.
    2. Local channel JSON under Data/<channel.path> when present (e.g. 'full' mode).
    3. Extensible single-message provider hook (wired in Phase 2/3), else None.
    """
    mid_str = str(message_id)
    if flagged_content_map and mid_str in flagged_content_map:
        return t.format_excerpt(flagged_content_map[mid_str])

    if channel and channel.path and base_path:
        c_path = Path(channel.path)
        candidates = [Path(base_path) / c_path, Path(base_path) / "Data" / c_path]
        for f_path in candidates:
            if f_path.exists():
                try:
                    chan_data = t.load_from_json(f_path.as_posix())
                    for m in chan_data.get("messages", []):
                        if str(m.get("id")) == mid_str:
                            return t.format_excerpt(str(m.get("content", "") or ""))
                except Exception:
                    pass
                break

    if _EXTENSIBLE_EXCERPT_PROVIDER is not None and channel:
        raw = _EXTENSIBLE_EXCERPT_PROVIDER(str(backup_id), str(channel.discord_id), mid_str)
        if raw is not None:
            return t.format_excerpt(raw)

    return None


def upsert_channel_skeletons(
    backup_id: str,
    base_path: str,
    channel_discord_id: Any,
    skeletons: List[MessageSkeletonModel],
    effective_after_id: Optional[Any] = None,
) -> Set[int]:
    """
    Bulk upserts MessageSkeletonModel rows for a channel into skeletons.sqlite.
    When `effective_after_id` is set, any existing skeleton row with
    `message_id > int(effective_after_id)` absent from `skeletons` is preserved
    with `SkeletonFlags.IS_DELETED` set. Returns the set of newly/kept deleted message IDs.
    """
    if not str(channel_discord_id).isdigit():
        return set()
    chan_id_int = int(channel_discord_id)
    after_int = int(effective_after_id) if (effective_after_id is not None and str(effective_after_id).isdigit()) else None

    fetched_map: Dict[int, MessageSkeletonModel] = {int(sk.message_id): sk for sk in skeletons}
    deleted_ids: Set[int] = set()

    with skeleton_db_session(backup_id=backup_id, backup_path=base_path) as skel_session:
        q = skel_session.query(MessageSkeletonModel).filter(
            MessageSkeletonModel.channel_discord_id == chan_id_int
        )
        if after_int is not None and after_int > 0:
            q = q.filter(MessageSkeletonModel.message_id > after_int)
        elif fetched_map:
            # First/full window: fetch all existing rows in channel so lookback/rescan detects deletions too
            pass

        existing_rows = q.all()
        existing_by_mid: Dict[int, MessageSkeletonModel] = {int(r.message_id): r for r in existing_rows}

        if after_int is not None:
            for mid_int, row in existing_by_mid.items():
                if mid_int not in fetched_map:
                    row.flags = int(row.flags or 0) | int(SkeletonFlags.IS_DELETED)
                    deleted_ids.add(mid_int)

        to_insert: List[MessageSkeletonModel] = []
        for mid_int, sk in fetched_map.items():
            existing = existing_by_mid.get(mid_int)
            if existing is not None:
                existing.author_id = int(sk.author_id)
                existing.timestamp_unix = int(sk.timestamp_unix)
                existing.flags = int(sk.flags)
            else:
                # Check if row exists outside window (when after_int == 0, existing_by_mid already has all rows)
                to_insert.append(
                    MessageSkeletonModel(
                        channel_discord_id=chan_id_int,
                        message_id=mid_int,
                        author_id=int(sk.author_id),
                        timestamp_unix=int(sk.timestamp_unix),
                        flags=int(sk.flags),
                    )
                )

        if to_insert:
            if after_int is not None and after_int > 0:
                # Avoid PK collision if a fetched message somehow <= after_int
                existing_outside = {
                    r[0]
                    for r in skel_session.query(MessageSkeletonModel.message_id).filter(
                        MessageSkeletonModel.channel_discord_id == chan_id_int,
                        MessageSkeletonModel.message_id.in_([s.message_id for s in to_insert]),
                    ).all()
                }
                if existing_outside:
                    for mid_out in existing_outside:
                        src_sk = fetched_map[int(mid_out)]
                        row = skel_session.query(MessageSkeletonModel).filter(
                            MessageSkeletonModel.channel_discord_id == chan_id_int,
                            MessageSkeletonModel.message_id == int(mid_out),
                        ).first()
                        if row is not None:
                            row.author_id = int(src_sk.author_id)
                            row.timestamp_unix = int(src_sk.timestamp_unix)
                            row.flags = int(src_sk.flags)
                    to_insert = [s for s in to_insert if int(s.message_id) not in existing_outside]
            if to_insert:
                skel_session.bulk_save_objects(to_insert)

    return deleted_ids


def _channel_key_prefix(chan_model: ChannelModel, chan_by_pk: Dict[int, ChannelModel]) -> Tuple[int, str]:
    if chan_model.type == "GuildPublicThread" and chan_model.parent_pk:
        parent_chan = chan_by_pk.get(chan_model.parent_pk)
        cat_chan = chan_by_pk.get(parent_chan.parent_pk) if parent_chan and parent_chan.parent_pk else parent_chan
        category_pk = cat_chan.pk if cat_chan else chan_model.pk
        key_prefix = f"{cat_chan.position if cat_chan else 0}-{parent_chan.position if parent_chan else 0}-{chan_model.position}"
    else:
        cat_chan = chan_by_pk.get(chan_model.parent_pk) if chan_model.parent_pk else chan_model
        category_pk = cat_chan.pk if cat_chan else chan_model.pk
        key_prefix = f"{cat_chan.position if cat_chan else 0}-{chan_model.position}"
    return category_pk, key_prefix


def _insert_channel_scenes_in_session(
    session,
    backup_id: str,
    chan_model: ChannelModel,
    chan_by_pk: Dict[int, ChannelModel],
    char_id_to_pk: Dict[int, int],
    chan_scenes: List[Dict[str, Any]],
    *,
    custom_name_by_chan_start: Dict[Tuple[str, str], str],
    custom_name_by_chan_end: Dict[Tuple[str, str], str],
    start_excerpt_cache: Dict[Tuple[str, str], str],
    end_excerpt_cache: Dict[Tuple[str, str], str],
    issue_excerpt_cache: Dict[str, str],
    resolved_by_candidate: Dict[str, SceneIssueModel],
    temp_keys: bool = False,
) -> List[Tuple[SceneModel, Dict[str, Any]]]:
    chan_discord_id = str(chan_model.discord_id)
    category_pk, key_prefix = _channel_key_prefix(chan_model, chan_by_pk)
    created_scenes: List[Tuple[SceneModel, Dict[str, Any]]] = []

    for idx, s in enumerate(chan_scenes):
        scene_key = f"tmp-ins-{chan_model.pk}-{idx}" if temp_keys else f"{key_prefix}-{idx + 1}"
        lifecycle_status = s.get("status", SceneStatus.CLOSED.value)

        start_at = _parse_dt(s.get("start", {}).get("timestamp")) or datetime.now(timezone.utc)
        end_at = _parse_dt(s.get("end", {}).get("timestamp")) or datetime.now(timezone.utc)
        start_msg_id = str(s.get("start", {}).get("id", ""))
        end_msg_id = str(s.get("end", {}).get("id", ""))
        start_message = str(s.get("start", {}).get("content", "") or "")
        end_message = str(s.get("end", {}).get("content", "") or "")

        start_excerpt = t.format_excerpt(start_message) if start_message else start_excerpt_cache.get((chan_discord_id, start_msg_id), "")
        end_excerpt = t.format_excerpt(end_message) if end_message else end_excerpt_cache.get((chan_discord_id, end_msg_id), "")

        start_idx_val = int(s.get("start", {}).get("index", 0))
        end_idx_val = int(s.get("end", {}).get("index", 0))
        msg_count_val = int(s.get("message_count") or max(0, end_idx_val - start_idx_val + 1))

        restored_custom_name = (
            custom_name_by_chan_start.get((chan_discord_id, start_msg_id))
            or custom_name_by_chan_end.get((chan_discord_id, end_msg_id))
            or s.get("custom_name")
        )

        scene_model = SceneModel(
            backup_id=str(backup_id),
            scene_key=scene_key,
            channel_pk=chan_model.pk,
            category_pk=category_pk,
            custom_name=restored_custom_name,
            kind=s.get("kind", SceneKind.SCENE.value),
            status=lifecycle_status,
            start_message_id=start_msg_id,
            end_message_id=end_msg_id,
            start_index=start_idx_val,
            end_index=end_idx_val,
            message_count=msg_count_val,
            start_at=start_at,
            end_at=end_at,
            start_author_id=str(s.get("start", {}).get("authorID") or s.get("start", {}).get("author", {}).get("id", "")),
            end_author_id=str(s.get("end", {}).get("authorID") or s.get("end", {}).get("author", {}).get("id", "")),
            start_excerpt=start_excerpt,
            end_excerpt=end_excerpt,
        )
        session.add(scene_model)
        created_scenes.append((scene_model, s))

    session.flush()

    for idx, (scene_model, s) in enumerate(created_scenes):
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
                            message_count=int(p_info.get("message_count") or 1),
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

        next_scene_model = created_scenes[idx + 1][0] if idx + 1 < len(created_scenes) else None
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

                cand_excerpt = iss.get("candidate_excerpt") or issue_excerpt_cache.get(cand_id_str)
                if cand_excerpt:
                    cand_excerpt = (
                        str(cand_excerpt)
                        if len(str(cand_excerpt)) <= EXCERPT_MAX_LEN
                        else str(cand_excerpt)[:(EXCERPT_MAX_LEN - 3)] + "..."
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

    return created_scenes


def save_channel_indexed_scenes(
    backup_id: str,
    base_path: str,
    channel_pk: int,
    scenes: List[Dict[str, Any]],
    min_affected_message_id: Optional[Any] = None,
) -> None:
    """
    Channel-scoped atomic scene upsert:
    - Deletes/replaces only non-event scenes in `channel_pk` whose
      `cast(SceneModel.end_message_id, BigInteger) >= int(min_affected_message_id)`
      (or all non-event scenes in `channel_pk` when `min_affected_message_id is None`).
    - Preserves historical frozen closed scenes before `min_affected_message_id`.
    - Preserves custom_names, boundary excerpts, and resolved `SceneIssueModel` decisions.
    - Renumbers `scene_key` deterministically for `channel_pk`.
    """
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    min_sf = int(min_affected_message_id) if (min_affected_message_id is not None and str(min_affected_message_id).isdigit()) else None

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        channels = session.query(ChannelModel).filter(ChannelModel.backup_id == str(backup_id)).all()
        chan_by_pk = {ch.pk: ch for ch in channels}
        chan_model = chan_by_pk.get(int(channel_pk))
        if not chan_model:
            return

        affected_q = session.query(SceneModel).filter(
            SceneModel.backup_id == str(backup_id),
            SceneModel.channel_pk == int(channel_pk),
            SceneModel.event_pk.is_(None),
        )
        if min_sf is not None:
            affected_q = affected_q.filter(cast(SceneModel.end_message_id, BigInteger) >= min_sf)

        affected_scenes = affected_q.all()
        affected_pks = [sc.pk for sc in affected_scenes]

        custom_name_by_chan_start: Dict[Tuple[str, str], str] = {}
        custom_name_by_chan_end: Dict[Tuple[str, str], str] = {}
        start_excerpt_cache: Dict[Tuple[str, str], str] = {}
        end_excerpt_cache: Dict[Tuple[str, str], str] = {}
        chan_did = str(chan_model.discord_id)

        for sc in affected_scenes:
            if sc.custom_name:
                if sc.start_message_id:
                    custom_name_by_chan_start[(chan_did, str(sc.start_message_id))] = sc.custom_name
                if sc.end_message_id:
                    custom_name_by_chan_end[(chan_did, str(sc.end_message_id))] = sc.custom_name
            if sc.start_excerpt and sc.start_message_id:
                start_excerpt_cache[(chan_did, str(sc.start_message_id))] = sc.start_excerpt
            if sc.end_excerpt and sc.end_message_id:
                end_excerpt_cache[(chan_did, str(sc.end_message_id))] = sc.end_excerpt

        issue_excerpt_cache: Dict[str, str] = {}
        if affected_pks:
            for cand_mid, cand_exc in session.query(
                SceneIssueModel.candidate_message_id, SceneIssueModel.candidate_excerpt
            ).filter(
                SceneIssueModel.backup_id == str(backup_id),
                SceneIssueModel.scene_pk.in_(affected_pks),
                SceneIssueModel.candidate_excerpt.isnot(None),
            ).all():
                if cand_mid and cand_exc:
                    issue_excerpt_cache[str(cand_mid)] = str(cand_exc)

            session.query(SceneIssueModel).filter(
                SceneIssueModel.backup_id == str(backup_id),
                SceneIssueModel.resolved_at.is_(None),
                SceneIssueModel.scene_pk.in_(affected_pks),
            ).delete(synchronize_session=False)

            session.query(SceneIssueModel).filter(
                SceneIssueModel.backup_id == str(backup_id),
                SceneIssueModel.resolved_at.isnot(None),
                or_(
                    SceneIssueModel.scene_pk.in_(affected_pks),
                    SceneIssueModel.next_scene_pk.in_(affected_pks),
                ),
            ).update({"scene_pk": None, "next_scene_pk": None}, synchronize_session="fetch")

            session.query(SceneParticipantModel).filter(
                SceneParticipantModel.scene_pk.in_(affected_pks)
            ).delete(synchronize_session=False)

            session.query(SceneModel).filter(SceneModel.pk.in_(affected_pks)).delete(synchronize_session=False)
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

        chars = (
            session.query(CharacterModel)
            .filter(CharacterModel.backup_id == str(backup_id))
            .all()
        )
        char_id_to_pk = {c.char_id: c.pk for c in chars}

        sorted_scenes = sorted(
            scenes,
            key=lambda x: (
                snowflake_int(x.get("start", {}).get("id")),
                x.get("start", {}).get("index", 0),
            ),
        )
        if min_sf is not None:
            sorted_scenes = [
                s for s in sorted_scenes
                if snowflake_int(s.get("end", {}).get("id")) >= min_sf
            ]

        created_scenes = _insert_channel_scenes_in_session(
            session,
            backup_id,
            chan_model,
            chan_by_pk,
            char_id_to_pk,
            sorted_scenes,
            custom_name_by_chan_start=custom_name_by_chan_start,
            custom_name_by_chan_end=custom_name_by_chan_end,
            start_excerpt_cache=start_excerpt_cache,
            end_excerpt_cache=end_excerpt_cache,
            issue_excerpt_cache=issue_excerpt_cache,
            resolved_by_candidate=resolved_by_candidate,
            temp_keys=True,
        )

        # Query all surviving (frozen + newly inserted) scenes in channel_pk ordered by Snowflake
        all_chan_scenes = (
            session.query(SceneModel)
            .filter(
                SceneModel.backup_id == str(backup_id),
                SceneModel.channel_pk == int(channel_pk),
                SceneModel.event_pk.is_(None),
            )
            .order_by(cast(SceneModel.start_message_id, BigInteger).asc(), SceneModel.start_at.asc())
            .all()
        )
        _, key_prefix = _channel_key_prefix(chan_model, chan_by_pk)
        for sc in all_chan_scenes:
            sc.scene_key = f"tmp-renum-{sc.pk}"
        session.flush()
        for idx, sc in enumerate(all_chan_scenes, start=1):
            sc.scene_key = f"{key_prefix}-{idx}"
        session.flush()

        # Re-link surviving resolved issues for this channel (including across frozen/affected boundary)
        scene_by_pk = {sc.pk: (idx, sc) for idx, sc in enumerate(all_chan_scenes)}
        for sc_idx, (sc_model, s_dict) in enumerate(created_scenes):
            res_start = s_dict.get("resolved_start")
            if res_start and str(res_start) in resolved_by_candidate:
                iss = resolved_by_candidate[str(res_start)]
                pos_in_all = scene_by_pk.get(sc_model.pk, (0, None))[0]
                prev_sc = all_chan_scenes[pos_in_all - 1] if pos_in_all > 0 else None
                iss.scene_pk = prev_sc.pk if prev_sc else None
                iss.next_scene_pk = sc_model.pk

            for cand_id in s_dict.get("resolved_inside", []):
                cand_id_str = str(cand_id)
                if cand_id_str in resolved_by_candidate:
                    iss = resolved_by_candidate[cand_id_str]
                    iss.scene_pk = sc_model.pk
                    iss.next_scene_pk = None

        session.flush()


def save_indexed_scenes(
    backup_id: str,
    base_path: str,
    scenes: List[Dict[str, Any]],
    debug_files: bool = False
) -> None:
    """
    Persists indexed scenes, participants, and detected issues into SQLite.
    Preserves existing resolved issue notes (resolved_at, resolved_note) and boundary excerpts
    across re-indexing runs. Optionally exports debug JSON snapshots (_scenes.json).
    """
    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    target_kinds = {s.get("kind", SceneKind.SCENE.value) for s in scenes} or {SceneKind.SCENE.value}

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        # 1. Capture surviving issue excerpts, delete unresolved issues, capture surviving resolved issues
        target_scene_pks_subquery = session.query(SceneModel.pk).filter(
            SceneModel.backup_id == str(backup_id),
            SceneModel.kind.in_(target_kinds)
        )

        issue_excerpt_cache: Dict[str, str] = {}
        for cand_mid, cand_exc in session.query(
            SceneIssueModel.candidate_message_id, SceneIssueModel.candidate_excerpt
        ).filter(
            SceneIssueModel.backup_id == str(backup_id),
            SceneIssueModel.scene_pk.in_(target_scene_pks_subquery),
            SceneIssueModel.candidate_excerpt.isnot(None),
        ).all():
            if cand_mid and cand_exc:
                issue_excerpt_cache[str(cand_mid)] = str(cand_exc)

        session.query(SceneIssueModel).filter(
            SceneIssueModel.backup_id == str(backup_id),
            SceneIssueModel.resolved_at.is_(None),
            SceneIssueModel.scene_pk.in_(target_scene_pks_subquery),
        ).delete(synchronize_session=False)
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
            SceneIssueModel.scene_pk.in_(target_scene_pks_subquery),
        ).update({"scene_pk": None, "next_scene_pk": None}, synchronize_session="fetch")
        session.flush()

        # Capture surviving custom_name values and boundary excerpts across re-indexing runs
        existing_scene_meta = (
            session.query(
                SceneModel.channel_pk,
                SceneModel.start_message_id,
                SceneModel.end_message_id,
                SceneModel.custom_name,
                SceneModel.start_excerpt,
                SceneModel.end_excerpt,
            )
            .filter(
                SceneModel.backup_id == str(backup_id),
                SceneModel.kind.in_(target_kinds),
            )
            .all()
        )
        chan_pk_to_discord = {
            pk: did for pk, did in session.query(ChannelModel.pk, ChannelModel.discord_id).all()
        }
        custom_name_by_chan_start: Dict[Tuple[str, str], str] = {}
        custom_name_by_chan_end: Dict[Tuple[str, str], str] = {}
        start_excerpt_cache: Dict[Tuple[str, str], str] = {}
        end_excerpt_cache: Dict[Tuple[str, str], str] = {}
        for ch_pk, start_mid, end_mid, c_name, s_exc, e_exc in existing_scene_meta:
            chan_id = chan_pk_to_discord.get(ch_pk, str(ch_pk))
            if c_name:
                if start_mid:
                    custom_name_by_chan_start[(chan_id, str(start_mid))] = c_name
                if end_mid:
                    custom_name_by_chan_end[(chan_id, str(end_mid))] = c_name
            if s_exc and start_mid:
                start_excerpt_cache[(chan_id, str(start_mid))] = str(s_exc)
            if e_exc and end_mid:
                end_excerpt_cache[(chan_id, str(end_mid))] = str(e_exc)

        # 2. Delete existing scene participants for target_kinds explicitly
        session.query(SceneParticipantModel).filter(
            SceneParticipantModel.scene_pk.in_(target_scene_pks_subquery)
        ).delete(synchronize_session=False)

        # Delete existing scenes for target_kinds
        session.query(SceneModel).filter(
            SceneModel.backup_id == str(backup_id),
            SceneModel.kind.in_(target_kinds)
        ).delete(synchronize_session=False)
        session.flush()

        # 3. Cache channels and characters for fast lookups (Schema v6: direct backup_id FK)
        channels = (
            session.query(ChannelModel)
            .filter(ChannelModel.backup_id == str(backup_id))
            .all()
        )
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

        channel_scenes_map: Dict[int, List[Tuple[SceneModel, Dict[str, Any]]]] = {}

        for chan_discord_id, chan_scenes in scenes_by_channel.items():
            chan_scenes.sort(
                key=lambda x: (
                    snowflake_int(x.get("start", {}).get("id")),
                    x.get("start", {}).get("index", 0),
                )
            )
            chan_model = chan_by_discord_id.get(chan_discord_id)
            if not chan_model:
                continue

            created_scenes = _insert_channel_scenes_in_session(
                session,
                backup_id,
                chan_model,
                chan_by_pk,
                char_id_to_pk,
                chan_scenes,
                custom_name_by_chan_start=custom_name_by_chan_start,
                custom_name_by_chan_end=custom_name_by_chan_end,
                start_excerpt_cache=start_excerpt_cache,
                end_excerpt_cache=end_excerpt_cache,
                issue_excerpt_cache=issue_excerpt_cache,
                resolved_by_candidate=resolved_by_candidate,
                temp_keys=False,
            )
            channel_scenes_map[chan_model.pk] = created_scenes

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
    kind: str = "scene",
    channels: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    statuses: Optional[List[str]] = None,
    status: str = "all",
    types: Optional[List[str]] = None,
    character_ids: Optional[List[int]] = None,
    character_group_ids: Optional[List[int]] = None,
    character_logic: str = "AND",
    writer_names: Optional[List[str]] = None,
    writer_logic: str = "AND",
    include_alter_egos: bool = False,
    include_familiars: bool = False,
    include_npcs: bool = False,
    search: Optional[str] = None,
    search_folder: str = "",
    before: Optional[str] = None,
    after: Optional[str] = None,
    sort: str = "asc",
    page: Optional[int] = None,
    per_page: int = 50,
    **kwargs
) -> Any:
    """
    Queries scenes or sessions from SQLite.
    Supports both unpaginated filtering (when page is None) and paginated responses (when page is int).
    """
    from utils.path_safety import escape_like, validate_search_query_safety

    if page is not None:
        page = max(1, int(page)) if isinstance(page, int) else 1
    per_page = max(1, min(int(per_page) if isinstance(per_page, int) else 50, 200))

    require_db(base_path, backup_id=backup_id)
    init_db(engine_or_backup_id=backup_id, backup_path=base_path)

    with db_session(backup_id=backup_id, backup_path=base_path) as session:
        backup = session.query(BackupModel).filter_by(backup_id=str(backup_id)).first()
        server_id = backup.server_id if backup and backup.server_id else ""

        query = session.query(SceneModel).filter(SceneModel.backup_id == str(backup_id))

        # Filter by kind (unless 'all')
        if kind and kind != "all":
            query = query.filter(SceneModel.kind == kind)

        # Filter by channels
        if channels and isinstance(channels, (list, tuple, set)):
            chan_subquery = session.query(ChannelModel.pk).filter(ChannelModel.name.in_(channels))
            query = query.filter(SceneModel.channel_pk.in_(chan_subquery))

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
            validate_search_query_safety(search_folder)
            clean_sf = escape_like(search_folder.strip("/\\").lower())
            query = query.join(ChannelModel, SceneModel.channel_pk == ChannelModel.pk)
            query = query.filter(func.lower(ChannelModel.path).like(f"%{clean_sf}%", escape="\\"))

        # Filter by before/after dates
        if before:
            before_dt = _parse_dt(before)
            if before_dt:
                query = query.filter(SceneModel.start_at < before_dt)
        if after:
            after_dt = _parse_dt(after)
            if after_dt:
                query = query.filter(SceneModel.start_at > after_dt)

        # Filter by character_ids and character_group_ids
        from db.character_service import resolve_character_filter_clusters
        resolved_clusters = resolve_character_filter_clusters(
            session=session,
            backup_id=backup_id,
            character_ids=character_ids,
            character_group_ids=character_group_ids,
            include_alter_egos=include_alter_egos,
            include_familiars=include_familiars,
            include_npcs=include_npcs,
        )
        if resolved_clusters is not None:
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
                matched_writers = (
                    session.query(WriterModel)
                    .outerjoin(WriterAliasModel)
                    .options(selectinload(WriterModel.characters).selectinload(CharacterModel.children))
                    .filter(
                        WriterModel.backup_id == str(backup_id),
                        or_(
                            func.lower(WriterModel.display_name).in_(w_lower),
                            func.lower(WriterAliasModel.alias).in_(w_lower)
                        )
                    )
                    .all()
                )

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

        # Filter by search query (custom_name, scene_key, channel name, or category name)
        if search and isinstance(search, str) and search.strip():
            validate_search_query_safety(search)
            s_term = escape_like(search.strip().lower())
            like_pattern = f"%{s_term}%"
            matching_chan_pks = session.query(ChannelModel.pk).filter(
                func.lower(ChannelModel.name).like(like_pattern, escape="\\")
            )
            query = query.filter(
                or_(
                    func.lower(SceneModel.custom_name).like(like_pattern, escape="\\"),
                    func.lower(SceneModel.scene_key).like(like_pattern, escape="\\"),
                    SceneModel.channel_pk.in_(matching_chan_pks),
                    SceneModel.category_pk.in_(matching_chan_pks),
                )
            )

        total_items = query.count()

        if str(sort).lower() in ("desc", "start_desc", "newest"):
            query = query.order_by(SceneModel.start_at.desc(), SceneModel.pk.desc())
        else:
            query = query.order_by(SceneModel.start_at.asc(), SceneModel.pk.asc())

        query = query.options(
            joinedload(SceneModel.channel),
            joinedload(SceneModel.category),
            selectinload(SceneModel.issues),
            selectinload(SceneModel.participants)
            .joinedload(SceneParticipantModel.character)
            .selectinload(CharacterModel.names),
        )

        if page is not None:
            total_pages = math.ceil(total_items / per_page) if per_page > 0 else 1
            page = max(1, min(page, max(1, total_pages)))
            offset = (page - 1) * per_page
            scenes_raw = query.offset(offset).limit(per_page).all()
        else:
            offset = 0
            scenes_raw = query.all()

        # Batch-check IS_DELETED flags for boundary messages in skeletons.sqlite if present
        deleted_boundary_keys: set = set()
        if scenes_raw and has_skeleton_db(base_path, backup_id=backup_id):
            chan_ids_to_check = set()
            msg_ids_to_check = set()
            for s in scenes_raw:
                if s.channel and str(s.channel.discord_id).isdigit():
                    cid_int = int(s.channel.discord_id)
                    if s.start_message_id and str(s.start_message_id).isdigit():
                        chan_ids_to_check.add(cid_int)
                        msg_ids_to_check.add(int(s.start_message_id))
                    if s.end_message_id and str(s.end_message_id).isdigit():
                        chan_ids_to_check.add(cid_int)
                        msg_ids_to_check.add(int(s.end_message_id))
            if chan_ids_to_check and msg_ids_to_check:
                try:
                    with skeleton_db_session(backup_id=backup_id, backup_path=base_path) as skel_session:
                        rows = (
                            skel_session.query(
                                MessageSkeletonModel.channel_discord_id,
                                MessageSkeletonModel.message_id,
                                MessageSkeletonModel.flags,
                            )
                            .filter(
                                MessageSkeletonModel.channel_discord_id.in_(chan_ids_to_check),
                                MessageSkeletonModel.message_id.in_(msg_ids_to_check),
                            )
                            .all()
                        )
                        for ch_id, m_id, fl in rows:
                            if int(fl or 0) & SkeletonFlags.IS_DELETED:
                                deleted_boundary_keys.add((str(ch_id), str(m_id)))
                except Exception:
                    pass

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
            channel_is_deleted = bool(channel and channel.is_deleted)
            start_message_deleted = (chan_discord_id, str(s.start_message_id)) in deleted_boundary_keys
            end_message_deleted = (chan_discord_id, str(s.end_message_id)) in deleted_boundary_keys
            is_deleted = bool(channel_is_deleted or start_message_deleted or end_message_deleted)

            start_link = f"https://discord.com/channels/{server_id}/{chan_discord_id}/{s.start_message_id}" if server_id and chan_discord_id and s.start_message_id else ""
            end_link = f"https://discord.com/channels/{server_id}/{chan_discord_id}/{s.end_message_id}" if server_id and chan_discord_id and s.end_message_id else ""

            sorted_participants = sorted(
                s.participants,
                key=lambda p: (p.position if p.position is not None else 0, p.character_pk)
            )
            characters = [p.character.char_id for p in sorted_participants if p.character]
            participant_details = [
                {
                    "char_id": p.character.char_id,
                    "name": p.character.names[0].name if p.character.names else f"Character #{p.character.char_id}",
                    "position": p.position if p.position is not None else 0,
                    "message_count": int(p.message_count or 1),
                    "first_message_id": p.first_message_id,
                    "first_timestamp": p.first_at.isoformat() if p.first_at else None,
                    "first_link": f"https://discord.com/channels/{server_id}/{chan_discord_id}/{p.first_message_id}" if server_id and chan_discord_id and p.first_message_id else "",
                    "last_message_id": p.last_message_id,
                    "last_timestamp": p.last_at.isoformat() if p.last_at else None,
                    "last_link": f"https://discord.com/channels/{server_id}/{chan_discord_id}/{p.last_message_id}" if server_id and chan_discord_id and p.last_message_id else "",
                }
                for p in sorted_participants
                if p.character
            ]

            formatted_scenes.append({
                "id": s.scene_key,
                "pk": s.pk,
                "scene_pk": s.pk,
                "index": (offset + idx + 1) if page is not None else (idx + 1),
                "scene_key": s.scene_key,
                "custom_name": s.custom_name,
                "kind": s.kind,
                "channelId": chan_discord_id,
                "channel": chan_name,
                "category": cat_name,
                "type": chan_type,
                "thread_name": thread_name,
                "status": s.status,
                "message_count": int(s.message_count or 0),
                "channel_is_deleted": channel_is_deleted,
                "start_message_deleted": start_message_deleted,
                "end_message_deleted": end_message_deleted,
                "is_deleted": is_deleted,
                "characters": characters,
                "participants": participant_details,
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
            res_dict = {
                "total_items": total_items,
                "current_page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "scenes": formatted_scenes,
            }
            if kind == "session":
                res_dict["sessions"] = formatted_scenes
            return res_dict

        return formatted_scenes


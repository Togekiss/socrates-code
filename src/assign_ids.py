import sys
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

import utils.tricks as t
import utils.exceptions as exc
from models import ServerBackup, CharacterList, Step

t.set_path()
from res import constants as c


def load_status() -> Tuple[ServerBackup, bool]:
    is_update = False
    try:
        t.log("debug", f"  Loading backup info from file: {c.BACKUP_INFO}")
        backup = ServerBackup.load(scope="base")
        if backup.is_updating():
            is_update = True
            t.log("debug", "An update is running. Using the update info file\n")
            backup = ServerBackup.load(scope="update")
        if backup.is_other_step_running(Step.ASSIGN_IDS):
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        if not backup.can_assign_ids():
            raise exc.DataNotReadyError(
                "The data may be corrupted. Ensure the backup downloaded successfully and try again."
            )
        t.log("debug", f"  The current status of the backup is '{backup.status}'\n")
        backup.start_assign_ids()
        t.log("debug", "  Backup info file is ready.\n")
    except (exc.DataNotReadyError, exc.AlreadyRunningError):
        raise
    except Exception as e:
        raise exc.AssignIDError("The export status file could not be read") from e
    return backup, is_update


def get_character_id(name: str):
    char_list = CharacterList.load(c.CHARACTER_LIST)
    return char_list.find_id_by_name(name)


def get_character_name(id: int):
    char_list = CharacterList.load(c.CHARACTER_LIST)
    return char_list.get_character_name(id)


def get_all_character_ids(name: str):
    char_list = CharacterList.load(c.CHARACTER_LIST)
    return char_list.get_all_character_ids(name)


def _accumulate_seen_user(
    seen_users_acc: Dict[str, Dict[str, Any]],
    user_obj: Dict[str, Any],
    *,
    increment_count: bool = False,
    msg_dt: Optional[Any] = None,
) -> None:
    if not isinstance(user_obj, dict) or user_obj.get("isBot"):
        return
    uid = str(user_obj.get("id") or "").strip()
    if not uid.isdigit() or int(uid) < t.TUPPER_ID_MAX:
        return

    username = str(user_obj.get("name") or user_obj.get("username") or "").strip()
    global_name = str(user_obj.get("global_name") or "").strip() or None
    nickname = str(user_obj.get("nickname") or "").strip() or None

    entry = seen_users_acc.get(uid)
    if entry is None:
        seen_users_acc[uid] = {
            "discord_user_id": uid,
            "username": username or f"User #{uid}",
            "global_name": global_name,
            "nickname": nickname,
            "message_count": 1 if increment_count else 0,
            "last_seen_at": msg_dt,
        }
        return

    if username and (not entry["username"] or entry["username"].startswith("User #")):
        entry["username"] = username
    if global_name:
        entry["global_name"] = global_name
    if nickname:
        entry["nickname"] = nickname
    if increment_count:
        entry["message_count"] = int(entry.get("message_count") or 0) + 1
    if msg_dt is not None:
        cur_dt = entry.get("last_seen_at")
        if cur_dt is None or msg_dt > cur_dt:
            entry["last_seen_at"] = msg_dt


def assign_ids_in_memory(
    messages: List[Dict[str, Any]],
    char_list: CharacterList,
    seen_users_acc: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Assigns unique Tupper character IDs in memory without disk I/O:
    - Detects `author.isBot` webhooks vs human posters.
    - Reuses or registers `char_id` in `char_list` in-memory.
    - Rewrites `msg["author"]["id"]` in-memory for Tupperbox messages.
    - Accumulates non-bot human author & mention metadata into `seen_users_acc`.

    Returns:
        `(messages, new_characters)` where `new_characters` lists newly registered characters.
    """
    new_characters: List[Dict[str, Any]] = []

    for message in messages:
        if not isinstance(message, dict):
            continue
        author = message.get("author")
        if not isinstance(author, dict):
            continue

        msg_dt = t.parse_datetime(message.get("timestamp"))

        if author.get("isBot"):
            author_name = str(author.get("name") or "").strip()
            if author_name:
                char_id = char_list.find_id_by_name(author_name)
                if char_id is None:
                    new_char = char_list.add_character(author_name)
                    char_id = new_char.id
                    new_characters.append({"id": char_id, "char_id": char_id, "name": author_name})
                    t.log("info", f"\t  Found a new Tupper: {author_name} (ID: {char_id})")

                char_id_str = str(char_id)
                if author.get("id") != char_id_str:
                    author["id"] = char_id_str
        elif seen_users_acc is not None:
            _accumulate_seen_user(seen_users_acc, author, increment_count=True, msg_dt=msg_dt)

        if seen_users_acc is not None:
            for mention in message.get("mentions") or []:
                _accumulate_seen_user(seen_users_acc, mention, increment_count=False, msg_dt=None)

    return messages, new_characters


def assign_ids_in_file(file_path: str, char_list: CharacterList) -> bool:
    """Assigns Tupper character IDs in a channel JSON file, saving only if author IDs changed."""
    t.log("debug", f"\t    Analysing {file_path}...")
    data = t.load_from_json(file_path)
    msgs = data.get("messages", [])
    before_ids = [
        (m.get("author") or {}).get("id") if isinstance(m, dict) else None
        for m in msgs
    ]
    assign_ids_in_memory(msgs, char_list)
    after_ids = [
        (m.get("author") or {}).get("id") if isinstance(m, dict) else None
        for m in msgs
    ]
    if before_ids != after_ids:
        t.save_to_json(data, file_path)
        return True
    return False


def assign_ids() -> None:
    backup, is_update = load_status()
    search_folder = c.UPDATE_FOLDER if is_update else c.DATA_FOLDER

    try:
        t.log("base", f"\n###  Assigning unique IDs to Tupperbox bots in {search_folder}...  ###\n")
        start_time = time.time()
        char_list = CharacterList.load()
        t.log("info", f"\tLoaded {len(char_list.characters)} main characters\n")
        t.log("debug", f"\tIterating over backup files in {search_folder}...\n")

        for path in backup.get_all_paths():
            full_path = (Path(search_folder) / path).as_posix()
            if Path(full_path).is_file():
                assign_ids_in_file(full_path, char_list)

        char_list.save()
        backup.finish_assign_ids(success=True)
        elapsed_time = time.time() - start_time
        t.log("base", f"\n### ID assigning finished --- {elapsed_time:.2f} seconds --- ###\n")

    except Exception as e:
        if c.DEBUG_FILES and "char_list" in locals():
            try:
                char_list.save()
            except Exception:
                pass
        backup.finish_assign_ids(success=False)
        raise exc.AssignIDError("Failed to assign unique IDs to Tupperbox bots") from e


if __name__ == "__main__":
    t.set_path()
    t.log("console", "Assign IDs step starting...")
    try:
        assign_ids()
        t.log("console", "Assign IDs step completed.")
    except KeyboardInterrupt:
        t.log("error", "\nProcess interrupted by user.\n")
        try:
            backup = ServerBackup.load(scope="base")
            if backup.is_updating():
                update = ServerBackup.load(scope="update")
                update.set_failed()
                backup.finish_update(success=False)
            else:
                backup.set_failed()
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
        sys.exit(1)

import os
import sys
from pathlib import Path
import time
import re
import utils.tricks as t
import utils.exceptions as exc
from find_character_scenes import has_end_tag
from models import ServerBackup, Step
from db import curation_service
t.set_path()
from res import constants as c

################ File summary #################

"""

This module fixes messages in the backup that have bad formatting.

Main function: fix_bad_messages()

    This function traverses all JSON files in the specified folder and its subdirectories to
    find messages with bad formatting and replace them with the corresponding fixed versions.

"""

################ Functions #################

"""
load_status()

    Loads backup information from a JSON file, and checks if it's ready to work with.

    Returns:
        ServerBackup: The current status of the backup.
"""
def load_status():

    try: 
        backup = ServerBackup.load(scope="base")

        if backup.is_other_step_running(Step.FIX_MESSAGES):
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        if not backup.can_fix_messages():
            raise exc.DataNotReadyError("The data may be corrupted or incomplete. Ensure the download is verified and IDs are assigned and try again.")

        t.log("debug", f"  The current status of the backup is '{backup.status}'\n")

        # flag it as running in case another execution of the script is launched
        backup.start_fix_messages()

        t.log("debug", "  Backup info file is ready.\n")

    except (exc.DataNotReadyError, exc.AlreadyRunningError) as e:
        raise e
     
    except Exception as e:
        raise exc.FixMessagesError("The export status file could not be read") from e
    
    return backup


"""
fix_messages_in_channel(file_path, backup, overrides, flagged_items)

    This function traverses through all the messages in a channel and,
    if it finds a message that has a fixed version in the overrides dictionary,
    it will replace it with the corresponding message from the dictionary.

    It also deletes messages from non-bot users if they only have a mention.

    Args:
        file_path (str): The path to the channel JSON file.
        backup (ServerBackup): The ServerBackup instance.
        overrides (dict): Active overrides mapping message_id -> {"content": ..., "author": ...}.
        flagged_items (list): Accumulator list for flagged messages to be saved to SQLite.

    Returns:
        None
"""
def fix_messages_in_channel(file_path, backup: ServerBackup, overrides: dict, flagged_items: list):

    channel = t.load_from_json(file_path)
    is_modified = False
    messages_to_remove = []

    pattern = r"^@[\w ]+$"
    pattern2 = r"^@deleted-role$"
    pattern3 = r"^@unknown-role$"

    for message in channel.get("messages", []):
        msg_id = str(message.get("id"))

        # if ID in overrides, replace it
        if msg_id in overrides:
            override = overrides[msg_id]
            t.log("debug", f"\tFound bad message {msg_id} from {message.get('author', {}).get('name')}.")
            t.log("debug", f"\t    Replacing it with fixed message from {override.get('author', {}).get('name')}.")

            message["content"] = override.get("content", message.get("content"))
            message["author"] = override.get("author", message.get("author"))
            is_modified = True

        content = message.get("content", "")
        # if the message has only a mention, remove it
        if re.search(pattern, content) or re.search(pattern2, content) or re.search(pattern3, content):
            t.log("debug", f"\tFound message with only a mention '{content}' from {message.get('author', {}).get('name')}.")
            messages_to_remove.append(message)

        # if message is from a non-tupper user
        author_id = message.get("author", {}).get("id")
        try:
            author_id_int = int(author_id)
        except (ValueError, TypeError):
            author_id_int = 0

        if message.get("type") == "Default" and author_id_int >= 10000:
            t.log("debug", f"\tFound message from non-tupper user '{message.get('author', {}).get('name')}'.")
            kind = "non_tupper_end_tag" if has_end_tag(message) else "non_tupper"
            flagged_items.append({
                "message_id": msg_id,
                "channel_discord_id": channel.get("channel", {}).get("id"),
                "kind": kind,
                "content": message.get("content", ""),
                "author": message.get("author", {}),
            })

        # if message is a thread creation, delete it
        if message.get("type") == "ThreadCreated":
            t.log("debug", f"\tFound thread creation message {msg_id} from {message.get('author', {}).get('name')}.")
            messages_to_remove.append(message)

    if len(messages_to_remove) > 0:
        t.log("debug", f"\t      Found {len(messages_to_remove)} messages to remove.")
        # remove messages from channel
        for message in messages_to_remove:
            channel["messages"].remove(message)
        is_modified = True

    if is_modified:
        channel["messageCount"] = len(channel["messages"])
        backup.update_message_count(channel["channel"]["id"], channel["messageCount"])
        t.log("debug", f"\tSaving channel to {file_path}")
        t.save_to_json(channel, file_path)


################# Main function #################

def fix_bad_messages():

    backup = load_status()
    b_id = backup.backup_id or getattr(c, "BACKUP_ID", None)
    b_path = backup.path or getattr(c, "BACKUP_BASE", None)

    try:

        t.log("base", f"\n###  Fixing badly formatted messages in {c.SERVER_NAME}...  ###\n")

        start_time = time.time()

        overrides = curation_service.get_overrides_map(b_id, b_path)
        t.log("info", f"    Found {len(overrides)} messages to patch\n")

        flagged_items = []

        for path in backup.get_all_paths():
            file_path = (Path(c.DATA_FOLDER) / path).as_posix()
            t.log("log", f"\t    Analysing {file_path}...")
            fix_messages_in_channel(file_path, backup, overrides, flagged_items)

        # Save flagged messages to SQLite (and optionally snapshots if c.DEBUG_FILES)
        curation_service.save_flagged_messages(
            backup_id=b_id,
            base_path=b_path,
            flagged_items=flagged_items,
            debug_files=c.DEBUG_FILES,
        )

        backup.save()
        backup.finish_fix_messages(success=True)

    except Exception as e:
        backup.finish_fix_messages(success=False)
        raise exc.FixMessagesError("Failed to fix bad messages in files") from e
    
    finally:

        t.log("base", f"### Finished fixing messages --- {time.time() - start_time:.2f} seconds --- ###\n")

        # if there was an exception, raise it again
        if 'e' in locals() and e is not None:
            raise e


if __name__ == "__main__":
    
    try:
        fix_bad_messages()

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
    
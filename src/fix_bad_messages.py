import os
import time
import re
import utils.tricks as t
import utils.exceptions as exc
from find_character_scenes import has_end_tag
from models import ServerBackup
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
        t.log("debug", f'  Loading backup info from file: {c.BACKUP_INFO}')

        backup = ServerBackup.from_json(c.BACKUP_INFO)

        if backup.is_running():
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
fix_messages_in_channel(file_path)

    This function traverses through all the messages in a channel and,
    if it finds a message that has a fixed version in the fixed_messages dictionary,
    it will replace it with the corresponding message from the dictionary.

    It also deletes messages from non-bot users if they only have a mention.

    Args:
        file_path (str): The path to the channel JSON file.

    Returns:
        channel (dict): The modified channel dictionary.
"""
def fix_messages_in_channel(file_path, backup: ServerBackup):

    channel = t.load_from_json(file_path)
    fixed_messages = t.load_from_json(c.FIXED_MESSAGES)

    messages_to_remove = []

    for message in channel["messages"]:

        # if ID in fixed_messages, replace it
        if message["id"] in fixed_messages:
            
            t.log("debug", f"\tFound bad message {message['id']} from {message['author']['name']}.")
            t.log("debug", f"\t    Replacing it with fixed message from {fixed_messages[message['id']]['author']['name']}.")

            message["content"] = fixed_messages[message["id"]]["content"]
            message["author"] = fixed_messages[message["id"]]["author"]
        

        # regex that match mentions
        pattern = r"^@[\w ]+$"
        pattern2 = r"^@deleted-role$"
        pattern3 = r"^@unknown-role$"
        
        # if the message has a only a mention, remove it
        if re.search(pattern, message["content"]) or re.search(pattern2, message["content"]) or re.search(pattern3, message["content"]):

            t.log("debug", f"\tFound message with only a mention '{message['content']}' from {message['author']['name']}.")

            # remove message from messages
            messages_to_remove.append(message)


        # if message is from a non-tupper user
        if message["type"] == "Default" and int(message["author"]["id"]) >= 10000:

            t.log("debug", f"\tFound message from non-tupper user '{message['author']['name']}'.")

            if has_end_tag(message):
                bad_end_list = t.load_from_json(c.BAD_END_MESSAGES)
                bad_end_list[message["id"]] = {
                    "content": message["content"],
                    "author": message["author"],
                    "link": f"https://discord.com/channels/{channel['guild']['id']}/{channel['channel']['id']}/{message['id']}"
                }
                t.save_to_json(bad_end_list, c.BAD_END_MESSAGES)
                t.log("debug", f"\t    Saved message with an end tag to {c.BAD_END_MESSAGES}")

            else:
                # append to c.BAD_MESSAGES
                bad_message_list = t.load_from_json(c.BAD_MESSAGES)
                bad_message_list[message["id"]] = {
                    "content": message["content"],
                    "author": message["author"],
                    "link": f"https://discord.com/channels/{channel['guild']['id']}/{channel['channel']['id']}/{message['id']}"
                }
                t.save_to_json(bad_message_list, c.BAD_MESSAGES)
                t.log("debug", f"\t    Saved message to {c.BAD_MESSAGES}")
        
        # if message is a thread creation, delete it
        if message["type"] == "ThreadCreated":
            t.log("debug", f"\tFound thread creation message {message['id']} from {message['author']['name']}.")
            messages_to_remove.append(message)

    if len(messages_to_remove) > 0:
        t.log("debug", f"\t      Found {len(messages_to_remove)} messages to remove.")
        # remove messages from channel
        for message in messages_to_remove:
            channel["messages"].remove(message)

    channel["messageCount"] = len(channel["messages"])
    backup.update_message_count(channel["channel"]["id"], channel["messageCount"])

    # save channel
    t.log("debug", f"\tSaving channel to {file_path}")

    t.save_to_json(channel, file_path)

################# Main function #################

def fix_bad_messages():

    backup = load_status()

    try:

        t.log("base", f"\n###  Fixing badly formatted messages in {c.SERVER_NAME}...  ###\n")

        start_time = time.time()

        try:
            fixed_messages = t.load_from_json(c.FIXED_MESSAGES)
            t.log("debug", f"    Loaded {len(fixed_messages)} fixed messages from {c.FIXED_MESSAGES}\n")
        except FileNotFoundError:
            t.log("debug", f"    No fixed messages file found. Creating a new one at {c.FIXED_MESSAGES}\n")
            fixed_messages = {}
            t.save_to_json(fixed_messages, c.FIXED_MESSAGES)

        t.log("info", f"    Found {len(fixed_messages)} messages to patch\n")

        # clean the bad messages files
        t.save_to_json({}, c.BAD_MESSAGES)
        t.save_to_json({}, c.BAD_END_MESSAGES)

        for path in backup.get_all_paths():
            file_path = os.path.join(c.DATA_FOLDER, path)
            t.log("log", f"\t    Analysing {file_path}...")
            fix_messages_in_channel(file_path, backup)

        backup.finish_fix_messages()

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
    
    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
    
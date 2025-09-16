import os
import time
import re
import tricks as t
import exceptions as exc
from find_scenes import has_end_tag
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
check_base_status()

    Checks the status file, and raises exceptions if the backup is not ready to be sorted.

"""
def check_base_status():

    try: 
        t.log("debug", "\nChecking the status of the backup...")

        backup_info = t.load_from_json(c.BACKUP_INFO)

        t.log("debug", "  Loaded the status file\n")

        t.log("debug", f"  The current status of the backup is '{backup_info["status"]}'\n")

        main_status = backup_info["status"] + ""

        if backup_info["status"] == "running":
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        if backup_info["status"] == "failed":
            raise exc.DataNotReadyError("The data may be corrupted. Ensure the backup downloaded successfully and try again.")
        
        if backup_info["steps"]["idAssignStatus"] != "success":
            raise exc.DataNotReadyError("The backup is not fully updated. Ensure the ID assignment process ran and try again.")

        if backup_info["steps"]["mergeStatus"] != "success":
            raise exc.DataNotReadyError("The backup is not fully updated. Ensure the merge process ran and try again.")

        backup_info["status"] = "running"
        backup_info["steps"]["messageFixStatus"] = "running"

        t.save_to_json(backup_info, c.BACKUP_INFO)

        return main_status

    except (exc.AlreadyRunningError, exc.DataNotReadyError) as e:
        raise e
    
    except Exception as e:
        raise exc.FixMessagesError("The export status file could not be read") from e
    

"""
fix_messages_in_channel(file_path, fixed_messages)

    This function traverses through all the messages in a channel and,
    if it finds a message that has a fixed version in the fixed_messages dictionary,
    it will replace it with the corresponding message from the dictionary.

    It also deletes messages from non-bot users if they only have a mention.

    Args:
        file_path (str): The path to the channel JSON file.

    Returns:
        channel (dict): The modified channel dictionary.
"""
def fix_messages_in_channel(file_path):

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

    # save channel
    t.log("debug", f"\tSaving channel to {file_path}")

    t.save_to_json(channel, file_path)

################# Main function #################

def fix_bad_messages():

    try:

        t.log("base", f"\n###  Fixing badly formatted messages in {c.SERVER_NAME}...  ###\n")

        start_time = time.time()

        check_base_status()

        fixed_messages = t.load_from_json(c.FIXED_MESSAGES)

        t.log("info", f"    Found {len(fixed_messages)} messages to patch\n")

        # clean the bad messages files
        t.save_to_json({}, c.BAD_MESSAGES)
        t.save_to_json({}, c.BAD_END_MESSAGES)

        # Iterate over all channel JSON files in the folder and its subfolders
        for root, dirs, files in os.walk(c.SEARCH_FOLDER):
            for filename in files:
                if filename.endswith(".json") and not filename.endswith("scenes.json"):

                    file_path = os.path.join(root, filename)

                    t.log("log", f"\t    Analysing {file_path}...")

                    # find and fix bad messages
                    fix_messages_in_channel(file_path)

        step_status = "success"
        main_status = "success"

    except Exception as e:
        main_status = "failed"
        step_status = "failed"
        raise exc.FixMessagesError("Failed to fix bad messages in files") from e
    
    finally:
        try:
            t.log("base", f"### Finished fixing messages --- {time.time() - start_time:.2f} seconds --- ###\n")
            backup_info = t.load_from_json(c.BACKUP_INFO)
            backup_info["status"] = main_status
            backup_info["steps"]["messageFixStatus"] = step_status
            t.save_to_json(backup_info, c.BACKUP_INFO)

        except Exception as e:
            t.log("error", f"\tFailed to save the status file: {e}\n")


if __name__ == "__main__":
    
    try:
        fix_bad_messages()
    
    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
    
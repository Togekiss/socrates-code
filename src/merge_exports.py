import os
import shutil
import time
import utils.tricks as t
import utils.exceptions as exc
from models import ServerBackup
t.set_path()
from res import constants as c

################# File summary #################

"""

This module merges the channel history files from the "Update" folder to the "Old" folder.

Main function: merge_exports()

    The "Update" folder should contain the new channel history files exported by DCE.
    The "Old" folder should contain the old channel history files to be updated.

    This function will walk through all files in the "Update" folder and its subfolders.
    For each file, it will check if an equivalent file exists in the "Old" folder.
    If it does, it will merge the two files by appending new messages to the old file.
    If not, it will create the necessary subfolders in "Old" to maintain the same directory tree
    and copy the file from "Update" to "Old".

"""

################## Functions #################


"""
load_status()

    Loads backup information from a JSON file, and checks if it's ready to work with.

    Returns:
        ServerBackup: The current status of the backup.
        bool: Whether the backup is in update mode or not.
"""
def load_status():

    is_update = False

    try: 
        t.log("debug", f'  Loading backup info from file: {c.BACKUP_INFO}')

        backup = ServerBackup.from_json(c.BACKUP_INFO)
        
        # If it's in update mode, we'll use the update info file
        if backup.is_updating():

            is_update = True

            t.log("debug", "An update is running. Using the update info file\n")

            backup = ServerBackup.from_json(c.BACKUP_INFO_UPDATE)

        if backup.is_running():
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        if not backup.can_merge():
            raise exc.DataNotReadyError("The data may be corrupted. Ensure the backup downloaded successfully and try again.")


        t.log("debug", f"  The current status of the backup is '{backup.status}'\n")

        # flag it as running in case another execution of the script is launched
        backup.start_merge()

        t.log("debug", "  Backup info file is ready.\n")

    except (exc.DataNotReadyError, exc.AlreadyRunningError) as e:
        raise e
     
    except Exception as e:
        raise exc.MergeError("The export status file could not be read") from e
    
    return backup, is_update
     

"""
find_message_index(messages, id, base=0)

    Find the index of a message with a specified ID in a list of messages.

    Args:
        messages (list): A list of messages in JSON format, each containing an 'id' key.
        id (str): The ID of the message to find.
        base (int, optional): The starting index to begin the search at. Defaults to 0.

    Returns:
        int or None: The index of the message with the specified ID, or None if not found.
"""
def find_message_index(messages, id, base=0):
    
    index = None
    for i, message in enumerate(messages[base:], start=base):
        if message['id'] == id:
            index = i
            break

    return index


"""
merge_channel(old, update)

    This function merges the channel data from an update file into an existing old file.

    It loads both files in JSON format, and iterates through the channel history update's messages.
    If the message is found in the old channel history, it is updated (to account for edited content).
    If the message is not found, it and the rest of the update are appended to the old channel history.
    
    The merged data is then saved back to the `old` file, maintaining a complete and up-to-date channel history.

    Args:
        old (str): The file path to the existing channel history file.
        update (str): The file path to the new channel update file.

    Returns:
        None, but saves the merged data to the `old` file.
"""
def merge_channel(old, update, main_backup):
    
    # Load data from old file
    old_data = t.load_from_json(old)

    # Load data from update file
    update_data = t.load_from_json(update)

    # Extract messages from both JSONs
    full_messages = old_data["messages"]
    update_messages = update_data["messages"]

    # set counters
    full_index = 0
    update_index = 0

    # For each new message in the update
    for i, new_message in enumerate(update_messages):
        
        # keep track of the message being evaluated
        update_index = i

        # Extract the ID to look for
        id = update_messages[i]["id"]

        # Look for it in the old list - only counting from last message evaluated
        index = find_message_index(full_messages, id, full_index)
        
        # Check if the message was found
        
        # If not, it means it's new. exit
        if index is None:
            break

        # If found, update the message and continue
        else:
            full_index = index
            full_messages[full_index] = new_message

    # Append all the new messages
    full_messages.extend(update_messages[update_index:])
          
    # Update metadata and messages to the whole JSON 
    old_data['exportedAt'] = update_data['exportedAt']
    old_data['messageCount'] = len(full_messages)
    old_data['messages'] = full_messages

    # save merged data to json
    t.save_to_json(old_data, old)

    main_backup.update_message_count(old_data['channel']['id'], len(full_messages))


"""
merge_file(path, update_folder, old_folder, main_backup)

    This function attempts to bring a file from the update folder into the old folder.
    If the file doesn't exist in the old folder, it creates the necessary subfolders and copies it.
    If they file exists, it will call merge_channel() to merge the two files.

    Args:
        path (str): The path to the file in the update folder.
        update_folder (str): The path to the update folder.
        old_folder (str): The path to the old folder.
        main_backup (ServerBackup): The main backup object.

"""
def merge_file(path, update_folder, old_folder, main_backup):

    update_file_path = os.path.join(update_folder, path)
    old_file_path = os.path.join(old_folder, path)

    # Check if an equivalent file exists in the "Old" folder
    
    # If it does, merge the two files
    if os.path.exists(old_file_path) and os.path.exists(update_file_path):
        t.log("debug", f"\tMerging {update_file_path} into {old_file_path}")
        if not c.DRY_RUN:
            merge_channel(old_file_path, update_file_path, main_backup)
        else:
            t.log("info", f"DRY RUN: Would merge {update_file_path} into {old_file_path}")

    elif os.path.exists(update_file_path) and not os.path.exists(old_file_path):
        # If not, create the necessary subfolders in "Old" to maintain the same directory tree
        if not os.path.dirname(old_file_path):
            if not c.DRY_RUN:
                os.makedirs(os.path.dirname(old_file_path), exist_ok=True)
            else:
                t.log("info", f"DRY RUN: Would create {os.path.dirname(old_file_path)}")

        # Copy the file from "Update" to "Old"
        if not c.DRY_RUN:
            shutil.copy2(update_file_path, old_file_path)
        else:
            t.log("info", f"DRY RUN: Would copy {update_file_path} to {old_file_path}")
        t.log("info", f"\tFound new file: Moving {update_file_path} to {old_file_path}")
    
    else:
        t.log("debug", f"\t{old_file_path} doesn't have an update. Skipping...")


################# Main function ################

def merge_exports():

    backup, is_update = load_status()

    if not is_update:
        t.log("base", "\n### There is nothing to merge. Exiting merge step. ###\n")
        backup.finish_merge()
        return
    
    try:

        t.log("base", f"\n### Merging files from the update folder into the main folder...  ###\n")

        start_time = time.time()

        main_backup = ServerBackup.from_json(c.BACKUP_INFO)

        for path in backup.get_all_paths():
            merge_file(path, c.UPDATE_FOLDER, c.MERGE_FOLDER, main_backup)

        backup.finish_merge()

    except Exception as e:
        backup.finish_merge(success=False)
        raise exc.MergeError("Failed to merge files") from e
    
    finally:
        try:
            t.log("base", f"### Merging finished --- {time.time() - start_time:.2f} seconds --- ###\n")
            
            if is_update and backup.is_failed():
                main_backup = ServerBackup.from_json(c.BACKUP_INFO)
                main_backup.finish_update(success=False)

        except Exception as e:
            t.log("error", f"\tFailed to save the status file: {e}\n")
        
        # if there was an exception, raise it again
        if 'e' in locals() and e is not None:
            raise e

if __name__ == "__main__":

    try:
        merge_exports()

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
    

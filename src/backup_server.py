from datetime import datetime, timedelta
import time
import os
import shutil
import threading
import utils.tricks as t
import utils.exceptions as exc
from models import ServerBackup
t.set_path()
from res import constants as c
from get_server_info import get_server_info
from download_channels import download_channels
from update_paths import update_paths
from merge_exports import merge_exports
from assign_ids import assign_ids
from fix_bad_messages import fix_bad_messages
from verify_download import verify_download
from index_scenes import index_scenes


################# File summary #################

"""

This module orchestrates all the steps of downloading a backup of the server
and tidying up the resulting files.

Main function: backup_server()

    This script downloads all channels from the server specified in the constants.py file, either the full history or from a specified date.
    If there is no previous backup, downloads all channels from the server.
    If there is a previous backup, downloads all channels from the day before the last backup and merges them to the main files.
    Then, assigns a proper ID to each character.
    
"""


################# Functions #################

"""
check_base_status()

    Checks the status file, and raises exceptions if the backup is not ready to start.

"""
def check_base_status():

    try: 
        t.log("debug", "\nChecking the status of the backup...")

        if not os.path.exists(c.BACKUP_INFO):
            raise FileNotFoundError

        backup = ServerBackup.from_json(c.BACKUP_INFO)

        t.log("debug", "  Loaded the status file\n")

        if backup.is_running():
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        t.log("debug", f"  The current status of the backup is '{backup.status}'\n")

    except exc.AlreadyRunningError as e:
        raise e
     
    except FileNotFoundError:
        t.log("debug", '  No backup info file was found. Will start one from scratch.\n')

    except Exception as e:
        raise exc.BackupError("The backup process could not start") from e


"""
clean()

    Function to clean up old temporary files and logs.

"""
def clean():

    t.log("debug", "\n# Cleaning up old temporary files...  #\n")

    # if log file is bigger than 10 MB, delete it
    if os.path.exists(c.LOG_FILE) and os.path.getsize(c.LOG_FILE) > 10 * 1024 * 1024:
        os.remove(c.LOG_FILE)
        t.log("debug", f"\tDeleted log file: {c.LOG_FILE}")

    # if there's an "Update" folder, delete it
    if os.path.exists("Update"):
        t.log("debug", "\tDeleted 'Update' folder")
        os.system(f"rm -rf Update")


"""
set_day_before(timestamp_str)

    Adjusts the given timestamp by subtracting one day to ensure downloading the whole update.

    Args:
        timestamp_str (str): The original timestamp in ISO format.

    Returns:
        str: The adjusted timestamp in ISO format, representing the day before the original.
"""
def set_day_before(timestamp_str):

    # Parse the timestamp into a datetime object
    timestamp = datetime.fromisoformat(timestamp_str)

    # Subtract one day (24 hours) from the timestamp
    new_timestamp = timestamp - timedelta(days=1)

    # Format the new timestamp back into the original format
    new_timestamp_str = new_timestamp.isoformat()

    return new_timestamp_str

"""
set_export_date()

    Returns the date of the last export in ISO format as a string or None if there is no previous backup.

    The date is retrieved from backup_info.json.

    Note: Backups are dated as a whole. This assumes the whole list of channels was downloaded at that time.
          If the export was interrupted, this does NOT keep track of which channels were downloaded and which weren't.
"""
def set_export_date():
    
    date = None

    backup = ServerBackup.from_json(c.BACKUP_INFO)

    # if the previous export failed, use the last good export date
    # TODO

    # Check if there is a previous backup
    if backup.exported_at != "":

        t.log("info", f'\tThe last backup was downloaded at {backup.exported_at}')
        date = set_day_before(backup.exported_at)
        t.log("info", f'\tWill download updates after {date}\n')

    else:
        t.log("info", '\tNo previous backup was found. Will download the full history\n')
  
    return date

def finish_update():

    update_info = ServerBackup.from_json(c.BACKUP_INFO_UPDATE)
    main_info = ServerBackup.from_json(c.BACKUP_INFO)

    if main_info.is_updating() and update_info.can_finish_update():

        update_info.finish_update()
        main_info.updated_at = update_info.updated_at
        main_info.exported_from = update_info.exported_from
        main_info.exported_at = update_info.exported_at
        main_info.finish_update()

        t.log("info", f"\nFinished the update! The backup is now up to date as of {main_info.updated_at}\n")
    
        try:
            # Rename the c.DATA_FOLDER to "Old Data" and the c.MERGE_FOLDER to c.DATA_FOLDER
            os.rename(c.DATA_FOLDER, f"{c.DATA_FOLDER}_Old")
            os.rename(c.MERGE_FOLDER, c.DATA_FOLDER)

            t.log("debug", f"\tRenamed '{c.DATA_FOLDER}' to '{c.DATA_FOLDER}_Old' and '{c.MERGE_FOLDER}' to '{c.DATA_FOLDER}'")

        except Exception as e:
            raise exc.BackupError(f"The data or merge folder could not be renamed: {e}") from e

        if not c.DEBUG_FILES:
            try:
                # Delete the old data and update folders
                shutil.rmtree(f"{c.DATA_FOLDER}_Old")
                t.log("debug", f"\tDeleted old data folder: '{c.DATA_FOLDER}_Old'")
                shutil.rmtree(c.UPDATE_FOLDER)
                t.log("debug", f"\tDeleted update folder: '{c.UPDATE_FOLDER}'")

                # Delete the backup_info_update.json file
                os.remove(c.BACKUP_INFO_UPDATE)
                t.log("debug", f"\tDeleted backup_info_update.json")

            except Exception as e:
                raise exc.BackupError(f"The old folders could not be deleted: {e}") from e


################# Main function ################

def backup_server():

    t.log("base", f"\n# Exporting a backup of the server {c.SERVER_NAME}...  #\n")

    check_base_status()

    try:

        clean()

        start_time = time.time()

        # refresh the list of channels to download to find new channels
        is_update = get_server_info()

        # start thread to create the merge folder while we download channels
        merge_thread = None
        if is_update:
            merge_thread = threading.Thread(target=t.create_merge_folder)
            merge_thread.start()

        # run through channel list to download it all    
        download_channels()
        
        # add position numbers to the exported filenames
        verify_download()

        # assign a proper ID to each character
        assign_ids()

        # wait for thread to end
        if merge_thread is not None:
            merge_thread.join()

        # update the paths of the backup
        update_paths()

        # merge the updates to the main files
        merge_exports()

        # mark the update as finished 
        if is_update:
            finish_update()

        # use the fixed_messages list to fix any messages 
        fix_bad_messages()

        # find and index all scenes in the backup
        index_scenes()
        

    except Exception as e:
        raise e
    
    finally:
        t.log("base", f"\n# Export finished --- {time.time() - start_time:.2f} seconds --- #\n")


if __name__ == "__main__":
    
    try:
        backup_server()

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
    
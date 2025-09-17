from datetime import datetime, timedelta
import time
import os
import tricks as t
import exceptions as exc
t.set_path()
from res import constants as c
from get_channel_list import get_channel_list
from download_channels import download_channels
from merge_exports import merge_exports
from assign_ids import assign_ids
from fix_bad_messages import fix_bad_messages
from sort_exported_files import sort_exported_files
from update_info import update_info


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

        backup_info = t.load_from_json(c.BACKUP_INFO)

        t.log("debug", "  Loaded the status file\n")

        if backup_info["status"] == "running":
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        t.log("debug", f"  The current status of the backup is '{backup_info["status"]}'\n")

    except exc.AlreadyRunningError as e:
        raise e
     
    except OSError:
        t.log("debug", '  No export status file was not found. Creating a new one....\n')
        backup_info = {
            "status": "pending",
            "steps": {
                "updateStatus": "running",
                "updateCleanStatus": "pending",
                "downloadStatus": "pending",
                "sortingReadStatus": "pending",
                "sortingCleanStatus": "pending",
                "sortingWriteStatus": "pending",
                "mergeStatus": "pending",
                "idAssignStatus": "pending",
                "messageFixStatus": "pending"
            }
        }

        t.save_to_json(backup_info, c.BACKUP_INFO)

    except Exception:
        t.log("debug", '  The export status file could not be read. Will create it with the list of channels.\n')


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

    backup_info = t.load_from_json(c.BACKUP_INFO)

    # if the previous export failed, use the last good export date
    if backup_info["steps"]["downloadStatus"] == "failed":
        backup_info["dates"]["exportedAt"] = backup_info["dates"]["lastGoodExport"]

    # Check if there is a previous backup
    if backup_info["dates"]["exportedAt"] is not None:

        t.log("info", f'\tThe last backup was downloaded at {backup_info["dates"]["exportedAt"]}')
        date = set_day_before(backup_info["dates"]["exportedAt"])
        t.log("info", f'\tWill download updates after {date}\n')

    else:
        t.log("info", '\tNo previous backup was found. Will download the full history\n')

    t.save_to_json(backup_info, c.BACKUP_INFO)
    
    return date

def skip_merge():
    t.log("info", "\tNo previous backup was found. Skipping the merge step.\n")

    backup_info = t.load_from_json(c.BACKUP_INFO)
    backup_info["steps"]["mergeStatus"] = "success"
    t.save_to_json(backup_info, c.BACKUP_INFO)


################# Main function ################

def backup_server():

    t.log("base", f"\n# Exporting a backup of the server {c.SERVER_NAME}...  #\n")

    check_base_status()

    try:

        clean()

        start_time = time.time()

        # refresh the list of channels to download to find new channels
        get_channel_list()

        # calculate the date to export from, either the day before the last export or "None"
        date = set_export_date()
 
        # run through channel list to download it all    
        download_channels(date)
        
        # add position numbers to the exported filenames
        sort_exported_files(c.SERVER_NAME if date is None else "Update")

        # assign a proper ID to each character
        t.log("info", "\n\tGenerating IDs for character bots...\n") 
        assign_ids(c.SERVER_NAME if date is None else "Update")

        # merge the updates to the main files
        if date is not None:
            t.log("info", "\n\tMerging the update to the main backup...\n") 
            merge_exports()
        else:
            skip_merge()

        t.log("info", "\n\tFixing bad messages...\n") 
        fix_bad_messages()

        t.log("info", "\n\nUpdating information of the backup...\n")
        update_info()


    except Exception as e:
        raise e
    
    finally:
        t.log("base", f"\n# Export finished --- {time.time() - start_time:.2f} seconds --- #\n")


if __name__ == "__main__":
    
    try:
        backup_server()

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
    
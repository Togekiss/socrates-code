from datetime import datetime, timedelta
import time
import os
import tricks as t
import exceptions as exc
t.set_path()
from res import constants as c
from res import tokens
from get_channel_list import get_channel_list 
from merge_exports import merge_exports
from assign_ids import assign_ids
from fix_bad_messages import fix_bad_messages
from sort_exported_files import sort_exported_files
from update_info import update_info


################# File summary #################

"""

This module downloads a backup of all channels from the server.

Main function: export_channels()

    This script downloads all channels from the server specified in the constants.py file, either the full history or from a specified date.
    If there is no previous backup, downloads all channels from the server.
    If there is a previous backup, downloads all channels from the day before the last backup and merges them to the main files.
    Then, assigns a proper ID to each character.
    
"""


################# Functions #################

def check_busy():

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
        t.log("debug", '  No export status file was not found. Will create it with the list of channels.\n')
    
    except Exception:
        t.log("debug", '  The export status file could not be read. Will create it with the list of channels.\n')

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
get_export_date()

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

    # flag it as running in case another execution of the script is launched
    backup_info["status"] = "running"
    t.save_to_json(backup_info, c.BACKUP_INFO)
    
    return date



"""
export_category(item, date, type)

    Downloads set of channels or threads.

    For each channel, DCE is called to download the messages and store them in JSON format, either the full history or from a specified date.
    Downloads are run in parallel in groups of 3 or 5 to improve performance.

    Args:
        item (dict): The category data in JSON format.
        date (str, optional): The timestamp of the last export in ISO format. If not provided, downloads the full history.
        type (str, optional): The type of channels to download, should be "channels" or "threads". Defaults to "channels".

    Returns:
        None, but saves the downloaded messages to JSON files.
"""
def export_category(item, date, type="channels"):

    try:
        category = item["category"].replace(":", "_")
        folder = c.SERVER_NAME if date is None else "Update"
        date = "" if date is None else "--after " + date

        path = f"{folder}/{item["position"]}# {category}/%p# %C.json" if type == "channels" else f"{folder}/{item["position"]}# {category}/Threads/%p# %C.json"
        group_size = 3 if category in c.DM_CATEGORIES else 5

        channels = item[type]
        for i in range(0, len(channels), group_size):

            group = channels[i:i + group_size]

            channel_ids = ""
            for channel in group:
                channel_ids = channel_ids + " " + channel["id"]

            cli_command = f'dotnet DCE/DiscordChatExporter.Cli.dll export --parallel {group_size} -c {channel_ids} -t {tokens.DISCORD_BOT} -f Json -o "{path}" --locale "en-GB" {date} --fuck-russia'
            t.run_command(cli_command, group_size)
            t.log("info", f"\t\tExported {i+group_size} {type} out of {len(channels)}")
    
    except Exception as e:
        raise exc.DownloadExportError(f"An error occurred while downloading '{category}' {type}") from e

"""
download_exports(date=None)

    Opens the channel list in the file backup_info.json, and downloads the channels of each category.

    Args:
        date (str, optional): The timestamp of the last export in ISO format. If not provided, downloads the full history.

    Returns:
        None, but saves the downloaded messages to JSON files.
"""
def download_exports(date=None):

    try:
        t.log("base", "\tExporting channels... This may take several minutes\n") 

        # saving the current timestamp before starting, since it can take a long time
        now = datetime.now().astimezone().isoformat(sep='T', timespec='microseconds')

        backup_info = t.load_from_json(c.BACKUP_INFO)

        # flag it as running in case another execution of the script is launched
        backup_info["steps"]["downloadStatus"] = "running"
        t.save_to_json(backup_info, c.BACKUP_INFO)
        
        channel_count = 0

        # for each category, get channel and thread list
        for item in backup_info["categories"]:

            channels_in_category = len(item["channels"])
            threads_in_category = len(item["threads"])
            total_channels = channels_in_category + threads_in_category

            t.log("info", f"\n\tExporting {total_channels} channels and threads from '{item['category']}'...")

            export_category(item, date, "channels")
            channel_count += channels_in_category

            if len(item["threads"]) > 0:
                export_category(item, date, "threads")
                channel_count += threads_in_category

            t.log("info", f"\n\tExported {channel_count} channels out of {backup_info['numberOfChannels']}\n")

        backup_info["steps"]["downloadStatus"] = "success"
        backup_info["status"] = "pending"
        backup_info["dates"]["lastGoodExport"] = now

    # this covers both ExportError and built-in exceptions like OSError and JSON-related ones
    except Exception as e:
        backup_info["steps"]["downloadStatus"] = "failed"
        backup_info["status"] = "failed"
        raise exc.ExportError(f"An error occurred while exporting the backup") from e
    
    finally:
        try:
            backup_info["dates"]["exportedAt"] = now
            t.save_to_json(backup_info, c.BACKUP_INFO)
        except Exception as e:
            t.log("error", f"\tFailed to save the backup status: {e}\n")



################# Main function ################

def export_channels():

    t.log("base", f"\n# Exporting a backup of the server {c.SERVER_NAME}...  #\n")

    check_busy()

    try:

        clean()

        start_time = time.time()

        # refresh the list of channels to download to find new channels
        get_channel_list()

        # calculate the date to export from, either the day before the last export or "None"
        date = set_export_date()
 
        # run through channel list to download it all    
        download_exports(date)
        
        # add position numbers to the exported filenames
        sort_exported_files(c.SERVER_NAME if date is None else "Update")

        # assign a proper ID to each character
        t.log("info", "\n\tGenerating IDs for character bots...\n") 
        assign_ids(c.SERVER_NAME if date is None else "Update")

        # merge the updates to the main files
        if date is not None:
            t.log("info", "\n\tMerging the update to the main backup...\n") 
            merge_exports()

        t.log("info", "\n\tFixing bad messages...\n") 
        fix_bad_messages()

        t.log("info", "\n\Updating information of the backup...\n")
        update_info()


    except Exception as e:
        raise e
    
    finally:
        t.log("base", f"\n# Export finished --- {time.time() - start_time:.2f} seconds --- #\n")


if __name__ == "__main__":
    
    try:
        export_channels()

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
    
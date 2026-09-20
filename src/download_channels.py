from datetime import datetime, timedelta
import time
import utils.tricks as t
import utils.exceptions as exc
from models import ServerBackup
t.set_path()
from res import constants as c



################# File summary #################

"""

This module downloads a backup of all channels from the server.

Main function: download_channels(date=None)

    Opens the channel list in the file backup_info.json, and downloads the channels of each category.

    Args:
        date (str, optional): The timestamp of the last export in ISO format. If not provided, downloads the full history.

    Returns:
        None, but saves the downloaded messages to JSON files.
    
"""


################# Functions #################


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
load_status()

    Loads backup information from a JSON file, and checks if it's ready to be downloaded.
    If the backup is in update mode, it will calculate the date to export from.

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
            date = backup.exported_at

            t.log("debug", "An update is running. Using the update info file\n")

            backup = ServerBackup.from_json(c.BACKUP_INFO_UPDATE)

        if backup.is_running():
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        if not backup.can_download():
            raise exc.DataNotReadyError("The channel list is not up to date. Ensure the previous step ran and try again.")


        t.log("debug", f"  The current status of the backup is '{backup.status}'\n")

        backup.exported_from = set_day_before(date) if is_update else ""

        # flag it as running in case another execution of the script is launched
        backup.start_download()

        t.log("debug", "  Backup info file is ready.\n")

    except (exc.DataNotReadyError, exc.AlreadyRunningError) as e:
        raise e
     
    except Exception as e:
        raise exc.ExportError("The export status file could not be read") from e
    
    return backup, is_update


"""
download_full_category(cat_name, cat_id, date)

    Downloads an entire category in one go.

    DCE is called to download the messages and store them in JSON format, either the full history or from a specified date.
    Downloads are run in parallel in groups of 3 or 5 to improve performance.

    Args:
        cat_name (str): The name of the category to download.
        cat_id (str): The ID of the category to download.
        date (str, optional): The timestamp of the last export in ISO format. If not provided, downloads the full history.

"""
def download_full_category(cat_name, cat_id, date):

    try:
        folder = c.DATA_FOLDER if date is None else c.UPDATE_FOLDER
        date = "" if date is None else "--after " + date
        group_size = 3 if cat_name in c.DM_CATEGORIES else 5

        output_paths = f"-o \"{folder}/%P# %T/%p# %C.json\" --threads-output \"{folder}/%N# %M/Threads/%P-%p# %C.json\""
        
        cli_command = f'dotnet DCE/DiscordChatExporter.Cli.dll export --parallel {group_size} -c {cat_id} -f Json {output_paths} --locale "en-GB" {date} --fuck-russia --include-threads all --relative-positions'
        t.run_command(cli_command, group_size)
               
    
    except Exception as e:
        raise exc.DownloadExportError(f"An error occurred while downloading '{cat_name}' {type}") from e

################# Main function ################


def download_channels():

    backup, is_update = load_status()

    try:
        t.log("base", "\tExporting channels... This may take several minutes\n") 
        
        
        # saving the current timestamp before starting, since it can take a long time
        backup.exported_at = datetime.now().astimezone().isoformat(sep='T', timespec='microseconds')
        start_time = time.time()
        
        date = backup.exported_from if is_update else None

        # for each category, get channel and thread list
        for cat in backup.categories:

            t.log("info", f"\n\tExporting {cat.number_of_channels} channels and {cat.number_of_threads} threads from '{cat.name}'...")

            download_full_category(cat.name, cat.id, date)

            t.log("info", f"\n\tFinished exporting channels and threads from '{cat.name}'\n")
        
        backup.finish_download()

    # this covers both ExportError and built-in exceptions like OSError and JSON-related ones
    except Exception as e:
        backup.finish_download(success=False)
        raise exc.ExportError(f"An error occurred while exporting the backup") from e
    
    finally:
        try:
            t.log("base", f"### Downloading finished --- {time.time() - start_time:.2f} seconds --- ###\n")

            if is_update and backup.is_failed():
                main_backup = ServerBackup.from_json(c.BACKUP_INFO)
                main_backup.finish_update(success=False)

        except Exception as e:
            t.log("error", f"\tFailed to save the backup status: {e}\n")
        
        # if there was an exception, raise it again
        if 'e' in locals() and e is not None:
            raise e


if __name__ == "__main__":
    
    try:
        download_channels()

    except KeyboardInterrupt:
        t.log("error", "\nProcess interrupted by user.\n")
        try:
            backup = ServerBackup.from_json(c.BACKUP_INFO)
            if backup.is_updating():
                update = ServerBackup.from_json(c.BACKUP_INFO_UPDATE)
                update.set_failed()
                backup.finish_update(success=False)
            else:
                backup.set_failed()
        except Exception:
            pass

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
    
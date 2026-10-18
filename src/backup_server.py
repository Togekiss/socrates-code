from datetime import datetime, timedelta
import time
import os
import sys
from pathlib import Path
import shutil
import threading
import contextvars
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

        backup = ServerBackup.load(scope="base")

        t.log("debug", f"  Loaded the status of backup '{backup.backup_name}'\n")

        if backup.is_running():
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        t.log("debug", f"  The current status of the backup is '{backup.status}'\n")

    except exc.AlreadyRunningError as e:
        raise e
     
    except (FileNotFoundError, exc.DatabaseConnectionError, exc.ServerBackupClassError):
        t.log("debug", '  No backup info was found. Will create one from scratch.\n')

    except Exception as e:
        raise exc.BackupError("The backup process could not start") from e


"""
clean()

    Function to clean up old temporary files and logs.

"""
def clean():

    t.log("debug", "\n# Cleaning up old temporary files...  #\n")

    # if log file is bigger than 10 MB, delete it
    log_path = Path(c.LOG_FILE)
    if log_path.exists() and log_path.stat().st_size > 10 * 1024 * 1024:
        log_path.unlink()
        t.log("debug", f"\tDeleted log file: {c.LOG_FILE}")

    # if there's an "Update" folder, delete it
    if Path(c.UPDATE_FOLDER).exists():
        t.log("debug", f"\tDeleted update folder: '{c.UPDATE_FOLDER}'")
        shutil.rmtree(c.UPDATE_FOLDER, ignore_errors=True)

    old_data_path = Path(f"{c.DATA_FOLDER}_Old")
    if old_data_path.exists():
        t.log("debug", f"\tDeleted old data folder: '{old_data_path}'")
        shutil.rmtree(old_data_path, ignore_errors=True)

    if Path(c.MERGE_FOLDER).exists():
        t.log("debug", f"\tDeleted merge folder: '{c.MERGE_FOLDER}'")
        shutil.rmtree(c.MERGE_FOLDER, ignore_errors=True)


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

    try:
        backup = ServerBackup.load(scope="base")

        # Check if there is a previous backup
        if backup.exported_at != "":

            t.log("info", f'\tThe last backup was downloaded at {backup.exported_at}')
            date = set_day_before(backup.exported_at)
            t.log("info", f'\tWill download updates after {date}\n')

        else:
            t.log("info", '\tNo previous backup was found. Will download the full history\n')

    except (FileNotFoundError, exc.DatabaseConnectionError, exc.ServerBackupClassError):
        t.log("info", '\tNo previous backup was found. Will download the full history\n')
  
    return date

def finish_update():
    from db import status_service

    update_info = ServerBackup.load(scope="update")
    main_info = ServerBackup.load(scope="base")

    if main_info.is_updating() and update_info.can_finish_update():

        update_info.finish_update(success=True)
        main_info.updated_at = update_info.updated_at
        main_info.exported_from = update_info.exported_from
        main_info.exported_at = update_info.exported_at
        main_info.finish_update(success=True)

        status_service.cleanup_update_export(c.BACKUP_ID, c.BACKUP_BASE)

        t.log("info", f"\nFinished the update! The backup is now up to date as of {main_info.updated_at}\n")
    
        try:
            # Rename the c.DATA_FOLDER to "Old Data" and the c.MERGE_FOLDER to c.DATA_FOLDER
            old_data_target = f"{c.DATA_FOLDER}_Old"
            if Path(old_data_target).exists():
                shutil.rmtree(old_data_target, ignore_errors=True)
            try:
                os.rename(c.DATA_FOLDER, old_data_target)
                os.rename(c.MERGE_FOLDER, c.DATA_FOLDER)
                t.log("debug", f"\tRenamed '{c.DATA_FOLDER}' to '{old_data_target}' and '{c.MERGE_FOLDER}' to '{c.DATA_FOLDER}'")
            except (PermissionError, OSError) as rename_err:
                t.log("debug", f"\tDirectory rename failed on Windows ({rename_err}). Falling back to syncing merge folder into data folder...")
                if c.DEBUG_FILES:
                    try:
                        shutil.copytree(c.DATA_FOLDER, old_data_target, dirs_exist_ok=True)
                    except Exception:
                        pass
                # Overwrite data folder with merged content
                shutil.copytree(c.MERGE_FOLDER, c.DATA_FOLDER, dirs_exist_ok=True)
                # Remove obsolete files/dirs in data folder that are not present in merge folder
                merge_path = Path(c.MERGE_FOLDER)
                data_path = Path(c.DATA_FOLDER)
                for root, dirs, files in os.walk(data_path, topdown=False):
                    rel = Path(root).relative_to(data_path)
                    m_root = merge_path / rel
                    for f in files:
                        if not (m_root / f).exists():
                            try:
                                (Path(root) / f).unlink()
                            except OSError:
                                pass
                    for d in dirs:
                        if not (m_root / d).exists():
                            try:
                                (Path(root) / d).rmdir()
                            except OSError:
                                pass
                shutil.rmtree(c.MERGE_FOLDER, ignore_errors=True)
                t.log("debug", f"\tMerged files synced into '{c.DATA_FOLDER}' and '{c.MERGE_FOLDER}' cleaned up.")

        except Exception as e:
            raise exc.BackupError(f"The data or merge folder could not be renamed: {e}") from e

        if not c.DEBUG_FILES:
            try:
                # Delete the old data and update folders
                if Path(f"{c.DATA_FOLDER}_Old").exists():
                    shutil.rmtree(f"{c.DATA_FOLDER}_Old", ignore_errors=True)
                    t.log("debug", f"\tDeleted old data folder: '{c.DATA_FOLDER}_Old'")
                if Path(c.UPDATE_FOLDER).exists():
                    shutil.rmtree(c.UPDATE_FOLDER, ignore_errors=True)
                    t.log("debug", f"\tDeleted update folder: '{c.UPDATE_FOLDER}'")

                # Delete the backup_info_update.json file
                if Path(c.BACKUP_INFO_UPDATE).exists():
                    Path(c.BACKUP_INFO_UPDATE).unlink()
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
            ctx = contextvars.copy_context()
            merge_thread = threading.Thread(target=ctx.run, args=(t.create_merge_folder,))
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
    
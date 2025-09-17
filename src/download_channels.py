from datetime import datetime
import time
import tricks as t
import exceptions as exc
t.set_path()
from res import constants as c
from res import tokens



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
check_base_status()

    Checks the status file, and raises exceptions if the backup is not ready to be downloaded.

"""
def check_base_status():

    try: 
        t.log("debug", "\nChecking the status of the backup...")

        backup_info = t.load_from_json(c.BACKUP_INFO)

        t.log("debug", "  Loaded the status file\n")

        if backup_info["status"] == "running":
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        if backup_info["steps"]["updateCleanStatus"] != "success":
            raise exc.DataNotReadyError("The channel list is not up to date. Ensure the previous step ran and try again.")


        t.log("debug", f"  The current status of the backup is '{backup_info["status"]}'\n")

        # flag it as running in case another execution of the script is launched
        backup_info["status"] = "running"
        backup_info["steps"]["downloadStatus"] = "running"

        t.save_to_json(backup_info, c.BACKUP_INFO)

    except (exc.DataNotReadyError, exc.AlreadyRunningError) as e:
        raise e
     
    except Exception as e:
        raise exc.ExportError("The export status file could not be read") from e

"""
download_category(cat, date, type)

    Downloads set of channels or threads.

    For each channel, DCE is called to download the messages and store them in JSON format, either the full history or from a specified date.
    Downloads are run in parallel in groups of 3 or 5 to improve performance.

    Args:
        cat (dict): The category data in JSON format.
        date (str, optional): The timestamp of the last export in ISO format. If not provided, downloads the full history.
        type (str, optional): The type of channels to download, should be "channels" or "threads". Defaults to "channels".

    Returns:
        None, but saves the downloaded messages to JSON files.
"""
def download_category(cat, date, type="channels"):

    try:
        category = cat["category"].replace(":", "_")
        folder = c.SERVER_NAME if date is None else "Update"
        date = "" if date is None else "--after " + date

        path = f"{folder}/{cat["position"]}# {category}/%p# %C.json" if type == "channels" else f"{folder}/{cat["position"]}# {category}/Threads/%p# %C.json"
        group_size = 3 if category in c.DM_CATEGORIES else 5

        channels = cat[type]
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



################# Main function ################


def download_channels(date=None):

    try:
        t.log("base", "\tExporting channels... This may take several minutes\n") 

        # saving the current timestamp before starting, since it can take a long time
        now = datetime.now().astimezone().isoformat(sep='T', timespec='microseconds')
        start_time = time.time()

        check_base_status()

        backup_info = t.load_from_json(c.BACKUP_INFO)
        
        channel_count = 0

        # for each category, get channel and thread list
        for cat in backup_info["categories"]:

            channels_in_category = cat["numberOfChannels"]
            threads_in_category = cat["numberOfThreads"]
            total_channels = channels_in_category + threads_in_category

            t.log("info", f"\n\tExporting {total_channels} channels and threads from '{cat['category']}'...")

            download_category(cat, date, "channels")
            channel_count += channels_in_category

            if threads_in_category > 0:
                download_category(cat, date, "threads")
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
            t.log("base", f"### Downloading finished --- {time.time() - start_time:.2f} seconds --- ###\n")
            backup_info["dates"]["exportedAt"] = now
            t.save_to_json(backup_info, c.BACKUP_INFO)

        except Exception as e:
            t.log("error", f"\tFailed to save the backup status: {e}\n")


if __name__ == "__main__":
    
    try:
        download_channels()

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
    
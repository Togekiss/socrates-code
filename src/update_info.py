import os
import time
import re
import tricks as t
import exceptions as exc
from sort_exported_files import super_normalize, find_channel_file
t.set_path()
from res import constants as c

################ File summary #################

"""

This module updates the file with information about the status of the backup.

Main function: update_info()

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

        if backup_info["status"] == "running":
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        if backup_info["status"] == "failed":
            raise exc.DataNotReadyError("The data may be corrupted. Ensure the backup downloaded successfully and try again.")

    except (exc.AlreadyRunningError, exc.DataNotReadyError) as e:
        raise e
    
    except Exception as e:
        raise exc.UpdateInfoError("The export status file could not be read") from e
    

def check_overall_status():

    info = t.load_from_json(c.BACKUP_INFO)

    # check if all statuses in info["steps"] are "success"
    if all(info["steps"][key] == "success" for key in info["steps"]):
        info["status"] = "success"

    # if any status is "failed"
    elif any(info["steps"][key] == "failed" for key in info["steps"]):
        info["status"] = "failed"

    else:
        info["status"] = "pending"

    t.log("info", f"  The current status of the backup is '{info['status']}'\n")
    
    t.save_to_json(info, c.BACKUP_INFO)

def get_category_folder(category):

    folder_name = category["category"].replace(":", "_")
    return os.path.join(c.SERVER_NAME, f"{category['position']}# {folder_name}")

def count_scenes_in_category(category=None):

    info = t.load_from_json(c.BACKUP_INFO)

    if category is not None:
        scenes_folder = get_category_folder(category)
        scenes_file = f"{scenes_folder}/scenes.json"
    else:
        scenes_file = f"{c.SERVER_NAME}/scenes.json"
    
    try:
        scenes = t.load_from_json(scenes_file)
    except FileNotFoundError:
        t.log("debug", f"{t.YELLOW}  {scenes_file} does not exist. Skipping...")
        scenes = []
    except Exception as e:
        t.log("debug", f"{t.YELLOW}  {scenes_file} could not be read: {e}. Skipping...")
        scenes = []

    if category is not None:
        # find category in info["categories"]
        for cat in info["categories"]:
            if cat["category"] == category["category"]:
                cat["numberOfScenes"] = len(scenes)
    else:
        info["numberOfScenes"] = len(scenes)

    t.log("debug", f"\t  Found {len(scenes)} scenes in {scenes_file}")

    t.save_to_json(info, c.BACKUP_INFO)


def count_scenes_in_channel(folder, channel):

    channel_name = super_normalize(channel["channel"])

    channel_file = f"{folder}/{channel["position"]}# {channel_name}.json"
    scenes_file = f"{folder}/Scenes/{channel["position"]}# {channel_name}_scenes.json"

    # count the number of messages
    channel_data = t.load_from_json(channel_file)
    numberOfMessages = channel_data["messageCount"]

    t.log("debug", f"\t  Found {numberOfMessages} messages in {channel["channel"]}")

    # count the number of scenes
    try:
        scenes = t.load_from_json(scenes_file)
        numberOfScenes = len(scenes)
    except FileNotFoundError:
        t.log("debug", f"{t.YELLOW}  {scenes_file} does not exist. Skipping...")
        numberOfScenes = 0
    except Exception as e:
        t.log("debug", f"{t.YELLOW}  {scenes_file} could not be read: {e}. Skipping...")
        numberOfScenes = 0

    t.log("debug", f"\t  Found {numberOfScenes} scenes in {scenes_file}")

    return numberOfMessages, numberOfScenes


def count_scenes_in_thread(folder, channel):

    channel_name = f"{channel["position"]}-{channel["threadPosition"]}# {channel["thread"]}"

    channel_file = f"{folder}/Threads/{find_channel_file(folder+"/Threads", channel_name)}"

    # count the number of messages
    channel_data = t.load_from_json(channel_file)
    numberOfMessages = channel_data["messageCount"]

    return numberOfMessages


################# Main function #################

def update_info():

    try:

        t.log("base", f"\n###  Updating information of the backup {c.SERVER_NAME}...  ###\n")

        start_time = time.time()

        check_base_status()

        # check if all steps are "success"
        check_overall_status()

        # count the number of scenes
        count_scenes_in_category()

        t.log("debug", "\n  Analyzing the channels in the backup... ###")
        
        backup_info = t.load_from_json(c.BACKUP_INFO)

         # For each category in the channel list
        for category in backup_info["categories"]:

            count_scenes_in_category(category)

            folder = get_category_folder(category)

            t.log("debug", f"\n\t  Analyzing {category["category"]}... ###")

            for channel in category["channels"]:

                channel["numberOfMessages"], channel["numberOfScenes"] = count_scenes_in_channel(folder, channel)
                t.save_to_json(backup_info, c.BACKUP_INFO)

            for thread in category["threads"]:

                thread["numberOfMessages"] = count_scenes_in_thread(folder, thread)
                t.save_to_json(backup_info, c.BACKUP_INFO)


    except Exception as e:
        raise exc.UpdateInfoError("Failed to update backup info") from e
    
    finally:
        t.log("base", f"### Finished updating info --- {time.time() - start_time:.2f} seconds --- ###\n")


if __name__ == "__main__":
    
    try:
        update_info()
    
    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
    
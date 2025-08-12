import os
import json
import re
import tricks as t
t.set_path()
from res import constants as c

################# File summary #################

"""

'export_channels' can numerate categories just fine, but not channels or threads.
This module renames the exported JSON files to reflect channel positions inside the category.

This module is meant to be run after `src/export_channels.py`. It will assume the backup folder contains the channels of channel_list.json.

Main function: sort_exported_files(base_folder)

    This script first goes through the backup folder and analyzes the current order of channels.
    It substitutes the global position index for a local (category-based) position index, and updates the channel_list.json with this new info.

    Then, it cleans up the filenames from the old position numbers.

    Lastly, it goes through the backup folder and renames the JSON files to reflect the localized positions.

    Note: It fails if the channel files don't match the 'export_channels' format.

    Args:
        base_folder (str): The base folder where the exported JSON files are stored.

"""

################# Functions #################

"""
super_normalize(text)

    Aggressively normalizes a string by removing non-alphanumeric characters and converting it all to lowercase.

"""
def super_normalize(text):
    return re.sub(r'[^a-zA-Z0-9-]', '', text).lower()


"""
find_channel_file(folder, target_name)

    Finds a channel file in the specified folder that matches the target name.

    Args:
        folder (str): The folder to search in.
        target_name (str): The target name to search for.

    Returns:
        str: The actual filename of the matching channel file, or None if not found.
"""
def find_channel_file(folder, target_name):

    normalized_target = super_normalize(target_name)

    for filename in os.listdir(folder):
        if filename.endswith(".json") and not filename.endswith("scenes.json"):
            
            file_name = os.path.splitext(filename)[0]

            if super_normalize(file_name) == normalized_target:
                return filename  # Return actual filename with full characters
            
    return None

"""
remove_number_from_files(folder)

    Removes the position number from the filenames of the channel files in the specified folder.

    Args:
        folder (str): The folder to search in.

"""
def remove_number_from_files(folder):

    t.log("info", f"\n\tCleaning up position numbers in the filenames of {folder}...\n")

    # Iterate over all channel JSON files in the folder and its subfolders
    for root, dirs, files in os.walk(folder):
        for filename in files:
            if filename.endswith(".json") and not filename.endswith("scenes.json"):

                t.log("log", f"\t  Cleaning {filename}...")

                # remove number# from the filename
                new_filename = filename.split("# ")[1]
                src = os.path.join(root, filename)
                dst = os.path.join(root, new_filename)
                os.rename(src, dst)

    t.log("info", f"\n\tFinished cleaning up position numbers from channel files\n")

"""
get_number_from_files(folder)

    Analyzes the current order of channel files in the specified folder.
    
    Per each category folder, it goes through the channel filenames and writes down the actual position numbers.
    If this is executed right after `export_channels`, the numbers should be the global position index.
    Then, it replaces those numbers by a localized index for each category, maintaining the order of channels.

    The channel_list structure is updated to reflect the new positions.

    Args:
        search_folder (str): The folder to search in.
        channel_list (dict): The channel list to update.

"""
def get_number_from_files(search_folder, channel_list):

    t.log("info", f"\n\tAnalyzing current order in {search_folder}...\n")

    # For each category in the channel list
    for category in channel_list.get("categories", []):

        folder_name = category["category"].replace(":", "_")
        folder = os.path.join(search_folder, f"{category['position']}# {folder_name}")

        t.log("debug", f"\n\t  Analyzing current order in {folder}... ###")

        # get a list of file names
        file_names = [f.name for f in os.scandir(folder) if f.is_file()]
        t.log("debug", f"\t    Found {len(file_names)} files in {folder}")

        file_dict = {}

        for file in file_names:
            # get number# from the filename
            if not file.endswith("scenes.json"):
                channel_position, channel_name = file.split("# ")
                norm_channel_name = super_normalize(channel_name.split(".js")[0])
                file_dict[norm_channel_name] = int(channel_position)

        # sort dictionary by value
        sorted_dict = {k: v for k, v in sorted(file_dict.items(), key=lambda item: item[1])}

        # renumber the dictionary
        for index, (key, value) in enumerate(sorted_dict.items(), start=1):
            sorted_dict[key] = index

        t.log("debug", f"\n\t  Sorted the dictionary of files in {folder}\n")
        
        for channel in category.get("channels", []):
            channel["position"] = sorted_dict[super_normalize(channel["channel"])]
            t.log("log", f"\tFound channel: {channel['position']}# {channel['channel']}")
        
        # sort channels by position
        category["channels"] = sorted(category["channels"], key=lambda x: x["position"])

        for thread in category.get("threads", []):
            thread["position"] = sorted_dict[super_normalize(thread["channel"])]
            t.log("l9og", f"\tFound thread: {thread['position']}-{thread['threadPosition']}# {thread['thread']}")

        # sort threads by position then threadPosition
        category["threads"] = sorted(category["threads"], key=lambda x: (x["position"], x["threadPosition"]))

    t.log("info", "\n\tFinished analyzing current order\n")

    return

################# Main function #################

def sort_exported_files(base_folder):

    t.log("base", f"\n###  Sorting channel files in {base_folder}...  ###\n")

    channel_list = t.load_from_json(c.CHANNEL_LIST)

    get_number_from_files(base_folder, channel_list)

    remove_number_from_files(base_folder)

    # For each category in the channel list
    for category in channel_list.get("categories", []):

        category_pos = category["position"]
        category_name = category["category"].replace(":", "_")
        category_folder = os.path.join(base_folder, f"{category_pos}# {category_name}")

        t.log("info", f"\n  Sorting {category_pos}# {category_name}...")

        t.log("info", f"    Renaming {len(category['channels'])} channel files...")

        # Rename channel files
        for channel in category.get("channels", []):

            channel_name = channel["channel"]
            channel_pos = channel["position"]

            # Find the file that corresponds to the channel
            old_filename = find_channel_file(category_folder, channel_name)

            if old_filename:

                new_filename = f"{channel_pos}# {old_filename}"

                src = os.path.join(category_folder, old_filename)
                dst = os.path.join(category_folder, new_filename)
                os.rename(src, dst)

                t.log("log", f"\tRenamed file: {old_filename} → {new_filename}")

            else:
                t.log("info", f"{t.RED}\tChannel file not found: {channel_name}")

        # Rename thread files
        threads_folder = os.path.join(category_folder, "Threads")
        t.log("info", f"    Renaming {len(category['threads'])} thread files...")

        for thread in category.get("threads", []):

            channel_name = thread["channel"]
            channel_pos = thread["position"]
            thread_title = thread["thread"]
            thread_pos = thread["threadPosition"]

            # Find the file that corresponds to the thread
            old_filename = find_channel_file(threads_folder, thread_title)

            if old_filename:

                new_filename = f"{channel_pos}-{thread_pos}# {old_filename}"

                src = os.path.join(threads_folder, old_filename)
                dst = os.path.join(threads_folder, new_filename)
                os.rename(src, dst)

                t.log("log", f"\tRenamed file: {old_filename} → {new_filename}")

            else:
                t.log("info", f"{t.RED}\tThread file not found: {thread_title}")

    t.save_to_json(channel_list, c.CHANNEL_LIST)
    
    t.log("base", f"### Finished renaming files ###\n")

if __name__ == "__main__":
    
    sort_exported_files(c.SERVER_NAME)

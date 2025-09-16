import os
import time
import tricks as t
import exceptions as exc
from assign_ids import get_character_name
from find_scenes import find_character_scenes_in_channel
from update_info import update_info
t.set_path()
from res import constants as c

################ File summary #################

"""

This module is intended to map all the scenes of the server backup

Main function: find_all_scenes()

    This module aims to create complete lists of scenes found in the whole server backup, in each category, and in each channel.
    The fact it creates a lot of duplication is known, but it may be useful for some purposes.
    If the intermediate files are not needed, the function can be modified to only save the final one.

    To do this, the main function goes through all the categories and then through all the channels.
    Per each channel, it finds all the characters involved, searches the scenes they appear in, and saves all the distinct scenes into a JSON.
    Once it has searched through all the channels of a category, it aggregates all the scenes and saves them to a JSON file.
    
    To finish, it aggregates all the scenes found in all the categories and saves them to a JSON file.
"""

################# Functions #################

"""
check_base_status()

    Checks the status file, and raises exceptions if the backup is not ready to be sorted.

"""
def check_base_status():

    try: 

        # update_info()

        t.log("debug", "\nChecking the status of the backup...")

        backup_info = t.load_from_json(c.BACKUP_INFO)

        t.log("debug", "  Loaded the status file\n")

        t.log("debug", f"  The current status of the backup is '{backup_info["status"]}'\n")

        if backup_info["status"] == "running":
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        if backup_info["status"] != "success":
            raise exc.DataNotReadyError("The data may be corrupted or incomplete. Ensure the backup downloaded successfully and try again.")

    except (exc.AlreadyRunningError, exc.DataNotReadyError) as e:
        raise e
    
    except Exception as e:
        raise exc.FindScenesError("The export status file could not be read") from e


def validate_scenes(scene_list):

    bad_scene_list = []

    # get the first scene as a reference
    prev_scene = scene_list[0]

    for scene in scene_list[1:]:

        # if the next scene "starts" at the same time as the previous one
        if scene["start"]["index"] == prev_scene["end"]["index"]:
            scene["status"] = "consecutive"
            bad_scene_list.append(prev_scene)
            bad_scene_list.append(scene)

            # if scene starts and ends in the same  message
            if scene["start"]["index"] == scene["end"]["index"]:
                scene_list.remove(scene)
            
        # if the next scene does not start right after the previous one
        elif scene["start"]["index"] > prev_scene["end"]["index"]+1:
            scene["status"] = "gap"
            bad_scene_list.append(prev_scene)
            bad_scene_list.append(scene)
        
        # if the next scene "starts" before the end of the previous one
        elif scene["start"]["index"] < prev_scene["end"]["index"]:

            # if both scenes ended at the same time,
            # it was probably because a character walked in the middle of a scene
            if scene["end"]["index"] == prev_scene["end"]["index"]:
                
                # we merge the two lists of characters
                prev_scene["characters"] = list(set(prev_scene["characters"] + scene["characters"]))
                
                # delete the second scene
                scene["status"] = "late-start-merged"
                bad_scene_list.append(scene)
                scene_list.remove(scene)
            
            elif scene["end"]["index"] < prev_scene["end"]["index"]:
                # if the next scene ended before the end of the previous one,
                # it was probably because a character left the scene in the middle of it

                # we merge the two lists of characters
                prev_scene["characters"] = list(set(prev_scene["characters"] + scene["characters"]))
                
                # delete the second scene
                scene["status"] = "early-end-merged"
                bad_scene_list.append(scene)
                scene_list.remove(scene)
            
            else:
                # no idea
                scene["status"] = "overlap"
                bad_scene_list.append(scene)
        
        prev_scene = scene
    
    return bad_scene_list


"""
find_all_scenes_in_channel(channel):

    Function to find all scenes in a channel.

    To do this, it first gets a list of all characters in the channel.
    Then, for each character, it finds all scenes in the channel with that character.
    Once it has found all scenes, it saves every distinct one to a final list.

    It's a known fact that this method implies parsing the whole channel many more times than it should be necessary,
    but this method allows us to reuse the same function to find scenes of a specific character.
    Besides, detecting starts and ends of scenes is more robust when using a specific character as a marker.

    Once all the distinct scenes in a channel are gathered, they are reordered and saved to a JSON file.

    Args:
        channel (dict): The channel in JSON format.

    Returns:
        list: A list of scenes.

"""
def find_all_scenes_in_channel(channel, category_pos=1, channel_pos=1, thread_pos=0):
    
    characters_in_channel = []
    total_scenes = []
    scene_starts_lookup = []
    total_scenes_debug = []

    t.log("info", f"\n\tFinding scenes in channel '{channel['channel']['name']}'")

    # Get a list of all characters in the channel
    for message in channel["messages"]:
        character = int(message["author"]["id"])
        if character < 1000 and character not in characters_in_channel:
            characters_in_channel.append(character)

    t.log("info", f"\t  Found {len(characters_in_channel)} characters in the channel\n")

    if len(characters_in_channel) == 0:
        return [], []

    # find the scenes for each character
    for character in characters_in_channel:

        t.log("debug", f"\t  Finding scenes with '{get_character_name(character)}'...")

        scenes, discard_id = find_character_scenes_in_channel(channel, [character], 0, True)

        # if a new scene was found, add it to the total list
        for scene in scenes:
            if scene["start"]["id"] not in scene_starts_lookup:
                scene_starts_lookup.append(scene["start"]["id"])
                total_scenes.append(scene)
    
        t.log("debug", f"\t    Found {len(scenes)} scenes with '{get_character_name(character)}', adding up to {len(total_scenes)} total scenes\n")

    # sort the scenes by start time
    total_scenes.sort(key=lambda x: x["start"]["index"])

    # see if there are conflicting scenes
    total_scenes_debug = validate_scenes(total_scenes)

    # give the scenes new IDs
    for i, scene in enumerate(total_scenes):
        scene["index"] = i+1
        scene["id"] = f"{category_pos}{channel_pos}{"" if thread_pos == 0 else thread_pos}{scene['index']}"

    return total_scenes, total_scenes_debug

def prep_channel(channel, category):

    file_path = os.path.join(c.SEARCH_FOLDER, channel["path"])
    t.log("log", f"  Analysing {channel.get('thread', channel['channel'])}...")

    # Load JSON channel from file
    json_data = t.load_from_json(file_path)

    # Find scene starts and ends involving character
    scenes, scenes_debug = find_all_scenes_in_channel(json_data, category["position"], channel["position"], channel.get("threadPosition", 0))

    # save the file
    scenes_file = file_path.replace(".json", "_scenes.json")
    scenes_path = scenes_path = scenes_file.replace("\\Threads\\", "\\Scenes\\") if "\\Threads\\" in scenes_file else os.path.join(os.path.dirname(scenes_file), "Scenes", os.path.basename(scenes_file))

    # TODO this is temporary to find the ones that need fixing. save evrything later
    if len(scenes_debug) > 0:
        t.save_to_json(scenes, scenes_path)
        t.save_to_json(scenes_debug, scenes_path.replace("_scenes.json", "_debug_scenes.json"))

    t.log("log", f"\tSaved {len(scenes)} scenes to {scenes_file}")

    return scenes, scenes_debug


"""
find_scenes_in_category(folder_path):

    Function to find all scenes in a category.

    It first gets a list of all JSON files in the category folder and its subfolders.
    Then, for each JSON file, it calls find_all_scenes_in_channel() to find all scenes in the file.

    Once all the scenes in a category are gathered, they are reordered and saved to a JSON file.

    Args:
        folder_path (str): The path to the category folder.

    Returns:
        list: A list of scenes.
"""

def find_scenes_in_category(category):

    start_time = time.time()

    # Create an empty list to store scene starts and ends
    all_scenes = []
    all_scenes_debug = []

    t.log("info", f"\n    ## Finding scenes in {category['category']}... ##")

    for channel in category["channels"]:

        scenes, scenes_debug = prep_channel(channel, category)

        # Add the messages to the respective lists, can be more than one per channel
        all_scenes.extend(scenes)
        all_scenes_debug.extend(scenes_debug)

        t.log("info", f"\t  Found {len(scenes)} scenes in '{scenes[0]["channel"] if len(scenes) > 0 else 'this channel'}', adding up to {len(all_scenes)} total scenes\n")

    for thread in category["threads"]:

        scenes, scenes_debug = prep_channel(thread, category)

        # Add the messages to the respective lists, can be more than one per channel
        all_scenes.extend(scenes)
        all_scenes_debug.extend(scenes_debug)

        t.log("info", f"\t  Found {len(scenes)} scenes in '{scenes[0]['channel'] if len(scenes) > 0 else 'this thread'}', adding up to {len(all_scenes)} total scenes\n")

    # sort the scenes by start time
    all_scenes.sort(key=lambda x: x["start"]["timestamp"])

    # give the scenes new IDs
    for i, scene in enumerate(all_scenes):
        scene["index"] = i+1

    folder_path = os.path.join(c.SEARCH_FOLDER, category["path"])

    t.save_to_json(all_scenes, f"{folder_path}/scenes.json")
    t.save_to_json(all_scenes_debug, f"{folder_path}/debug_scenes.json")

    t.log("debug", f"\n    Saved {len(all_scenes)} scenes to {folder_path}/scenes.json")
    t.log("info", f"\n    ## Finished finding scenes in {folder_path} --- {time.time() - start_time:.2f} seconds --- ##\n")

    return all_scenes

################ Main function #################

def find_all_scenes():

    try:
        start_time = time.time()

        t.log("base", f"\n# Indexing all the scenes in {c.SEARCH_FOLDER}... #\n")

        check_base_status()
    
        full_scenes = []

        backup_info = t.load_from_json(c.BACKUP_INFO)

        for category in backup_info["categories"]:

            # TODO temporarily skip some categories to speed things up
            if category["position"] != 11:
                continue

            # create Scenes folder if it doesn't exist
            if not os.path.exists(f"{c.SEARCH_FOLDER}/{category["path"]}/Scenes"):
                os.makedirs(f"{c.SEARCH_FOLDER}/{category["path"]}/Scenes")

            scenes = find_scenes_in_category(category)

            full_scenes.extend(scenes)
            t.log("info", f"  Found {len(scenes)} scenes in {category["path"]}, adding up to {len(full_scenes)} total scenes\n")

        # sort the scenes by start time
        full_scenes.sort(key=lambda x: x["start"]["timestamp"])

        # update scene indexes
        for i, scene in enumerate(full_scenes):
            scene["index"] = i+1

        t.save_to_json(full_scenes, f"{c.SEARCH_FOLDER}\\scenes.json")

        t.log("info", f"\n  Saved {len(full_scenes)} scenes to {c.SEARCH_FOLDER}\\scenes.json")

    except Exception as e:
        raise exc.FindScenesError("Failed to find all scenes") from e

    finally:
        t.log("base", f"\n# Scene indexing finished --- {time.time() - start_time:.2f} seconds --- #\n")


if __name__ == "__main__":
    
    try:
        find_all_scenes()

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
    
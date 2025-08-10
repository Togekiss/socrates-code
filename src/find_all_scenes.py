import json
import os
import re
import time
import unicodedata
import tricks as t
from assign_ids import get_character_name
from find_scenes import find_character_scenes_in_channel
t.set_path()
from res import constants as c
from output_scene_list import output_scene_list

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
def find_all_scenes_in_channel(channel):
    
    characters_in_channel = []
    total_scenes = []
    scene_starts_lookup = []

    t.log("info", f"\n\tFinding scenes in channel '{channel['channel']['name']}'")

    # Get a list of all characters in the channel
    for message in channel["messages"]:
        character = int(message["author"]["id"])
        if character < 1000 and character not in characters_in_channel:
            characters_in_channel.append(character)

    t.log("info", f"\t  Found {len(characters_in_channel)} characters in the channel\n")

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
    total_scenes.sort(key=lambda x: x["start"]["timestamp"])

    # give the scenes new IDs
    for i, scene in enumerate(total_scenes):
        scene["sceneId"] = i+1

    return total_scenes

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

def find_scenes_in_category(folder_path):
    
    start_time = time.time()

    # Create an empty list to store scene starts and ends
    all_scenes = []
    scene_id = -1

    t.log("info", f"\n    ## Finding scenes in {folder_path}... ##")

    # Iterate over all JSON files in the server folder and its subfolders
    for root, dirs, files in os.walk(folder_path):
        for filename in files:
            if filename.endswith(".json") and not filename.endswith("scenes.json"):
                
                file_path = os.path.join(root, filename)
                t.log("log", f"  Analysing {file_path}...")

                # Load JSON channel from file
                json_data = t.load_from_json(file_path)

                # Find scene starts and ends involving character
                scenes = find_all_scenes_in_channel(json_data)

                # save the file
                scenes_file = f"{folder_path}/Scenes/{filename.split('.')[0]}_scenes.json"
                t.save_to_json(scenes, scenes_file)

                t.log("log", f"\tSaved {len(scenes)} scenes to {scenes_file}")

                # Add the messages to the respective lists, can be more than one per channel
                all_scenes.extend(scenes)

                t.log("info", f"\t  Found {len(scenes)} scenes in '{scenes[0]["channel"] if len(scenes) > 0 else 'this channel'}', adding up to {len(all_scenes)} total scenes\n")

    # sort the scenes by start time
    all_scenes.sort(key=lambda x: x["start"]["timestamp"])

    # give the scenes new IDs
    for i, scene in enumerate(all_scenes):
        scene["sceneId"] = i+1

    t.save_to_json(all_scenes, f"{folder_path}\scenes.json")

    t.log("debug", f"\n    Saved {len(all_scenes)} scenes to {folder_path}\scenes.json")
    t.log("info", f"\n    ## Finished finding scenes in {folder_path} --- {time.time() - start_time:.2f} seconds --- ##\n")

    return all_scenes

################ Main function #################

def find_all_scenes():

    start_time = time.time()

    t.log("base", f"\n# Indexing all the scenes in {c.SEARCH_FOLDER}... #\n")
 
    full_scenes = []

    # get all folders in folder c.SEARCH_FOLDER
    folders = [f.path for f in os.scandir(c.SEARCH_FOLDER) if f.is_dir()]

    # find all scenes in all folders
    for folder in folders:

        # create Scenes folder if it doesn't exist
        if not os.path.exists(f"{folder}/Scenes"):
            os.makedirs(f"{folder}/Scenes")

        scenes = find_scenes_in_category(folder)

        full_scenes.extend(scenes)
        t.log("info", f"  Found {len(scenes)} scenes in {folder}, adding up to {len(full_scenes)} total scenes\n")

    # sort the scenes by start time
    full_scenes.sort(key=lambda x: x["start"]["timestamp"])

    # give the scenes new IDs
    for i, scene in enumerate(full_scenes):
        scene["sceneId"] = i+1

    t.save_to_json(full_scenes, f"{c.SEARCH_FOLDER}\scenes.json")

    t.log("info", f"\n  Saved {len(full_scenes)} scenes to {c.SEARCH_FOLDER}\scenes.json")

    t.log("base", f"\n# Scene indexing finished --- {time.time() - start_time:.2f} seconds --- #\n")


if __name__ == "__main__":
    find_all_scenes()
    
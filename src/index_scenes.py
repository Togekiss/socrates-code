import os
import time
import utils.tricks as t
import utils.exceptions as exc
from assign_ids import get_character_name
from find_character_scenes import find_character_scenes_in_channel
from models import ServerBackup, Category, Channel, Thread
t.set_path()
from res import constants as c

################ File summary #################

"""

This module is intended to map all the scenes of the server backup

Main function: index_scenes()

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
load_status()

    Loads backup information from a JSON file, and checks if it's ready to work with.

    Returns:
        ServerBackup: The current status of the backup.
"""
def load_status():

    try: 
        t.log("debug", f'  Loading backup info from file: {c.BACKUP_INFO}')

        backup = ServerBackup.from_json(c.BACKUP_INFO)

        if backup.is_running():
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        if not backup.can_index_scenes():
            raise exc.DataNotReadyError("The data may be corrupted or incomplete. Ensure the backup downloaded successfully and try again.")

        t.log("debug", f"  The current status of the backup is '{backup.status}'\n")

        # flag it as running in case another execution of the script is launched
        backup.start_index_scenes()

        t.log("debug", "  Backup is ready.\n")

    except (exc.DataNotReadyError, exc.AlreadyRunningError) as e:
        raise e
     
    except Exception as e:
        raise exc.IndexScenesError("The export status file could not be read") from e
    
    return backup


"""
validate_scenes()

    Checks if the list of scenes is valid, and returns it.

    Args:
        scene_list (list): The list of scenes to check.

    Returns:
        list: The list of valid scenes.
"""
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

            # if scene starts and ends in the same message
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
def find_all_scenes_in_channel(channel, id_builder):
    
    characters_in_channel = []
    total_scenes = []
    scene_starts_lookup = []
    total_bad_scenes = []

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

    # see if there are conflicting or duplicated scenes
    total_bad_scenes = validate_scenes(total_scenes)

    # give the scenes new indexes
    for i, scene in enumerate(total_scenes):
        scene["index"] = i+1
        scene["id"] = f"{id_builder}{scene['index']}"

    return total_scenes, total_bad_scenes



def process_channel(channel:Channel|Thread, id_builder:str):

    file_path = os.path.join(c.DATA_FOLDER, channel.path)
    t.log("log", f"  Analysing {channel.name}...")

    # Load JSON channel from file
    json_data = t.load_from_json(file_path)

    # Find scene starts and ends for all characters
    scenes, bad_scenes = find_all_scenes_in_channel(json_data, id_builder)

    # save the file
    scenes_file = file_path.replace(".json", "_scenes.json")
    scenes_path = scenes_file.replace("\\Threads\\", "\\Scenes\\") if "\\Threads\\" in scenes_file else os.path.join(os.path.dirname(scenes_file), "Scenes", os.path.basename(scenes_file))

    # TODO this is temporary to find the ones that need fixing. save evrything later
    t.save_to_json(scenes, scenes_path)
    if len(bad_scenes) > 0:
        t.save_to_json(bad_scenes, scenes_path.replace("_scenes.json", "_bad_scenes.json"))

    t.log("log", f"\tSaved {len(scenes)} scenes to {scenes_file}")

    # Update the model with the scene count
    channel.scenes = len(scenes)

    return scenes, bad_scenes


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

def find_scenes_in_category(category:Category):

    start_time = time.time()

    # Create an empty list to store scene starts and ends
    all_scenes = []
    all_bad_scenes = []

    t.log("info", f"\n    ## Finding scenes in {category.name}... ##")

    for channel in category.channels:

        scenes, bad_scenes = process_channel(channel, f"{category.position}{channel.position}")

        # Add the messages to the respective lists, can be more than one per channel
        all_scenes.extend(scenes)
        all_bad_scenes.extend(bad_scenes)

        t.log("info", f"\t  Found {len(scenes)} scenes in '{scenes[0]["channel"] if len(scenes) > 0 else 'this channel'}', adding up to {len(all_scenes)} total scenes\n")

        for thread in channel.threads:

            scenes, bad_scenes = process_channel(thread, f"{category.position}{channel.position}{thread.position}")

            # Add the messages to the respective lists, can be more than one per channel
            all_scenes.extend(scenes)
            all_bad_scenes.extend(bad_scenes)

            t.log("info", f"\t  Found {len(scenes)} scenes in '{scenes[0]['channel'] if len(scenes) > 0 else 'this thread'}', adding up to {len(all_scenes)} total scenes\n")

    # sort the scenes by start time
    all_scenes.sort(key=lambda x: x["start"]["timestamp"])

    # give the scenes new indexes
    for i, scene in enumerate(all_scenes):
        scene["index"] = i+1

    folder_path = os.path.join(c.DATA_FOLDER, category.path)

    t.save_to_json(all_scenes, f"{folder_path}/_scenes.json")
    t.save_to_json(all_bad_scenes, f"{folder_path}/_bad_scenes.json")

    t.log("debug", f"\n    Saved {len(all_scenes)} scenes to {folder_path}/_scenes.json")
    t.log("info", f"\n    ## Finished finding scenes in {folder_path} --- {time.time() - start_time:.2f} seconds --- ##\n")

    return all_scenes

################ Main function #################

def index_scenes():

    backup = load_status()

    try:
        start_time = time.time()

        t.log("base", f"\n# Indexing all the scenes in {c.SERVER_NAME}... #\n")
    
        full_scenes = []

        for category in backup.categories:

            # create Scenes folder if it doesn't exist
            if not os.path.exists(f"{c.DATA_FOLDER}/{category.path}/Scenes"):
                os.makedirs(f"{c.DATA_FOLDER}/{category.path}/Scenes")

            scenes = find_scenes_in_category(category)

            full_scenes.extend(scenes)
            t.log("info", f"  Found {len(scenes)} scenes in {category.path}, adding up to {len(full_scenes)} total scenes\n")

        # sort the scenes by start time
        full_scenes.sort(key=lambda x: x["start"]["timestamp"])

        # update scene indexes
        for i, scene in enumerate(full_scenes):
            scene["index"] = i+1

        t.save_to_json(full_scenes, f"{c.DATA_FOLDER}\\_scenes.json")

        t.log("info", f"\n  Saved {len(full_scenes)} scenes to {c.DATA_FOLDER}\\_scenes.json")

        # Update the overall backup model and save to the status file
        backup.save()
        backup.finish_index_scenes()

    except Exception as e:
        backup.finish_index_scenes(success=False)
        raise exc.IndexScenesError("Failed to index all scenes") from e

    finally:
        t.log("base", f"\n# Scene indexing finished --- {time.time() - start_time:.2f} seconds --- #\n")

        # if there was an exception, raise it again
        if 'e' in locals() and e is not None:
            raise e

if __name__ == "__main__":
    
    try:
        index_scenes()

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
    
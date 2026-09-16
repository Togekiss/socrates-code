import os
import time
import utils.tricks as t
import utils.exceptions as exc
from models import ServerBackup, CharacterList
t.set_path()
from res import constants as c

################ File summary #################

"""

This module assigns unique IDs to the Tupperbox bots in the backup of a Discord server.

Main function: assign_ids(search_folder)

    This function traverses all JSON files in the specified folder and its subdirectories to assign unique 
    identifiers to each bot found within the message data. If a character ID mapping file exists, it will be 
    loaded and updated; otherwise, a new mapping will be created. The function ensures that each bot has a 
    unique ID, updates the original JSON files with these IDs, and saves the mapping back to the character 
    ID file for future reference.

"""

################ Functions #################


"""
load_status()

    Loads backup information from a JSON file, and checks if it's ready to work with.

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

            t.log("debug", "An update is running. Using the update info file\n")

            backup = ServerBackup.from_json(c.BACKUP_INFO_UPDATE)

        if backup.is_running():
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        if not backup.can_assign_ids():
            raise exc.DataNotReadyError("The data may be corrupted. Ensure the backup downloaded successfully and try again.")

        t.log("debug", f"  The current status of the backup is '{backup.status}'\n")

        # flag it as running in case another execution of the script is launched
        backup.start_assign_ids()

        t.log("debug", "  Backup info file is ready.\n")

    except (exc.DataNotReadyError, exc.AlreadyRunningError) as e:
        raise e
     
    except Exception as e:
        raise exc.AssignIDError("The export status file could not be read") from e
    
    return backup, is_update


# Backwards compatibility wrappers for other modules
def get_character_id(name):
    char_list = CharacterList.load(c.CHARACTER_LIST)
    return char_list.find_id_by_name(name)

def get_character_name(id):
    char_list = CharacterList.load(c.CHARACTER_LIST)
    return char_list.get_character_name(id)

def get_all_character_ids(name):
    char_list = CharacterList.load(c.CHARACTER_LIST)
    return char_list.get_all_character_ids(name)


"""
assign_ids_in_file(data, char_list)

    Assigns unique IDs to the Tupperbox bots in the given data and updates the ID mapping accordingly.

    Args:
        file_path (str): The JSON file of the channel, containing a list of messages.
        char_list (CharacterList): The character list model.

    Returns:
        None
"""
def assign_ids_in_file(file_path, char_list: CharacterList):

    t.log("debug", f"\t    Analysing {file_path}...")

    # Load channel JSON data from file
    data = t.load_from_json(file_path)

    for message in data["messages"]:
        # only do this for tuppers
        if message["author"]["isBot"]:
            author_name = message["author"]["name"]

            # If the character is not already in the list, add it
            char_id = char_list.find_id_by_name(author_name)
            if char_id is None:
                new_char = char_list.add_character(author_name)
                char_id = new_char.id
                t.log("info", f"\t  Found a new Tupper: {author_name} (ID: {char_id})")
                char_list.save(c.CHARACTER_LIST)
         
            # Update the author's ID in the message
            message["author"]["id"] = f"{char_id}"

    # Save the updated JSON data to the file
    t.save_to_json(data, file_path)
    

################ Main function #################

def assign_ids():

    backup, is_update = load_status()
    search_folder = c.UPDATE_FOLDER if is_update else c.DATA_FOLDER

    try:

        t.log("base", f"\n###  Assigning unique IDs to Tupperbox bots in {search_folder}...  ###\n")

        start_time = time.time()

        # Open or create a dictionary to store character info
        char_list = CharacterList.load(c.CHARACTER_LIST)

        t.log("info", f"\tLoaded {len(char_list.characters)} main characters\n")

        t.log("debug", f"\tIterating over backup files in {search_folder}...\n")  

        # Iterate over all channel files
        for path in backup.get_all_paths():
            assign_ids_in_file(os.path.join(search_folder, path), char_list)
        
        # We flag the successful backup state
        backup.finish_assign_ids(success=True)
        
        elapsed_time = time.time() - start_time

        t.log("base", f"\n### ID assigning finished --- {elapsed_time:.2f} seconds --- ###\n")

    except Exception as e:
        backup.finish_assign_ids(success=False)
        raise exc.AssignIDError("Failed to assign unique IDs to Tupperbox bots") from e


# We leave this to allow for independent execution
if __name__ == "__main__":
    t.set_path()
    from res import constants as c
    
    t.log("console", "Assign IDs step starting...")
    
    try:
        assign_ids()
        t.log("console", "Assign IDs step completed.")

    except Exception as e:
        t.log("error", str(e))
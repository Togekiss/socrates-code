import os
import re
import utils.tricks as t
import utils.exceptions as exc
from models import ServerBackup, Category, Channel
t.set_path()
from res import constants as c

################# File summary #################

"""
Main function: verify_download(base_folder)

    This script is meant to be run after `src/download_channels.py`.
    It goes through the backup folder and checks if the downloaded folders and files exist 
    and correspond to the expected format.

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
load_status()

    Checks the status file, and raises exceptions if the backup is not ready to be verified.

    Returns:
        backup (ServerBackup): The loaded ServerBackup object.
        is_update (bool): Whether the backup is in update mode or not.

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
       
        if not backup.can_verify():
            raise exc.DataNotReadyError("There is no data to verify. Ensure the backup downloaded successfully and try again.")
        
        t.log("debug", f"  The current status of the backup is '{backup.status}'\n")

        backup.start_verify()

        t.log("debug", "  Backup info file is ready.\n")

    except (exc.AlreadyRunningError, exc.DataNotReadyError) as e:
        raise e
    
    except Exception as e:
        raise exc.VerifyError("The export status file could not be read") from e
    
    return backup, is_update

"""
count_files(target_number, folder)

    Counts the number of files in the folder to check if they match the number of channels.

    Args:
        target_number (int): The expected number of files.
        folder (str): The folder to count the files in.

    Returns:
        files (list): A list of the files in the folder, to not have to read the folder again.
        
"""
def count_files(target_number, folder):

    # Check if the folder exists
    if not os.path.exists(folder):
        raise exc.VerifyPathsError(f"The folder '{folder}' does not exist.")

    t.log("debug", f"\tFound folder '{folder}'")

    # Get all .json files that don't end with '_scenes.json'
    files = [f for f in os.listdir(folder) if f.endswith(".json") and not f.endswith("_scenes.json")]

    t.log("debug", f"\t\tWe found {len(files)} files in the folder '{folder}'")

    # Check if the number of files match the target_number
    if (len(files) != target_number):
        raise exc.VerifyPathsError(f"The number of files ({len(files)}) in the folder '{folder}' does not match the number ({target_number}) set in the info file.")

    t.log("debug", f"\t\tThe number of files matches the number set in the info file ({target_number}).\n")

    return files


"""
verify_channel_file(cat: Category, folder, filename)

    Checks if the file corresponds to an entry in the info file, and if the information is correct.

    Args:
        cat (Category): The category info.
        folder (str): The folder to find the file in.
        filename (str): The name of the file to check.
"""
def verify_channel_file(cat: Category, folder, filename):

    t.log("debug", f"\tChecking the channel in the file '{filename}'...")
    
    # load the file
    file_data = t.load_from_json(os.path.join(folder, filename))
    file_id = file_data["channel"]["id"]

    if (file_data["channel"]["categoryId"] != cat.id):
        raise exc.VerifyPathsError(f"The folder '{cat.name}'s ID does not match the category of '{file_data['channel']['category']}' ID in the file '{filename}'.")
    
    t.log("debug", f"\t\tThe folder '{cat.name}'s ID matches the category ID in the file '{filename}'.")

    # check if channel exists
    if not cat.has_channel(file_id):
        raise exc.VerifyPathsError(f"The channel '{file_id}' in the file '{filename}' does not exist in the category '{cat.name}'.")
    
    ch = cat.get_channel_by_id(file_id)

    t.log("debug", f"\t\tFound channel '{ch.name}' with id '{file_id}' in '{filename}'")
    
    # parse the number in the filename before # and check if it matches the position in the status file
    if int(filename.split("# ")[0]) != ch.position:
        raise exc.VerifyPathsError(f"The position of the channel's file '{filename}' does not match the position ({ch.position}#) set in the info file.")

    t.log("debug", f"\t\tThe position of the channel's file '{filename}' matches the position set in the info file.")
   
    # update numberOfMessages
    ch.messages = file_data["messageCount"]
    ch.path = os.path.join(cat.path, filename)

    t.log("debug", f"\t\tFile '{ch.path}' verified with {ch.messages} messages\n")

"""
verify_thread_file(cat: Category, folder, filename)

    Checks if the file corresponds to an entry in the info file, and if the information is correct.

    Args:
        cat (Category): The category info.
        folder (str): The folder to find the file in.
        filename (str): The name of the file to check.

"""
def verify_thread_file(cat: Category, folder, filename):

    t.log("debug", f"\tChecking the thread in the file '{filename}'...")
    
    # load the file
    file_data = t.load_from_json(os.path.join(folder, filename))
    file_id = file_data["channel"]["id"]

    # check if cat["channels"][file_id] exists
    if not cat.has_thread(file_id):
        raise exc.VerifyPathsError(f"The thread '{file_id}' in the file '{filename}' does not exist in the category '{cat.name}'.")
    
    th, ch = cat.get_thread_and_parent_channel(file_id)

    t.log("debug", f"\t\tFound thread '{th.name}' in channel '{ch.name}' with id '{file_id}' in '{filename}'")

    if (file_data["channel"]["categoryId"] != ch.id):
        raise exc.VerifyPathsError(f"The parent channel '{ch.name}'s ID does not match the category of '{file_data['channel']['category']}' ID in the file '{filename}'.")
    
    t.log("debug", f"\t\tThe parent channel '{ch.name}'s ID matches the category ID in the file '{filename}'.")

    if (
        int(filename.split("# ")[0].split("-")[0]) != ch.position
        or int(filename.split("# ")[0].split("-")[1]) != th.position
    ):
        raise exc.VerifyPathsError(f"The position of the thread's file '{filename}' does not match the position ({ch.position}-{th.position}#) set in the info file.")

    t.log("debug", f"\t\tThe position of the thread's file '{filename}' matches the position set in the info file.")

    # update numberOfMessages
    th.messages = file_data["messageCount"]
    th.path = os.path.join(cat.path, "Threads", filename)

    t.log("debug", f"\t\tFile '{th.path}' verified with {th.messages} messages\n")



"""
verify_category(cat, is_update)

    This function accesses a category's folder to verify if it exists,
    its number of files, and if the information in the files matches the info file.

    Args:
        cat (Category): The category to verify.
        cat_folder (str): The path to the category files.

"""
def verify_category_folder(cat: Category, folder):

    t.log("debug", f"\tChecking '{cat.name}'...")

    cat_folder = os.path.join(folder, cat.path)

    # Check if the category folder exists
    if not os.path.exists(cat_folder):
        raise exc.VerifyPathsError(f"The category folder '{cat_folder}' does not exist.")
    
    t.log("debug", f"\t\tFound category folder '{cat_folder}'\n")

    files = count_files(cat.number_of_channels, cat_folder)

    # open each file
    for filename in files:
        
        verify_channel_file(cat, cat_folder, filename)

    # If it has threads
    if cat.number_of_threads != 0:

        threads_folder = os.path.join(cat_folder, "Threads")

        files = count_files(cat.number_of_threads, threads_folder)

        # open each file
        for filename in files:
            
            verify_thread_file(cat, threads_folder, filename)

            

"""
verify_files(is_update)

    This function navigates the backup folder and, for each folder and file,
    checks if it has an entry in the status file.

    Args:
        backup (ServerBackup): The loaded ServerBackup object.
        is_update (bool): Whether the backup is in update mode or not.

    Returns:
        None
"""
def verify_files(backup: ServerBackup, is_update):
        
    try:
        folder = c.UPDATE_FOLDER if is_update else c.DATA_FOLDER

        t.log("info", f"\n\tVerifying paths in {folder}...\n")

        # Check if number of folders match numberOfCategories 
        if len(os.listdir(folder)) != backup.number_of_categories:
            raise exc.VerifyPathsError(f"The number of folders ({len(os.listdir(folder))}) does not match the number of categories ({backup.number_of_categories}) in the status file.")
        
        t.log("debug", f"\n\tWe found {len(os.listdir(folder))} folders that match {backup.number_of_categories} categories.\n")

        # Check each category
        for cat in backup.categories:
            verify_category_folder(cat, folder)
            backup.to_json()
            
        t.log("info", f"\nAll folders have been verified.\n")
    
    except Exception as e:
        raise e

            

################# Main function #################

def verify_download():

    t.log("base", f"\n###  Verifying files in {c.SERVER_NAME}...  ###\n")

    backup, is_update = load_status()

    try:

        # Check that everything was downloaded correctly
        verify_files(backup, is_update)

        backup.finish_verify()
    
    except Exception as e:
        backup.finish_verify(success=False)
        raise exc.VerifyError(f"An error occurred while verifying files in {c.SERVER_NAME}") from e

    finally:
        try:
            t.log("info", "\n\tFinished verifying file paths\n")

            if is_update and backup.is_failed():
                main_backup = ServerBackup.from_json(c.BACKUP_INFO)
                main_backup.finish_update(success=False)

        except Exception as e:
            t.log("error", f"\tFailed to save the status file: {e}\n")
        
        # if there was an exception, raise it again
        if 'e' in locals() and e is not None:
            raise e


if __name__ == "__main__":

    try:
        verify_download()

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")

import os
import shutil
import time
import utils.tricks as t
import utils.exceptions as exc
from models import ServerBackup, Category, Channel, Thread
t.set_path()
from res import constants as c

################# File summary #################

"""

This module ensures the "Old" backup folder has the same structure as the "Update" folder.

Main function: update_paths()

    The "Update" folder should contain the new channel history files exported by DCE.
    The "Old" folder should contain the old channel history files to be updated.

    Between updates, it's possible that the structure of the server changed as items can be
    renamed, reordered, or deleted. This function spots differences between the two structures,
    and applies the necessary changes to the "Old" folder to match the latest update.

    First, it will walk through all the items in the update, and find their equivalent in the old folder.
    If the path location does not match, it writes the new data and marks it for update.
    After that, it walks through items in the "Old" folder that did not appear in the update-
    which indicates they were deleted from the server.

    Finally, it will go through all the items marked for update, and apply the
    changes to the "Old" folder.

"""

################## Functions #################


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
        
        if not backup.can_compare():
            raise exc.DataNotReadyError("The data may be corrupted. Ensure the backup downloaded successfully and try again.")


        t.log("debug", f"  The current status of the backup is '{backup.status}'\n")

        # Check if the merge folder exists
        if not os.path.exists(c.MERGE_FOLDER):
            t.create_merge_folder()

        # flag it as running in case another execution of the script is launched
        backup.start_compare()

        t.log("debug", "  Backup info file is ready.\n")

    except (exc.DataNotReadyError, exc.AlreadyRunningError) as e:
        raise e
     
    except Exception as e:
        raise exc.UpdatePathsError("The export status file could not be read") from e
    
    return backup, is_update


"""
detect_deleted(main_backup, update_backup)

    Looks for categories, channels and threads in the main backup that are not in the update backup,
    and marks them as deleted.

    Marking them as not deleted might look redundant, but it's possible that one that was marked as deleted
    has been restored in the new backup update.

    Args:
        main_backup (ServerBackup): The main backup to check.
        update_backup (ServerBackup): The update backup to compare against.

"""
def detect_deleted(main_backup: ServerBackup, update_backup: ServerBackup):

    t.log("info", "\tChecking for deleted items...\n")

    for category in main_backup.categories:
        
        # If it's not in the update backup, it means it was deleted
        if not update_backup.has_category(category.id):
            t.log("info", f"  Category '{category.name}' isn't part of the update.")

            # We only add '_deleted' if it's not already deleted, to avoid duplicates
            if not category.is_deleted:
                category.new_path = category.path + "_deleted"
            category.is_deleted = True

            t.log("debug", f"  Category '{category.name}' marked as deleted.")
            
        else:
            t.log("debug", f"  Category '{category.name}' is part of the update.")
            category.is_deleted = False

        for channel in category.channels:
            if not update_backup.has_channel(channel.id):
                t.log("info", f"  Channel '{channel.name}' isn't part of the update.")
                if not channel.is_deleted:
                    channel.new_path = channel.path.replace(category.path, category.new_path if category.new_path is not None else category.path).replace(".json", "_deleted.json")
                channel.is_deleted = True

                t.log("debug", f"  Channel '{channel.name}' marked as deleted.")

            else:
                t.log("debug", f"  Channel '{channel.name}' is part of the update.")
                channel.is_deleted = False

            for thread in channel.threads:
                if not update_backup.has_thread(thread.id):
                    t.log("info", f"  Thread '{thread.name}' isn't part of the update.")
                    if not thread.is_deleted:
                        thread.new_path = thread.path.replace(category.path, category.new_path if category.new_path is not None else category.path).replace(".json", "_deleted.json")
                    thread.is_deleted = True

                    t.log("debug", f"  Thread '{thread.name}' marked as deleted.")

                else:
                    t.log("debug", f"  Thread '{thread.name}' is part of the update.")
                    thread.is_deleted = False
    
    main_backup.save()


"""
compare_thread(thread, main_backup, main_channel)

    Compares a thread from the update backup with the main backup.
    If the thread is new, it is added to the main backup.
    If it exists, it checks for discrepancies in name, position, and path and fixes them if needed.

    Args:
        thread (Thread): The thread from the update backup to compare.
        main_backup (ServerBackup): The main backup to compare against.
        main_channel (Channel): The channel in the main backup where the thread should be.

"""
def compare_thread(thread: Thread, main_backup: ServerBackup, main_channel: Channel):

    t.log("debug", f"\tChecking thread '{thread.name}'...")

    # If the thread is not in the backup, it means it's new
    if not main_backup.has_thread(thread.id):
        
        t.log("debug", f"\t\tThread '{thread.name}' is new.")

        main_channel.add_thread_from_update(thread)
        main_backup.save()

        t.log("debug", f"\t\tThread '{thread.name}' added to the main backup.")

    # If the thread exists in the main backup
    else:
        t.log("debug", f"\t\tThread '{thread.name}' is already in the main backup.")

        # It  will always be under the same channel, as threads can't be moved
        main_thread = main_channel.get_thread_by_id(thread.id)

        # Check if the path (includes name and position) matches
        if thread.path != main_thread.path:
            t.log("debug", f"\t\tThread '{thread.name}' has a different name, position or path than in the main backup. Updating...")
            
            main_thread.update(thread.name, thread.position, thread.path)
            main_backup.build_indexes()

            t.log("debug", f"\t\tThread '{thread.name}' marked for update.\n")
        
        else:
            t.log("debug", f"\t\tThread '{thread.name}' is in the same location in the main backup.\n")


"""
compare_channel(channel, main_backup, main_cat)

    Compares a channel from the update backup with the main backup.
    If the channel is new, it is added to the main backup.
    If it exists, it checks for discrepancies in name, position, and path, and fixes them if needed.
    It also compares threads within the channel, checking for new or modified threads.

    Args:
        channel (Channel): The channel from the update backup to compare.
        main_backup (ServerBackup): The main backup to compare against.
        main_cat (Category): The category in the main backup where the channel should be.

"""
def compare_channel(channel: Channel, main_backup: ServerBackup, main_cat: Category):

    t.log("debug", f"\tChecking channel '{channel.name}'...")

    # If the channel is not in the backup (in any category), it means it's new
    if not main_backup.has_channel(channel.id):
        
        t.log("debug", f"\t\tChannel '{channel.name}' is new.")

        # This adds the channel along with its threads into the target category
        main_cat.add_channel_from_update(channel)
        main_backup.save()

        t.log("debug", f"\t\tChannel '{channel.name}' and its threads added to the main backup.")

        # Since it's a new addition, its threads won't need to be compared

    # If the channel exists in the main backup
    else:

        t.log("debug", f"\t\tChannel '{channel.name}' is already in the main backup.")

        main_channel = main_backup.get_channel_by_id(channel.id)

        # To check if it needs to be moved to another category
        main_cat_origin = main_backup.get_parent_category_of_channel(main_channel.id)

        if main_cat_origin.id != main_cat.id:
            t.log("debug", f"\t\t\tChannel '{channel.name}' is in a different category than in the main backup. Moving...")

            main_cat_origin.remove_channel_by_id(main_channel.id)
            main_cat.add_channel_from_update(main_channel)
            main_backup.save()

            t.log("debug", f"\t\t\tChannel '{channel.name}' moved to the right category in the main backup.")

        # Check if the path (includes name and position) matches. Should  always trigger if it was moved between categories
        if channel.path != main_channel.path:
            t.log("debug", f"\t\tChannel '{channel.name}' has a different name, position or path than in the main backup. Updating...")
            
            main_channel.update(channel.name, channel.position, channel.path)
            main_backup.build_indexes()

            t.log("debug", f"\t\tChannel '{channel.name}' marked for update.\n")
        
        else:
            t.log("debug", f"\t\tChannel '{channel.name}' is in the same location in the main backup.\n")

        # Iterate over the threads
        for thread in channel.threads:
            compare_thread(thread, main_backup, main_channel)


"""
compare_category(cat, main_backup)

    Compares a category from the update backup with the main backup.
    If the category is new, it is added to the main backup.
    If it exists, it checks for discrepancies in name, position, and path and fixes them if needed.
    It also compares channels within the category, checking for new or modified channels and threads.

    Args:
        cat (Category): The category from the update backup to compare.
        main_backup (ServerBackup): The main backup to compare against.

"""
def compare_category(cat:Category, main_backup:ServerBackup):
    
    t.log("debug", f"\tChecking category '{cat.name}'...")

    # If the category is not in the info file, it means it's new
    if not main_backup.has_category(cat.id):
        
        t.log("debug", f"\t\tCategory '{cat.name}' is new.")
        
        # This adds the category without channels, in case they already exist but in another category
        main_backup.add_category_from_update(cat)

        t.log("debug", f"\t\tCategory '{cat.name}' added to the main backup.")
    
    # Now that the category exists in the main backup, we have to make sure its data matches
    t.log("debug", f"\t\tCategory '{cat.name}' is in the main backup.")

    main_cat = main_backup.get_category_by_id(cat.id)

    # Check if the path (includes name and position) matches
    if cat.path != main_cat.path:
        t.log("debug", f"\t\tCategory '{cat.name}' has a different name, position or path than in the main backup. Updating...")
        
        main_cat.update(cat.name, cat.position, cat.path)
        main_backup.build_indexes()

        t.log("debug", f"\t\tCategory '{cat.name}' marked for update.\n")

    else:
        t.log("debug", f"\t\tCategory '{cat.name}' is in the same location in the main backup.\n")

    # Iterate over the channels
    for channel in cat.channels:
        compare_channel(channel, main_backup, main_cat)

"""
compare_update()

    Compares main backup with the update backup, checking for new or modified categories, channels, and threads.
    Then it marks for the ones that are not accounted for as deleted.
    Runs a final check for repeated IDs and positions.

    Args:
        backup_update (ServerBackup): The update backup to compare.

"""
def compare_update(backup_update:ServerBackup):
    
    t.log("info", "\nChecking if the update's structure matches the main backup...\n")

    # Load the main backup info
    main_backup = ServerBackup.from_json(c.BACKUP_INFO)


    t.log("info", "\n\tChecking if items are in the same location...\n")

    # Iterate over the categories
    for cat in backup_update.categories:
        compare_category(cat, main_backup)

    main_backup.save()

    # Look for deleted items
    detect_deleted(main_backup, backup_update)

    t.log("info", "\n\tChecking for repeated IDs and positions...\n")

    repeated_id = main_backup.repeated_id()
    if repeated_id is not None:
        raise exc.MergeError(f"The update file has a repeated ID ({repeated_id}). Please check the file.")

    repeated_position = main_backup.repeated_position()
    if repeated_position is not None:
        raise exc.MergeError(f"The update file has a repeated position in item ({repeated_position}). Please check the file.")
    
    t.log("info", "Structure verified!\n")

    return main_backup


"""
update_directory_path(cat)

    If a category's path was updated, it creates a new folder and marks the old one for deletion.

    Args:
        cat (Category): The category to update.
"""

def update_directory_path(cat:Category):
    
    old_path = None

    t.log("debug", f"Checking if category '{cat.name}' needs an update...")
    
    if cat.is_updated():           

        t.log("debug", f"\tCategory '{cat.name}' needs an update. Updating...")

        # We save the old path to clean up later
        old_path = os.path.join(c.MERGE_FOLDER, cat.path)
        target_path = os.path.join(c.MERGE_FOLDER, cat.new_path)

        # If we renamed it, we might corrupt the paths of its children.
        # So we create a new folder, and then files will be moved to it.
        if not c.DRY_RUN:
            os.makedirs(target_path, exist_ok=True)
            t.log("info", f"\tCreated new folder at '{target_path}'")
        else:
            t.log("info", f"\tDRY RUN: Would create new folder at '{target_path}'")

        cat.save_updates()

        t.log("debug", f"\t\tUpdated category '{cat.name}'\n")
    
    else:
        t.log("debug", f"\tCategory '{cat.name}' is up to date.\n")

    return old_path


"""
update_file_path(item, is_thread=False)

    If a channel or thread was updated, it tries to move the file to the new path.

    Args:
        item (Item): The item to update.
"""
def update_file_path(item):

    old_path = None

    t.log("debug", f"Checking if item '{item.name}' needs an update...")
    
    if item.is_updated(): 

        t.log("debug", f"\tItem '{item.name}' needs an update. Updating...")       

        # We save the old path to clean up later
        old_path = os.path.join(c.MERGE_FOLDER, item.path)
        target_path = os.path.join(c.MERGE_FOLDER, item.new_path)

        t.log("debug", f"\t\tOld path: '{old_path}'. Target path: '{target_path}'...")

        if os.path.exists(target_path):
            raise exc.MergeError(f"File '{target_path}' already exists in the target folder. Can't move.")

        t.log("debug", f"\t\tTarget path for item '{item.name}' is free.")

        if not c.DRY_RUN:
            # if item is thread, create folder /threads
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.move(old_path, target_path)
            t.log("info", f"\tMoved '{old_path}' to '{target_path}'")
        else:
            t.log("info", f"\tDRY RUN: Would move {old_path} to {target_path}")

        item.save_updates()

        t.log("debug", f"\t\tUpdated item '{item.name}'\n")
    
    else:
        t.log("debug", f"\tItem '{item.name}' is up to date.\n")

    return old_path

"""
fix_paths(main_backup)

    This function iterates over the categories, channels and threads in the main backup.
    For each item, it checks if it needs an update and applies it if needed.

    At the end, it goes through the folders marked for deletion.
    If they are empty, it deletes them.

    Args:
        main_backup (ServerBackup): The main backup to update.

"""
def fix_paths(main_backup:ServerBackup):
    
    old_paths = []

    t.log("info", "\nApplying path updates to the main backup...\n")

    for cat in main_backup.categories:
        
        old_path = update_directory_path(cat)

        if old_path is not None:
            old_paths.append(old_path)

        for channel in cat.channels:
            update_file_path(channel)

            for thread in channel.threads:
                update_file_path(thread)
        
        main_backup.save()


    t.log("debug", "\nCleaning up old folders...\n")

    # Wait until the end to clean old folders
    for path in old_paths:
        
        # get all files that don't end in '_scenes.json' and aren't a folder
        files = [f for f in os.listdir(path) if (not os.path.isdir(os.path.join(path, f)) and not f.endswith("_scenes.json"))]

        # If they have no files, delete the folder (they could have files registered as deleted)
        if len(files) == 0:
            t.log("debug", f"Deleting old folder '{path}'")
            if not c.DRY_RUN:
                shutil.rmtree(path)
            else:
                t.log("info", f"DRY RUN: Would delete {path}")
        else:
            t.log("error", f"Folder '{path}' still has files in it. Not deleting.")
        


################# Main function ################

def update_paths():

    backup, is_update = load_status()

    if not is_update:
        t.log("base", "\n### There is nothing to update from. Skipping... ###\n")
        backup.finish_compare()
        return
    
    try:

        t.log("base", f"\n### Updating backup paths to match the update...  ###\n")

        start_time = time.time()
        
        main_backup = compare_update(backup)

        fix_paths(main_backup)

        t.log("info", f"\nFinished comparing the update folder with the main folder.\n")

        backup.finish_compare()

    except Exception as e:
        backup.finish_compare(success=False)
        raise exc.UpdatePathsError("Failed to upate paths:") from e
    
    finally:
        try:
            t.log("base", f"### Path updates finished --- {time.time() - start_time:.2f} seconds --- ###\n")
            
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
        update_paths()

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")
    

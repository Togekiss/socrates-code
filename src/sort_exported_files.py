import os
import re
import tricks as t
import exceptions as exc
t.set_path()
from res import constants as c

################# File summary #################

"""

'export_channels' can numerate categories just fine, but not channels or threads.
This module renames the exported JSON files to reflect channel positions inside the category.

This module is meant to be run after `src/export_channels.py`. It will assume the backup folder contains the channels of backup_info.json.

Main function: sort_exported_files(base_folder)

    This script first goes through the backup folder and analyzes the current order of channels.
    It substitutes the global position index for a local (category-based) position index, and updates the backup_info.json with this new info.

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
check_base_status()

    Checks the status file, and raises exceptions if the backup is not ready to be sorted.

    Returns:
        str: The current status of the backup.

"""
def check_base_status():

    try: 
        t.log("debug", "\nChecking the status of the backup...")

        backup_info = t.load_from_json(c.BACKUP_INFO)

        t.log("debug", "  Loaded the status file\n")

        if backup_info["status"] == "running":
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        t.log("debug", f"  The current status of the backup is '{backup_info["status"]}'\n")

        if backup_info["steps"]["downloadStatus"] != "success":
            raise exc.DataNotReadyError("There is no data to sort. Ensure the backup downloaded successfully and try again.")
        
    except (exc.AlreadyRunningError, exc.DataNotReadyError) as e:
        raise e
    
    except Exception as e:
        raise exc.FileSortingError("The export status file could not be read") from e
    
    finally:
        return backup_info["status"]

"""
check_read_status()

    Checks the status file, and raises exceptions if the backup file names are not ready to be read.

    Args:
        backup_info (dict): The channel list dictionary which contains the status of the backup.

"""
def check_read_status(backup_info):

    try: 
        t.log("debug", "\n  Checking the status of the backup to read file order...")

        if backup_info["status"] == "running":
            raise exc.AlreadyRunningError("The program is still running in another process. Exiting...")
        
        if backup_info["steps"]["sortingCleanStatus"] == "failed" or backup_info["steps"]["sortingWriteStatus"] == "failed":
            raise exc.DataNotReadyError("Filenames may have been partially cleaned of position numbers. Exiting...")

        if backup_info["steps"]["sortingCleanStatus"] == "success" and backup_info["steps"]["sortingWriteStatus"] != "success":
            raise exc.AlreadyRunningError("Filenames have been cleaned of position numbers. Skipping...")
        
    except (exc.AlreadyRunningError, exc.DataNotReadyError) as e:
        raise e
    
    except Exception as e:
        raise exc.FileSortingError("The export status file could not be read") from e


"""
check_clean_status()

    Checks the status file, and raises exceptions if the backup file names are not ready to be cleaned.

    Args:
        backup_info (dict): The channel list dictionary which contains the status of the backup.

"""
def check_clean_status(backup_info):

    try: 
        t.log("debug", "\n  Checking the status of the backup to clean file order...")

        if backup_info["status"] == "running":
            raise exc.AlreadyRunningError("The program is still running in another process. Exiting...")
        
        if backup_info["steps"]["sortingReadStatus"] != "success":
            raise exc.DataNotReadyError("Filenames were not read correctly. Ensure the reading process completed successfully and try again.")

        if backup_info["steps"]["sortingCleanStatus"] == "success" and backup_info["steps"]["sortingWriteStatus"] != "success":
            raise exc.AlreadyRunningError("Filenames have been cleaned of position numbers. Skipping...")
        
    except (exc.AlreadyRunningError, exc.DataNotReadyError) as e:
        raise e
    
    except Exception as e:
        raise exc.FileSortingError("The export status file could not be read") from e

"""
check_write_status()

    Checks the status file, and raises exceptions if the backup file names are not ready to be written.

    Args:
        backup_info (dict): The channel list dictionary which contains the status of the backup.

"""
def check_write_status(backup_info):

    try: 
        t.log("debug", "\n  Checking the status of the backup to write file order...")

        if backup_info["status"] == "running":
            raise exc.AlreadyRunningError("The program is still running in another process. Exiting...")
        
        if backup_info["steps"]["sortingCleanStatus"] != "success":
            raise exc.DataNotReadyError("Filenames were not cleaned correctly. Ensure the cleaning process ran and try again.")

        if backup_info["steps"]["sortingCleanStatus"] == "success" and backup_info["steps"]["sortingWriteStatus"] != "pending":
            raise exc.DataNotReadyError("Filenames have already been numbered. Clean them again if you want to re-do it.")


    except (exc.AlreadyRunningError, exc.DataNotReadyError) as e:
        raise e
    
    except Exception as e:
        raise exc.FileSortingError("The export status file could not be read") from e



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

    # remove the position tag if it has it
    try:
        target = target_name.split("# ")[1]
    except IndexError:
        target = target_name

    normalized_target = super_normalize(target)

    for filename in os.listdir(folder):
        if filename.endswith(".json") and not filename.endswith("scenes.json"):
            
            file_name = os.path.splitext(filename)[0]
            try:
                file = file_name.split("# ")[1]
            except IndexError:
                file = file_name

            if super_normalize(file) == normalized_target:
                return filename  # Return actual filename with full characters
            
    return None

"""
get_file_dictionary(folder)

    Gets all filenames in the specified folder, sorts them, and returns them as a dictionary.

    Args:
        folder (str): The folder to search in.

    Returns:
        dict: A dictionary of file names and their position numbers.

"""
def get_file_dictionary(folder):

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

    # print the sorted dictionary to the log
    for key, value in sorted_dict.items():
        t.log("log", f"\t  {key}: {value}")

    return sorted_dict

"""
sort_threads_in_channel(threads, search_folder=None)

    In DCE, threads can only be sorted by alphabetical order.
    This method opens thread files to get their date of creation, 
    and sorts them by channel and then by date.

    Args:
        threads (list): The list of threads to be sorted.
        search_folder (str, optional): The folder to search in.

"""
def sort_threads_in_channel(threads, search_folder=c.SEARCH_FOLDER):

    max = 1

    for thread in threads:

        # get the date of the first message
        file_path = os.path.join(search_folder, thread["path"])
        data = t.load_from_json(file_path)
        thread["date"] = data["messages"][0]["timestamp"]

        # get the largest value of "position" in the list
        if thread["position"] > max:
            max = thread["position"]

    # sort the list by position, then by timestamp
    threads.sort(key=lambda x: (x["position"], x["date"]))

    # for each position (associated with a channel), assing thread positions
    for i in range(1, max+1):

        threadPos = 1
        
        # find the first thread with position i
        for thread in threads:
            if thread["position"] == i:
                thread["threadPosition"] = threadPos
                threadPos += 1

                #remove date
                thread.pop("date")

"""
read_order_in_category(category, search_folder, backup_info)    

    In a category folder, it goes through the channel filenames and writes down the actual position numbers.
    If this is executed right after `export_channels`, the numbers should be the global position index.
    Then, it replaces those numbers by a localized index for each category, maintaining the order of channels.

    To finish, it reorders the threads in each channel, and assigns them a thread position.

    Args:
        category (dict): The category dictionary which contains the status of the backup.
        search_folder (str): The folder to search in.
        backup_info (dict): The channel list dictionary which contains the status of the backup.

"""
def read_order_in_category(category, search_folder, backup_info):
    
    folder_name = category["category"].replace(":", "_")
    folder = os.path.join(search_folder, f"{category['position']}# {folder_name}")
    t.save_to_json(backup_info, c.BACKUP_INFO)
        
    t.log("debug", f"\n\t  Analyzing current order in {folder}... ###")

    # get the filenames and sort them
    sorted_dict = get_file_dictionary(folder)

    t.log("debug", f"\n\t  Sorted the dictionary of files in {folder}\n")
    
    for channel in category["channels"]:
        channel["position"] = sorted_dict[super_normalize(channel["channel"])]
        channel["path"] = f"{category['position']}# {folder_name}\\{find_channel_file(folder, channel["channel"])}"
        t.log("log", f"\tFound channel: {channel['position']}# {channel['channel']}")
    
    # sort channels by position
    category["channels"] = sorted(category["channels"], key=lambda x: x["position"])

    for thread in category.get("threads", []):
        thread["position"] = sorted_dict[super_normalize(thread["channel"])]
        thread["path"] = f"{category['position']}# {folder_name}\\Threads\\{find_channel_file(folder+"/Threads", thread["thread"])}"
        t.log("log", f"\tFound thread: {thread['position']}-{thread['threadPosition']}# {thread['thread']}")

    sort_threads_in_channel(category.get("threads", []), search_folder)

    # sort threads by position then threadPosition
    category["threads"] = sorted(category["threads"], key=lambda x: (x["position"], x["threadPosition"]))

    t.save_to_json(backup_info, c.BACKUP_INFO)

"""
read_order_from_files(search_folder, main_status)

    Analyzes the current order of channel files in the specified folder.
    
    Reads the order of the files in each category folder, and assigns them a position.

    The backup_info structure is updated to reflect the new positions.

    Args:
        search_folder (str): The folder to search in.
        main_status (str): The main status of the backup.

"""
def read_order_from_files(search_folder, main_status):

    t.log("info", f"\n\tReading the current file order in {search_folder}...\n")

    try:
        backup_info = t.load_from_json(c.BACKUP_INFO)

        check_read_status(backup_info)

    # If "clean" has already been run, there will be nothing to read,  so we can skip
    except exc.AlreadyRunningError as e:
        t.log("debug", f"\t  {e}\n")
        return
    
    try:

        # flag it as running in case another execution of the script is launched
        backup_info["status"] = "running"
        backup_info["steps"]["sortingReadStatus"] = "running"
        t.save_to_json(backup_info, c.BACKUP_INFO)

        # For each category in the channel list
        for category in backup_info["categories"]:

            read_order_in_category(category, search_folder, backup_info)

        backup_info["steps"]["sortingReadStatus"] = "success"
        backup_info["steps"]["sortingCleanStatus"] = "pending"
        backup_info["status"] = main_status
    
    except Exception as e:
        backup_info["status"] = "failed"
        backup_info["steps"]["sortingReadStatus"] = "failed"
        
        raise exc.FileSortingReadError(f"An error occurred while reading the current order in {search_folder}") from e

    finally:
        try:
            t.log("info", "\n\tFinished analyzing current order\n")
            t.save_to_json(backup_info, c.BACKUP_INFO)

        except Exception as e:
            t.log("error", f"\tFailed to save the list of channels: {e}\n")

"""
remove_order_from_files(search_folder)

    Removes the position number from the filenames of the channel files in the specified folder.

    Args:
        search_folder (str): The folder to search in.

"""
def remove_order_from_files(search_folder):

    # function to clean the filenames
    def clean_filename(item):
        # separate path from filename
        folder, filename = os.path.split(item["path"])

        t.log("log", f"\t  Cleaning {filename}...")

        root = os.path.join(search_folder, folder)

        # remove 'number#' from the filename
        new_filename = filename.split("# ")[1]
        src = os.path.join(root, filename)
        dst = os.path.join(root, new_filename)
        os.rename(src, dst)
        item["path"] = os.path.join(folder, new_filename)

    t.log("info", f"\n\tCleaning up position numbers in the filenames of {search_folder}...\n")
    
    try:
        backup_info = t.load_from_json(c.BACKUP_INFO)

        check_clean_status(backup_info)

    # If "clean" has already been run, there will be nothing to clean, so we can skip
    except exc.AlreadyRunningError as e:
        t.log("debug", f"\t  {e}\n")
        return
    
    try:
        # flag it as running in case another execution of the script is launched
        backup_info["status"] = "running"
        backup_info["steps"]["sortingCleanStatus"] = "running"
        t.save_to_json(backup_info, c.BACKUP_INFO)

        # Iterate over all categories
        for category in backup_info["categories"]:

            for channel in category["channels"]:
                clean_filename(channel)
            
            for thread in category["threads"]:
                clean_filename(thread)
            
            t.save_to_json(backup_info, c.BACKUP_INFO)
   

        backup_info["status"] = "pending"
        backup_info["steps"]["sortingCleanStatus"] = "success"
        backup_info["steps"]["sortingWriteStatus"] = "pending"
    
    except Exception as e:
        backup_info["status"] = "failed"
        backup_info["steps"]["sortingCleanStatus"] = "failed"
        backup_info["steps"]["sortingWriteStatus"] = "pending"
        
        raise exc.FileSortingCleanError(f"An error occurred while cleaning the current order in {search_folder}") from e

    finally:
        try:
            t.log("info", f"\n\tFinished cleaning up position numbers from channel files\n")
            t.save_to_json(backup_info, c.BACKUP_INFO)

        except Exception as e:
            t.log("error", f"\tFailed to save the status file: {e}\n")

"""
write_order_to_files(search_folder, main_status)

    Writes the position number to the filenames of the channel files in the specified folder.

    Args:
        search_folder (str): The folder to search in.
        main_status (str): The main status of the program.

"""

def write_order_to_files(search_folder, main_status):

    # function to write into channels
    def rename_file(item):

         # separate path from filename
        folder, filename = os.path.split(item["path"])

        root = os.path.join(search_folder, folder)

        # add 'number#' from the filename
        # if item has ["threadPosition"] is a thread
        if "threadPosition" in item:
            new_filename = f"{item["position"]}-{item['threadPosition']}# {filename}"
        else:
            new_filename = f"{item["position"]}# {filename}"

        src = os.path.join(root, filename)
        dst = os.path.join(root, new_filename)
        os.rename(src, dst)
        item["path"] = os.path.join(folder, new_filename)

        t.log("log", f"\tRenamed file: {filename} → {new_filename}")



    t.log("info", f"\n\tWriting channel order to files in {search_folder}...\n")

    try:
        backup_info = t.load_from_json(c.BACKUP_INFO)

        check_write_status(backup_info)

    # If "write" has already been run, there will be nothing to write, so we can skip
    except exc.AlreadyRunningError as e:
        t.log("debug", f"\t  {e}\n")
        return
    
    try:
        # flag it as running in case another execution of the script is launched
        backup_info["status"] = "running"
        backup_info["steps"]["sortingWriteStatus"] = "running"
        t.save_to_json(backup_info, c.BACKUP_INFO)

        # For each category in the channel list
        for category in backup_info["categories"]:

            t.log("info", f"\n  Sorting '{category["category"]}'...")

            t.log("info", f"    Renaming {category["numberOfChannels"]} channel files...")

            # Rename channel files
            for channel in category["channels"]:

                rename_file(channel)

            t.log("info", f"    Renaming {category['numberOfThreads']} thread files...")

            for thread in category.get("threads", []):

                rename_file(thread)
            
            t.save_to_json(backup_info, c.BACKUP_INFO)


        backup_info["steps"]["sortingWriteStatus"] = "success"
        backup_info["status"] = main_status
    
    except Exception as e:
        backup_info["status"] = "failed"
        backup_info["steps"]["sortingWriteStatus"] = "failed"
        
        raise exc.FileSortingWriteError(f"An error occurred while reading the current order in {search_folder}") from e

    finally:
        try:
            t.log("info", "\n\tFinished writing channel order to files\n")
            t.save_to_json(backup_info, c.BACKUP_INFO)

        except Exception as e:
            t.log("error", f"\tFailed to save the status file: {e}\n")


################# Main function #################

def sort_exported_files(base_folder=c.SEARCH_FOLDER):

    t.log("base", f"\n###  Sorting channel files in {base_folder}...  ###\n")

    try:

        main_status = check_base_status()

        read_order_from_files(base_folder, main_status)

        remove_order_from_files(base_folder)

        write_order_to_files(base_folder, main_status)
    
    except Exception as e:
        raise exc.FileSortingError(f"An error occurred while sorting channel files in {base_folder}:") from e

    finally:
        t.log("base", f"### Finished sorting files ###\n")


if __name__ == "__main__":

    try:
        sort_exported_files(c.SEARCH_FOLDER)

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")

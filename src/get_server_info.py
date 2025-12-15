import time
import os
from datetime import datetime
import tricks as t
import exceptions as exc
t.set_path()
from res import constants as c
from res import tokens

############### File summary #################

"""

This module gets or updates the list of channels from the server.

Main function: get_server_info()

    This function calls the DiscordChatExporter CLI tool to get the list of all the server's channels.
    It processes the output and saves it as a JSON.

    Then it reads the list of categories to ignore from the config file,
    and removes the entries from the JSON data that have matching categories.

    Finally, the function saves the data to a JSON file.

    The function does not return any value, but it saves the data to the specified JSON file.

"""

############### Functions #################
"""
check_base_status()

    Checks the status file, and raises exceptions if the backup is not ready to start.

"""
def check_base_status():

    try: 
        t.log("debug", "\nChecking the status of the backup...")

        #check if a SERVER_NAME/INFO folder exists, if not, create it
        if not os.path.exists(c.INFO_FOLDER):
            os.makedirs(c.INFO_FOLDER, exist_ok=True)

        backup_info = t.load_from_json(c.BACKUP_INFO)

        t.log("debug", "  Loaded the status file\n")

        if backup_info["status"] == "running":
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        t.log("debug", f"  The current status of the backup is '{backup_info["status"]}'\n")

    except exc.AlreadyRunningError as e:
        raise e
     
    except FileNotFoundError:
        t.log("debug", '  No backup info file was found. Creating a new one....\n')
        
        backup_info = {
            "status": "pending",
            "steps": {
                "getInfoStatus": "pending",
                "cleanInfoStatus": "pending",
                "downloadStatus": "pending",
                "sortingReadStatus": "pending",
                "sortingCleanStatus": "pending",
                "sortingWriteStatus": "pending",
                "idAssignStatus": "pending",
                "mergeStatus": "pending",
                "messageFixStatus": "pending"
            }
        }

        t.save_to_json(backup_info, c.BACKUP_INFO)

    except Exception as e:
        raise exc.GetChannelListError("The backup process could not start") from e

"""
load_last_update()

    Loads the previous list of channels from a JSON file.
    If there is no previous list of channels, returns None.

    Args:
        None

    Returns:
        tuple: A tuple containing the previous update timestamp and the previous export timestamp.

"""
def has_previous_export():

    t.log("debug", "\t\nLoading the info of the last update...")

    # Load the JSON file
    backup_info = t.load_from_json(c.BACKUP_INFO)

    t.log("debug", "\t  Loaded the status file\n")

    base_status = backup_info["status"]

    # if there's already a completed export
    if backup_info.get("updatedAt") is not None and backup_info["steps"]["downloadStatus"] == "success":

        # Disabled now that i'm testing the code in pieces to not block myself all the time
        # TODO backup_info["status"] = "running"
        backup_info["steps"]["updateStatus"] = "running"
        t.save_to_json(backup_info, c.BACKUP_INFO)

        return True, base_status

    # if there's no previous export
    return False, base_status




"""
parse_output(output)

    Parses the output of the DiscordChatExporter CLI tool and returns a list of channel data.

    Args:
        output (str): The output of the DiscordChatExporter CLI tool.

    Returns:
        dict: A list of channel data in JSON format.
"""
def parse_output(output):

    t.log("info", "\tParsing the list of channels...")

    categories = []

    category_names = []

    lines = []
    
    try:
        lines = output.strip().split("\n")

        # Saving the 'parent channel' in case we encounter threads  
        parent_channel = None
        thread_counter = 0

        for line in lines:

            t.log("debug", f"\t\t Analyzing line: {line}")

            parts = line.split(" | ")

            # If it's a category
            if len(parts) < 2:
                t.log("debug", "\t\t\t It's a category")

                cat_id = parts[0].split(" \\ ")[0].strip()
                cat_name = parts[0].split(" \\ ")[1].strip()

                # Add it to the list
                category_names.append(cat_name)

                # Create a new category
                new_category = {
                    "id": cat_id,
                    "category": cat_name,
                    "position": len(category_names),
                    "numberOfChannels": 0,
                    "numberOfThreads": 0,
                    "numberOfScenes": 0,
                    "path": f"{len(category_names)}# {cat_name.replace(':', '_')}",
                    "channels": [],
                    "threads": []
                }

                # Add it to the data
                categories.append(new_category)
                thread_counter = 0

                continue
            
            # If it's a channel
            if len(parts) == 2:

                t.log("debug", "\t\t\t It's a channel")

                entry = {
                    "id": parts[0].strip(),
                    "category": parts[1].split(" / ")[0].strip(),
                    "channel": parts[1].split(" / ")[1].strip(),
                    "isThread": False,
                    "thread": "",
                }
                # save it as a reference
                parent_channel = entry
                thread_counter = 0
            
            # If it's a thread
            if len(parts) == 3:

                t.log("debug", "\t\t\t It's a thread")

                entry = {
                    "id": parts[0].replace('*', '').strip(),
                    "category": parent_channel["category"],
                    "channel": parent_channel["channel"],
                    "isThread": True,
                    "thread": parts[1].split(" / ")[1].strip(),
                }
                thread_counter += 1

            # this should not trigger if --include-categories is used, but we can leave it for compatibility
            if entry["category"] not in category_names:

                t.log("debug", f"\t\t\t It's a new category: {entry['category']}")

                # Save it in the list
                category_names.append(entry["category"])

                # Create a new category
                new_category = {
                    "category": entry["category"],
                    "position": len(category_names),
                    "numberOfChannels": 0,
                    "numberOfThreads": 0,
                    "numberOfScenes": 0,
                    "path": f"{len(category_names)}# {entry['category'].replace(':', '_')}",
                    "channels": [],
                    "threads": []
                }

                # Add it to the data
                categories.append(new_category)

            # create the base for the new channel
            new_channel = {
                "id": entry["id"],
                "channel": entry["channel"]
            }

            # add extra info if it's a thread
            if entry["isThread"]:
                new_channel["position"] = categories[-1]["numberOfChannels"]
                new_channel["thread"] = entry["thread"]
                new_channel["threadPosition"] = thread_counter
                new_channel["numberOfMessages"] = 0
                
                categories[-1]["numberOfThreads"] += 1
                categories[-1]["threads"].append(new_channel)
            
            else:
                categories[-1]["numberOfChannels"] += 1
                new_channel["position"] = categories[-1]["numberOfChannels"]
                new_channel["numberOfScenes"] = 0
                new_channel["numberOfMessages"] = 0

                
                categories[-1]["channels"].append(new_channel)

        t.log("info", f"\tFound {len(lines)} channels in {len(categories)} categories\n")
    
    except Exception as e:
        raise exc.GetChannelListError("Failed to parse the list of channels") from e
    
    finally:
        return categories, len(lines)

"""
get_server_info_from_discord()

    Gets a list of channels from Discord using the DiscordChatExporter CLI tool,
    then parses the output into a JSON format.

    Returns:
        dict: A list of channel data in JSON format.

"""
def get_server_info_from_discord(info_file):

    try: 
        t.log("base", "  #  This may take a few minutes...  #\n")

        t.log("info", "\tGetting a list of channels from Discord...")

        # Call the CLI command and capture its output
        cli_command = f"dotnet DCE/DiscordChatExporter.Cli.dll channels -g {c.SERVER_ID} -t {tokens.DISCORD_BOT} --include-threads all --include-categories --relative-positions"
        code, output = t.run_command(cli_command)

        if code != 0:
            raise exc.ConsoleCommandError("DCE command failed")

        t.log("info", f"\tGot a list of channels from DCE: {code}\n")

        # Process the output and create the desired JSON format
        categories, channel_num = parse_output(output)

        backup_info = t.load_from_json(info_file)

        backup_info["numberOfCategories"] = len(categories)
        backup_info["numberOfChannels"] = channel_num
        backup_info["categories"] = categories

        backup_info["steps"]["getInfoStatus"] = "success"

        t.save_to_json(backup_info, info_file)

    except Exception as e:
        raise exc.GetChannelListError("Failed to get the list of channels") from e

        


def prepare_info_file(info_file):

    t.log("info", "\tPreparing the info file...")

    backup_info = {
            "id": c.SERVER_ID,
            "name": c.SERVER_NAME,
            "updatedAt": datetime.now().astimezone().isoformat(sep='T', timespec='microseconds'),
            "exportedAt": "",
            "status": "running",
            "steps": {
                "getInfoStatus": "running",
                "cleanInfoStatus": "pending",
                "downloadStatus": "pending",
                "sortingReadStatus": "pending",
                "sortingCleanStatus": "pending",
                "sortingWriteStatus": "pending",
                "idAssignStatus": "pending",
                "mergeStatus": "pending",
                "messageFixStatus": "pending"
            }
        }
    
    t.save_to_json(backup_info, info_file)

    return backup_info

"""
remove_categories(json_data), keep_categories(json_data)
    Functions to clean up the channel list.
"""
def remove_categories(json_data):
    return [entry for entry in json_data if entry["category"] not in c.CATEGORIES_TO_IGNORE]
    
def keep_categories(json_data):
    return [entry for entry in json_data if entry["category"] in c.CATEGORIES_TO_KEEP]


"""
clean_channel_list(backup_info)

    Cleans up the channel list by removing categories and updating the number of channels.

    Returns:
        dict: A cleaned up list of channel data in JSON format.
"""
def clean_channel_list(info_file):

    t.log("info", "\tCleaning the list of channels...")

    try:

        backup_info = t.load_from_json(info_file)

        backup_info["steps"]["cleanInfoStatus"] = "running"
        t.save_to_json(backup_info, info_file)

        if c.KEEP_MODE:
            backup_info["categories"] = keep_categories(backup_info["categories"])
        else:
            backup_info["categories"] = remove_categories(backup_info["categories"])

        t.log("info", f"\t  Cleaned up categories")

        # Update the number of channels
        backup_info["numberOfChannels"] = 0

        for category in backup_info["categories"]:
            category["numberOfChannels"] = len(category["channels"])
            category["numberOfThreads"] = len(category["threads"])
            backup_info["numberOfChannels"] += len(category["channels"]) + len(category["threads"])
        backup_info["numberOfCategories"] = len(backup_info["categories"])
            
        t.log("info", f"\t  Kept {backup_info['numberOfChannels']} channels across {len(backup_info['categories'])} categories\n")

        backup_info["steps"]["cleanInfoStatus"] = "success"
        t.save_to_json(backup_info, info_file)

    except Exception as e:
        raise exc.CleanChannelListError("Failed to clean the list of channels") from e


################# Main function #################


def get_server_info():

    t.log("base", f"\n###  Getting a list of all channels from the server {c.SERVER_NAME}...  ###\n")
    
    main_status = "pending"
    info_status = "pending"
    clean_status = "pending"
    is_update = False
    
    check_base_status()

    try:

        start_time = time.time()

        is_update, base_status = has_previous_export()
        info_file = c.BACKUP_INFO_UPDATE if is_update else c.BACKUP_INFO

        prepare_info_file(info_file)

        get_server_info_from_discord(info_file)

        info_status = "success"

        clean_channel_list(info_file)

        clean_status = "success"
        main_status = "pending"

    except exc.CleanChannelListError as e:

        clean_status = "failed"
        main_status = "failed"

        raise exc.ChannelListError from e
    
    except Exception as e:

        info_status = "failed"
        clean_status = "pending"
        main_status = "failed"

        raise exc.ChannelListError from e

    finally:
        try:
            backup_info = t.load_from_json(info_file)
            
            backup_info["status"] = main_status
            backup_info["steps"]["getInfoStatus"] = info_status
            backup_info["steps"]["cleanInfoStatus"] = clean_status

            t.save_to_json(backup_info, info_file)
            t.log("info", f"\t\nSaved the new list of channels to {info_file}\n")

            if is_update and main_status == "failed":
                base_info = t.load_from_json(c.BACKUP_INFO)
                base_info["status"] = base_status
                base_info["steps"]["updateStatus"] = main_status
                t.save_to_json(base_info, c.BACKUP_INFO)
            
        except Exception as e:
            t.log("error", f"\tFailed to save the list of channels: {e}\n")

        t.log("base", f"\n### Channel list finished --- {time.time() - start_time:.2f} seconds --- ###\n")

        return is_update


if __name__ == "__main__":

    try:
        get_server_info()

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")

    

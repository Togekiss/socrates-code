import time
from datetime import datetime
import tricks as t
import exceptions as exc
t.set_path()
from res import constants as c
from res import tokens

############### File summary #################

"""

This module gets or updates the list of channels from the server.

Main function: get_channel_list()

    This function calls the DiscordChatExporter CLI tool to get the list of all the server's channels.
    It processes the output and saves it as a JSON.

    Then it reads the list of categories to ignore from the config file,
    and removes the entries from the JSON data that have matching categories.

    Finally, the function saves the data to a JSON file.

    The function does not return any value, but it saves the data to the specified JSON file.

"""

############### Functions #################

"""
load_last_update()

    Loads the previous list of channels from a JSON file.
    If there is no previous list of channels, returns None.

    Args:
        None

    Returns:
        tuple: A tuple containing the previous update timestamp and the previous export timestamp.

"""
def load_last_update():

    try:
        t.log("debug", "\t\nChecking the status of the backup...")

        # Load the JSON file
        last_channel_list = t.load_from_json(c.BACKUP_INFO)

        t.log("debug", "\t  Loaded the status file\n")

        if last_channel_list["status"] == "running":
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        t.log("debug", f"\t  The current status of the backup is '{last_channel_list['status']}'\n")

        last_update = last_channel_list["dates"]["updatedAt"]
        last_export = last_channel_list["dates"]["exportedAt"]

        t.log("debug", f"\t  The last update was downloaded at {last_update}")

        # If the update failed, use the previous update
        if last_channel_list["steps"]["updateStatus"] == "failed" or last_channel_list["steps"]["updateCleanStatus"] == "failed":
            t.log("debug", "\t  The previous update failed. Will use the last good update\n")
            last_update = last_channel_list["dates"]["lastGoodUpdate"]

        # flag it as running in case another execution of the script is launched
        last_channel_list["status"] = "running"
        last_channel_list["steps"]["updateStatus"] = "running"
        t.save_to_json(last_channel_list, c.BACKUP_INFO)

        return last_update, last_export

    except exc.AlreadyRunningError as e:
        raise e
    
    except OSError as e:
        t.log("debug", f"\tNo status file could be loaded: {e}\n")
        return None, None
    
    except Exception as e:
        t.log("debug", f"\tThe status file could not be read: {e}\n")
        raise e

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

    # Base object
    backup_data = {
        "id": c.SERVER_ID,
        "name": c.SERVER_NAME,
        "dates": "",
        "status": "",
        "steps": "",
        "numberOfCategories": 0,
        "numberOfChannels": 0, 
        "numberOfScenes": 0,
        "categories": []
    }

    category_list = []
    
    try:
        lines = output.strip().split("\n")

        # Saving the 'parent channel' in case we encounter threads  
        parent_channel = None
        for line in lines:

            t.log("debug", f"\t\t Analyzing line: {line}")

            parts = line.split(" | ")
            
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

            # If we encountered a new category
            if entry["category"] not in category_list:

                t.log("debug", f"\t\t\t It's a new category: {entry['category']}")

                # Save it in the list
                category_list.append(entry["category"])

                # Create a new category
                category_data = {
                    "category": entry["category"],
                    "position": len(category_list) + 1,
                    "numberOfChannels": 0,
                    "numberOfThreads": 0,
                    "numberOfScenes": 0,
                    "channels": [],
                    "threads": []
                }

                # Add it to the data
                backup_data["categories"].append(category_data)

            channel_data = {
                "id": entry["id"],
                "channel": entry["channel"],
                "position": len(backup_data["categories"][category_list.index(entry["category"])]["channels"]) + 1,
            }

            # Add the channel to the category
            if entry["isThread"]:
                channel_data["thread"] = entry["thread"]

                # calculate "threadPosition" based on how many threads in the category have the same channel
                thread_position = 1
                for thread in backup_data["categories"][category_list.index(entry["category"])]["threads"]:
                    if thread["channel"] == entry["channel"]:
                        thread_position += 1
                channel_data["threadPosition"] = thread_position
                channel_data["numberOfMessages"] = 0
                
                backup_data["categories"][category_list.index(entry["category"])]["threads"].append(channel_data)
            
            else:
                channel_data["numberOfScenes"] = 0
                channel_data["numberOfMessages"] = 0
                backup_data["categories"][category_list.index(entry["category"])]["channels"].append(channel_data)
            backup_data["numberOfChannels"] += 1

        t.log("info", f"\tFound {backup_data['numberOfChannels']} channels in {len(backup_data['categories'])} categories\n")
        
        return backup_data
    
    except Exception as e:
        raise exc.GetChannelListError("Failed to parse the list of channels") from e
    
"""
get_channel_list_from_discord()

    Gets a list of channels from Discord using the DiscordChatExporter CLI tool,
    then parses the output into a JSON format.

    Returns:
        dict: A list of channel data in JSON format.

"""
def get_channel_list_from_discord():

    t.log("base", "  #  This may take a few minutes...  #\n")

    t.log("info", "\tGetting a list of channels from Discord...")

    # Call the CLI command and capture its output
    cli_command = f"dotnet DCE/DiscordChatExporter.Cli.dll channels -g {c.SERVER_ID} -t {tokens.DISCORD_BOT} --include-threads all"
    code, output = t.run_command(cli_command)

    if code != 0:
        raise exc.ConsoleCommandError("DCE command failed")

    t.log("info", f"\tGot a list of channels from DCE: {code}\n")

    # Process the output and create the desired JSON format
    backup_info = parse_output(output)

    return backup_info

"""
remove_categories(json_data, categories_to_remove), keep_categories(json_data, categories_to_keep)
    Functions to clean up the channel list.
"""
def remove_categories(json_data, categories_to_remove):
    return [entry for entry in json_data if entry["category"] not in categories_to_remove]
    

def keep_categories(json_data, categories_to_keep):
    return [entry for entry in json_data if entry["category"] in categories_to_keep]


"""
clean_channel_list(backup_info)

    Cleans up the channel list by removing categories and updating the number of channels.

    Returns:
        dict: A cleaned up list of channel data in JSON format.
"""
def clean_channel_list(backup_info):

    t.log("info", "\tCleaning the list of channels...")

    try: 
        backup_info["categories"] = remove_categories(backup_info["categories"], c.CATEGORIES_TO_IGNORE)

        t.log("info", f"\t  Removed {len(c.CATEGORIES_TO_IGNORE)} categories")

        # Update the number of channels
        backup_info["numberOfChannels"] = 0
        for category in backup_info["categories"]:
            category["numberOfChannels"] = len(category["channels"])
            category["numberOfThreads"] = len(category["threads"])
            backup_info["numberOfChannels"] += len(category["channels"]) + len(category["threads"])
        backup_info["numberOfCategories"] = len(backup_info["categories"])
            
        t.log("info", f"\t  Kept {backup_info['numberOfChannels']} channels across {len(backup_info['categories'])} categories\n")

        return backup_info

    except Exception as e:
        raise exc.CleanChannelListError("Failed to clean the list of channels") from e


################# Main function #################


def get_channel_list():

    t.log("base", f"\n###  Getting a list of all channels from the server {c.SERVER_NAME}...  ###\n")

    last_update, last_export = load_last_update()

    try:

        start_time = time.time()

        update_history = {
            "updatedAt": datetime.now().astimezone().isoformat(sep='T', timespec='microseconds'),
            "exportedAt": last_export,
            "lastGoodUpdate": last_update,
            "lastGoodExport": last_export
        }

        main_status = "running"

        update_status = {
            "updateStatus": "running",
            "updateCleanStatus": "pending",
            "downloadStatus": "pending",
            "sortingReadStatus": "pending",
            "sortingCleanStatus": "pending",
            "sortingWriteStatus": "pending",
            "mergeStatus": "pending",
            "idAssignStatus": "pending",
            "messageFixStatus": "pending"
        }

        backup_info = get_channel_list_from_discord()

        update_status["updateStatus"] = "success"
        update_status["updateCleanStatus"] = "running"

        backup_info = clean_channel_list(backup_info)

        update_status["updateCleanStatus"] = "success"
        main_status = "pending"
        update_history["lastGoodUpdate"] = datetime.now().astimezone().isoformat(sep='T', timespec='microseconds')

    except exc.CleanChannelListError as e:

        update_status["updateCleanStatus"] = "failed"
        main_status = "failed"

        raise exc.ChannelListError from e
    
    except Exception as e:

        update_status["updateStatus"] = "failed"
        update_status["updateCleanStatus"] = "pending"
        main_status = "failed"

        if last_update is not None:
            backup_info = t.load_from_json(c.BACKUP_INFO)
        else:
            backup_info = {}         

        raise exc.ChannelListError from e


    finally:
        try:
            backup_info["status"] = main_status
            backup_info["steps"] = update_status
            backup_info["dates"] = update_history
            t.save_to_json(backup_info, c.BACKUP_INFO)
            t.log("info", f"\t\nSaved the list of channels to {c.BACKUP_INFO}\n")
            
        except Exception as e:
            t.log("error", f"\tFailed to save the list of channels: {e}\n")

        t.log("base", f"\n### Channel list finished --- {time.time() - start_time:.2f} seconds --- ###\n")


if __name__ == "__main__":

    try:
        get_channel_list()

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")

    

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
load_previous_update()

    Loads the previous list of channels from a JSON file.
    If there is no previous list of channels, returns None.

    Args:
        None

    Returns:
        tuple: A tuple containing the previous update timestamp and the previous export timestamp.

"""
def load_previous_update():

    try:
        t.log("debug", "\tLoading a previous list of channels...")

        # Load the JSON file
        previous_channel_list = t.load_from_json(c.CHANNEL_LIST)

        t.log("debug", "\tLoaded a previous list of channels\n")
        if previous_channel_list["status"]["updateStatus"] == "failed":
            previous_update = previous_channel_list["status"]["previousUpdate"]

        previous_update = previous_channel_list["updatedAt"]
        previous_export = previous_channel_list["exportedAt"]

        return previous_update, previous_export

    except OSError:
        t.log("debug", "\tNo previous list of channels file could be loaded\n")
        return None, None
    
    except Exception :
        t.log("debug", "\tThe previous list of channels could not be read\n")
        return None, None

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

    # Timestamp
    updated_at = datetime.now().astimezone().isoformat(sep='T', timespec='microseconds')

    # Base object
    backup_data = {
        "id": c.SERVER_ID,
        "name": c.SERVER_NAME,
        "updatedAt": updated_at,
        "numberOfChannels": 0,
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
                    "channels": [],
                    "threads": []
                }

                # Add it to the data
                backup_data["categories"].append(category_data)

            channel_data = {
                "id": entry["id"],
                "channel": entry["channel"],
                "position": len(backup_data["categories"][category_list.index(entry["category"])]["channels"]) + 1
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
                
                backup_data["categories"][category_list.index(entry["category"])]["threads"].append(channel_data)
            
            else:
                backup_data["categories"][category_list.index(entry["category"])]["channels"].append(channel_data)
            backup_data["numberOfChannels"] += 1

        t.log("info", f"\tFound {backup_data['numberOfChannels']} channels in {len(backup_data['categories'])} categories\n")
        
        return backup_data
    
    except Exception as e:
        raise exc.ChannelListGetException("Failed to parse the list of channels") from e
    
"""
get_channel_list_from_discord()

    Gets a list of channels from Discord using the DiscordChatExporter CLI tool,
    then parses the output into a JSON format.

    Returns:
        dict: A list of channel data in JSON format.

"""
def get_channel_list_from_discord():

    t.log("info", "\tGetting a list of channels from Discord...")

    # Call the CLI command and capture its output
    cli_command = f"dotnet DCE/DiscordChatExporter.Cli.dll channels -g {c.SERVER_ID} -t {tokens.DISCORD_BOT} --include-threads all"
    code, output = t.run_command(cli_command)

    if code != 0:
        raise exc.ConsoleCommandException("DCE command failed")

    t.log("info", f"\tGot a list of channels from DCE: {code}\n")

    # Process the output and create the desired JSON format
    channel_list = parse_output(output)

    return channel_list

"""
remove_categories(json_data, categories_to_remove), keep_categories(json_data, categories_to_keep)
    Functions to clean up the channel list.
"""
def remove_categories(json_data, categories_to_remove):
    return [entry for entry in json_data if entry["category"] not in categories_to_remove]
    

def keep_categories(json_data, categories_to_keep):
    return [entry for entry in json_data if entry["category"] in categories_to_keep]


"""
clean_channel_list(channel_list)

    Cleans up the channel list by removing categories and updating the number of channels.

    Returns:
        dict: A cleaned up list of channel data in JSON format.
"""
def clean_channel_list(channel_list):

    t.log("info", "\tCleaning the list of channels...")

    try: 
        channel_list["categories"] = remove_categories(channel_list["categories"], c.CATEGORIES_TO_IGNORE)

        t.log("info", f"\t  Removed {len(c.CATEGORIES_TO_IGNORE)} categories")

        # Update the number of channels
        channel_list["numberOfChannels"] = 0
        for category in channel_list["categories"]:
            channel_list["numberOfChannels"] += len(category["channels"]) + len(category["threads"])
            
        t.log("info", f"\t  Kept {channel_list['numberOfChannels']} channels across {len(channel_list['categories'])} categories\n")

        return channel_list

    except Exception as e:
        raise exc.ChannelListCleanException("Failed to clean the list of channels") from e


################# Main function #################


def get_channel_list():

    try:

        t.log("base", f"\n###  Getting a list of all channels from the server {c.SERVER_NAME}...  ###\n")
        t.log("base", "  #  This may take a few minutes...  #\n")

        start_time = time.time()

        previous_update, previous_export = load_previous_update()

        update_status = {
            "previousUpdate": previous_update,
            "updateStatus": "running",
            "updateCleanStatus": "pending",
            "previousExport": previous_export,
            "isPartialUpdate": False if previous_export is None else True,
            "downloadStatus": "pending",
            "sortingReadStatus": "pending",
            "sortingCleanStatus": "pending",
            "sortingWriteStatus": "pending",
            "mergeStatus": "pending",
            "idAssignStatus": "pending",
            "messageFixStatus": "pending"
        }

        channel_list = get_channel_list_from_discord()

        channel_list["exportedAt"] = previous_export
        update_status["updateStatus"] = "success"
        update_status["updateCleanStatus"] = "running"

        channel_list = clean_channel_list(channel_list)

        update_status["updateCleanStatus"] = "success"


    except exc.ChannelListCleanException as e:

        update_status["updateCleanStatus"] = "failed"   

        raise exc.ChannelListException from e
    
    except Exception as e:

        update_status["updateStatus"] = "failed"
        update_status["updateCleanStatus"] = "pending"

        if previous_update is not None:
            channel_list = t.load_from_json(c.CHANNEL_LIST)
        else:
            channel_list = {}        

        channel_list["updatedAt"] = datetime.now().astimezone().isoformat(sep='T', timespec='microseconds')   

        raise exc.ChannelListException from e


    finally:
        try:
            channel_list["status"] = update_status
            t.save_to_json(channel_list, c.CHANNEL_LIST)
            t.log("info", f"\t\nSaved the list of channels to {c.CHANNEL_LIST}\n")
            
        except Exception as e:
            t.log("error", f"\tFailed to save the list of channels: {e}\n")

        t.log("base", f"\n### Channel list finished --- {time.time() - start_time:.2f} seconds --- ###\n")


if __name__ == "__main__":

    try:
        get_channel_list()

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")

    

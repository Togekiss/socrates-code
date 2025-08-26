import time
from datetime import datetime
import tricks as t
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
parse_output(output)

    Parses the output of the DiscordChatExporter CLI tool and returns a list of channel data.

    Args:
        output (str): The output of the DiscordChatExporter CLI tool.

    Returns:
        dict: A list of channel data in JSON format.
"""

def parse_output(output, update_status):

    t.log("info", "\tParsing the list of channels...")

    # set timezone to 

    lines = output.strip().split("\n")
    updated_at = datetime.now().astimezone().isoformat(sep='T', timespec='microseconds')

    # Base object
    backup_data = {
        "id": c.SERVER_ID,
        "name": c.SERVER_NAME,
        "updatedAt": updated_at,
        "exportedAt": update_status["previousExport"],
        "status": update_status,
        "numberOfChannels": 0,
        "categories": []
    }

    category_list = []
    
    try:
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
        t.log("error", f"\tError parsing the list of channels: {e}\n")
        backup_data["status"]["updateStatus"] = "failed"
        return backup_data
    
    
"""
remove_categories(json_data, categories_to_remove), keep_categories(json_data, categories_to_keep)
    Function to clean up the channel list.
"""
def remove_categories(json_data, categories_to_remove):
    return [entry for entry in json_data if entry["category"] not in categories_to_remove]
    

def keep_categories(json_data, categories_to_keep):
    return [entry for entry in json_data if entry["category"] in categories_to_keep]


################# Main function #################


def get_channel_list():

    t.log("base", f"\n###  Getting a list of all channels from the server {c.SERVER_NAME}...  ###\n")
    t.log("base", "This may take a few minutes...\n")

    start_time = time.time()

    
    previous_update = None
    previous_export = None

    #if a previous channel list exists
    try:
        t.log("debug", "\tLoading a previous list of channels...")

        # Load the JSON file
        previous_channel_list = t.load_from_json(c.CHANNEL_LIST)

        t.log("debug", "\tLoaded a previous list of channels\n")
        if previous_channel_list["status"]["updateStatus"] == "failed":
            previous_update = previous_channel_list["status"]["previousUpdate"]

        previous_update = previous_channel_list["updatedAt"]
        previous_export = previous_channel_list["exportedAt"]

    except FileNotFoundError:
        t.log("debug", "\tNo previous list of channels was found\n")

    update_status = {
        "previousUpdate": previous_update,
        "updateStatus": "running",
        "updateCleanStatus": "pending",
        "previousExport": previous_export,
        "isPartialUpdate": False,
        "downloadStatus": "pending",
        "sortingReadStatus": "pending",
        "sortingCleanStatus": "pending",
        "sortingWriteStatus": "pending",
        "mergeStatus": "pending",
        "idAssignStatus": "pending",
        "messageFixStatus": "pending"
    }

    try:
        t.log("info", "\tGetting a list of channels from Discord...")

        # Call the CLI command and capture its output
        cli_command = f"dotnet DCE/DiscordChatExporter.Cli.dll channels -g {c.SERVER_ID} -t {tokens.DISCORD_BOT} --include-threads all"
        code, output = t.run_command(cli_command)

        t.log("info", "\tGot a list of channels from DCE\n")

        # Process the output and create the desired JSON format
        channel_list = parse_output(output, update_status)

        if channel_list["status"]["updateStatus"] == "failed":
            raise Exception("Failed to parse the list of channels")

        channel_list["status"]["updateStatus"] = "success"
        channel_list["status"]["updateCleanStatus"] = "running"

        try:
            t.log("info", "\tCleaning the list of channels...")

            channel_list["categories"] = remove_categories(channel_list["categories"], c.CATEGORIES_TO_IGNORE)

            t.log("info", f"\t  Removed {len(c.CATEGORIES_TO_IGNORE)} categories")

            # Update the number of channels
            channel_list["numberOfChannels"] = 0
            for category in channel_list["categories"]:
                channel_list["numberOfChannels"] += len(category["channels"]) + len(category["threads"])

                
            t.log("info", f"\t  Kept {channel_list['numberOfChannels']} channels across {len(channel_list['categories'])} categories\n")

            channel_list["status"]["updateCleanStatus"] = "success"
        
        except Exception as e:
            t.log("error", f"\n\tFailed to clean the list of channels: {e}\n")
            channel_list["status"]["updateCleanStatus"] = "failed"


    except Exception as e:
        t.log("error", f"\n\tFailed to get a list of channels: {e}\n")

        if previous_update is not None:
            # TODO save with the previous info, if there is
            channel_list = previous_channel_list

        channel_list["updatedAt"] = datetime.now().astimezone().isoformat(sep='T', timespec='microseconds')
        channel_list["status"] = update_status
        channel_list["status"]["updateStatus"] = "failed"
        channel_list["status"]["updateCleanStatus"] = "pending"
        
    t.save_to_json(channel_list, c.CHANNEL_LIST)
    t.log("info", f"\tSaved the list of channels to {c.CHANNEL_LIST}\n")

    t.log("base", f"\n### Channel list finished --- {time.time() - start_time:.2f} seconds --- ###\n")

if __name__ == "__main__":
    get_channel_list()

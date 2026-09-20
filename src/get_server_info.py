import time
import os
from datetime import datetime
import utils.tricks as t
import utils.exceptions as exc
from models import ServerBackup, Category, Channel, Thread
t.set_path()
from res import constants as c


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
load_status()

    Checks that the info folder and file exist, and loads the backup status from the JSON file.
    It ensures the backup isn't already running in another process, and checks if it should be in update mode.
    Then, it prepares the backup info file for the export.

    Returns:
        ServerBackup: The ServerBackup object with the loaded status.
        bool: True if the backup is in update mode, False otherwise.    
"""
def load_status():

    is_update = False

    # check if a SERVER_NAME/INFO folder exists, if not, create it
    if not os.path.exists(c.INFO_FOLDER):
        t.log("debug", f'  Info folder "{c.INFO_FOLDER}" does not exist. Creating it...')
        os.makedirs(c.INFO_FOLDER, exist_ok=True)
        
        # Add to global index if not present
        if t.add_backup_to_index(c.BACKUP_NAME, c.SERVER_ID, c.SERVER_NAME, c.BACKUP_BASE):
            t.log("debug", f"  Added new backup to global index")
            
        # Seed backup_config.json
        config_path = f"{c.BACKUP_BASE}/backup_config.json"
        if not os.path.exists(config_path):
            if os.path.exists(c.GLOBAL_CONFIG):
                import shutil
                shutil.copy(c.GLOBAL_CONFIG, config_path)
                t.log("debug", "  Seeded backup_config.json from global config.")
            else:
                raise FileNotFoundError(f"Global config file '{c.GLOBAL_CONFIG}' not found.")
    
    t.log("debug", f'  Info folder "{c.INFO_FOLDER}" is ready.')
    
    try: 
        # Load the JSON file 
        t.log("debug", f'  Loading backup info from file: {c.BACKUP_INFO}')
        backup = ServerBackup.from_json(c.BACKUP_INFO)

        if backup.is_running():
            raise exc.AlreadyRunningError("The export is still running in another process. Exiting...")
        
        t.log("debug", f"  The current status of the backup is '{backup.status}'")

        # If there already is a completed export, it will be an update
        if backup.needs_update():
            is_update = True

            t.log("debug", "  The backup was completed. It will be an update.")

            # We save the update status in the main file
            backup.start_update()

    except FileNotFoundError:
        t.log("debug", '  No backup info file was found. Will start one from scratch.')

    t.log("debug", "  Preparing the backup info file for the export...\n")

    # If we can start, we'll create a new info file
    backup = ServerBackup(
        path = c.BACKUP_INFO_UPDATE if is_update else c.BACKUP_INFO,
        id = c.SERVER_ID,
        name = c.SERVER_NAME,
        updated_at = datetime.now().astimezone().isoformat(sep='T', timespec='microseconds')
    )

    backup.start_get_info()

    t.log("debug", "  Backup info file is ready.\n")

    return backup, is_update



"""
parse_output(output, backup: ServerBackup)

    Parses the output of the DiscordChatExporter CLI tool and returns a list of channel data.

    Args:
        output (str): The output of the DiscordChatExporter CLI tool.
        backup (ServerBackup): The ServerBackup object to store parsed data.

"""
def parse_output(output, backup: ServerBackup):

    t.log("info", "\tParsing the list of channels...")

    lines = []
    
    try:
        lines = output.strip().split("\n")

        t.log("debug", f"\t\t We got {len(lines)} lines from DCE. Analyzing...")

        for line in lines:
            if not line.strip():
                continue

            t.log("debug", f"\t\t Analyzing line: {line}")

            parts = line.split(" | ")

            # If it's a category
            if len(parts) < 2 and " \\ " in parts[0]:
                t.log("debug", "\t\t\t It's a category")

                cat_info = parts[0].split(" \\ ",1)[1].strip()
                pos_str, cat_name = cat_info.split("#", 1)
                cat_position = int(pos_str.strip())
                cat_name = cat_name.strip()

                new_category = Category(
                    id = parts[0].split(" \\ ")[0].strip(),
                    name = cat_name,
                    position = cat_position,
                    path = f"{cat_position}# {cat_name.replace(':', '_')}"
                )
                
                t.log("debug", f"\t\t\t Created new category: {new_category.name} (ID: {new_category.id})")

                # Add it to the data
                backup.add_new_category(new_category)


            # If it's a channel
            elif len(parts) == 2:

                t.log("debug", "\t\t\t It's a channel")

                pos_str, ch_info = parts[1].split("#", 1)

                new_channel = Channel(
                    id = parts[0].strip(),
                    name = ch_info.split(" / ", 1)[1].strip(),
                    position = int(pos_str.strip())
                )

                t.log("debug", f"\t\t\t Created new channel: {new_channel.name} (ID: {new_channel.id})")

                # Add it to the data
                backup.add_new_channel(new_channel)
            

            # If it's a thread
            elif len(parts) == 3:

                t.log("debug", "\t\t\t It's a thread")

                pos_str, th_info = parts[1].split("#", 1)

                new_thread = Thread(
                    id = parts[0].replace('*', '').strip(),
                    name = th_info.split(" / ", 1)[1].strip(),
                    position = int(pos_str.strip())
                )
                
                t.log("debug", f"\t\t\t Created new thread: {new_thread.name} (ID: {new_thread.id})")

                # Add it to the data
                backup.add_new_thread(new_thread)

            
            else:
                t.log("debug", "\t\t\tThe line format was not recognized.")


        t.log("info", f"\tAnalyzed {len(lines)} lines and found {backup.number_of_categories} categories, {backup.number_of_channels} channels and {backup.number_of_threads} threads \n")
    
    except Exception as e:
        raise exc.GetChannelListError("Failed to parse the list of channels") from e
    

"""
get_server_info_from_discord(backup: ServerBackup)

    Gets a list of channels from Discord using the DiscordChatExporter CLI tool,
    then parses the output to save it in the ServerBackup object and a JSON file.

    Args:
        backup (ServerBackup): The ServerBackup object that holds the data.

"""
def get_server_info_from_discord(backup: ServerBackup):

    try: 
        t.log("base", "  #  This may take a few minutes...  #\n")

        t.log("info", "\tGetting a list of channels from Discord...")

        # Call the CLI command and capture its output
        cli_command = f"dotnet DCE/DiscordChatExporter.Cli.dll channels -g {c.SERVER_ID} -t {tokens.DISCORD_BOT} --include-threads all --include-categories --relative-positions --show-positions"
        code, output = t.run_command(cli_command)

        if code != 0:
            raise exc.ConsoleCommandError(f"DCE command failed with code '{code}'")

        t.log("info", f"\tGot a list of channels from DCE. Parsing...\n")

        # Process the output and create the desired JSON format
        parse_output(output, backup)

        backup.finish_get_info()

        t.log("info", "\tFinished saving the list of channels\n")

    except Exception as e:
        backup.finish_get_info(success=False)
        raise exc.GetChannelListError("Failed to get the list of channels") from e

        
"""
clean_channel_list(backup: ServerBackup)

    Cleans up the channel list by removing categories and updating the number of channels.

    Args:
        backup (ServerBackup): The ServerBackup object that holds the data.
"""
def clean_channel_list(backup: ServerBackup):

    t.log("info", "\tCleaning the list of channels...")

    try:

        backup.start_clean_info()

        if c.KEEP_MODE:
            t.log("debug", f"\t  Keeping only the specified categories...")
            backup.keep_categories(c.CATEGORIES_TO_KEEP)
        else:
            t.log("debug", f"\t  Removing the specified categories...")
            backup.remove_categories(c.CATEGORIES_TO_IGNORE)

        t.log("info", f"\t  Kept {backup.number_of_channels} channels across {backup.number_of_categories} categories\n")

        backup.finish_clean_info()

        t.log("info", "\t  Finished cleaning the list of channels\n")

    except Exception as e:
        backup.finish_clean_info(success=False)
        raise exc.CleanChannelListError("Failed to clean the list of channels") from e


def get_categories(server_id: str) -> dict[str, str]:

    categories = {}

    try:
        t.log("info", "\tGetting the list of categories from the server...")
        
        cli_command = f"dotnet DCE/DiscordChatExporter.Cli.dll channels -g {server_id} --include-categories --relative-positions"
        code, output = t.run_command(cli_command)
        
        if code != 0:
            raise exc.ConsoleCommandError(f"DCE command failed with code '{code}'")

        lines = output.strip().split("\n")
        
        for line in lines:
            parts = line.split(" | ")
            if len(parts) < 2:
                cat_name = parts[0].split(" \\ ")[1].strip()
                cat_id = parts[0].split(" \\ ")[0].strip()
                categories[cat_id] = cat_name
        
        t.log("info", f"\t\t\t Found {len(categories)} categories\n")

    except Exception as e:
        raise exc.GetChannelListError("Failed to get the list of channels") from e
    
    return categories


################# Main function #################


def get_server_info():

    t.log("base", f"\n###  Getting a list of all channels from the server {c.SERVER_NAME}...  ###\n")
    
    is_update = False
    
    backup, is_update = load_status()

    try:

        start_time = time.time()

        get_server_info_from_discord(backup)

        clean_channel_list(backup)

    except exc.CleanChannelListError as e:

        raise exc.ChannelListError from e
    
    except Exception as e:

        raise exc.ChannelListError from e

    finally:
        try:
            if is_update and backup.is_failed():

                main_backup = ServerBackup.from_json(c.BACKUP_INFO)
                main_backup.finish_update(success=False)
    
        except Exception as e:
            t.log("error", f"\tFailed to save the failed update status to the main file: {e}\n")

        t.log("base", f"\n### Channel list finished --- {time.time() - start_time:.2f} seconds --- ###\n")

        # if there was an exception, raise it again
        if 'e' in locals() and e is not None:
            raise e
    
    return is_update


if __name__ == "__main__":
    
    try:
        get_server_info()
    
    except KeyboardInterrupt:
        t.log("error", "\nProcess interrupted by user.\n")
        try:
            backup = ServerBackup.from_json(c.BACKUP_INFO)
            if backup.is_updating():
                update = ServerBackup.from_json(c.BACKUP_INFO_UPDATE)
                update.set_failed()
                backup.finish_update(success=False)
            else:
                backup.set_failed()
        except Exception:
            pass

    except Exception as e:
        t.log("error", f"\n{exc.unwrap(e)}\n")

import os
import json
import time
import re
import tricks as t
t.set_path()
from res import constants as c

################ File summary #################

"""

This module fixes messages in the backup that have bad formatting.

Main function: fix_bad_messages()

    This function traverses all JSON files in the specified folder and its subdirectories to
    find messages with bad formatting and replace them with the corresponding fixed versions.

"""

################ Functions #################


"""
fix_messages_in_channel(messages, fixed_messages)

    This function traverses through all the messages in a channel and,
    if it finds a message that has a fixed version in the fixed_messages dictionary,
    it will replace it with the corresponding message from the dictionary.

    It also deletes messages from non-bot users if they only have a mention.

    Args:
        messages (list): A list of messages in the channel.
        fixed_messages (dict): A dictionary containing fixed versions of messages.

    Returns:
        None
"""
def fix_messages_in_channel(messages, fixed_messages):

    for message in messages:

        # if ID in fixed_messages, replace it
        if message["id"] in fixed_messages:
            
            t.log("debug", f"\tFound bad message {message['id']} from {message['author']['name']}.")
            t.log("debug", f"\t    Replacing it with {fixed_messages[message['id']]['id']} from {fixed_messages[message['id']]['author']['name']}.")

            message = fixed_messages[message["id"]]
        
        # if message is from a non-tupper user
        if message["type"] == "Default" and int(message["author"]["id"]) >= 100000:

            # regex that matches `@[more than one word]`
            pattern = r"^@[\w ]+$"

            # if the message has a mention, remove it
            if re.search(pattern, message["content"]):

                t.log("debug", f"\tFound message with only a mention '{message['content']}' from {message['author']['name']}.")

                #remove message from messages
                messages.remove(message)

################# Main function #################

def fix_bad_messages():

    t.log("base", f"\n###  Fixing badly formatted messages in {c.SERVER_NAME}...  ###\n")

    start_time = time.time()

    fixed_messages = t.load_from_json(c.FIXED_MESSAGES)

    t.log("info", f"    Found {len(fixed_messages)} messages to patch\n")

    # Iterate over all channel JSON files in the folder and its subfolders
    for root, dirs, files in os.walk(c.SEARCH_FOLDER):
        for filename in files:
            if filename.endswith(".json") and not filename.endswith("scenes.json"):

                file_path = os.path.join(root, filename)

                t.log("log", f"\t    Analysing {file_path}...")

                # Load channel JSON data from file
                channel_data = t.load_from_json(file_path)

                # find and fix bad messages
                fix_messages_in_channel(channel_data["messages"], fixed_messages)

                # Save the modified JSON data back to the file
                t.save_to_json(channel_data, file_path)

    t.log("base", f"### Finished fixing messages --- {time.time() - start_time:.2f} seconds --- ###\n")

if __name__ == "__main__":
    fix_bad_messages()
    
import json
import os
from pathlib import Path
import re
import tricks as t
t.set_path()

################# File summary #################

"""

This module is used to test and debug the regex pattern to detect the end of a scene.

Main function: test_regex()

    This script searches for messages in a folder of JSON files that match a regex pattern.
    It creates a new JSON file with the matched messages.

"""

################# Functions #################

script_dir = Path(__file__).resolve().parent.as_posix()
folder_name = "Elysium/Scenes/Kaminashi City"
folder_path = (Path(script_dir) / folder_name).as_posix()
output_file = "regex_results.json"  # Replace with the desired output file name

regex_pattern = r"(?i)(?:`|```).*\b(?:end|hold|close)\w*.{0,5}(?:`|```)\n*(?:$|@.*)"

all_messages = []

# Iterate over all files in the folder
if Path(folder_path).exists():
    for filename in os.listdir(folder_path):
        if filename.endswith(".json"):
            file_path = (Path(folder_path) / filename).as_posix()
            
            # Load JSON file
            with open(file_path, "r", encoding="utf-8-sig") as file:
                data = json.load(file)
                
                # Extract messages that match the regex pattern
                messages = [message for message in data["messages"] if re.search(regex_pattern, message["content"], re.DOTALL)]
                all_messages.extend(messages)

# Create output JSON file with matched messages
output_data = {"messages": all_messages}
output_path = (Path(script_dir) / output_file).as_posix()
with open(output_path, "w", encoding="utf-8") as file:
    json.dump(output_data, file, indent=4, ensure_ascii=False)

print("Output file created:", output_path)

import datetime
import sys
import os
import subprocess
import json
import re
import inspect
import shutil
from . import exceptions as exc
from collections import deque

GRAY = '\033[90m'
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[34m'
MAGENTA = '\033[95m'
CYAN = '\033[96m'
RESET = '\033[0m'

################ File summary #################

"""

This module holds a handful of useful functions and helpers.

"""

################ Functions #################
"""
set_path()

    This function sets the path to the project folder.

"""
def set_path():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    if project_root not in sys.path:
        sys.path.append(project_root)

"""
save_to_json(data, file_path), load_from_json(file_path)

    Functions to read and write a JSON file.
    
"""
def load_from_json(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_to_json(data, file_path):
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)

def get_backups_index():
    index_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'res', 'backups_index.json')
    if not os.path.exists(index_path):
        return []
    with open(index_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def add_backup_to_index(backup_id, backup_name, server_id, path):
    index = get_backups_index()
    if not any(b["path"] == path for b in index):
        index.append({
            "backup_id": backup_id,
            "backup_name": backup_name,
            "server_id": server_id,
            "path": path
        })
        index_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'res', 'backups_index.json')
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index, f, indent=4)
        return True
    return False


"""
clean(message)

    Function to remove ANSI escape sequences from a string and remove leading and trailing newlines.
"""
def clean(message):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    no_ansi = ansi_escape.sub('', message)

    return no_ansi.lstrip('\n').rstrip('\n')

"""
log(level, message)

    Centralized function to handle information messages.
    
    It prints the message if the corresponding flag is set in the constants module.
    It also writes the message to a log file if the LOG flag is set.

    Args:
        level (str): The level of the message (info, debug, console).
        message (str): The message to be logged.

"""
def log(level="base", message=""):
    set_path()
    from res import constants as c

    # Determine caller module
    stack = inspect.stack()
    caller_frame = stack[1]
    caller_module = inspect.getmodule(caller_frame.frame)
    caller_name = caller_module.__name__ if caller_module else None

    # Prepend tab if not called from export_channels.py
    if caller_name != "export_channels":
        message = "\t" + message

    if level == "base":
        print(GREEN + message + RESET)
    elif level == "info":
        if c.INFO:
            print(CYAN + message + RESET)
    elif level == "debug":
        if c.DEBUG:
            print(BLUE + message + RESET)
    elif level == "console":
        if c.CONSOLE:
            print(GRAY + message, end="")
    elif level == "error":
        print(RED + message + RESET)
    
    level = "console" if level == "consolelog" else level
    
    if c.LOG:
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        
        # create directory if it doesn't exist
        if not os.path.exists(os.path.dirname(c.LOG_FILE)):
            os.makedirs(os.path.dirname(c.LOG_FILE))

        log_line = f"[{timestamp}]{level}: {clean(message)}\n"
        
        with open(c.LOG_FILE, "a", encoding="utf-8") as file:
            file.write(log_line)

def global_log(level="base", message=""):
    set_path()
    from res import constants as c
    
    if level == "base":
        print(GREEN + message + RESET)
    elif level == "error":
        print(RED + message + RESET)
    else:
        print(message)
        
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    
    if not os.path.exists(os.path.dirname(c.GLOBAL_LOG_FILE)):
        os.makedirs(os.path.dirname(c.GLOBAL_LOG_FILE))

    with open(c.GLOBAL_LOG_FILE, "a", encoding="utf-8") as file:
        file.write(f"[{timestamp}]{level}: {clean(message)}\n")

"""
run_command(command: str, show_lines: int = 0)

    Run a shell command, stream its output in real time, and return the full output.
    
    Args:
        command (str): The shell command to run.
        show_lines (int, optional): The number of lines to clear before streaming output.
    
    Returns:
        tuple[int, str]: A tuple containing the return code and the full output.
"""
def run_command(command: str, show_lines: int = None):
    set_path()
    from res import constants as c

    try:
        log("console", f"# RUNNING CONSOLE COMMAND #\n")
        log("console", f"> {MAGENTA}{command}{GRAY}\n")

        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        full_output = []
        tail_buffer = deque(maxlen=show_lines+2 if show_lines else 0)

        try:
            for line in process.stdout:
                full_output.append(line)  # Collect output for return

                if show_lines and c.CONSOLE:
                    # Clear previous lines (simulate dynamic overwrite)
                    print("\033[F" * len(tail_buffer), end="")  # Move cursor up

                    tail_buffer.append(line)
                    
                    for l in tail_buffer:
                        print(f"\t> {l.strip():<80}")  # Print line padded to overwrite
                        log("consolelog", f">\t{l}")
                else:
                    log("console", f">\t{line}")
                
        except KeyboardInterrupt:
            log("base", f"{YELLOW}\nCommand interrupted by user.\n")
            process.terminate()

        process.wait()

        log("console", f"\n{RESET}# END OF CONSOLE COMMAND #\n\n")
        return process.returncode, ''.join(full_output)

    except Exception as e:
        raise exc.ConsoleCommandError("An error occurred while running the command") from e

"""
create_merge_folder()

    Copies the c.DATA_FOLDER to c.MERGE_FOLDER.
    Then deletes all the files that end with "_scenes.json" from the c.MERGE_FOLDER.
"""
def create_merge_folder():
    set_path()
    from res import constants as c  

    if os.path.exists(c.MERGE_FOLDER):
        log("base", f"Deleting old merge folder: {c.MERGE_FOLDER}")
        shutil.rmtree(c.MERGE_FOLDER)

    log("base", f"Creating merge folder by copying {c.DATA_FOLDER} to {c.MERGE_FOLDER}")
    shutil.copytree(c.DATA_FOLDER, c.MERGE_FOLDER, dirs_exist_ok=True)


    # delete all the folders named "Scenes" and all the files that end with "_scenes.json" from the "Merge" folder
    for root, dirs, files in os.walk(c.MERGE_FOLDER):
        for dir in dirs:
            if dir == "Scenes":
                shutil.rmtree(os.path.join(root, dir))
        for file in files:
            if file.endswith("_scenes.json"):
                os.remove(os.path.join(root, file)) 
    
    log("base", f"Finished creating merge folder: {c.MERGE_FOLDER}\n")

################ End Functions ################

if __name__ == "__main__":
    print("\nThis module is not intended to be run directly.\n")
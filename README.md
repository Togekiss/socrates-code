# Socrates, the record keeper of Elysium

## What is Socrates?

A Discord bot specifically made for Elysium, a RP server, with plans to adapt it to work on any roleplaying or collaborative writing server that uses similar tagging systems.

The main goal of this bot is to find and list all the scenes a character has participated in. 

Additionally, it serves as a history backup and chat analyser prepper.

## Current status

Socrates is in development process. Currently, the bot itself only serves as a watcher to export channels using DCE and its token. All logic and scripts have to be run manually and locally. Server structure and search parameters are set through a configuration file, and functionality is split in several files.

Its basic functionality is robust, but it relies on user-reviewed files having a proper format, and the pipeline excuting successfully.

The next step will be to implement better error handling for those cases, and a main menu to launch all the steps.

Once this is in working condition, the focus will shift to uploading the bot to a server to be operational 24/7 and invoked with Discord commands.


 ## Folder structure

- `DCE`: contains the CLI version of https://github.com/Tyrrrz/DiscordChatExporter

- `[Server name]`: contains the server backup downloaded with DCE
  - Each folder represents a category, and contains:
    - `[num]# [channel name].json`: the backup file of a channel
    - `Threads` folder: contains the backup files of threads, with format `[channel num]-[thread num]# [thread name].json`
    - `Scenes` folder: contains a `_scenes.json` file for each channel and thread, with the list of all detected scenes in that file
    - `scenes.json`: the cumulative list of all detected scenes in that category
  - The root folder also contains a `scenes.json` file with the list of all detected scenes in the whole server

- `res`: contains configuration files and metadata files the bot uses to download and navigate through channels
  - `tokens.py`: contains the bot token. DO NOT SHARE!
  - `server_data.py`: contains the server ID and some category name. SHARE WITH CAUTION!
  - `constants.py`: configuration file with search parameters, output parameters, and more
  - `character_ids.json`: a list of tupperbox characters and their associated IDs
  - `channel_list.json`: list of channels and threads to be downloaded
  - `fixed_messages.json`: for each message known to have a bad formatting in the backup, a fixed version is stored here

- `out`: contains the results of scene searches, both for link lists and full scene extractions
  - `[Character name]` folder: contains extracted scenes for a specific character, in HTML format
  - `scene-links.txt`: contains a list of scenes with links to their messages, according to the filters set in `res/constants.py`
  - `scenes.json`: contains all the data for all the scenes found

- `src`: contains the scripts to download channels, parse them, and extract scenes. 
  - `export_channels.py`: updates the server backup by downloading new content from Discord with DCE
  - `get_channel_list.py`: updates the list of channels to be downloaded by `export_channels.py`
  - `sort_exported_files.py`: adds numbers to the backup files so they are in the same order as in the server
  - `merge_exports.py`: merges the downloaded updates to the main server backup files
  - `assign_ids.py`: parses the server backup and assigns a unique ID to each tupperbox bot
  - `fix_bad_messages.py`: parses the server backup and fixes bad messages
  - `find_all_scenes.py`: parses the server backup and creates a complete list of scenes
  - `find_scenes.py`: parses the server backup and gathers a list of scenes for the specified character
  - `export_scenes.py`: uses the list of found scenes to download the full scenes with DCE in HTML format
  - `create_scene_list.py`: helper function to create URLs that link to the starting messages of found scenes
  - `tricks.py`: helper functions to do a variety of things
  - `test_regex.py`: helper script to test new regex patterns against the server backup
  - `test_discord.py`: helper script to test connection with Discord


## How to use in local (in case you want to help or play with it!)

(Note: These instructions are for its current state of development. They will change when the code is clean and adapted to use on other servers. They're a mess, I know. Ask me for more info if you need!)

- Create a folder named `DCE` and download the CLI version of https://github.com/Tyrrrz/DiscordChatExporter

- Fill in `res/tokens.py` and `res/server_data.py` with your bot token and server info

- Run `src/export_channels.py`

- Manually double check `res/character_ids.json`.
  - If a new character has been introduced, add known aliases, writer and tags manually
  - Changing the name of the tupper bot (for example, "John Doe" has been renamed to "John D") and aliases (another tupper for the same character, for example, if John Doe has a tupper of his secret identity "Jon Buck") is registered as a new character.
  If this happens, find the original character form and add the new character as an alias or an "other version".
- Save the file and run `src/assign_ids.py` again to update the server backup messages.

- Run `src/find_scenes.py`

- You should have the scenes list in `out/scene-links.txt`
  - After this, you don't have to run `src/find_scenes.py` if you just want to search a different status for the same character. You can just change the status in `res/constants.py` and run `src/create_scene_list.py` to get a new list.

- Run `src/export_scenes.py` if you want to download the full scenes in HTML.

## How does it work?

Given the use of Tupperbox to send message as roleplaying characters, native Discord search is unable to look for messages from a particular one.

Every X time, Socrates will use https://github.com/Tyrrrz/DiscordChatExporter to download the specified writing channels. Then it will traverse through the exported .JSON files to detect all the unique Tupperbox-made characters and manually give each a unique ID, effectively turning them into individual users in the eyes of applications such as https://github.com/mlomb/chat-analytics

After exporting the backup, Socrates analyzes the whole server and creates a list of all the scenes found.

**IN PROGRESS:** When a user runs the script to find scenes with a specified character name, or more than one, Socrates will look for their scenes directly in the `scenes.json` file.

**LEGACY:** When a user runs the script to find scenes with a specified character name, the bot navigates through all channels looking for the first appearence of said character to save the message link and flag it as 'start of scene'.
Then, it will keep that scene alive until it encounters an 'end' tag or similar from a specified list, an EOF, or the character doesn't appear for a specified number of messages. When it considers a scene is over, it will save the last message as 'end of scene' and its status: closed, active, or timed out.

After having gone through all channels, it will output a list of scenes, with the channel name, the date, and the link to the starting message.

## Things to implement

### Scene detection tuning
- Work on a different set of rules to log open interactions, like chatrooms or events
- Check if a scene starts with a date tag for more accurate in-universe timeline keeping
- ~~Expand and adjust the selection of 'end of scene' tags - and account for variations or mistakes~~ Doesn't detect super edge cases, but that's a skill issue of whoever didn't set them correctly
  - If a badly formatted message is found, it can be added to `fixed_messages.json` with proper formatting and use `src/fix_bad_messages.py` to apply it
- ~~Detect the names of other character(s) in the scene~~ Their IDs are added to `out/scenes.json`. Their names are easy to find
- ~~Detect the true start of the scene, not the first message of the requested character~~ Done
  - ~~Trace back until you find a previous end tag or SOF to find the proper start~~
  - ~~Or until its from a character not in the scene, in case last wasn't closed properly~~
  - ~~Will most likely need an index attribute in the JSON to iterate back and forth~~

### Extra search parameters
*Note: Detecting all scenes is reasonably fast, so these are only filters to narrow down the final list given to the user. Internally, all scenes are accounted for.*
- Input two characters and find scenes with them
- Input a date range
- ~~Input a specific channel/category to look in~~ Use `SEARCH_FOLDER` in `res/constants.py` to limit it down to a category
  - ~~Load only the category folder or channel file and operate as usual~~
  - ~~This will be especially useful to differenciate scenes from DMs~~ Use `TYPE` in `res/constants.py`
- ~~Input a scene status (Closed, Active, Timed out)~~ Use `STATUS` in `res/constants.py`

### Chat exporting
- It'd be cool to add "number of messages, number of scenes" in `res/channel_list.json`
- Avoid re-processing channels that have already been exported
  - Keep a list of channels that did get updates (no empty message list)
  - Run `assign_ids.py` against the update batch
  - Dry run `find_all_scenes.py` against the update batch *without* timeout protection to detect badly formatted messages
  - Manually check for timed out scenes, update `fixed_messages.json` and run `fix_bad_messages.py` against the update batch
  - Run `find_all_scenes.py` against the update batch
    - If the channel had no open scenes, add any new scenes to the corresponding `_scenes.json` files
    - If the channel had an open scene, try to detect its end and update the scene in the corresponding `_scenes.json` files
  - And THEN merge the backup files with `merge_exports.py`

### Releasing it to the public
- Investigate where it should be hosted
  - Requirements:
    - Always online
    - Be Discord-approved    
    - Have a way to securely store tokens
    - Get the code directly from the GitHub repo
    - Be able to run scheduled actions
    - Allow users to download zipped results (HTML scenes for users, Server backup files for admins)
  - GitHub is a good choice, it has Github Actions and could even have a web interface to not have to search through Discord
  - Heroku is a no-go, it declines my european payments :(

- Schedule a weekly backup of channels
  - Add a fast search option (against the last download) vs updated search option (update the backup and then search)


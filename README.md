# Socrates, the record keeper of Elysium

## What is Socrates?

A Discord tool specifically made for Elysium, a RP server, with plans to adapt it to work on any roleplaying or collaborative writing server that uses similar tagging systems.

The main goal of this tool is to find and list all the scenes a character has participated in. 

Additionally, it serves as a history backup and chat analyser prepper.

## Current status

Socrates is in development process. Currently, the Discord bot itself only serves as a hook to export channels using DCE and its token. All logic and scripts have to be run manually and locally. Server structure and search parameters are set through a configuration file, and functionality is split in several files.

Once configuration files are set up, running `src/backup_server.py` will automatically perform all the steps to download/update the server backup and index all scenes. Error and interruption detection are in place. In case of an error, interruption, or manual changes to `character_list.json` and `fixed_messages.json`, the steps to re-apply them can be run independently.

Its basic functionality is robust, but it relies on users editing config and JSON files properly.

Currently we're working on a UI to view and change configurations, launch the pipeline, and view the results.

Once this is in working condition, the focus will shift to uploading the bot to a server to be operational 24/7 and invoked with Discord commands.


 ## Folder structure

- `DCE`: contains a CLI version of https://github.com/Tyrrrz/DiscordChatExporter with custom parameters found in https://github.com/Togekiss/DiscordChatExporter

- `Backups`: contains the server backups. Each server has its own folder:
  - `[Server name]`: contains the server backup downloaded with DCE
    - `Info` folder: contains several metadata files:
      - `backup_info.json`: status of each backup step, and list of channels with info like IDs, position, number of messages, etc.
      - `<backup_info_update.json>`: same as `backup_info.json` to keep track of the status of an update batch. Only exists if an update batch is in progress, or if you chose to keep temporary files in the settings.
      - `character_list.json`: a list of tupperbox characters with their IDs and metadata
      - `bad_messages.json`: a list of messages known to have a bad formatting
      - `bad_end_messages.json`: a list of messages known to be the end of a scene, but with no end tag
      - `fixed_messages.json`: for each message known to have a bad formatting in the backup, a fixed version is stored here
    - `Data` folder: Contains everything downloaded from Discord. Contains one folder per category. In each folder:
      - `_scenes.json`: the cumulative list of all detected scenes in that folder
      - `<_scenes_debug.json>`: Intermediate steps of scene detection. Only exists if you chose to keep temporary files in the settings.
      - `[num]# [channel name].json`: the backup file of a channel
      - `Threads` folder: contains the backup files of threads, with format `[channel num]-[thread num]# [thread name].json`
      - `Scenes` folder: contains a `_scenes.json` file for each channel and thread, with the list of all detected scenes in that file
    - `<Update>` folder: Contains all the new data from an update batch. Only exists if an update batch is in progress, or if you chose to keep temporary files in the settings.  
    - `<Merge>` folder: Contains the merged backup files, with the same structure as `Data` folder. Only exists if an update batch is in progress, or if you chose to keep temporary files in the settings.

- `res`: contains configuration files and metadata files the bot uses to download and navigate through channels
  - `tokens.py`: contains the bot token. DO NOT SHARE THIS ONE! UPLOAD ONLY A SAMPLE VERSION!
  - `server_data.py`: contains the server ID and some category names. SHARE WITH CAUTION!
  - `constants.py`: configuration file with search parameters, output parameters, and more

- `out`: contains the results of scene searches, both for link lists and full scene extractions
  - `[Character name]` folder: contains extracted scenes for a specific character, in HTML format
  - `scene-links.txt`: contains a list of scenes with links to their messages, according to the filters set in `res/constants.py`
  - `log.txt`: contains a log of the tool's actions

- `src`: contains the scripts to download channels, parse them, and extract scenes. 
  - `backup_server.py`: orchestrates all the steps to download or update a server backup
  - `get_server_info.py`: updates the list of channels to be downloaded
  - `download_channels.py`: downloads new content from Discord with DCE
  - `update_paths.py`: updates the paths of the backup files so they match the update
  - `merge_exports.py`: merges the downloaded updates to the main server backup files
  - `assign_ids.py`: parses the server backup and assigns a unique ID to each tupperbox bot
  - `fix_bad_messages.py`: parses the server backup and fixes bad messages
  - `index_scenes.py`: parses the server backup and creates a complete list of scenes
  - `find_character_scenes.py`: parses the server backup and gathers a list of scenes for the specified character
  - `export_scenes.py`: uses the list of found scenes to download the full scenes with DCE in HTML format
  - `create_scene_list.py`: helper function to create URLs that link to the starting messages of found scenes
  - `test_regex.py`: helper script to test new regex patterns against the server backup
  - `test_discord.py`: helper script to test connection with Discord
  - `main.py`: WIP of a main menu to see and edit configs, status, and launch the bot
  - `server.py`: FastAPI interface between the frontend and the python scripts

  - `utils`: contains helper modules
    - `exceptions.py`: helper to log exceptions
    - `tricks.py`: helper functions to do a variety of things
  
  - `models`: contains helper classes
    - `server_backup.py`: helper class to hold all the information about a server backup, corresponding to the `backup_info.json` file
    - `category.py`, `channel.py`, `thread.py`: helper classes to hold information about a category, channel, or thread

- `ui`: contains the frontend for the web UI. It's built with Vite, React and TypeScript

## How to use in local (in case you want to help or play with it!)

(Note: These instructions are for its current state of development. They will change when the code is clean and adapted to use on other servers. They're a mess, I know. Ask me for more info if you need!)

- Create a folder named `DCE` and download the CLI version of https://github.com/Togekiss/DiscordChatExporter
  - ***IMPORTANT UPDATE:*** It will not work with the original version of the program. And Releases aren't working well, so download the CLI from 'Actions' or download the source code and compile it.
  - To compile it, download .NET 9 and C# Dev Kit extension in VSCode, right-click the `.sln` and click "Build". Or use Visual Studio i guess. Or `dotnet build -t:CSharpierFormat --configuration Release`. 

- Fill in `res/tokens.py` with your bot token.

### Running the Web UI (Recommended)

Socrates now comes with a browser-based UI to manage configurations and run the pipeline.

1. **Start the Backend:**
   Open a terminal in the root folder and start the FastAPI server:
   ```bash
   .\.venv\Scripts\uvicorn src.server:app --reload
   ```

2. **Start the Frontend:**
   Open a second terminal, navigate into the `ui` folder, install dependencies (if not done yet), and start the Vite dev server:
   ```bash
   cd ui
   npm install
   npm run dev
   ```

3. Open your browser to `http://localhost:5173`. You can change settings, see server status, and start the backup pipeline directly from the interface!

### Running via CLI (Manual approach)

- Check `res/config.json` to adjust settings like server info, verbosity, search filters and file paths.
- Run `src/backup_server.py`

- Manually double check `res/character_list.json`.
  - If a new character has been introduced, add known aliases, writer and tags manually
  - If a tupperbot changed its name (for example, "John Doe" has been renamed to "John D") or has two bots (another tupper for the same character, for example, if John Doe has a tupper of his secret identity "Jon Buck"), Socrates will register it as a new character. In this case, find the original character form and add the new one as an alias or an "other version".
- Save the file and run `src/assign_ids.py` again to update the server backup messages.

- Run `src/find_character_scenes.py`

- You should have the scenes list in `out/scene-links.txt`
  - After this, you don't have to run `src/find_character_scenes.py` if you just want to search a different status for the same character. You can just change the status in `res/config.json` and run `src/create_scene_list.py` to get a new list.

- Run `src/export_scenes.py` if you want to download the full scenes listed in `out/scene-links.txt` in HTML.

## How does it work?

Given the use of Tupperbox to send message as roleplaying characters, native Discord search is unable to look for messages from a particular one.

Every X time, Socrates will use https://github.com/Tyrrrz/DiscordChatExporter to download the specified writing channels. 

If it sees there's already a backup file, it will only download messages starting from the last backup, and then merge the new messages to the main backup file.

Then it will traverse through the exported .JSON files to detect all the unique Tupperbox-made characters and manually give each a unique ID, effectively turning them into individual users to the eyes of applications such as https://github.com/mlomb/chat-analytics

Then it applies the patches stored in `Info/fixed_messages.json` to correct known issues.

After exporting the backup, Socrates analyzes the whole server to find scenes. It looks for scene closing tags like `[END]` or a sudden change in participants. With this, it creates lists of scenes with links to the message it starts and ends, which characters are participants, if it's closed or open, etc.

When a user wants to find scenes with one or more characters, Socrates will look for their scenes directly in the `_scenes.json` file. Then it will fetch the scenes and create a list of links to each one of them.


## Things to implement

### Scene detection tuning
- Work on a different set of rules to log open interactions, like chatrooms or events
- Check if a scene starts with a date tag for more accurate in-universe timeline keeping
- ~~Expand and adjust the selection of 'end of scene' tags - and account for variations or mistakes~~ Doesn't detect super edge cases, but that's a skill issue of whoever didn't set them correctly
  - If a badly formatted message is found, it can be added to `fixed_messages.json` with proper formatting and use `src/fix_bad_messages.py` to apply it
- ~~Detect the names of other character(s) in the scene~~ Their IDs are added to `_scenes.json`. Their names are easy to find
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

### Chanel exporting

- ~~Make a cumulative scene detection to not analyze the whole thing every time~~ It's fast enough to not need this
- ~~Order threads by creation date~~
- ~~It'd be cool to add "number of messages, number of scenes" in `backup_info.json`~~

### Releasing it to the public
- Investigate where it should be hosted
  - Requirements:
    - Always online
    - Run both the bot and a web app
    - Be Discord-approved    
    - Have a way to securely store tokens
    - Get the code directly from the GitHub repo
    - Be able to run scheduled actions
    - Allow users to download zipped results (HTML scenes for users, Server backup files for admins)
  - Heroku is a no-go, it declines my european payments :(

- Schedule a weekly backup of channels
  - Add a fast search option (against the last download) vs updated search option (update the backup and then search)


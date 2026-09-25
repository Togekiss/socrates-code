# Socrates, the record keeper of Elysium

## What is Socrates?

A Discord tool specifically made for Elysium, a RP server, with plans to adapt it to work on any roleplaying or collaborative writing server that uses similar tagging systems.

The main goal of this tool is to find and list all the scenes a character has participated in. 

Additionally, it serves as a history backup and chat analyser prepper.

## Current status

Socrates is in development process. Currently, the Discord bot itself only serves as a hook to authenticate and export channels using DCE and its token. It can run locally or from the hosted cloud infrastructure.

Its basic functionality is robust and the web UI makes it a bit more foolproof, but it still relies on users knowing how to edit the config properly.

Now it's hosted online (GCP and Firebase), but this broke the Discord authentication. Next step is fixing that and whatever other issues the migration caused

Once this is in working condition, the focus will shift to turning it into a Discord iframe application.

## Current Architecture

- **Backend:** Python (FastAPI) + .NET 9 Runtime running in a Docker container on **Google Cloud Run**.
- **Frontend:** Vite + React deployed to **Firebase Hosting**.
- **Data Persistence:** `.JSON` files are stored in a **Google Cloud Storage** bucket, which is mounted to the Cloud Run container via **GCS FUSE** at the path `/mnt/socrates-data`. The Python backend resolves paths using the `SOCRATES_DATA_DIR` env variable. In local, it defaults to `/Backups`
- **Secrets:** Handled via **Google Secret Manager** and injected into Cloud Run as environment variables. In local, they're handled via `.env`
- **CI/CD:** Managed via GitHub Actions in [Togekiss/socrates-code](https://github.com/Togekiss/socrates-code):
  - `deploy-backend.yml`: Uses `google-github-actions/deploy-cloudrun` (Source deploy).
  - `deploy-frontend.yml`: Uses `FirebaseExtended/action-hosting-deploy` pointing to `./ui`.
- **UI API Connection:** The Vite frontend resolves the backend URL to `/api`.


 ## Folder structure

- `DCE`: contains a CLI version of https://github.com/Tyrrrz/DiscordChatExporter with custom parameters found in https://github.com/Togekiss/DiscordChatExporter

- `Backups`: contains the server backups. Each backup has its own folder:
  - `backups_index.json`: contains the list of backups with their IDs and paths
  - `[Backup name]`: contains the server backup downloaded with DCE
    - `backup_config.json`: the configuration file used to create this backup. It's a copy of the default config file in `res/`
    - `log.txt`: log file of processes specific to this backup  
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

  - `config.json`: global configuration file with search parameters, output parameters, and more
  - `constants.py`: parses CLI arguments and config.json into paths and other constants used by the scripts

- `out`: contains the results of scene searches, both for link lists and full scene extractions
  - `[Character name]` folder: contains extracted scenes for a specific character, in HTML format
  - `scene-links.txt`: contains a list of scenes with links to their messages, according to the filters set in `res/constants.py`
  - `log.txt`: global log of the tool's generic actions and API calls

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
    - `character.py` and `scene_manager.py`: helper classes to hold information about a character and scenes

- `ui`: contains the frontend for the web UI. It's built with Vite, React and TypeScrip

- `.env`: environment variables, used to store sensitive information like tokens, secrets, etc. ***DO NOT UPLOAD THIS FILE***
- `.env.example`: dummy example of .env meant to be uploaded to source control

- `install_socrates.bat`: installs the UI dependencies
- `start_socrates.bat`: launches the server and browser UI in local mode


## How to use in local (in case you want to help or play with it!)

(Note: These instructions are for its current state of development. They will change when the code is clean and adapted to use on other servers. They're a mess, I know. Ask me for more info if you need!)

- Create a folder named `DCE` and download the CLI version of https://github.com/Togekiss/DiscordChatExporter
  - ***IMPORTANT UPDATE:*** It will not work with the original version of the program. And Releases aren't working well, so download the CLI from 'Actions' or download the source code and compile it.
  - To compile it, download .NET 9 and C# Dev Kit extension in VSCode, right-click the `.sln` and click "Build". Or use Visual Studio i guess. Or `dotnet build -t:CSharpierFormat --configuration Release`. 

- Copy `.env.example` to `.env` and fill it in with your own secrets.

### Running the Web UI (Recommended)

Socrates now comes with a browser-based UI to manage configurations and run the pipeline.

If it's your first time launching it, run `install_socrates.bat` to install the UI dependencies.

Run `start_socrates.bat` to launch the server and browser UI in local mode. Then go to http://localhost:5173 in your browser to open it! It's that simple!

### Running via CLI (Manual approach)

- Check `res/config.json` to adjust settings like server info, verbosity, search filters and file paths. It's especially important if you don't have any backup yet.
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

Once launched, Socrates will use https://github.com/Tyrrrz/DiscordChatExporter to download the specified writing channels.

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
- ~~Detect the names of other character(s) in the scene~~ Their IDs are added to `_scenes.json`. The UI resolves them to their names!
- ~~Detect the true start of the scene, not the first message of the requested character~~ Done
  - ~~Trace back until you find a previous end tag or SOF to find the proper start~~
  - ~~Or until its from a character not in the scene, in case last wasn't closed properly~~
  - ~~Will most likely need an index attribute in the JSON to iterate back and forth~~

### Extra search parameters
*Note: Detecting all scenes is reasonably fast, so these are only filters to narrow down the final list given to the user. Internally, all scenes are accounted for.*
- ~~Input two characters and find scenes with them~~ The UI can filter by as many characters as you want
- ~~Input a date range~~ The UI can filter by a date range
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

## Cloud Deployment & Architecture

Socrates is fully containerized and deployed to Google Cloud Platform (GCP) and Firebase. The deployment is completely automated via GitHub Actions, and designed to scale-to-zero when not in use to save costs.

### Architecture Overview

- **Backend (API):** Python FastAPI + .NET 9 Runtime. Hosted on **Google Cloud Run**.
- **Frontend (UI):** Vite + React + TypeScript. Hosted on **Firebase Hosting**.
- **Data Storage:** `.JSON` files are stored in a **Google Cloud Storage (GCS)** bucket.
  - The bucket is mounted directly to the Cloud Run container via **GCS FUSE** at `/mnt/socrates-data`.
  - The backend uses the `SOCRATES_DATA_DIR` environment variable to transparently read/write to the FUSE mount as if it were a local disk.
- **Secrets:** Discord tokens, OAuth credentials, and JWT secrets are securely managed in **Google Secret Manager** and exposed to Cloud Run as environment variables. 
- **CI/CD Pipeline:** Two GitHub Actions in `.github/workflows` in [Togekiss/socrates-code](https://github.com/Togekiss/socrates-code):
  - `deploy-backend.yml`: Uses Cloud Build to package the Dockerfile and deploy to Cloud Run.
  - `deploy-frontend.yml`: Builds the Vite app and deploys to Firebase Hosting.

### Replicating the Setup / Debugging

If you ever need to set this up from scratch or debug the infrastructure, follow these steps:

1. **GCP Project & Services:**
   - Enable APIs: Cloud Run, Secret Manager, Artifact Registry.
   - Create a GCS Bucket for data storage.
   - Add backend secrets to Secret Manager.
2. **First Cloud Run Deployment (Manual):**
   - It is highly recommended to do the *first* deployment of the Cloud Run service via the GCP Web Console.
   - Deploy a sample container, attach the GCS bucket as a volume mount to `/mnt/socrates-data`, add `SOCRATES_DATA_DIR=/mnt/socrates-data` as an environment variable, and attach the secrets.
   - Once the "plumbing" is set up, the GitHub Action will overwrite the sample container with the actual Socrates backend without losing the volume/secret bindings.
3. **GitHub Actions Auth:**
   - Create a Service Account in GCP with roles: `Cloud Run Admin`, `Service Account User`, `Artifact Registry Writer`, `Cloud Build Editor`, `Storage Object Admin`, and `Firebase Hosting Admin`.
   - Export a JSON key and add it to your GitHub repository secrets as `GCP_CREDENTIALS`.
4. **Frontend Configuration:**
   - Backend URL defaults to `/api`.
   - Deployment uses `FirebaseExtended/action-hosting-deploy` with `entryPoint: ./ui`.


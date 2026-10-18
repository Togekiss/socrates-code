# Socrates, the record keeper of Elysium

## What is Socrates?

A Discord tool specifically made for Elysium, a RP server, with plans to adapt it to work on any roleplaying or collaborative writing server that uses similar tagging systems.

The primary goals of Socrates are:
1. **Archive RP History:** Download channel and thread message histories, restricted to roleplay channels.
2. **Index Tupperbox Characters:** Automatically detect Tupperbox bots, assign an ID to each of them, and save extra data like aliases, linked NPCs, and human writers.
3. **Automated Scene Detection:** Parse channels to find opening and end tags, or sudden changes in participating characters, to index roleplay scenes.
4. **Interactive Search & Curation:** Use a web interface to search characters and scenes using various filters, manage character groups and writers, and fix issues that the automated scene detection might have missed.
5. **Bonus: Chat Analysis Prepping:** Giving each Tupper a unique ID turns them into individual users to the eyes of tools like [Chat Analytics](https://github.com/mlomb/chat-analytics), that allow you to see cool numbers like which character says 'fuck' more often.

## AI usage disclosure

> **No agent, LLM or any other GenAI tool has access to data downloaded from Discord servers.** They can only see the code and configuration files. No one's messages or writing have been accessed by AI, so there is no risk of roleplays leaking or being used to train LLMs.
> 
> *Really- at some point, my agents thought I was working with Ace Attorney RP servers. That should tell you how blind they are lmao*


I use LLM agents (from a paid subscription, for added privacy) to help me implement features I am not familiar with, debug complex errors, and keep technical documentation updated.

The core logic of this program -what downloads backups, discovers characters, and detects when scenes start and end- **was done by me, entirely by hand,** back when LLMs were little more than glorified Google searches. Scene detection, fix suggestions and Discord user recognition are clever pattern recognition formulas, not AI.

---

## Current status

Socrates is in active development.

Currently, the Discord bot itself only serves as a hook to authenticate and export channels using DCE and its token.

Socrates can run locally or from the hosted cloud infrastructure (GCP and Firebase), and its basic functionality is robust in both deployment methods.

It has recently undergone a complete refactor to use **SQLite database per backup (`backup.sqlite`)** managed by **SQLAlchemy 2.0**, instead of loose JSON files.

The immediate next step is implementing special detection rules for chatroom and event scene detections.

After that, the focus will shift to turning it into a Discord iframe application so it can be opened directly from the Discord bot.

---

## Current architecture

- **Backend:** Python (FastAPI) + .NET 9 Runtime running in a Docker container on **Google Cloud Run** (or locally via Uvicorn).
- **Frontend:** Vite + React + TypeScript deployed to **Firebase Hosting** (or locally via `npm run dev`).
- **Data Persistence:**
  - **SQLite Database (`backup.sqlite`):** Runtime single source of truth per backup for metadata, channels, characters, writers, groups, scenes, issues, and overrides.
  - **Raw Chatlogs:** Raw Discord channel message JSONs are stored in `Data/` (mounted via **GCS FUSE** at `/mnt/socrates-data` in production, controlled by `SOCRATES_DATA_DIR`).
  - **Human-Readable Snapshots:** Optional atomic JSON exports (`backup_info.json`, `character_list.json`) generated on step completion when `debugFiles` is enabled.
- **Secrets:** Managed via **Google Secret Manager** in production and `.env` in local development.
- **CI/CD:** Managed via GitHub Actions in [Togekiss/socrates-code](https://github.com/Togekiss/socrates-code):
  - `deploy-backend.yml`: Source deployment to Cloud Run via Cloud Build.
  - `deploy-frontend.yml`: Deploys the Vite app to Firebase Hosting.

---

## Documentation

Comprehensive technical documentation is available in the [`docs/`](file:///d:/usuario/VSCode/socrates/docs) directory:

- [**System Architecture & Reference (`docs/README.md`)**](file:///d:/usuario/VSCode/socrates/docs/README.md): System overview, deployment topology, and data flow.
- [**Database Architecture & Schema (`docs/database_design.md`)**](file:///d:/usuario/VSCode/socrates/docs/database_design.md): Full 15-table relational schema, ERD, foreign keys, cascades, and WAL configuration.
- [**Component Implementation Map (`docs/component_map.md`)**](file:///d:/usuario/VSCode/socrates/docs/component_map.md): Module inventory across `src/db/`, `src/models/`, `src/*.py`, `src/server.py`, and `ui/src/`.
- [**Architectural Rules & Invariants (`docs/architectural_rules.md`)**](file:///d:/usuario/VSCode/socrates/docs/architectural_rules.md): Core invariants, JSON read whitelisting, atomic writes, and separation of concerns.
- [**Testing & Validation Guide (`docs/testing_and_validation.md`)**](file:///d:/usuario/VSCode/socrates/docs/testing_and_validation.md): Running unit, API, and integration test suites, reversible test grounding, and reset tooling.
- [**Design Notes & Common Pitfalls (`docs/pitfalls_and_design_notes.md`)**](file:///d:/usuario/VSCode/socrates/docs/pitfalls_and_design_notes.md): Windows WAL file locking, TanStack virtualizer dynamic heights, and API gotchas.

---

## Folder structure

See a detailed breakdown of the folder structure in [docs/README.md](file:///d:/usuario/VSCode/socrates/docs/README.md).

```text
socrates/
├── DCE/                     # Custom DiscordChatExporter CLI (.NET 9 binary)
├── Backups/                 # Backups directory
│   ├── backups_index.json   # Catalog mapping backup_id -> directory path
│   └── [Backup Name]/       # One folder per backup with its raw data and database
├── res/                     # Global configurations & constants
├── out/                     # Extracted HTML scenes and global logs
├── src/                     # Core Python backend
│   ├── server.py            # FastAPI server
│   ├── ****.py              # Scripts to download, index, and process data
│   ├── db/                  # Scripts to load, save, and query the database
│   ├── models/              # Models that describe and work with the data
│   └── utils/               # Shared utilities and exceptions
├── tests/                   # Automated regression test suites
└── ui/                      # Frontend web application (Vite + React + TS)

```

---

## How to run locally

(Note: These instructions are for its current state of development. They will change when the code is clean and adapted to use on other servers. They're a mess, I know. Ask me for more info if you need!)

### 1. Prerequisites
- **Python 3.12+** with a virtual environment:
  ```cmd
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
  ```
- **Node.js 18+** for the web frontend.
- Embedded **DCE**: `.NET 9` runtime if compiling DCE CLI from source.
  - ***IMPORTANT NOTE:*** It will not work with the original version of the program.
  - To compile it, download .NET 9 and C# Dev Kit extension in VSCode, right-click the `.sln` and click "Build". Or use Visual Studio i guess. Or `dotnet build -t:CSharpierFormat --configuration Release`. 
- Configure secrets: copy `.env.example` to `.env` and fill it in with your own secrets.

### 2. Running the Web UI (Recommended)
1. Install UI dependencies:
   ```cmd
   install_socrates.bat
   ```
2. Start both the FastAPI backend (`localhost:8000`) and the Vite frontend (`localhost:5173`):
   ```cmd
   start_socrates.bat
   ```
3. Open your browser at `http://localhost:5173`.

### 3. Running via CLI
To run pipeline operations manually from the terminal:
```cmd
:: Activate virtual environment
call .venv\Scripts\activate

:: 0. Check `res/config.json` to adjust settings like server info, select categories, or verbosity.
:: It's especially important if you don't have any backup yet.

:: 1. Run full backup or incremental update
python src/backup_server.py

:: 2. Re-assign tupper IDs to downloaded messages
python src/assign_ids.py

:: 3. Apply dialogue overrides & flag bad messages
python src/fix_bad_messages.py

:: 4. Re-index scenes across the backup
python src/index_scenes.py

:: 5. Extract scenes for a character to out/
python src/find_character_scenes.py
```

> Note: When Socrates stored characters and message overrides in JSON files, you could modify said files and re-run `assign_ids.py` and `fix_bad_messages.py` to update the changes. Now that it uses databases, it's highly recommended you edit those via the web UI instead of editing the SQLite database directly, and then re-run those steps.


### 4. Running regression tests
All tests run locally in the sandbox without requiring external database servers:
```cmd
:: Run all backend test suites
.venv\Scripts\python.exe -m unittest discover tests

:: Reset test backup to pristine state after test runs
.venv\Scripts\python.exe tests/reset_test_backup.py

:: Verify frontend build and linting
cd ui && npm run build && npm run lint
```

---

## How does it work?

Given the use of Tupperbox to send message as roleplaying characters, native Discord search is unable to look for messages from a particular one.

1. Once launched, Socrates will use [DiscordChatExporter](https://github.com/Togekiss/DiscordChatExporter) to download the specified writing channels.
2. On updates, it will only download messages starting from the last backup, and then carefully merge the new messages into the main backup files, preserving channel name modifications without removing any that may have been deleted.


3. Then it will traverse through the exported .JSON files to detect all the unique Tupperbox-made characters and manually gives each a unique ID and registers them in the database.

4. Then it works on fixing message issues: it finds messages not sent by a tupper and saves them, and applies all manually created patches to the backup.

5. After exporting the backup, Socrates analyzes all the channels to find scenes. It looks for scene closing tags like `[END]` or a sudden change in participants. With this, it creates lists of scenes with links to the message it starts and ends, which characters are participants, if it's closed or open, etc. and saves those in the database.

6. When you want to find scenes with one or more characters, by writter, by time, or any other filter, you can use the UI and Socrates will find those in the database in less than 5 milliseconds.

---

## Things to implement

### Scene detection tuning
- Work on a different set of rules to log open interactions, like chatrooms or events
- Check if a scene starts with a date tag for more accurate in-universe timeline keeping
- ~~Expand and adjust the selection of 'end of scene' tags - and account for variations or mistakes~~ Doesn't detect super edge cases, but that's a skill issue of whoever didn't set them correctly
  - If a badly formatted message is found, it can be added to the database with proper formatting and use `src/fix_bad_messages.py` to apply it
- ~~Detect the names of other character(s) in the scene~~ Done
- ~~Detect the true start of the scene, not the first message of the requested character~~ Done
  - ~~Trace back until you find a previous end tag or SOF to find the proper start~~
  - ~~Or until its from a character not in the scene, in case last wasn't closed properly~~
  - ~~Will most likely need an index attribute in the JSON to iterate back and forth~~

### Curation
- Get more writer link suggestions from other channels or from Discord API itself
- Suggest non-tupper messages auto-fix by using one of the scene's tupper characters, preferrably if the discord user has a registered character in the scene
 
### Extra search parameters
*Note: Detecting all scenes is reasonably fast, so these are only filters to narrow down the final list given to the user. Internally, all scenes are accounted for.*
All these filters are in the UI
- ~~Input two characters and find scenes with them~~
- ~~Input a date range~~
- ~~Input a specific channel/category to look in~~ 
  - ~~Load only the category folder or channel file and operate as usual~~
  - ~~This will be especially useful to differenciate scenes from DMs~~
- ~~Input a scene status (Closed, Active, Timed out)~~

### Chanel exporting

- ~~Make a cumulative scene detection to not analyze the whole thing every time~~ It's fast enough to not need this
- ~~Order threads by creation date~~
- ~~It'd be cool to add "number of messages, number of scenes" in `backup_info.json`~~

### Releasing it to the public
- Turn it into a discord iFrame
- Add stronger separation between server members and admins
- Create a 'backupless' mode to analyze straight from Discord- I don't want to host other people's servers


- Schedule a weekly backup of channels
  - Add a fast search option (against the last download) vs updated search option (update the backup and then search)


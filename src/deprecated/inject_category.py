import sys
import json
import shutil
from pathlib import Path

# Add src to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, (PROJECT_ROOT / "src").as_posix())
sys.path.insert(0, PROJECT_ROOT.as_posix())

import utils.tricks as t
from models.backup_context import BackupContext
from models import ServerBackup, Category, Channel, Thread, CharacterList
from assign_ids import assign_ids_in_file
from index_scenes import index_scenes
from res import constants as c

"""
INSTRUCTIONS

This script is meant to be a quick hack to add a whole new category to an existing backup.
We need this because "updating" only downloads starting from the last update date.

Before running:
- Open a random file in Backups/<backup>/Data and write down the "exportedAt" value
- Use DCE to manually download said category into Backups/<backup>/Data.
  Use the command in src/download_channels.py to make sure they have the correct name pattern,
  and add "--before <exportedAt date>" to the command
- If the category position clashed with an existing one, just change the folder name to a free number
- Once it's done downloading, change the constants in this script and run it
  - If injecting an event category (EVENT, EVENT STORAGE, NSFW Events), set IS_EVENT = True
    It will automatically normalize the category and channels into the faux 'Events' category ('event-1..N')
    and index all events and character movements into SQLite!
  - If injecting a regular RP or chatroom category, leave IS_EVENT = False

At any point:
- Check Backups/<backup>/backup_config.json and make sure the new category is added there
"""

BACKUP_ID = "1"
BACKUP_PATH = "Backups/Elysium"
CATEGORY_NAME = "Events"
IS_EVENT = True  # Set to True when injecting an event category (e.g. EVENT, EVENT STORAGE, NSFW Events, Events)


def inject_category(
    backup_id: str = BACKUP_ID,
    backup_path: str = BACKUP_PATH,
    category_name: str = CATEGORY_NAME,
    is_event: bool = IS_EVENT,
) -> None:
    # 1. Back up database first
    sqlite_path = Path(backup_path) / "backup.sqlite"
    if sqlite_path.exists():
        shutil.copy2(sqlite_path, sqlite_path.with_suffix(".sqlite.bak_pre_inject"))
        print(f"Created safety backup at {sqlite_path}.bak_pre_inject")

    # 2. Enter Backup Context
    ctx_mgr = (
        BackupContext.create(backup_id=backup_id, backup_path=backup_path)
        if backup_path
        else BackupContext.from_backup_id(backup_id)
    )
    with ctx_mgr:
        data_dir = Path(backup_path) / "Data"

        # Locate category folder
        cat_dirs = [d for d in data_dir.iterdir() if d.is_dir() and category_name.lower() in d.name.lower()]
        if not cat_dirs:
            print(f"Error: Could not find folder matching '{category_name}' in {data_dir}")
            sys.exit(1)
        cat_dir = cat_dirs[0]
        cat_pos = int(cat_dir.name.split("#")[0]) if "#" in cat_dir.name else 28

        # Read channel files
        chan_files = sorted([f for f in cat_dir.glob("*.json") if not f.name.startswith("_")])
        if not chan_files:
            print("Error: No channel JSON files found in category folder.")
            sys.exit(1)

        # Grab category discord snowflake from the first channel file
        with open(chan_files[0], "r", encoding="utf-8") as f:
            first_payload = json.load(f)
        cat_discord_id = str(first_payload["channel"]["categoryId"])
        print(f"Found Category: {category_name} (Discord ID: {cat_discord_id}, Pos: {cat_pos})")

        # Load SQLite backup state
        backup = ServerBackup.load(scope="base", backup_id=backup_id, backup_path=backup_path)

        new_cat = Category(
            id=cat_discord_id,
            name=category_name,
            position=cat_pos,
            path=cat_dir.name,
        )

        def normalize_date_range(data: dict) -> bool:
            date_range = data.get("dateRange")
            if date_range and date_range.get("before"):
                data["exportedAt"] = date_range["before"]
                date_range["before"] = None
                return True
            return False

        for cf in chan_files:
            with open(cf, "r", encoding="utf-8") as f:
                cdata = json.load(f)
            if normalize_date_range(cdata):
                t.save_to_json(cdata, cf.as_posix())

            ch_info = cdata["channel"]
            chan_pos = int(cf.name.split("#")[0]) if "#" in cf.name else 0
            msg_count = len(cdata.get("messages", []))

            ch_model = Channel(
                id=str(ch_info["id"]),
                name=ch_info["name"],
                position=chan_pos,
                path=f"{cat_dir.name}/{cf.name}",
                messages=msg_count,
            )
            new_cat.add_channel(ch_model)
            print(f"  + Channel: #{ch_info['name']} (ID: {ch_info['id']}, Pos: {chan_pos}, Msgs: {msg_count})")

        # Handle threads if present
        threads_dir = cat_dir / "Threads"
        if threads_dir.exists():
            for tf in sorted(threads_dir.glob("*.json")):
                with open(tf, "r", encoding="utf-8") as f:
                    tdata = json.load(f)
                if normalize_date_range(tdata):
                    t.save_to_json(tdata, tf.as_posix())

                th_info = tdata["channel"]
                parent_id = str(th_info.get("categoryId"))
                parent_ch = new_cat.get_channel_by_id(parent_id)
                if parent_ch:
                    th_pos = int(tf.name.split("#")[0].split("-")[1]) if "-" in tf.name else 0
                    th_model = Thread(
                        id=str(th_info["id"]),
                        name=th_info["name"],
                        position=th_pos,
                        path=f"{cat_dir.name}/Threads/{tf.name}",
                        messages=len(tdata.get("messages", [])),
                    )
                    parent_ch.add_thread(th_model)
                    print(f"    + Thread: {th_info['name']} (ID: {th_info['id']})")

        if is_event:
            # Update backup_config.json if present
            cfg_path = Path(backup_path) / "backup_config.json"
            if cfg_path.exists():
                cfg = t.load_from_json(cfg_path.as_posix())
                admin = cfg.setdefault("admin", {})
                ev_cats = admin.setdefault("eventCategories", [])
                for name in (category_name, "Events"):
                    if name not in ev_cats:
                        ev_cats.append(name)
                keep_cats = admin.setdefault("categoriesToKeep", [])
                for name in (category_name, "Events"):
                    if name not in keep_cats:
                        keep_cats.append(name)
                ign_cats = admin.get("categoriesToIgnore", [])
                admin["categoriesToIgnore"] = [c_name for c_name in ign_cats if c_name not in (category_name, "Events")]
                t.save_json_atomic(cfg, cfg_path.as_posix())

            # Ensure runtime context has event categories
            if not hasattr(c, "EVENT_CATEGORIES") or not c.EVENT_CATEGORIES:
                c.EVENT_CATEGORIES = []
            for name in (category_name, "Events"):
                if name not in c.EVENT_CATEGORIES:
                    c.EVENT_CATEGORIES.append(name)

            # Register category and normalize into faux 'Events' category ('event-1..N')
            backup.categories = [cat for cat in backup.categories if cat.id != cat_discord_id]
            backup.add_new_category(new_cat)

            from update_paths import normalize_event_categories
            normalize_event_categories(backup, folder=data_dir.as_posix(), is_update=False)
            backup.save(write_snapshot=True)
            print("-> Successfully registered and normalized event category in backup.sqlite!")
        else:
            # Save to SQLite (replaces old entry if already registered)
            backup.categories = [cat for cat in backup.categories if cat.id != cat_discord_id]
            backup.add_new_category(new_cat)
            backup.sort_categories()
            backup.save(write_snapshot=True)
            print("-> Successfully registered category and channels in backup.sqlite!")

        # 3. Assign Tupper IDs for new files
        print("\nAssigning Tupper IDs in new files...")
        char_list = CharacterList.load(backup_id=backup_id, base_path=backup_path)
        target_cats = (
            [cat for cat in backup.categories if cat.id == "events_category" or cat.name == "Events"]
            if is_event
            else [cat for cat in backup.categories if cat.id == cat_discord_id]
        )
        for target_cat in target_cats:
            for ch in target_cat.channels:
                assign_ids_in_file((data_dir / ch.path).as_posix(), char_list)
                for thr in ch.threads:
                    assign_ids_in_file((data_dir / thr.path).as_posix(), char_list)
        char_list.save()
        print("-> Tupper characters resolved and saved to database.")

        # 4. Index scenes across all categories (scenes, chat sessions, and events)
        print("\nIndexing scenes...")
        index_scenes(backup_id=backup_id, backup_path=backup_path)
        print("-> Done! Scenes, sessions, and events indexed and saved to backup.sqlite.")


if __name__ == "__main__":
    inject_category()

import sys
import json
import shutil
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, "src")

import utils.tricks as t
from models.backup_context import BackupContext
from models import ServerBackup, Category, Channel, Thread, CharacterList
from assign_ids import assign_ids_in_file
from index_sessions import index_sessions

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

At any point:
- Check Backups/<backup>/backup_config.json and make sure the new category is added there

"""

BACKUP_ID = "1"
BACKUP_PATH = "Backups/Elysium"
CATEGORY_NAME = "Group Chats"

# 1. Back up database first
sqlite_path = Path(BACKUP_PATH) / "backup.sqlite"
shutil.copy2(sqlite_path, sqlite_path.with_suffix(".sqlite.bak_pre_inject"))
print(f"Created safety backup at {sqlite_path}.bak_pre_inject")

# 2. Enter Backup Context
with BackupContext.from_backup_id(BACKUP_ID):
    data_dir = Path(BACKUP_PATH) / "Data"
    
    # Locate category folder
    cat_dirs = [d for d in data_dir.iterdir() if d.is_dir() and CATEGORY_NAME.lower() in d.name.lower()]
    if not cat_dirs:
        print(f"Error: Could not find folder matching '{CATEGORY_NAME}' in {data_dir}")
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
    print(f"Found Category: {CATEGORY_NAME} (Discord ID: {cat_discord_id}, Pos: {cat_pos})")

    # Load SQLite backup state
    backup = ServerBackup.load(scope="base", backup_id=BACKUP_ID, backup_path=BACKUP_PATH)

    new_cat = Category(
        id=cat_discord_id,
        name=CATEGORY_NAME,
        position=cat_pos,
        path=cat_dir.name
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
            t.save_to_json(cdata, cf)

        ch_info = cdata["channel"]
        chan_pos = int(cf.name.split("#")[0]) if "#" in cf.name else 0
        msg_count = len(cdata.get("messages", []))

        ch_model = Channel(
            id=str(ch_info["id"]),
            name=ch_info["name"],
            position=chan_pos,
            path=f"{cat_dir.name}/{cf.name}",
            messages=msg_count
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
                t.save_to_json(tdata, tf)

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
                    messages=len(tdata.get("messages", []))
                )
                parent_ch.add_thread(th_model)
                print(f"    + Thread: {th_info['name']} (ID: {th_info['id']})")

    # Save to SQLite (replaces old entry if already registered)
    backup.categories = [c for c in backup.categories if c.id != cat_discord_id]
    backup.add_new_category(new_cat)
    backup.sort_categories()
    backup.save()
    print("-> Successfully registered category and channels in backup.sqlite!")

    # 3. Assign Tupper IDs for new files
    print("\nAssigning Tupper IDs in new files...")
    char_list = CharacterList.load(backup_id=BACKUP_ID, base_path=BACKUP_PATH)
    for ch in new_cat.channels:
        assign_ids_in_file((data_dir / ch.path).as_posix(), char_list)
        for thr in ch.threads:
            assign_ids_in_file((data_dir / thr.path).as_posix(), char_list)
    char_list.save()
    print("-> Tupper characters resolved and saved to database.")

    # 4. Index Chat Sessions
    print("\nDetecting and indexing chat sessions...")
    sessions = index_sessions(backup_id=BACKUP_ID, backup_path=BACKUP_PATH)
    print(f"-> Done! {len(sessions)} chat sessions saved to backup.sqlite.")
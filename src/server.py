import os
import sys
import json
import subprocess
import time

################ File summary #################

"""
This module serves as the FastAPI backend for Socrates. It exposes REST API endpoints 
that the React frontend uses to query, manage, and execute background tasks related 
to Discord backups.

Main functionality:
    - Managing and tracking subprocesses for downloading and parsing Discord backups.
    - Providing read/write access to `backup_info.json`, configurations, and logs.
    - Exposing endpoints for complex Scene filtering with pagination.
    - Exposing endpoints for manipulating the Character data (merging, nesting, renaming).
"""

###############################################

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional

class MergeCharactersRequest(BaseModel):
    source_id: int
    target_id: int

class NestCharacterRequest(BaseModel):
    child_id: int
    parent_id: int
    version_type: str = "npc"

class UpdateCharacterRequest(BaseModel):
    tags: Optional[List[str]] = None
    names: Optional[List[str]] = None
    writer: Optional[List[str]] = None

# Add src to sys.path so that 'utils' can be imported
sys.path.insert(0, os.path.dirname(__file__))
import utils.tricks as t

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def get_backup_path(backup_id: str):
    index = t.get_backups_index()
    for b in index:
        if b["backup_id"] == backup_id:
            return os.path.join(get_project_root(), b["path"])
    raise HTTPException(status_code=404, detail="Backup ID not found in index")

def api_log(backup_id: str, level: str, message: str):
    import datetime
    try:
        base_path = get_backup_path(backup_id)
        log_path = os.path.join(base_path, "log.txt")
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}]{level}: API: {message}\n")
    except Exception:
        # Fallback to global log if backup_id is invalid
        t.global_log(level, f"API ({backup_id}): {message}")

@app.get("/api/config/global")
def get_global_config():
    config_path = os.path.join(get_project_root(), 'res', 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/config/global")
def update_global_config(config: Dict[str, Any]):
    config_path = os.path.join(get_project_root(), 'res', 'config.json')
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/backups")
def get_backups():
    return t.get_backups_index()

@app.get("/api/backups/{backup_id}")
def get_backup_info(backup_id: str):
    base_path = get_backup_path(backup_id)
    info_path = os.path.join(base_path, 'Info', 'backup_info.json')
    char_path = os.path.join(base_path, 'Info', 'character_list.json')
    
    if not os.path.exists(info_path):
        raise HTTPException(status_code=404, detail="Backup info file not found")
        
    data = t.load_from_json(info_path)
    
    # Augment with character count
    data["number_of_characters"] = 0
    if os.path.exists(char_path):
        try:
            char_data = t.load_from_json(char_path)
            if isinstance(char_data, list):
                data["number_of_characters"] = len(char_data)
            elif "characters" in char_data:
                data["number_of_characters"] = len(char_data["characters"])
        except Exception:
            pass
            
    return data

@app.get("/api/backups/{backup_id}/config")
def get_backup_config(backup_id: str):
    base_path = get_backup_path(backup_id)
    config_path = os.path.join(base_path, 'backup_config.json')
    if not os.path.exists(config_path):
        # Fallback to global config if local doesn't exist yet
        return get_global_config()
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

active_processes: Dict[str, subprocess.Popen] = {}

def run_script_in_background(script_name: str, backup_id: str):
    # Use the python executable from the virtual environment if possible
    python_exec = sys.executable
    script_path = os.path.join(get_project_root(), 'src', script_name)
    process = subprocess.Popen([python_exec, script_path, '--backup-id', backup_id])
    active_processes[backup_id] = process
    process.wait()
    if backup_id in active_processes:
        del active_processes[backup_id]

@app.post("/api/backups/{backup_id}/cancel")
def cancel_backup_action(backup_id: str):
    if backup_id in active_processes:
        process = active_processes[backup_id]
        process.terminate()  # Sends SIGTERM, equivalent to CTRL+C for the subprocess
        del active_processes[backup_id]
        t.global_log("info", f"API: Canceled ongoing process for backup {backup_id}")
        return {"status": "canceled"}
    return {"status": "not_running"}

@app.post("/api/backups/{backup_id}/run")
def run_backup(backup_id: str, config: Dict[str, Any], background_tasks: BackgroundTasks):
    base_path = get_backup_path(backup_id)
    config_path = os.path.join(base_path, 'backup_config.json')
    
    # Save the config
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        t.global_log("error", f"API: Failed to save config for backup {backup_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save backup config: {e}")
    
    t.global_log("info", f"API: Starting backup pipeline for {backup_id}...")
    background_tasks.add_task(run_script_in_background, 'backup_server.py', backup_id)
    return {"status": "started"}

@app.post("/api/backups/{backup_id}/rerun/{action}")
def rerun_backup_step(backup_id: str, action: str, background_tasks: BackgroundTasks):
    action_map = {
        "reapply_characters": "assign_ids.py",
        "fix_messages": "fix_messages.py",
        "reindex": "index_scenes.py"
    }
    
    if action not in action_map:
        raise HTTPException(status_code=400, detail=f"Invalid action. Allowed actions are: {', '.join(action_map.keys())}")
        
    script_name = action_map[action]
    t.global_log("info", f"API: Rerunning {action} for backup {backup_id}...")
    background_tasks.add_task(run_script_in_background, script_name, backup_id)
    return {"status": "started", "action": action}

@app.post("/api/backups")
def create_new_backup(config: Dict[str, Any], background_tasks: BackgroundTasks):
    global_config_path = os.path.join(get_project_root(), 'res', 'config.json')
    try:
        with open(global_config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        t.global_log("error", f"API: Failed to save global config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update global config: {e}")
        
    t.global_log("info", f"API: Creating new backup pipeline from global config...")
    python_exec = sys.executable
    script_path = os.path.join(get_project_root(), 'src', 'backup_server.py')
    subprocess.Popen([python_exec, script_path])
    
    return {"status": "started", "detail": "Starting new backup pipeline. Check global logs."}

@app.get("/api/backups/{backup_id}/characters")
def get_characters(backup_id: str):
    base_path = get_backup_path(backup_id)
    char_path = os.path.join(base_path, 'Info', 'character_list.json')
    if not os.path.exists(char_path):
        raise HTTPException(status_code=404, detail="Character list not found")
    return t.load_from_json(char_path)

@app.post("/api/backups/{backup_id}/characters/merge")
def merge_characters(backup_id: str, req: MergeCharactersRequest):
    api_log(backup_id, "info", f"Merging character {req.source_id} into {req.target_id}...")
    base_path = get_backup_path(backup_id)
    char_path = os.path.join(base_path, 'Info', 'character_list.json')
    from models import CharacterList
    char_list = CharacterList.load(char_path)
    try:
        char_list.merge_characters(req.source_id, req.target_id)
        char_list.save(char_path)
        api_log(backup_id, "base", "Merge completed successfully.")
        return {"status": "success"}
    except Exception as e:
        api_log(backup_id, "error", f"Merge failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/backups/{backup_id}/characters/nest")
def nest_character(backup_id: str, req: NestCharacterRequest):
    api_log(backup_id, "info", f"Nesting character {req.child_id} under {req.parent_id} as {req.version_type}...")
    base_path = get_backup_path(backup_id)
    char_path = os.path.join(base_path, 'Info', 'character_list.json')
    from models import CharacterList
    char_list = CharacterList.load(char_path)
    try:
        char_list.nest_character(req.child_id, req.parent_id, req.version_type)
        char_list.save(char_path)
        api_log(backup_id, "base", "Nest completed successfully.")
        return {"status": "success"}
    except Exception as e:
        api_log(backup_id, "error", f"Nest failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/backups/{backup_id}/characters/{char_id}/unnest")
def unnest_character(backup_id: str, char_id: int):
    api_log(backup_id, "info", f"Unnesting character {char_id}...")
    base_path = get_backup_path(backup_id)
    char_path = os.path.join(base_path, 'Info', 'character_list.json')
    from models import CharacterList
    char_list = CharacterList.load(char_path)
    try:
        char_list.unnest_character(char_id)
        char_list.save(char_path)
        api_log(backup_id, "base", "Unnest completed successfully.")
        return {"status": "success"}
    except Exception as e:
        api_log(backup_id, "error", f"Unnest failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/backups/{backup_id}/characters/{char_id}")
def update_character(backup_id: str, char_id: int, req: UpdateCharacterRequest):
    api_log(backup_id, "info", f"Updating character {char_id} attributes...")
    base_path = get_backup_path(backup_id)
    char_path = os.path.join(base_path, 'Info', 'character_list.json')
    from models import CharacterList
    char_list = CharacterList.load(char_path)
    
    char, _ = char_list.find_character(char_id)
    if not char:
        api_log(backup_id, "error", f"Character {char_id} not found.")
        raise HTTPException(status_code=404, detail="Character not found")
        
    if req.tags is not None:
        char.tags = req.tags
    if req.names is not None:
        char.names = req.names
    if req.writer is not None:
        char.writer = req.writer
        
    char_list.save(char_path)
    api_log(backup_id, "base", "Attributes updated successfully.")
    return {"status": "success", "character": char.to_dict()}

@app.get("/api/backups/{backup_id}/scenes")
def get_scenes(
    backup_id: str,
    page: int = Query(1),
    per_page: int = Query(50),
    categories: Optional[List[str]] = Query(None),
    statuses: Optional[List[str]] = Query(None),
    types: Optional[List[str]] = Query(None),
    characters: Optional[List[int]] = Query(None),
    character_logic: str = Query('OR'),
    writers: Optional[List[str]] = Query(None),
    writer_logic: str = Query('OR'),
    before: Optional[str] = Query(None),
    after: Optional[str] = Query(None)
):
    base_path = get_backup_path(backup_id)
    char_path = os.path.join(base_path, 'Info', 'character_list.json')
    from models import SceneManager, CharacterList
    
    char_list = None
    if writers and os.path.exists(char_path):
        char_list = CharacterList.load(char_path)
        
    manager = SceneManager.get_instance(backup_id, base_path)
    
    return manager.get_paginated_scenes(
        page=page,
        per_page=per_page,
        categories=categories,
        statuses=statuses,
        types=types,
        character_ids=characters,
        character_logic=character_logic,
        writer_names=writers,
        writer_logic=writer_logic,
        char_list=char_list,
        before=before,
        after=after
    )

@app.get("/api/backups/{backup_id}/writers")
def get_writers(backup_id: str):
    base_path = get_backup_path(backup_id)
    char_path = os.path.join(base_path, 'Info', 'character_list.json')
    from models import CharacterList
    char_list = CharacterList.load(char_path)
    
    writers = set()
    for char in char_list.characters:
        for w in char.writer:
            writers.add(w)
        for alt in char.other_versions:
            for w in alt.writer:
                writers.add(w)
                
    return sorted(list(writers))

@app.get("/api/backups/{backup_id}/logs/stream")
def stream_logs(backup_id: str):
    base_path = get_backup_path(backup_id)
    log_file = os.path.join(base_path, "log.txt")
    
    def log_generator():
        # Wait for the file to be created if it doesn't exist yet
        for _ in range(20):
            if os.path.exists(log_file): break
            time.sleep(0.5)
            
        if not os.path.exists(log_file):
            yield "data: [Log file not found]\n\n"
            return
            
        with open(log_file, mode='r', encoding='utf-8') as f:
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.1)
                else:
                    yield f"data: {line.strip()}\n\n"
                    
    return StreamingResponse(log_generator(), media_type="text/event-stream")

@app.get("/api/logs/global")
def get_global_logs(lines: int = Query(100)):
    global_log_file = os.path.join(get_project_root(), "out", "log.txt")
    if not os.path.exists(global_log_file):
        return {"logs": []}
        
    try:
        with open(global_log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            
        # Return last N lines
        return {"logs": [line.strip() for line in all_lines[-lines:]]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/logs/global")
def clear_global_logs():
    log_path = os.path.join(get_project_root(), "out", "log.txt")
    if os.path.exists(log_path):
        open(log_path, "w").close()
    return {"status": "cleared"}


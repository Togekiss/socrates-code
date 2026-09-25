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

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Depends, Cookie, Response, Request
from fastapi.responses import StreamingResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import httpx
import jwt
import urllib.parse
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

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

cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://socrates-backend-509220.web.app",
    "https://socrates-backend-509220.firebaseapp.com",
]
extra_origins = os.environ.get("CORS_ORIGINS")
if extra_origins:
    cors_origins.extend([o.strip() for o in extra_origins.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$|^https://socrates-backend-509220\.(web\.app|firebaseapp\.com)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def get_data_root():
    return os.environ.get("SOCRATES_DATA_DIR", get_project_root())

load_dotenv(os.path.join(get_project_root(), '.env'))

def get_backup_path(backup_id: str):
    index = t.get_backups_index()
    for b in index:
        if b["backup_id"] == backup_id:
            return os.path.join(get_data_root(), b["path"])
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

# --- AUTHENTICATION ---

class AuthCallback(BaseModel):
    code: str

def get_auth_config():
    return {
        "client_id": os.environ.get("DISCORD_CLIENT_ID"),
        "client_secret": os.environ.get("DISCORD_CLIENT_SECRET"),
        "redirect_uri": os.environ.get("DISCORD_REDIRECT_URI"),
        "jwt_secret": os.environ.get("JWT_SECRET", "dev_secret"),
        "bot_token": os.environ.get("DISCORD_TOKEN")
    }

def get_session_token(request: Request) -> Optional[str]:
    # Firebase Hosting rewrite CDN only preserves '__session'; fallback to 'session_token' for dev/direct access
    return request.cookies.get("__session") or request.cookies.get("session_token")

def get_current_user(request: Request):
    token = get_session_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        config = get_auth_config()
        payload = jwt.decode(token, config["jwt_secret"], algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session")

def get_optional_user(request: Request):
    token = get_session_token(request)
    if not token:
        return None
    try:
        config = get_auth_config()
        payload = jwt.decode(token, config["jwt_secret"], algorithms=["HS256"])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

@app.get("/api/auth/login-url")
def get_login_url():
    config = get_auth_config()
    if not config["client_id"] or not config["redirect_uri"]:
        raise HTTPException(status_code=500, detail="OAuth not configured")
    
    url = "https://discord.com/api/oauth2/authorize?" + urllib.parse.urlencode({
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": "identify guilds"
    })
    return {"url": url}

@app.post("/api/auth/discord")
async def auth_discord(callback: AuthCallback, response: Response, request: Request):
    config = get_auth_config()
    if not config["client_id"] or not config["client_secret"]:
        raise HTTPException(status_code=500, detail="OAuth not configured")

    async with httpx.AsyncClient() as client:
        # 1. Exchange code for user access token
        token_resp = await client.post("https://discord.com/api/v10/oauth2/token", data={
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "grant_type": "authorization_code",
            "code": callback.code,
            "redirect_uri": config["redirect_uri"]
        })
        if token_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Invalid authorization code")
        
        token_data = token_resp.json()
        access_token = token_data.get("access_token")

        # 2. Get user info
        user_resp = await client.get("https://discord.com/api/v10/users/@me", headers={"Authorization": f"Bearer {access_token}"})
        if user_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch user info")
        user_data = user_resp.json()

        # 3. Get user's guilds
        guilds_resp = await client.get("https://discord.com/api/v10/users/@me/guilds", headers={"Authorization": f"Bearer {access_token}"})
        if guilds_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch user guilds")
        user_guilds_raw = guilds_resp.json()
        user_guilds = {str(g["id"]) for g in user_guilds_raw}
        user_guilds_dict = {str(g["id"]): g["name"] for g in user_guilds_raw}

        # 4. Get bot's guilds
        bot_token = config["bot_token"]
        bot_guilds = set()
        if bot_token:
            bot_guilds_resp = await client.get("https://discord.com/api/v10/users/@me/guilds", headers={"Authorization": f"Bot {bot_token}"})
            if bot_guilds_resp.status_code == 200:
                bot_guilds = {str(g["id"]) for g in bot_guilds_resp.json()}
            else:
                t.global_log("error", f"API: Failed to fetch bot guilds: {bot_guilds_resp.text}")

        # Fallback to backups index
        index = t.get_backups_index()
        for b in index:
            if "server_id" in b:
                bot_guilds.add(str(b["server_id"]))
                
        # 5. Check overlap
        authorized_guilds_ids = list(user_guilds.intersection(bot_guilds))
        
        if not authorized_guilds_ids:
            raise HTTPException(status_code=403, detail="User is not a member of any authorized servers")

        # Build list of dicts with names
        authorized_guilds = []
        for gid in authorized_guilds_ids:
            name = user_guilds_dict.get(gid, "Unknown Server")
            authorized_guilds.append({"id": gid, "name": name})

        # 6. Issue JWT
        exp = datetime.now(timezone.utc) + timedelta(hours=24)
        payload = {
            "sub": user_data["id"],
            "username": user_data["username"],
            "avatar": user_data.get("avatar"),
            "authorized_guilds": authorized_guilds,
            "exp": exp
        }
        
        token = jwt.encode(payload, config["jwt_secret"], algorithm="HS256")
        
        # In production/HTTPS, use secure cookies. Firebase CDN exclusively preserves '__session'.
        is_secure = request.headers.get("x-forwarded-proto") == "https" or bool(os.environ.get("K_SERVICE"))

        response.set_cookie(
            key="__session",
            value=token,
            httponly=True,
            samesite="lax",
            secure=is_secure,
            max_age=24 * 60 * 60
        )
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            samesite="lax",
            secure=is_secure,
            max_age=24 * 60 * 60
        )

        return {"status": "success", "user": {"id": user_data["id"], "username": user_data["username"]}}

@app.post("/api/auth/logout")
def logout(response: Response, request: Request):
    is_secure = request.headers.get("x-forwarded-proto") == "https" or bool(os.environ.get("K_SERVICE"))
    response.delete_cookie("session_token", httponly=True, samesite="lax", secure=is_secure)
    response.delete_cookie("__session", httponly=True, samesite="lax", secure=is_secure)
    return {"status": "success"}

@app.get("/api/auth/me")
def get_me(user = Depends(get_optional_user)):
    return {"user": user}

# --- END AUTHENTICATION ---

@app.get("/api/servers/{server_id}/categories")
def get_server_categories(server_id: str):
    from get_server_info import get_categories
    try:
        categories = get_categories(server_id)
        return categories
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config/global")
def get_global_config():
    config_path = os.path.join(get_data_root(), 'res', 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/config/global")
def update_global_config(config: Dict[str, Any]):
    config_path = os.path.join(get_data_root(), 'res', 'config.json')
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/backups")
def get_backups(user = Depends(get_current_user)):
    auth_guilds = user.get("authorized_guilds", [])
    authorized_guilds = set()
    for g in auth_guilds:
        if isinstance(g, dict):
            authorized_guilds.add(str(g.get("id")))
        else:
            authorized_guilds.add(str(g))
            
    all_backups = t.get_backups_index()
    return [b for b in all_backups if str(b.get("server_id", "")) in authorized_guilds]

@app.get("/api/backups-paths")
def get_all_backup_paths(user = Depends(get_current_user)):
    all_backups = t.get_backups_index()
    return [b.get("path") for b in all_backups if "path" in b]

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
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        
    process = subprocess.Popen([python_exec, script_path, '--backup-id', backup_id], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    active_processes[backup_id] = process
    process.wait()
    if backup_id in active_processes:
        del active_processes[backup_id]

@app.post("/api/backups/{backup_id}/cancel")
def cancel_backup_action(backup_id: str):

    t.global_log("info", f"API: Received cancel request for backup {backup_id}")

    if backup_id in active_processes:
        process = active_processes[backup_id]
        import signal
        if os.name == 'nt':
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
            
        # The background task will delete the process from active_processes once it finishes exiting
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
        "fix_messages": "fix_bad_messages.py",
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
    global_config_path = os.path.join(get_data_root(), 'res', 'config.json')
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

@app.get("/api/backups/{backup_id}/logs/raw")
def get_raw_log(backup_id: str):
    base_path = get_backup_path(backup_id)
    log_file = os.path.join(base_path, "log.txt")
    if not os.path.exists(log_file):
        raise HTTPException(status_code=404, detail="Log file not found")
    return FileResponse(log_file, media_type="text/plain")

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
            # Yield the last 10 lines instantly to avoid UI fast-forwarding
            from collections import deque
            last_lines = deque(f, 10)
            for line in last_lines:
                yield f"data: {line.strip()}\n\n"
                
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.1)
                else:
                    yield f"data: {line.strip()}\n\n"
                    
    return StreamingResponse(log_generator(), media_type="text/event-stream")

@app.get("/api/logs/global")
def get_global_logs(lines: int = Query(100)):
    global_log_file = os.path.join(get_data_root(), "out", "log.txt")
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
    log_path = os.path.join(get_data_root(), "out", "log.txt")
    if os.path.exists(log_path):
        open(log_path, "w").close()
    return {"status": "cleared"}


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
    - Providing read/write access to backup configurations and logs.
    - Exposing endpoints for complex Scene filtering with pagination via SQLite.
    - Exposing endpoints for manipulating Characters, Writers, Groups, Scene Issues,
      Flagged Messages, and Overrides backed exclusively by SQLite.
"""

###############################################

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Depends, Cookie, Response, Request, Body
from fastapi.responses import StreamingResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import httpx
import jwt
from pathlib import Path
import urllib.parse
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Add src to sys.path so that 'utils' and 'db' can be imported
sys.path.insert(0, Path(__file__).resolve().parent.as_posix())
import utils.tricks as t
from db import character_service, curation_service, status_service
from db.models import Step, Status


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


class CreateGroupRequest(BaseModel):
    names: List[str]
    member_ids: List[int]


class UpdateGroupRequest(BaseModel):
    names: Optional[List[str]] = None
    member_ids: Optional[List[int]] = None


class CreateWriterRequest(BaseModel):
    display_name: str
    aliases: Optional[List[str]] = None
    discord_user_id: Optional[str] = None


class UpdateWriterRequest(BaseModel):
    display_name: Optional[str] = None
    aliases: Optional[List[str]] = None
    discord_user_id: Optional[str] = None


class AssignCharacterWriterRequest(BaseModel):
    writer_id: int


class ResolveIssueRequest(BaseModel):
    note: Optional[str] = None


class PromoteFlaggedMessageRequest(BaseModel):
    content: Optional[str] = None
    author: Optional[Dict[str, Any]] = None


class AuthCallback(BaseModel):
    code: str


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
    return Path(__file__).resolve().parent.parent.as_posix()


def get_data_root():
    return Path(os.environ.get("SOCRATES_DATA_DIR", get_project_root())).as_posix()


load_dotenv((Path(get_project_root()) / '.env').as_posix())


def get_backup_path(backup_id: str):
    index = t.get_backups_index()
    for b in index:
        if str(b.get("backup_id")) == str(backup_id):
            return (Path(get_data_root()) / b["path"]).as_posix()
    raise HTTPException(status_code=404, detail="Backup ID not found in index")


def api_log(backup_id: str, level: str, message: str):
    import datetime
    try:
        base_path = get_backup_path(backup_id)
        log_path = (Path(base_path) / "log.txt").as_posix()
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}]{level}: API: {message}\n")
    except Exception:
        # Fallback to global log if backup_id is invalid
        t.global_log(level, f"API ({backup_id}): {message}")


# --- AUTHENTICATION ---


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
    if not request:
        return None
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
    config_path = (Path(get_project_root()) / 'res' / 'config.json').as_posix()
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/config/global")
def update_global_config(config: Dict[str, Any]):
    config_path = (Path(get_project_root()) / 'res' / 'config.json').as_posix()
    try:
        t.save_json_atomic(config, config_path)
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
    try:
        data = status_service.load_backup_state(backup_id, base_path)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Failed to load backup state: {e}")

    try:
        data["number_of_characters"] = character_service.get_character_count(backup_id, base_path)
    except Exception:
        data["number_of_characters"] = 0

    return data


@app.get("/api/backups/{backup_id}/config")
def get_backup_config(backup_id: str):
    base_path = get_backup_path(backup_id)
    config_path = (Path(base_path) / 'backup_config.json').as_posix()
    if not Path(config_path).exists():
        # Fallback to global config if local doesn't exist yet
        return get_global_config()
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


@app.put("/api/backups/{backup_id}/config")
def update_backup_config(backup_id: str, config: Dict[str, Any]):
    base_path = get_backup_path(backup_id)
    config_path = (Path(base_path) / 'backup_config.json').as_posix()
    try:
        Path(config_path).parent.mkdir(parents=True, exist_ok=True)
        t.save_json_atomic(config, config_path)
        return {"status": "success"}
    except Exception as e:
        t.global_log("error", f"API: Failed to save config for backup {backup_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save backup config: {e}")


active_processes: Dict[str, subprocess.Popen] = {}


def run_script_in_background(script_name: str, backup_id: str, step_name: Optional[str] = None):
    python_exec = sys.executable
    project_root = get_project_root()
    src_dir = (Path(project_root) / 'src').as_posix()
    script_path = (Path(src_dir) / script_name).as_posix()

    try:
        base_path = get_backup_path(backup_id)
    except Exception as e:
        t.global_log("error", f"API: Cannot resolve backup path for {backup_id}: {e}")
        return

    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512)

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    paths = [src_dir, project_root]
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(paths)

    stderr_lines: List[str] = []
    try:
        process = subprocess.Popen(
            [python_exec, script_path, '--backup-id', str(backup_id)],
            cwd=project_root,
            env=env,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs
        )
        active_processes[backup_id] = process

        if process.stderr:
            for line in process.stderr:
                clean_line = line.rstrip()
                if clean_line:
                    stderr_lines.append(clean_line)
                    api_log(backup_id, "error", clean_line)

        process.wait()
    except Exception as e:
        api_log(backup_id, "error", f"Failed to execute {script_name}: {e}")
        if step_name:
            status_service.update_step_status(backup_id, base_path, step_name, Status.FAILED.value, error=str(e))
        else:
            status_service.fail_running_steps(backup_id, base_path, error=str(e))
        return
    finally:
        if backup_id in active_processes:
            del active_processes[backup_id]

    if process.returncode != 0:
        err_msg = "\n".join(stderr_lines[-5:]) if stderr_lines else f"Process exited with code {process.returncode}"
        api_log(backup_id, "error", f"Execution of {script_name} failed (exit code {process.returncode})")
        if step_name:
            status_service.update_step_status(backup_id, base_path, step_name, Status.FAILED.value, error=err_msg)
        else:
            status_service.fail_running_steps(backup_id, base_path, error=err_msg)
    else:
        if step_name:
            step_statuses = status_service.get_step_statuses(backup_id, base_path)
            if step_statuses.get(step_name) == Status.RUNNING.value:
                status_service.update_step_status(backup_id, base_path, step_name, Status.SUCCESS.value)


@app.post("/api/backups/{backup_id}/cancel")
def cancel_backup_action(backup_id: str):
    t.global_log("info", f"API: Received cancel request for backup {backup_id}")
    try:
        base_path = get_backup_path(backup_id)
    except Exception:
        base_path = None

    if backup_id in active_processes:
        process = active_processes[backup_id]
        import signal
        if os.name == 'nt':
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
            
        t.global_log("info", f"API: Canceled ongoing process for backup {backup_id}")
        return {"status": "canceled"}

    if base_path:
        status_service.fail_running_steps(backup_id, base_path, error="Canceled by user")
        api_log(backup_id, "info", "Cleared stuck running steps via cancel request.")
    return {"status": "canceled"}


@app.post("/api/backups/{backup_id}/run")
def run_backup(
    backup_id: str,
    background_tasks: BackgroundTasks = None,
    config: Optional[Dict[str, Any]] = Body(default=None)
):
    base_path = get_backup_path(backup_id)
    if config:
        config_path = (Path(base_path) / 'backup_config.json').as_posix()
        try:
            Path(config_path).parent.mkdir(parents=True, exist_ok=True)
            t.save_json_atomic(config, config_path)
        except Exception as e:
            t.global_log("error", f"API: Failed to save config for backup {backup_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to save backup config: {e}")

    t.global_log("info", f"API: Starting backup pipeline for {backup_id}...")
    if background_tasks:
        background_tasks.add_task(run_script_in_background, 'backup_server.py', backup_id)
    return {"status": "started"}


@app.post("/api/backups/{backup_id}/rerun/{action}")
def rerun_backup_step(backup_id: str, action: str, background_tasks: BackgroundTasks):
    action_map = {
        "reapply_characters": ("assign_ids.py", Step.ASSIGN_IDS.value),
        "fix_messages": ("fix_bad_messages.py", Step.FIX_MESSAGES.value),
        "reindex": ("index_scenes.py", Step.INDEX_SCENES.value)
    }
    
    if action not in action_map:
        raise HTTPException(status_code=400, detail=f"Invalid action. Allowed actions are: {', '.join(action_map.keys())}")
        
    script_name, step_name = action_map[action]
    base_path = get_backup_path(backup_id)
    status_service.update_step_status(backup_id, base_path, step_name, Status.RUNNING.value)
    t.global_log("info", f"API: Rerunning {action} for backup {backup_id}...")
    background_tasks.add_task(run_script_in_background, script_name, backup_id, step_name)
    return {"status": "started", "action": action}


@app.post("/api/backups")
def create_new_backup(config: Dict[str, Any], background_tasks: BackgroundTasks):
    global_config_path = (Path(get_project_root()) / 'res' / 'config.json').as_posix()
    try:
        t.save_json_atomic(config, global_config_path)
    except Exception as e:
        t.global_log("error", f"API: Failed to save global config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update global config: {e}")
        
    t.global_log("info", f"API: Creating new backup pipeline from global config...")
    python_exec = sys.executable
    project_root = get_project_root()
    script_path = (Path(project_root) / 'src' / 'backup_server.py').as_posix()
    env = os.environ.copy()
    src_dir = (Path(project_root) / 'src').as_posix()
    existing_pythonpath = env.get("PYTHONPATH", "")
    paths = [src_dir, project_root]
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    subprocess.Popen([python_exec, script_path], cwd=project_root, env=env)
    
    return {"status": "started", "detail": "Starting new backup pipeline. Check global logs."}


# --- CHARACTER ENDPOINTS ---


@app.get("/api/backups/{backup_id}/characters")
def get_characters(
    backup_id: str,
    format: str = Query("legacy"),
    by_me: bool = Query(False),
    request: Request = None
):
    base_path = get_backup_path(backup_id)
    if not isinstance(format, str):
        format = "legacy"
    if not isinstance(by_me, bool):
        by_me = False

    writer_id = None
    if by_me and request:
        user = get_optional_user(request)
        if user and user.get("sub"):
            writer_info = curation_service.get_my_writer(backup_id, base_path, str(user["sub"]))
            if writer_info:
                writer_id = writer_info["id"]
            else:
                return [] if format == "legacy" else {"writers": [], "groups": [], "characters": []}
        else:
            return [] if format == "legacy" else {"writers": [], "groups": [], "characters": []}

    try:
        return character_service.get_characters(
            backup_id=backup_id,
            base_path=base_path,
            format_type=format,
            by_writer_id=writer_id
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Failed to load characters: {e}")


@app.post("/api/backups/{backup_id}/characters/merge")
def merge_characters(backup_id: str, req: MergeCharactersRequest):
    api_log(backup_id, "info", f"Merging character {req.source_id} into {req.target_id}...")
    base_path = get_backup_path(backup_id)
    try:
        character_service.merge_characters(backup_id, base_path, req.source_id, req.target_id)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        api_log(backup_id, "base", "Merge completed successfully.")
        return {"status": "success"}
    except Exception as e:
        api_log(backup_id, "error", f"Merge failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/backups/{backup_id}/characters/nest")
def nest_character(backup_id: str, req: NestCharacterRequest):
    api_log(backup_id, "info", f"Nesting character {req.child_id} under {req.parent_id} as {req.version_type}...")
    base_path = get_backup_path(backup_id)
    try:
        character_service.nest_character(backup_id, base_path, req.child_id, req.parent_id, req.version_type)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        api_log(backup_id, "base", "Nest completed successfully.")
        return {"status": "success"}
    except Exception as e:
        api_log(backup_id, "error", f"Nest failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/backups/{backup_id}/characters/{char_id}/unnest")
def unnest_character(backup_id: str, char_id: int):
    api_log(backup_id, "info", f"Unnesting character {char_id}...")
    base_path = get_backup_path(backup_id)
    try:
        character_service.unnest_character(backup_id, base_path, char_id)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        api_log(backup_id, "base", "Unnest completed successfully.")
        return {"status": "success"}
    except Exception as e:
        api_log(backup_id, "error", f"Unnest failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/backups/{backup_id}/characters/{char_id}")
def update_character(backup_id: str, char_id: int, req: UpdateCharacterRequest):
    api_log(backup_id, "info", f"Updating character {char_id} attributes...")
    base_path = get_backup_path(backup_id)
    try:
        char_dict = character_service.update_character(
            backup_id,
            base_path,
            char_id,
            names=req.names,
            tags=req.tags,
            writer=req.writer
        )
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        api_log(backup_id, "base", "Attributes updated successfully.")
        return {"status": "success", "character": char_dict}
    except ValueError as e:
        api_log(backup_id, "error", f"Character {char_id} update failed: {e}")
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Update failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/backups/{backup_id}/writers")
def get_writers(backup_id: str):
    base_path = get_backup_path(backup_id)
    try:
        return character_service.get_writers(backup_id, base_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- SCENE ENDPOINTS ---


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
    after: Optional[str] = Query(None),
    by_me: bool = Query(False),
    request: Request = None
):
    base_path = get_backup_path(backup_id)
    if not isinstance(page, int): page = 1
    if not isinstance(per_page, int): per_page = 50
    if not isinstance(categories, (list, tuple, set)): categories = None
    if not isinstance(statuses, (list, tuple, set)): statuses = None
    if not isinstance(types, (list, tuple, set)): types = None
    if not isinstance(characters, (list, tuple, set)): characters = None
    if not isinstance(character_logic, str): character_logic = 'OR'
    if not isinstance(writers, (list, tuple, set)): writers = None
    if not isinstance(writer_logic, str): writer_logic = 'OR'
    if not isinstance(before, str): before = None
    if not isinstance(after, str): after = None

    if by_me and request:
        user = get_optional_user(request)
        if user and user.get("sub"):
            writer_info = curation_service.get_my_writer(backup_id, base_path, str(user["sub"]))
            if writer_info:
                writers = [writer_info["display_name"]]
            else:
                return {
                    "total_items": 0,
                    "current_page": 1,
                    "per_page": per_page,
                    "total_pages": 0,
                    "scenes": []
                }
        else:
            return {
                "total_items": 0,
                "current_page": 1,
                "per_page": per_page,
                "total_pages": 0,
                "scenes": []
            }

    from models import SceneManager
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
        before=before,
        after=after
    )


# --- CHARACTER GROUPS ENDPOINTS ---


@app.get("/api/backups/{backup_id}/groups")
def get_groups(backup_id: str):
    base_path = get_backup_path(backup_id)
    try:
        return character_service.get_groups(backup_id, base_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/backups/{backup_id}/groups")
def create_group(backup_id: str, req: CreateGroupRequest):
    api_log(backup_id, "info", f"Creating group with names {req.names}...")
    base_path = get_backup_path(backup_id)
    try:
        res = character_service.create_group(backup_id, base_path, req.names, req.member_ids)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        api_log(backup_id, "base", "Group created successfully.")
        return res
    except Exception as e:
        api_log(backup_id, "error", f"Group creation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/backups/{backup_id}/groups/{group_id}")
def update_group(backup_id: str, group_id: int, req: UpdateGroupRequest):
    api_log(backup_id, "info", f"Updating group #{group_id}...")
    base_path = get_backup_path(backup_id)
    try:
        res = character_service.update_group(backup_id, base_path, group_id, names=req.names, member_ids=req.member_ids)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        api_log(backup_id, "base", "Group updated successfully.")
        return res
    except ValueError as e:
        api_log(backup_id, "error", f"Group update failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Group update failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/backups/{backup_id}/groups/{group_id}")
def delete_group(backup_id: str, group_id: int):
    api_log(backup_id, "info", f"Deleting group #{group_id}...")
    base_path = get_backup_path(backup_id)
    try:
        res = curation_service.delete_group(backup_id, base_path, group_id)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        api_log(backup_id, "base", "Group deleted successfully.")
        return res
    except ValueError as e:
        api_log(backup_id, "error", f"Group deletion failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Group deletion failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# --- CURATION & WRITERS MANAGEMENT ENDPOINTS ---


@app.get("/api/backups/{backup_id}/writers/detailed")
def get_writers_detailed(backup_id: str):
    base_path = get_backup_path(backup_id)
    try:
        return curation_service.get_writers_detailed(backup_id, base_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/backups/{backup_id}/writers")
def create_writer(backup_id: str, req: CreateWriterRequest):
    api_log(backup_id, "info", f"Creating writer '{req.display_name}'...")
    base_path = get_backup_path(backup_id)
    try:
        res = curation_service.create_writer(
            backup_id,
            base_path,
            display_name=req.display_name,
            aliases=req.aliases,
            discord_user_id=req.discord_user_id
        )
        api_log(backup_id, "base", "Writer created successfully.")
        return res
    except ValueError as e:
        api_log(backup_id, "error", f"Writer creation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Writer creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/backups/{backup_id}/writers/{writer_id}")
def update_writer(backup_id: str, writer_id: int, req: UpdateWriterRequest):
    api_log(backup_id, "info", f"Updating writer #{writer_id}...")
    base_path = get_backup_path(backup_id)
    try:
        res = curation_service.update_writer(
            backup_id,
            base_path,
            writer_id=writer_id,
            display_name=req.display_name,
            aliases=req.aliases,
            discord_user_id=req.discord_user_id
        )
        api_log(backup_id, "base", "Writer updated successfully.")
        return res
    except ValueError as e:
        api_log(backup_id, "error", f"Writer update failed: {e}")
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Writer update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/backups/{backup_id}/writers/{writer_id}")
def delete_writer(backup_id: str, writer_id: int):
    api_log(backup_id, "info", f"Deleting writer #{writer_id}...")
    base_path = get_backup_path(backup_id)
    try:
        res = curation_service.delete_writer(backup_id, base_path, writer_id=writer_id)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        api_log(backup_id, "base", "Writer deleted successfully.")
        return res
    except ValueError as e:
        api_log(backup_id, "error", f"Writer deletion failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Writer deletion failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/backups/{backup_id}/writers/link-suggestions")
def get_writer_link_suggestions(backup_id: str):
    base_path = get_backup_path(backup_id)
    try:
        return curation_service.get_writer_link_suggestions(backup_id, base_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backups/{backup_id}/curation/summary")
def get_curation_summary(backup_id: str):
    base_path = get_backup_path(backup_id)
    try:
        return curation_service.get_curation_summary(backup_id, base_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- REVIEW QUEUES & OVERRIDES ENDPOINTS ---


@app.get("/api/backups/{backup_id}/characters/unassigned-writers")
def get_unassigned_characters(backup_id: str):
    base_path = get_backup_path(backup_id)
    try:
        return curation_service.get_unassigned_characters(backup_id, base_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/backups/{backup_id}/characters/{char_id}/assign-writer")
def assign_character_writer(backup_id: str, char_id: int, req: AssignCharacterWriterRequest):
    api_log(backup_id, "info", f"Assigning character #{char_id} to writer #{req.writer_id}...")
    base_path = get_backup_path(backup_id)
    try:
        res = curation_service.assign_character_writer(backup_id, base_path, char_id=char_id, writer_id=req.writer_id)
        from models import SceneManager
        SceneManager.clear_cache(backup_id)
        api_log(backup_id, "base", "Character assigned to writer successfully.")
        return res
    except ValueError as e:
        api_log(backup_id, "error", f"Assigning writer failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Assigning writer failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backups/{backup_id}/scene-issues")
def get_scene_issues(
    backup_id: str,
    kind: Optional[str] = Query(None),
    status: Optional[str] = Query("unresolved"),
    channel_id: Optional[str] = Query(None),
    page: int = Query(1),
    per_page: int = Query(50)
):
    base_path = get_backup_path(backup_id)
    try:
        return curation_service.get_scene_issues(
            backup_id,
            base_path,
            kind=kind,
            status=status,
            channel_id=channel_id,
            page=page,
            per_page=per_page
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/backups/{backup_id}/scene-issues/{issue_id}/resolve")
def resolve_scene_issue(backup_id: str, issue_id: int, req: Optional[ResolveIssueRequest] = None):
    api_log(backup_id, "info", f"Resolving scene issue #{issue_id}...")
    base_path = get_backup_path(backup_id)
    note = req.note if req else None
    try:
        res = curation_service.resolve_scene_issue(backup_id, base_path, issue_id=issue_id, note=note)
        api_log(backup_id, "base", "Scene issue resolved.")
        return res
    except ValueError as e:
        api_log(backup_id, "error", f"Resolving scene issue failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Resolving scene issue failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/backups/{backup_id}/scene-issues/{issue_id}/reopen")
def reopen_scene_issue(backup_id: str, issue_id: int):
    api_log(backup_id, "info", f"Reopening scene issue #{issue_id}...")
    base_path = get_backup_path(backup_id)
    try:
        res = curation_service.reopen_scene_issue(backup_id, base_path, issue_id=issue_id)
        api_log(backup_id, "base", "Scene issue reopened.")
        return res
    except ValueError as e:
        api_log(backup_id, "error", f"Reopening scene issue failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Reopening scene issue failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backups/{backup_id}/flagged-messages")
def get_flagged_messages(
    backup_id: str,
    kind: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(None),
    page: int = Query(1),
    per_page: int = Query(50)
):
    base_path = get_backup_path(backup_id)
    try:
        return curation_service.get_flagged_messages(
            backup_id,
            base_path,
            kind=kind,
            channel_id=channel_id,
            page=page,
            per_page=per_page
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/backups/{backup_id}/flagged-messages/{message_id}/promote")
def promote_flagged_message(backup_id: str, message_id: str, req: Optional[PromoteFlaggedMessageRequest] = None):
    api_log(backup_id, "info", f"Promoting flagged message #{message_id} to override...")
    base_path = get_backup_path(backup_id)
    content = req.content if req else None
    author = req.author if req else None
    try:
        res = curation_service.promote_flagged_message(
            backup_id,
            base_path,
            message_id=message_id,
            content=content,
            author=author
        )
        api_log(backup_id, "base", "Flagged message promoted successfully.")
        return res
    except ValueError as e:
        api_log(backup_id, "error", f"Promoting flagged message failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Promoting flagged message failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backups/{backup_id}/message-overrides")
def get_message_overrides(
    backup_id: str,
    page: int = Query(1),
    per_page: int = Query(50)
):
    base_path = get_backup_path(backup_id)
    try:
        return curation_service.get_message_overrides(
            backup_id,
            base_path,
            page=page,
            per_page=per_page
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/backups/{backup_id}/message-overrides/{message_id}")
def delete_message_override(backup_id: str, message_id: str):
    api_log(backup_id, "info", f"Deleting message override #{message_id}...")
    base_path = get_backup_path(backup_id)
    try:
        res = curation_service.delete_message_override(backup_id, base_path, message_id=message_id)
        api_log(backup_id, "base", "Message override deleted.")
        return res
    except ValueError as e:
        api_log(backup_id, "error", f"Deleting message override failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        api_log(backup_id, "error", f"Deleting message override failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- USER PROFILE & LOGS ENDPOINTS ---


@app.get("/api/backups/{backup_id}/me/writer")
def get_my_writer(backup_id: str, user = Depends(get_current_user)):
    base_path = get_backup_path(backup_id)
    discord_user_id = user.get("sub") if isinstance(user, dict) else None
    if not discord_user_id:
        return None
    try:
        return curation_service.get_my_writer(backup_id, base_path, str(discord_user_id))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backups/{backup_id}/logs")
def get_backup_logs(backup_id: str, lines: int = Query(100)):
    base_path = get_backup_path(backup_id)
    log_file = (Path(base_path) / "log.txt").as_posix()
    if not Path(log_file).exists():
        return {"lines": []}
    try:
        from collections import deque
        with open(log_file, "r", encoding="utf-8") as f:
            last_lines = list(deque(f, max(1, lines)))
        return {"lines": [line.strip() for line in last_lines]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backups/{backup_id}/logs/raw")
def get_raw_log(backup_id: str):
    base_path = get_backup_path(backup_id)
    log_file = (Path(base_path) / "log.txt").as_posix()
    if not Path(log_file).exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    return FileResponse(log_file, media_type="text/plain")


@app.get("/api/backups/{backup_id}/logs/stream")
def stream_logs(backup_id: str):
    base_path = get_backup_path(backup_id)
    log_file = (Path(base_path) / "log.txt").as_posix()
    
    def log_generator():
        # Wait for the file to be created if it doesn't exist yet
        for _ in range(20):
            if Path(log_file).exists(): break
            time.sleep(0.5)
            
        if not Path(log_file).exists():
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
    global_log_file = (Path(get_data_root()) / "out" / "log.txt").as_posix()
    if not Path(global_log_file).exists():
        return {"logs": []}
        
    try:
        with open(global_log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            
        return {"logs": [line.strip() for line in all_lines[-lines:]]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/logs/global")
def clear_global_logs():
    log_path = (Path(get_data_root()) / "out" / "log.txt").as_posix()
    if Path(log_path).exists():
        open(log_path, "w").close()
    return {"status": "cleared"}


# --- ADMIN TESTING & VERIFICATION ENDPOINTS ---

TEST_BACKUP_ID = "1791895360"


def _release_db_locks():
    """Releases SQLite WAL engine locks and clears SceneManager cache in the server process."""
    try:
        from db.session import close_all_engines
        from models import SceneManager
        SceneManager.clear_cache()
        close_all_engines()
    except Exception:
        pass


@app.post("/api/admin/test-backup/reset")
def reset_testing_backup():
    t.global_log("info", "API: Resetting testing backup (Elysium-sql-tests)...")
    _release_db_locks()
    try:
        from tests.reset_test_backup import reset_test_backup
        ok = reset_test_backup()
        _release_db_locks()
        if not ok:
            msg = "Failed to reset testing backup: pristine seed copy (Backups/Elysium-sql-tests-clean) not found."
            t.global_log("error", f"API: {msg}")
            raise HTTPException(status_code=500, detail=msg)
        msg = "Successfully restored Backups/Elysium-sql-tests from pristine copy."
        t.global_log("base", f"API: {msg}")
        return {"status": "success", "message": msg}
    except HTTPException:
        raise
    except Exception as e:
        t.global_log("error", f"API: Error resetting testing backup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/test-backup/migrate")
def migrate_testing_backup():
    t.global_log("info", f"API: Migrating testing backup (ID: {TEST_BACKUP_ID}) to SQLite...")
    _release_db_locks()
    try:
        from db.migrate import migrate_single_backup
        from models.backup_context import BackupContext

        index = t.get_backups_index()
        backup = next((b for b in index if str(b.get("backup_id")) == TEST_BACKUP_ID), None)
        if not backup:
            msg = f"Testing backup ID '{TEST_BACKUP_ID}' not found in backups_index.json"
            t.global_log("error", f"API: {msg}")
            raise HTTPException(status_code=404, detail=msg)

        with BackupContext.activate(backup_id=TEST_BACKUP_ID):
            report = migrate_single_backup(backup, dry_run=False, skip_snapshots=False)

        _release_db_locks()
        msg = (
            f"Successfully migrated '{backup['backup_name']}' to SQLite "
            f"({report.get('characters_count', 0)} characters, "
            f"{report.get('scenes_count', 0)} scenes, "
            f"{report.get('writers_count', 0)} writers)."
        )
        t.global_log("base", f"API: {msg}")
        return {"status": "success", "message": msg, "report": report}
    except HTTPException:
        raise
    except Exception as e:
        t.global_log("error", f"API: Error migrating testing backup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/tests/run")
def run_python_tests():
    t.global_log("info", "API: Running Python test suite (unittest discover tests)...")
    _release_db_locks()

    python_exec = sys.executable
    project_root = get_project_root()
    src_dir = (Path(project_root) / "src").as_posix()

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    paths = [src_dir, project_root]
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(paths)

    try:
        proc = subprocess.run(
            [python_exec, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        _release_db_locks()

        output_parts = []
        if proc.stdout and proc.stdout.strip():
            output_parts.append(proc.stdout.strip())
        if proc.stderr and proc.stderr.strip():
            output_parts.append(proc.stderr.strip())
        combined_output = "\n".join(output_parts)
        cleaned_output = t.clean(combined_output)

        if proc.returncode == 0:
            msg = "Python test suite passed (exit code 0)."
            t.global_log("base", f"API: {msg}")
            return {
                "status": "success",
                "returncode": 0,
                "message": msg,
                "output": cleaned_output,
            }
        else:
            msg = f"Python test suite failed (exit code {proc.returncode})."
            t.global_log("error", f"API: {msg}")
            return {
                "status": "failed",
                "returncode": proc.returncode,
                "message": msg,
                "output": cleaned_output,
            }
    except Exception as e:
        t.global_log("error", f"API: Failed to execute Python test suite: {e}")
        raise HTTPException(status_code=500, detail=str(e))


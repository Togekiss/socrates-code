/**
 * api.ts
 * 
 * Provides a standardized HTTP fetch wrapper (`api` object) to interact with the FastAPI backend.
 * All React components should use this file for fetching data rather than writing raw fetch() calls.
 * 
 * Base URL defaults to http://localhost:8000/api
 */

// In production, uses '/api' for same-origin proxy via Firebase Hosting rewrite.
// In development, uses local backend at 'http://localhost:8000/api'.
export const API_BASE = import.meta.env.DEV ? 'http://localhost:8000/api' : '/api';

const fetchWithAuth = async (url: string, options: RequestInit = {}) => {
  const res = await fetch(url, {
    ...options,
    credentials: 'include'
  });
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: res.statusText }));
    const error: any = new Error(errorBody.detail || `Request failed with status ${res.status}`);
    error.status = res.status;
    error.response = errorBody;
    throw error;
  }
  return res;
};

export const api = {
  getLoginUrl: () => fetchWithAuth(`${API_BASE}/auth/login-url`).then(res => res.json()),
  authDiscord: (code: string) => fetchWithAuth(`${API_BASE}/auth/discord`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code })
  }).then(res => res.json()),
  getMe: () => fetchWithAuth(`${API_BASE}/auth/me`).then(res => res.json()),
  logout: () => fetchWithAuth(`${API_BASE}/auth/logout`, { method: 'POST' }).then(res => res.json()),

  getGlobalConfig: () => fetchWithAuth(`${API_BASE}/config/global`).then(res => res.json()),
  updateGlobalConfig: (data: any) => fetchWithAuth(`${API_BASE}/config/global`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  }).then(res => res.json()),
  
  getServerCategories: (serverId: string) => fetchWithAuth(`${API_BASE}/servers/${serverId}/categories`).then(res => res.json()),
  
  getGlobalLogs: (lines: number = 100) => fetchWithAuth(`${API_BASE}/logs/global?lines=${lines}`).then(res => res.json()),
  clearGlobalLogs: () => fetchWithAuth(`${API_BASE}/logs/global`, { method: 'DELETE' }).then(res => res.json()),
  
  getBackups: () => fetchWithAuth(`${API_BASE}/backups`).then(res => res.json()),
  getAllBackupPaths: () => fetchWithAuth(`${API_BASE}/backups-paths`).then(res => res.json()),
  createNewBackup: (config: any) => fetchWithAuth(`${API_BASE}/backups`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config)
  }).then(res => res.json()),
  
  getBackupInfo: (backupId: string) => fetchWithAuth(`${API_BASE}/backups/${backupId}`).then(res => res.json()),
  getBackupConfig: (backupId: string) => fetchWithAuth(`${API_BASE}/backups/${backupId}/config`).then(res => res.json()),
  
  runBackup: (backupId: string, config: any) => fetchWithAuth(`${API_BASE}/backups/${backupId}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config)
  }).then(res => res.json()),

  cancelRun: (backupId: string) => fetchWithAuth(`${API_BASE}/backups/${backupId}/cancel`, {
    method: 'POST'
  }).then(res => res.json()),
  
  rerunAction: (backupId: string, action: string) => fetchWithAuth(`${API_BASE}/backups/${backupId}/rerun/${action}`, {
    method: 'POST'
  }).then(res => res.json()),
  
  getCharacters: (backupId: string) => fetchWithAuth(`${API_BASE}/backups/${backupId}/characters`).then(res => res.json()),
  
  mergeCharacters: (backupId: string, sourceId: number, targetId: number) => fetchWithAuth(`${API_BASE}/backups/${backupId}/characters/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_id: sourceId, target_id: targetId })
  }).then(res => res.json()),
  
  nestCharacter: (backupId: string, childId: number, parentId: number, versionType: string) => fetchWithAuth(`${API_BASE}/backups/${backupId}/characters/nest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ child_id: childId, parent_id: parentId, version_type: versionType })
  }).then(res => res.json()),
  
  unnestCharacter: (backupId: string, charId: number) => fetchWithAuth(`${API_BASE}/backups/${backupId}/characters/${charId}/unnest`, {
    method: 'POST'
  }).then(res => res.json()),
  
  updateCharacter: (backupId: string, charId: number, data: any) => fetchWithAuth(`${API_BASE}/backups/${backupId}/characters/${charId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  }).then(res => res.json()),
  
  getScenes: (backupId: string, queryParams: URLSearchParams = new URLSearchParams()) => 
    fetchWithAuth(`${API_BASE}/backups/${backupId}/scenes?${queryParams.toString()}`).then(res => res.json()),
    
  getWriters: (backupId: string) => fetchWithAuth(`${API_BASE}/backups/${backupId}/writers`).then(res => res.json()),
  
  // Expose the base stream URL for EventSource. Note: EventSource might need `withCredentials: true` in the component
  getLogsStreamUrl: (backupId: string) => `${API_BASE}/backups/${backupId}/logs/stream`
};

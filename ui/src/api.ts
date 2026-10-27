/**
 * api.ts
 * 
 * Provides a standardized, strongly typed HTTP fetch client (`api` object) to interact with
 * the FastAPI backend. All React components should use this client for network requests.
 */

import type {
  AdminTestActionResponse,
  AuthResponse,
  BackupConfig,
  BackupInfo,
  Character,
  CharacterGroup,
  CurationSummary,
  DiscordAuthor,
  FlaggedMessagesResponse,
  GlobalConfig,
  IssueResolution,
  MeResponse,
  MessageOverridesResponse,
  MyWriter,
  SceneIssuesResponse,
  ScenesResponse,
  UnassignedCharacter,
  Writer,
  WriterDetailed,
  WriterLinkSuggestion,
} from './types';

// In production, uses '/api' for same-origin proxy via Firebase Hosting rewrite.
// In development, uses local backend at 'http://localhost:8000/api'.
export const API_BASE = import.meta.env.DEV ? 'http://localhost:8000/api' : '/api';

export interface ApiError extends Error {
  status?: number;
  response?: { detail?: string };
}

const fetchWithAuth = async (url: string, options: RequestInit = {}): Promise<Response> => {
  const res = await fetch(url, {
    ...options,
    credentials: 'include',
  });
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: res.statusText }));
    const error = new Error(errorBody.detail || `Request failed with status ${res.status}`) as ApiError;
    error.status = res.status;
    error.response = errorBody;
    throw error;
  }
  return res;
};

export const api = {
  // --- Auth Endpoints ---
  getLoginUrl: (): Promise<{ url: string }> =>
    fetchWithAuth(`${API_BASE}/auth/login-url`).then(res => res.json()),

  authDiscord: (code: string): Promise<AuthResponse> =>
    fetchWithAuth(`${API_BASE}/auth/discord`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    }).then(res => res.json()),

  getMe: (): Promise<MeResponse> =>
    fetchWithAuth(`${API_BASE}/auth/me`).then(res => res.json()),

  logout: (): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/auth/logout`, { method: 'POST' }).then(res => res.json()),

  // --- Configuration Endpoints ---
  getGlobalConfig: (): Promise<GlobalConfig> =>
    fetchWithAuth(`${API_BASE}/config/global`).then(res => res.json()),

  updateGlobalConfig: (data: Partial<GlobalConfig>): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/config/global`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  getServerCategories: (serverId: string): Promise<Array<{ id: string; name: string }>> =>
    fetchWithAuth(`${API_BASE}/servers/${serverId}/categories`).then(res => res.json()),

  // --- Global Logs ---
  getGlobalLogs: (lines: number = 100): Promise<{ logs: string[] }> =>
    fetchWithAuth(`${API_BASE}/logs/global?lines=${lines}`).then(res => res.json()),

  clearGlobalLogs: (): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/logs/global`, { method: 'DELETE' }).then(res => res.json()),

  // --- Backups Management ---
  getBackups: (): Promise<BackupInfo[]> =>
    fetchWithAuth(`${API_BASE}/backups`).then(res => res.json()),

  getAllBackupPaths: (): Promise<string[]> =>
    fetchWithAuth(`${API_BASE}/backups-paths`).then(res => res.json()),

  createNewBackup: (config: BackupConfig): Promise<{ status: string; id: string }> =>
    fetchWithAuth(`${API_BASE}/backups`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    }).then(res => res.json()),

  getBackupInfo: (backupId: string): Promise<BackupInfo> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}`).then(res => res.json()),

  getBackupLogs: (backupId: string, lines: number = 10): Promise<{ lines: string[] }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/logs?lines=${lines}`).then(res => res.json()),

  getBackupConfig: (backupId: string): Promise<BackupConfig> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/config`).then(res => res.json()),

  updateBackupConfig: (backupId: string, config: Partial<BackupConfig>): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    }).then(res => res.json()),

  runBackup: (backupId: string, config?: Partial<BackupConfig>): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config || {}),
    }).then(res => res.json()),

  cancelRun: (backupId: string): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/cancel`, {
      method: 'POST',
    }).then(res => res.json()),

  rerunAction: (backupId: string, action: string): Promise<{ status: string; action: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/rerun/${action}`, {
      method: 'POST',
    }).then(res => res.json()),

  upgradeBackup: (backupId: string): Promise<{ status: string; message?: string; report?: Record<string, unknown> }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/upgrade`, {
      method: 'POST',
    }).then(res => res.json()),

  // --- Curation Summary ---
  getCurationSummary: (backupId: string): Promise<CurationSummary> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/curation/summary`).then(res => res.json()),

  // --- Characters & Character Groups ---
  getCharacters: (backupId: string, byMe: boolean = false): Promise<Character[]> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/characters?by_me=${byMe}`).then(res => res.json()),

  mergeCharacters: (backupId: string, sourceId: number, targetId: number): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/characters/merge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_id: sourceId, target_id: targetId }),
    }).then(res => res.json()),

  nestCharacter: (backupId: string, childId: number, parentId: number, versionType: string = 'npc'): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/characters/nest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ child_id: childId, parent_id: parentId, version_type: versionType }),
    }).then(res => res.json()),

  unnestCharacter: (backupId: string, charId: number): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/characters/${charId}/unnest`, {
      method: 'POST',
    }).then(res => res.json()),

  updateCharacter: (
    backupId: string,
    charId: number,
    data: { tags?: string[]; names?: string[]; writer?: string[] }
  ): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/characters/${charId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  getGroups: (backupId: string): Promise<CharacterGroup[]> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/groups`).then(res => res.json()),

  createGroup: (backupId: string, data: { names: string[]; member_ids: number[] }): Promise<{ status: string; group_id: number }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/groups`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  updateGroup: (
    backupId: string,
    groupId: number,
    data: { names?: string[]; member_ids?: number[] }
  ): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/groups/${groupId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  deleteGroup: (backupId: string, groupId: number): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/groups/${groupId}`, {
      method: 'DELETE',
    }).then(res => res.json()),

  // --- Scenes ---
  getScenes: (backupId: string, queryParams: URLSearchParams = new URLSearchParams()): Promise<ScenesResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/scenes?${queryParams.toString()}`).then(res => res.json()),

  // --- Writers & User Linking ---
  getWriters: (backupId: string): Promise<Writer[]> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/writers`).then(res => res.json()),

  getWritersDetailed: (backupId: string): Promise<WriterDetailed[]> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/writers/detailed`).then(res => res.json()),

  createWriter: (
    backupId: string,
    data: { display_name: string; aliases?: string[]; discord_user_id?: string }
  ): Promise<{ status: string; writer_id: number }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/writers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  updateWriter: (
    backupId: string,
    writerId: number,
    data: { display_name?: string; aliases?: string[]; discord_user_id?: string | null }
  ): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/writers/${writerId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  deleteWriter: (backupId: string, writerId: number): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/writers/${writerId}`, {
      method: 'DELETE',
    }).then(res => res.json()),

  getWriterLinkSuggestions: (backupId: string): Promise<WriterLinkSuggestion[]> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/writers/link-suggestions`).then(res => res.json()),

  getUnassignedCharacters: (backupId: string): Promise<UnassignedCharacter[]> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/characters/unassigned-writers`).then(res => res.json()),

  assignCharacterWriter: (backupId: string, charId: number, writerId: number): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/characters/${charId}/assign-writer`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ writer_id: writerId }),
    }).then(res => res.json()),

  getMyWriter: (backupId: string): Promise<MyWriter | null> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/me/writer`).then(res => res.json()),

  // --- Scene Issues Review Queue ---
  getSceneIssues: (backupId: string, params: URLSearchParams = new URLSearchParams()): Promise<SceneIssuesResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/scene-issues?${params.toString()}`).then(res => res.json()),

  resolveSceneIssue: (
    backupId: string,
    issueId: number,
    resolution: IssueResolution,
    note?: string
  ): Promise<{
    status: string;
    issue_id: number;
    resolved_at: string;
    resolved_note: string;
    resolution: string;
    action_performed?: boolean;
    action?: string;
    scene_pk?: number;
    scene_key?: string;
    merged_scene_key?: string;
    next_scene_pk?: number;
    next_scene_key?: string;
  }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/scene-issues/${issueId}/resolve`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resolution, note }),
    }).then(res => res.json()),

  reopenSceneIssue: (backupId: string, issueId: number): Promise<{ status: string; issue_id: number; reopened: boolean }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/scene-issues/${issueId}/reopen`, {
      method: 'PUT',
    }).then(res => res.json()),

  // --- Flagged Messages & Overrides ---
  getFlaggedMessages: (backupId: string, params: URLSearchParams = new URLSearchParams()): Promise<FlaggedMessagesResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/flagged-messages?${params.toString()}`).then(res => res.json()),

  promoteFlaggedMessage: (
    backupId: string,
    messageId: string,
    data: { content?: string; author?: DiscordAuthor } = {}
  ): Promise<{ status: string; message_id: string; override_id?: number; promoted_at?: string; is_update?: boolean }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/flagged-messages/${messageId}/promote`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  getMessageOverrides: (backupId: string, params: URLSearchParams = new URLSearchParams()): Promise<MessageOverridesResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/message-overrides?${params.toString()}`).then(res => res.json()),

  deleteMessageOverride: (backupId: string, messageId: string): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/message-overrides/${messageId}`, {
      method: 'DELETE',
    }).then(res => res.json()),

  // --- Live Log Stream URL ---
  getLogsStreamUrl: (backupId: string): string => `${API_BASE}/backups/${backupId}/logs/stream`,

  // --- Admin Testing & Verification ---
  resetTestingBackup: (): Promise<AdminTestActionResponse> =>
    fetchWithAuth(`${API_BASE}/admin/test-backup/reset`, {
      method: 'POST',
    }).then(res => res.json()),

  migrateTestingBackup: (): Promise<AdminTestActionResponse> =>
    fetchWithAuth(`${API_BASE}/admin/test-backup/migrate`, {
      method: 'POST',
    }).then(res => res.json()),

  upgradeAllDatabases: (): Promise<AdminTestActionResponse> =>
    fetchWithAuth(`${API_BASE}/admin/upgrade-all`, {
      method: 'POST',
    }).then(res => res.json()),

  runPythonTests: (): Promise<AdminTestActionResponse> =>
    fetchWithAuth(`${API_BASE}/admin/tests/run`, {
      method: 'POST',
    }).then(res => res.json()),
};

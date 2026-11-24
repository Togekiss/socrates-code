/**
 * api.ts
 * 
 * Provides a standardized, strongly typed HTTP fetch client (`api` object) to interact with
 * the FastAPI backend. All React components should use this client for network requests.
 */

import type {
  AdminTestActionResponse,
  AuditLogsResponse,
  AuthResponse,
  BackupConfig,
  BackupInfo,
  Character,
  CharacterGroup,
  CurationSummary,
  DiscordAuthor,
  DiscordRolesResponse,
  EventRecord,
  EventsResponse,
  FlaggedMessage,
  FlaggedMessagesResponse,
  FlaggedResolution,
  FullContentResponse,
  GlobalConfig,
  IssueResolution,
  ManualSplitResponse,
  MeResponse,
  MessageOverridesResponse,
  MyWriter,
  RbacConfig,
  SceneIssuesResponse,
  ScenesResponse,
  SessionsResponse,
  SceneMergeNeighborsResponse,
  SeenDiscordUser,
  MergeSceneResponse,
  AcceptAllWriterSuggestionsResponse,
  CreateWritersFromDiscordUsersResponse,
  UnassignedCharacter,
  WriterDetailed,
  WriterLinkSuggestion,
} from './types';

// Uses same-origin '/api' proxy (Vite dev server in development, Firebase Hosting rewrite in production).
export const API_BASE = '/api';

let csrfToken: string | null = null;
export const getCsrfToken = (): string | null => csrfToken;

export interface ApiError extends Error {
  status?: number;
  code?: string;
  response?: { detail?: string; error?: string };
}

export const getErrorMessage = (err: unknown, fallback: string): string => {
  if (err && typeof err === 'object' && 'message' in err && typeof (err as Error).message === 'string') {
    const msg = (err as Error).message.trim();
    if (msg) return msg;
  }
  return fallback;
};

// In-flight GET request deduplication cache
const inFlightGetRequests = new Map<string, Promise<Response>>();

const fetchWithAuth = async (url: string, options: RequestInit = {}): Promise<Response> => {
  const method = (options.method || 'GET').toUpperCase();
  const isGet = method === 'GET';

  if (isGet) {
    const existing = inFlightGetRequests.get(url);
    if (existing) {
      const res = await existing;
      return res.clone();
    }
  }

  const requestPromise = (async () => {
    const headers = new Headers(options.headers);
    if (!isGet && method !== 'HEAD' && method !== 'OPTIONS') {
      headers.set('X-Requested-With', 'Socrates-UI');
      if (csrfToken && !headers.has('X-CSRF-Token')) {
        headers.set('X-CSRF-Token', csrfToken);
      }
    }
    const res = await fetch(url, { ...options, headers, credentials: 'include' });
    if (!res.ok) {
      const errorBody = await res.json().catch(() => ({ detail: res.statusText }));
      const error = new Error(errorBody.detail || `Request failed with status ${res.status}`) as ApiError;
      error.status = res.status;
      error.code = typeof errorBody.error === 'string' ? errorBody.error : undefined;
      error.response = errorBody;
      throw error;
    }
    return res;
  })();

  if (isGet) {
    inFlightGetRequests.set(url, requestPromise);
    requestPromise.finally(() => {
      inFlightGetRequests.delete(url);
    });
  }

  const res = await requestPromise;
  return isGet ? res.clone() : res;
};

export const api = {
  // --- Auth Endpoints ---
  getLoginUrl: (): Promise<{ url: string; state?: string }> =>
    fetchWithAuth(`${API_BASE}/auth/login-url`).then(res => res.json()),

  authDiscord: (code: string, state?: string | null): Promise<AuthResponse> =>
    fetchWithAuth(`${API_BASE}/auth/discord`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state ? { code, state } : { code }),
    })
      .then(res => res.json())
      .then((data: AuthResponse) => {
        if (data.csrf_token) {
          csrfToken = data.csrf_token;
        }
        return data;
      }),

  getMe: (): Promise<MeResponse> =>
    fetchWithAuth(`${API_BASE}/auth/me`)
      .then(res => res.json())
      .then((data: MeResponse) => {
        if (!data.user) {
          csrfToken = null;
        } else if (data.csrf_token) {
          csrfToken = data.csrf_token;
        }
        return data;
      }),

  devLogin: (): Promise<AuthResponse> => {
    if (!(import.meta.env.DEV && import.meta.env.VITE_ENABLE_DEV_LOGIN === 'true')) {
      return Promise.reject(new Error('Dev login is disabled'));
    }
    return fetchWithAuth(`${API_BASE}/auth/dev-login`, { method: 'POST' })
      .then(res => res.json())
      .then((data: AuthResponse) => {
        if (data.csrf_token) {
          csrfToken = data.csrf_token;
        }
        return data;
      });
  },

  logout: (): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/auth/logout`, { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        csrfToken = null;
        return data;
      }),

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

  createNewBackup: (config: BackupConfig): Promise<{ status: string; backup_id?: string; path?: string }> =>
    fetchWithAuth(`${API_BASE}/backups`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    }).then(res => res.json()),

  getBackupInfo: (backupId: string): Promise<BackupInfo> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}`).then(res => res.json()),

  getBackupLogs: (backupId: string, lines: number = 10): Promise<{ lines: string[] }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/logs?lines=${lines}`).then(res => res.json()),

  getBackupRawLogs: (backupId: string): Promise<string> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/logs/raw`).then(res => res.text()),

  clearBackupLogs: (backupId: string): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/logs`, { method: 'DELETE' }).then(res => res.json()),

  getBackupConfig: (backupId: string): Promise<BackupConfig> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/config`).then(res => res.json()),

  updateBackupConfig: (backupId: string, config: Partial<BackupConfig>): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    }).then(res => res.json()),

  syncBackup: (
    backupId: string,
    data: { mode: 'incremental' | 'resume' | 'rescan_discord' | 'rescan_local_json'; config?: Partial<BackupConfig> }
  ): Promise<{ status: string; mode: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  reindexBackup: (
    backupId: string,
    data: { rescan_json?: boolean } = {}
  ): Promise<{ status: string; rescan_json: boolean }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/reindex`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  runBackup: (backupId: string, config?: Partial<BackupConfig>): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config || {}),
    }).then(res => res.json()),

  cancelRun: (backupId: string): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/cancel`, { method: 'POST' }).then(res => res.json()),

  upgradeBackup: (backupId: string): Promise<{ status: string; message?: string; report?: Record<string, unknown> }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/upgrade`, { method: 'POST' }).then(res => res.json()),

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
    fetchWithAuth(`${API_BASE}/backups/${backupId}/characters/${charId}/unnest`, { method: 'POST' }).then(res => res.json()),

  updateCharacter: (
    backupId: string,
    charId: number,
    data: { tags?: string[]; names?: string[]; writer?: string[]; writer_id?: number | null }
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

  updateGroup: (backupId: string, groupId: number, data: { names?: string[]; member_ids?: number[] }): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/groups/${groupId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  deleteGroup: (backupId: string, groupId: number): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/groups/${groupId}`, { method: 'DELETE' }).then(res => res.json()),

  // --- Scenes, Chat Sessions & Events ---
  getScenes: (backupId: string, queryParams: URLSearchParams = new URLSearchParams()): Promise<ScenesResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/scenes?${queryParams.toString()}`).then(res => res.json()),

  getSessions: (backupId: string, queryParams: URLSearchParams = new URLSearchParams()): Promise<SessionsResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/sessions?${queryParams.toString()}`).then(res => res.json()),

  updateSceneMetadata: (
    backupId: string,
    sceneId: string | number,
    data: { custom_name?: string | null; name?: string | null }
  ): Promise<{ status: string; pk: number; scene_pk: number; scene_key: string; custom_name?: string | null }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/scenes/${sceneId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  getSceneMergeNeighbors: (
    backupId: string,
    sceneId: string | number
  ): Promise<SceneMergeNeighborsResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/scenes/${sceneId}/merge-neighbors`).then(res => res.json()),

  mergeScene: (
    backupId: string,
    sceneId: string | number,
    direction: 'prev' | 'next',
    force: boolean = false,
    note?: string | null
  ): Promise<MergeSceneResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/scenes/${sceneId}/merge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ direction, force, note }),
    }).then(res => res.json()),

  getEvents: (backupId: string, queryParams: URLSearchParams = new URLSearchParams()): Promise<EventsResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/events?${queryParams.toString()}`).then(res => res.json()),

  fetchEvents: (backupId: string, queryParams: URLSearchParams = new URLSearchParams()): Promise<EventsResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/events?${queryParams.toString()}`).then(res => res.json()),

  updateEventMetadata: (
    backupId: string,
    eventPk: number,
    data: { name?: string | null; channel_names?: Record<string | number, string | null> }
  ): Promise<{ status: string; event: EventRecord }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/events/${eventPk}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  mergeEvents: (
    backupId: string,
    targetEventPk: number,
    sourceEventPk: number,
    name?: string | null
  ): Promise<{ status: string; event: EventRecord }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/events/merge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event_pks: [targetEventPk, sourceEventPk],
        target_event_pk: targetEventPk,
        source_event_pk: sourceEventPk,
        name,
      }),
    }).then(res => res.json()),

  splitEvent: (
    backupId: string,
    eventPk: number,
    scenePks: number[],
    newEventName?: string | null
  ): Promise<{ status: string; original_event: EventRecord; new_event: EventRecord }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/events/${eventPk}/split`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scene_pks: scenePks,
        scene_ids: scenePks.map(String),
        new_event_name: newEventName,
      }),
    }).then(res => res.json()),

  // --- Writers & User Linking ---
  getWriters: (backupId: string): Promise<string[]> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/writers`).then(res => res.json()),

  getWritersDetailed: (backupId: string): Promise<WriterDetailed[]> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/writers/detailed`).then(res => res.json()),

  createWriter: (backupId: string, data: { display_name: string; aliases?: string[]; discord_user_id?: string }): Promise<WriterDetailed> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/writers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  updateWriter: (backupId: string, writerId: number, data: { display_name?: string; aliases?: string[]; discord_user_id?: string | null }): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/writers/${writerId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  deleteWriter: (backupId: string, writerId: number): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/writers/${writerId}`, { method: 'DELETE' }).then(res => res.json()),

  getWriterLinkSuggestions: (backupId: string): Promise<WriterLinkSuggestion[]> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/writers/link-suggestions`).then(res => res.json()),

  acceptAllWriterLinkSuggestions: (backupId: string): Promise<AcceptAllWriterSuggestionsResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/writers/link-suggestions/accept-all`, {
      method: 'POST',
    }).then(res => res.json()),

  createWritersFromDiscordUsers: (backupId: string): Promise<CreateWritersFromDiscordUsersResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/writers/create-from-discord-users`, {
      method: 'POST',
    }).then(res => res.json()),

  getSeenDiscordUsers: (backupId: string): Promise<SeenDiscordUser[]> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/seen-discord-users`).then(res => res.json()),

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
    fetchWithAuth(`${API_BASE}/backups/${backupId}/scene-issues/${issueId}/reopen`, { method: 'PUT' }).then(res => res.json()),

  createManualSceneSplit: (backupId: string, data: { discord_link: string; note?: string }): Promise<ManualSplitResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/scene-issues/manual-split`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  // --- Flagged Messages & Overrides ---
  getFlaggedMessages: (backupId: string, params: URLSearchParams = new URLSearchParams()): Promise<FlaggedMessagesResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/flagged-messages?${params.toString()}`).then(res => res.json()),

  addManualFlaggedMessage: (backupId: string, data: { discord_link: string; note?: string }): Promise<FlaggedMessage> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/flagged-messages/manual`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  getFlaggedMessageFullContent: (
    backupId: string,
    messageId: string | number
  ): Promise<FullContentResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/flagged-messages/${messageId}/full-content`).then(res => res.json()),

  resolveFlaggedMessage: (
    backupId: string,
    messageId: string,
    data: { resolution: FlaggedResolution; note?: string; override_content?: string | null; override_author?: DiscordAuthor }
  ): Promise<{ status: string; message_id: string; resolution: string; resolved_at: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/flagged-messages/${messageId}/resolve`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  reopenFlaggedMessage: (backupId: string, messageId: string): Promise<{ status: string; message_id: string; reopened: boolean }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/flagged-messages/${messageId}/reopen`, { method: 'PUT' }).then(res => res.json()),

  promoteFlaggedMessage: (
    backupId: string,
    messageId: string,
    data: { content?: string | null; author?: DiscordAuthor } = {}
  ): Promise<{ status: string; message_id: string; override_id?: number; promoted_at?: string; is_update?: boolean }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/flagged-messages/${messageId}/promote`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(res => res.json()),

  getMessageOverrides: (backupId: string, params: URLSearchParams = new URLSearchParams()): Promise<MessageOverridesResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/message-overrides?${params.toString()}`).then(res => res.json()),

  deleteMessageOverride: (backupId: string, messageId: string): Promise<{ status: string }> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/message-overrides/${messageId}`, { method: 'DELETE' }).then(res => res.json()),

  // --- Live Log Stream URL ---
  getLogsStreamUrl: (backupId: string): string => `${API_BASE}/backups/${backupId}/logs/stream`,

  // --- Admin Testing & Verification ---
  resetTestingBackup: (): Promise<AdminTestActionResponse> =>
    fetchWithAuth(`${API_BASE}/admin/test-backup/reset`, { method: 'POST' }).then(res => res.json()),

  migrateTestingBackup: (): Promise<AdminTestActionResponse> =>
    fetchWithAuth(`${API_BASE}/admin/test-backup/migrate`, { method: 'POST' }).then(res => res.json()),

  upgradeAllDatabases: (): Promise<AdminTestActionResponse> =>
    fetchWithAuth(`${API_BASE}/admin/upgrade-all`, { method: 'POST' }).then(res => res.json()),

  runPythonTests: (): Promise<AdminTestActionResponse> =>
    fetchWithAuth(`${API_BASE}/admin/tests/run`, { method: 'POST' }).then(res => res.json()),

  // --- Backup RBAC & Users Endpoints ---
  getBackupDiscordRoles: (backupId: string): Promise<DiscordRolesResponse> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/discord-roles`).then(res => res.json()),

  getBackupRbac: (backupId: string): Promise<RbacConfig> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/rbac`).then(res => res.json()),

  updateBackupRbac: (backupId: string, rbac: RbacConfig): Promise<RbacConfig> =>
    fetchWithAuth(`${API_BASE}/backups/${backupId}/rbac`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(rbac),
    })
      .then(res => res.json())
      .then((data: RbacConfig & { rbac?: RbacConfig }) => data?.rbac ?? data),

  getBackupAuditLogs: (backupId: string, params: URLSearchParams = new URLSearchParams()): Promise<AuditLogsResponse> => {
    const query = params.toString();
    return fetchWithAuth(`${API_BASE}/backups/${backupId}/audit-logs${query ? `?${query}` : ''}`).then(res => res.json());
  },

  getGlobalAuditLogs: (params: URLSearchParams = new URLSearchParams()): Promise<AuditLogsResponse> => {
    const query = params.toString();
    return fetchWithAuth(`${API_BASE}/admin/audit-logs${query ? `?${query}` : ''}`).then(res => res.json());
  },
};

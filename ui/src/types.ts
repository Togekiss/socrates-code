export type BackupRole =
  | 'instance_admin'
  | 'server_admin'
  | 'curator'
  | 'participant'
  | 'viewer';

export interface User {
  id?: string;
  sub?: string;
  username: string;
  avatar?: string | null;
  discriminator?: string;
  global_name?: string | null;
  admin?: boolean;
  is_instance_admin?: boolean;
  auth_method?: string;
  dev_role?: string;
  authorized_guilds?: Array<{ id: string; name: string }>;
}

export interface AuthResponse {
  status: string;
  user?: User;
  csrf_token?: string;
}

export interface MeResponse {
  user: User | null;
  csrf_token?: string;
}

export type StepStatus = 'pending' | 'running' | 'success' | 'failed';
export type StorageMode = 'backupless' | 'full';
export type SyncStatus = 'idle' | 'syncing' | 'paused' | 'failed';

export interface BackupStepStatus {
  [stepName: string]: StepStatus;
}

export interface BackupChannelSummary {
  id: string;
  name: string;
  position?: number;
  path?: string;
  is_deleted?: boolean;
  number_of_messages?: number;
  number_of_scenes?: number;
  number_of_threads?: number;
  threads?: BackupChannelSummary[];
}

export interface BackupCategory {
  id: string;
  name: string;
  position?: number;
  path?: string;
  is_deleted?: boolean;
  number_of_scenes?: number;
  number_of_channels?: number;
  number_of_threads?: number;
  channels?: BackupChannelSummary[];
}

export interface BackupInfo {
  id: string;
  name?: string;
  server_name?: string;
  server_id?: string;
  status: 'pending' | 'running' | 'success' | 'failed';
  steps?: BackupStepStatus;
  storage_mode?: StorageMode;
  sync_status?: SyncStatus;
  sync_started_at?: string | null;
  last_synced_at?: string | null;
  sync_error?: string | null;
  channels_total?: number;
  channels_done?: number;
  categories?: number | BackupCategory[];
  channels?: number | unknown[];
  threads?: number | unknown[];
  scenes?: number | unknown[];
  characters?: number | unknown[];
  messages?: number;
  path?: string;
  last_run?: string;
  error?: string;
  backup_id?: string;
  backup_name?: string;
  number_of_scenes?: number;
  number_of_sessions?: number;
  number_of_events?: number;
  number_of_characters?: number;
  number_of_writers?: number;
  number_of_categories?: number;
  number_of_channels?: number;
  number_of_threads?: number;
  updated_at?: string;
  schema_version?: number;
  current_schema_version?: number;
  is_schema_outdated?: boolean;
  has_data_files?: boolean;
  bot_in_guild?: boolean;
  effective_role?: BackupRole;
  role_level?: number;
}

export interface AdminConfig {
  verbosity?: Record<string, boolean>;
  eventCategories?: string[];
  chatroomCategories?: string[];
  categoriesToKeep?: string[];
  categoriesToIgnore?: string[];
  dmCategories?: string[];
  keepMode?: boolean;
  serverId?: string;
  serverName?: string;
  backupName?: string;
  path?: string;
  storageMode?: StorageMode;
  [key: string]: unknown;
}

export interface BackupConfig {
  server_id?: string;
  server_name?: string;
  format?: string;
  categories?: string[];
  channels?: string[];
  threads?: string[];
  include_archived?: boolean;
  export_formats?: string[];
  timezone?: string;
  storageMode?: StorageMode;
  admin?: AdminConfig;
  [key: string]: unknown;
}

export interface GlobalConfig {
  data_dir?: string;
  discord_token?: string;
  client_id?: string;
  client_secret?: string;
  redirect_uri?: string;
  admin?: AdminConfig;
  [key: string]: unknown;
}

export interface CurationSummary {
  unresolved_issues: number;
  unassigned_characters: number;
  flagged_messages: number;
  unlinked_writers: number;
  link_suggestions?: number;
}

export interface CharacterVersion {
  id: number;
  name?: string;
  names?: string[];
  writer?: string[];
  writer_id?: number | null;
  writer_name?: string | null;
  tags?: string[];
  version_type?: string;
  origin?: string | null;
  activity?: string | null;
  scene_count?: number;
  last_active_at?: string | null;
  last_channel_name?: string | null;
}

export interface Character {
  id: number;
  name?: string;
  names: string[];
  origin?: string | null;
  activity?: string | null;
  writer?: string[];
  writer_id?: number | null;
  writer_name?: string | null;
  group_id?: number | null;
  group_name?: string | null;
  tags?: string[];
  versions?: CharacterVersion[];
  other_versions?: CharacterVersion[];
  parent_id?: number | null;
  _parent?: Character;
  version_type?: string | null;
  scene_count?: number;
  last_active_at?: string | null;
  last_channel_name?: string | null;
}

export interface CharacterGroupMember { id: number; name: string; }
export interface CharacterGroup { id: number; name?: string; names: string[]; members: Array<CharacterGroupMember | number>; }
export interface Writer { id: number; name: string; aliases: string[]; }

export interface WriterDetailed {
  id: number;
  display_name: string;
  discord_user_id: string | null;
  is_self?: boolean;
  aliases: string[];
  character_count?: number;
  characters: Array<{ id: number; name: string; names: string[]; origin?: string | null; activity?: string | null }>;
}

export interface WriterLinkSuggestion {
  writer_id: number;
  writer_pk?: number;
  display_name: string;
  suggested_discord_id: string;
  suggested_discord_user_id?: string;
  suggested_username?: string;
  suggested_nickname?: string;
  confidence: number | string;
  confidence_level?: string;
  reason: string;
  evidence_count?: number;
}

export interface SeenDiscordUser {
  discord_user_id: string;
  username: string;
  global_name?: string | null;
  nickname?: string | null;
  is_current_member?: boolean;
  message_count?: number;
  last_seen_at?: string | null;
  linked_writer_id?: number | null;
  linked_writer_name?: string | null;
}

export interface AcceptAllWriterSuggestionsResponse {
  status: string;
  linked_count: number;
  skipped_count: number;
  linked: Array<{ writer_id: number; display_name: string; discord_user_id: string }>;
}

export interface CreateWritersFromDiscordUsersResponse {
  status: string;
  created_count: number;
  writers: WriterDetailed[];
}

export interface MyWriter { id: number; display_name: string; discord_user_id: string; aliases: string[]; character_ids: number[]; }
export interface UnassignedCharacter {
  id: number;
  name?: string;
  names: string[];
  origin?: string | null;
  activity?: string | null;
  scene_count?: number;
  last_active_at?: string | null;
  last_channel_name?: string | null;
}
export interface SceneParticipant { character_id: number; character_name: string; writer_name?: string; message_count: number; }

export interface SceneParticipantDetail {
  char_id: number;
  position: number;
  first_message_id?: string | null;
  first_timestamp?: string | null;
  first_link?: string;
  last_message_id?: string | null;
  last_timestamp?: string | null;
  last_link?: string;
}

export interface SceneIssueRef {
  id: number;
  kind: IssueKind | string;
  reason: IssueReason | string;
  candidate_message_id?: string | null;
  candidate_index?: number | null;
  resolved: boolean;
  resolved_at?: string | null;
  resolved_note?: string | null;
  resolution?: IssueResolution | string | null;
}

export interface Scene {
  id: number | string;
  pk?: number;
  scene_pk?: number;
  scene_key: string;
  custom_name?: string | null;
  kind?: 'scene' | 'session' | 'event';
  category_name?: string;
  channel_name?: string;
  start_time?: string;
  end_time?: string;
  start_message_id?: string;
  end_message_id?: string;
  message_count?: number;
  is_deleted?: boolean;
  channel_is_deleted?: boolean;
  start_message_deleted?: boolean;
  end_message_deleted?: boolean;
  participants?: SceneParticipant[] | SceneParticipantDetail[];
  status?: string;
  discord_url?: string;
  category?: string;
  channel?: string;
  channelId?: string;
  type?: string;
  thread_name?: string | null;
  characters?: number[];
  issues?: SceneIssueRef[];
  start_excerpt?: string;
  end_excerpt?: string;
  start?: { id?: string; timestamp?: string; index?: number; authorID?: string; content?: string; excerpt?: string; link?: string };
  end?: { id?: string; timestamp?: string; index?: number; authorID?: string; content?: string; excerpt?: string; link?: string };
}

export interface ChatSession {
  id: string | number;
  pk?: number;
  scene_pk?: number;
  index?: number;
  scene_key: string;
  custom_name?: string | null;
  kind: 'session';
  category: string;
  channel: string;
  channelId?: string;
  type?: string;
  thread_name?: string | null;
  status: string;
  message_count?: number;
  is_deleted?: boolean;
  channel_is_deleted?: boolean;
  start_message_deleted?: boolean;
  end_message_deleted?: boolean;
  characters: number[];
  participants: SceneParticipantDetail[];
  issues?: SceneIssueRef[];
  start_excerpt?: string;
  end_excerpt?: string;
  start: { id: string; timestamp: string; index: number; authorID: string; content: string; link: string };
  end: { id: string; timestamp: string; index: number; authorID: string; content: string; link: string };
}

export interface EventMovementHop {
  channel_id: string;
  channel_name: string;
  custom_name?: string | null;
  first_message_id: string;
  first_timestamp?: string | null;
  first_at?: string | null;
  first_link: string;
}

export interface EventChannelEntry {
  scene_pk: number;
  pk?: number;
  scene_key: string;
  channel_id: string;
  channel_name: string;
  custom_name?: string | null;
  type: 'channel' | 'thread';
  parent_channel_id?: string | null;
  status: string;
  message_count: number;
  is_deleted?: boolean;
  channel_is_deleted?: boolean;
  start_message_deleted?: boolean;
  end_message_deleted?: boolean;
  start: { id: string; timestamp: string; index?: number; authorID?: string; content?: string; link: string };
  end: { id: string; timestamp: string; index?: number; authorID?: string; content?: string; link: string };
  characters?: number[];
  participants: SceneParticipantDetail[];
  threads?: EventChannelEntry[];
}

export interface EventRecord {
  pk: number;
  id: string;
  event_key?: string;
  name?: string | null;
  status: string;
  is_curated?: boolean;
  start_timestamp: string;
  end_timestamp: string;
  start_at?: string;
  end_at?: string;
  message_count: number;
  is_deleted?: boolean;
  characters: number[];
  participants: SceneParticipantDetail[];
  character_movements: Record<string, EventMovementHop[]>;
  channels: EventChannelEntry[];
}

export interface SuggestedCharacter { char_id: number; name: string; writer_name?: string; reason: string; }

export type IssueKind = 'auto_split' | 'soft_boundary';
export type IssueResolution = 'split' | 'merged';
export type IssueReason = 'separate_roster' | 'start_tag_roster_change' | 'start_tag_same_roster' | 'roster_change' | 'manual' | 'inactivity_gap' | 'tupper_end_tag';
export type SceneStatus = 'open' | 'closed' | 'no_end_tag';
export type FlaggedKind = 'failed_tupper' | 'ooc_boundary' | 'ooc_message' | 'manual';
export type FlaggedResolution = 'override' | 'ignored' | 'kept';

export interface ManualSplitResponse {
  status: string; action: string; issue_id: number; scene_pk: number; scene_key: string;
  next_scene_pk: number; next_scene_key: string; resolution: string; resolved_at: string;
  resolved_note: string | null; action_performed: boolean;
}

export interface SceneIssue {
  id: number; kind: IssueKind; reason: IssueReason | string; scene_pk: number | null; scene_key: string;
  scene_kind?: 'scene' | 'session' | 'event'; channel_name: string; channel_discord_id: string;
  channel_is_deleted?: boolean; candidate_is_deleted?: boolean; is_deleted?: boolean;
  next_scene_pk?: number | null; next_scene_key?: string | null; candidate_message_id?: string | null;
  candidate_index?: number | null; candidate_excerpt?: string | null;
  previous_chars?: number[] | null; next_chars?: number[] | null;
  previous_char_names?: string[] | null; next_char_names?: string[] | null;
  discord_link: string; candidate_discord_link?: string | null;
  created_at: string | null; resolved_at: string | null; resolved_note: string | null;
  resolution?: IssueResolution | null; action_performed: boolean;
}

export interface DiscordAuthor {
  id?: string; name?: string; discriminator?: string; nickname?: string; avatar_url?: string;
}

export interface FlaggedMessage {
  id: number; message_id: string; kind: FlaggedKind; channel_name: string; channel_discord_id: string;
  content: string; author: DiscordAuthor; discord_link: string; flagged_at: string | null;
  is_excerpt_truncated?: boolean; is_deleted?: boolean; channel_is_deleted?: boolean; message_is_deleted?: boolean;
  resolution?: FlaggedResolution | null; override_content?: string | null;
  override_author?: DiscordAuthor | null; resolved_at?: string | null; resolved_note?: string | null;
  suggested_character?: SuggestedCharacter | null;
}

export interface FullContentResponse {
  content: string;
  is_deleted: boolean;
  is_truncated: boolean;
  hydrated: boolean;
  source: 'local_json' | 'discord_api' | 'deleted_fallback' | 'excerpt_fallback' | string;
}

export interface MessageOverride {
  id: number; message_id: string; channel_name: string; channel_discord_id: string;
  content: string; author: DiscordAuthor; discord_link: string; created_at: string | null;
  is_excerpt_truncated?: boolean; is_deleted?: boolean; channel_is_deleted?: boolean; message_is_deleted?: boolean;
}

export interface PaginatedResponse {
  total_items: number; current_page: number; per_page: number; total_pages: number;
}

export interface SceneIssuesResponse extends PaginatedResponse {
  issues: SceneIssue[];
  status_counts?: { unresolved: number; resolved: number; all: number };
  scope_counts?: Record<string, number>;
}

export interface FlaggedMessagesResponse extends PaginatedResponse {
  messages: FlaggedMessage[];
  status_counts?: { unresolved: number; resolved: number; all: number };
  scope_counts?: Record<string, number>;
}

export interface MessageOverridesResponse extends PaginatedResponse { overrides: MessageOverride[]; }
export interface ScenesResponse extends PaginatedResponse { scenes: Scene[]; }
export interface SessionsResponse extends PaginatedResponse { sessions: ChatSession[]; scenes?: Scene[]; }
export interface EventsResponse extends PaginatedResponse { events: EventRecord[]; }

export interface AdminTestActionResponse {
  status: 'success' | 'failed'; message: string; returncode?: number; output?: string; report?: Record<string, unknown>;
}
export interface SceneMergeNeighborInfo {
  exists: boolean;
  scene_pk: number | null;
  scene_key: string | null;
  custom_name: string | null;
  can_merge: boolean;
  disabled_reason: string | null;
  is_curator_split: boolean;
  issue_id: number | null;
  warning: string | null;
}

export interface SceneMergeNeighborsResponse {
  status: string;
  scene_pk: number;
  scene_key: string;
  kind: string;
  prev: SceneMergeNeighborInfo;
  next: SceneMergeNeighborInfo;
}

export interface MergeSceneResponse {
  status: 'success' | 'requires_confirmation';
  warning?: string;
  direction?: 'prev' | 'next';
  target_scene_key?: string;
  target_pk?: number;
  issue_id?: number | null;
  merged_scene?: {
    pk: number;
    scene_key: string;
    custom_name: string | null;
    kind: string;
  };
  deleted_scene_key?: string;
}

export interface DiscordRole {
  id: string;
  name: string;
  color?: number;
  position?: number;
  permissions?: string;
}

export interface DiscordRolesResponse {
  roles: DiscordRole[];
  bot_available: boolean;
}

export interface RbacConfig {
  adminRoleIds: string[];
  curatorRoleIds: string[];
  participantRoleIds: string[];
  restrictedUserIds: string[];
  blockedUserIds: string[];
}

export interface AuditLogEntry {
  id: number | string;
  actor_user_id?: string | null;
  actor_username?: string | null;
  actor_role?: string | null;
  auth_method?: string | null;
  backup_id?: string | null;
  action: string;
  target_type?: string | null;
  target_id?: string | null;
  before?: unknown;
  after?: unknown;
  metadata?: Record<string, unknown> | null;
  request_ip?: string | null;
  user_agent?: string | null;
  status: string;
  created_at: string;
}

export interface AuditLogsResponse {
  items: AuditLogEntry[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

export type BackupAuditLogEntry = AuditLogEntry;
export type BackupAuditLogsResponse = AuditLogsResponse;


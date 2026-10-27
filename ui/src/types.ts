export interface User {
  id?: string;
  sub?: string;
  username: string;
  avatar?: string | null;
  discriminator?: string;
  global_name?: string | null;
  admin?: boolean;
  authorized_guilds?: Array<{ id: string; name: string }>;
}

export interface AuthResponse {
  status: string;
  user?: User;
}

export interface MeResponse {
  user: User | null;
}

export type StepStatus = 'pending' | 'running' | 'success' | 'failed';

export interface BackupStepStatus {
  [stepName: string]: StepStatus;
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
  channels?: unknown[];
}

export interface BackupInfo {
  id: string;
  name?: string;
  server_name?: string;
  server_id?: string;
  status: 'pending' | 'running' | 'success' | 'failed';
  steps?: BackupStepStatus;
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
  number_of_characters?: number;
  number_of_categories?: number;
  number_of_channels?: number;
  number_of_threads?: number;
  updated_at?: string;
  schema_version?: number;
  current_schema_version?: number;
  is_schema_outdated?: boolean;
}

export interface BackupConfig {
  server_id: string;
  server_name?: string;
  format?: string;
  categories?: string[];
  channels?: string[];
  threads?: string[];
  include_archived?: boolean;
  export_formats?: string[];
  timezone?: string;
  [key: string]: unknown;
}

export interface GlobalConfig {
  data_dir?: string;
  discord_token?: string;
  client_id?: string;
  client_secret?: string;
  redirect_uri?: string;
  admin?: {
    verbosity: Record<string, boolean>;
    [key: string]: unknown;
  };
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
  name: string;
  version_type: string;
  origin?: string | null;
  activity?: string | null;
}

export interface Character {
  id: number;
  name: string;
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
  parent_id?: number | null;
  version_type?: string | null;
}

export interface CharacterGroupMember {
  id: number;
  name: string;
}

export interface CharacterGroup {
  id: number;
  name: string;
  names: string[];
  members: CharacterGroupMember[];
}

export interface Writer {
  id: number;
  name: string;
  aliases: string[];
}

export interface WriterDetailed {
  id: number;
  display_name: string;
  discord_user_id: string | null;
  aliases: string[];
  characters: Array<{
    id: number;
    name: string;
    names: string[];
    origin?: string | null;
    activity?: string | null;
  }>;
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

export interface MyWriter {
  id: number;
  display_name: string;
  discord_user_id: string;
  aliases: string[];
  character_ids: number[];
}

export interface UnassignedCharacter {
  id: number;
  name: string;
  names: string[];
  origin?: string | null;
  activity?: string | null;
}

export interface SceneParticipant {
  character_id: number;
  character_name: string;
  writer_name?: string;
  message_count: number;
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
  id: number;
  scene_key: string;
  category_name?: string;
  channel_name?: string;
  start_time: string;
  end_time: string;
  start_message_id?: string;
  end_message_id?: string;
  message_count: number;
  participants: SceneParticipant[];
  status?: string;
  discord_url?: string;
  category?: string;
  channel?: string;
  type?: string;
  thread_name?: string | null;
  characters?: number[];
  issues?: SceneIssueRef[];
  start?: {
    id?: string;
    timestamp?: string;
    index?: number;
    authorID?: string;
    content?: string;
    excerpt?: string;
    link?: string;
  };
  end?: {
    id?: string;
    timestamp?: string;
    index?: number;
    authorID?: string;
    content?: string;
    excerpt?: string;
    link?: string;
  };
}

export interface SuggestedCharacter {
  char_id: number;
  name: string;
  writer_name?: string;
  reason: string;
}

export type IssueKind = 'auto_split' | 'soft_boundary';
export type IssueResolution = 'split' | 'merged';
export type IssueReason = 'separate_roster' | 'start_tag_roster_change' | 'start_tag_same_roster' | 'roster_change';
export type SceneStatus = 'open' | 'closed' | 'no_end_tag';

export interface SceneIssue {
  id: number;
  kind: IssueKind;
  reason: IssueReason | string;
  scene_pk: number | null;
  scene_key: string;
  channel_name: string;
  channel_discord_id: string;
  next_scene_pk?: number | null;
  next_scene_key?: string | null;
  candidate_message_id?: string | null;
  candidate_index?: number | null;
  candidate_excerpt?: string | null;
  previous_chars?: number[] | null;
  next_chars?: number[] | null;
  previous_char_names?: string[] | null;
  next_char_names?: string[] | null;
  discord_link: string;
  candidate_discord_link?: string | null;
  created_at: string | null;
  resolved_at: string | null;
  resolved_note: string | null;
  resolution?: IssueResolution | null;
  action_performed: boolean;
}

export interface DiscordAuthor {
  id?: string;
  name?: string;
  discriminator?: string;
  nickname?: string;
  avatar_url?: string;
}

export interface FlaggedMessage {
  id: number;
  message_id: string;
  kind: string;
  channel_name: string;
  channel_discord_id: string;
  content: string;
  author: DiscordAuthor;
  discord_link: string;
  flagged_at: string | null;
  suggested_character?: SuggestedCharacter | null;
}

export interface MessageOverride {
  id: number;
  message_id: string;
  channel_name: string;
  channel_discord_id: string;
  content: string;
  author: DiscordAuthor;
  discord_link: string;
  created_at: string | null;
}

export interface PaginatedResponse {
  total_items: number;
  current_page: number;
  per_page: number;
  total_pages: number;
}

export interface SceneIssuesResponse extends PaginatedResponse {
  issues: SceneIssue[];
  status_counts?: {
    unresolved: number;
    resolved: number;
    all: number;
  };
}

export interface FlaggedMessagesResponse extends PaginatedResponse {
  messages: FlaggedMessage[];
}

export interface MessageOverridesResponse extends PaginatedResponse {
  overrides: MessageOverride[];
}

export interface ScenesResponse extends PaginatedResponse {
  scenes: Scene[];
}

export interface AdminTestActionResponse {
  status: 'success' | 'failed';
  message: string;
  returncode?: number;
  output?: string;
  report?: Record<string, unknown>;
}


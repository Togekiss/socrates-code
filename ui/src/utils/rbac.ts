import type { BackupInfo, BackupRole, User } from '../types';

export const ROLE_LEVELS: Record<BackupRole, number> = {
  viewer: 1,
  participant: 2,
  curator: 3,
  server_admin: 4,
  instance_admin: 5,
};

const ROLE_LABELS: Record<BackupRole, string> = {
  instance_admin: 'Instance Admin',
  server_admin: 'Server Admin',
  curator: 'Curator',
  participant: 'Participant',
  viewer: 'Viewer',
};

export function isBackupRole(value: unknown): value is BackupRole {
  return (
    value === 'instance_admin' ||
    value === 'server_admin' ||
    value === 'curator' ||
    value === 'participant' ||
    value === 'viewer'
  );
}

export function getRoleLevel(role?: BackupRole | string | null): number {
  if (role && isBackupRole(role)) {
    return ROLE_LEVELS[role];
  }
  return ROLE_LEVELS.viewer;
}

export function hasMinRole(
  role: BackupRole | string | null | undefined,
  minRole: BackupRole
): boolean {
  return getRoleLevel(role) >= ROLE_LEVELS[minRole];
}

export function getEffectiveRole(
  user?: User | null,
  backupInfo?: BackupInfo | null,
  selectedBackup?: BackupInfo | null
): BackupRole {
  if (isBackupRole(backupInfo?.effective_role)) {
    return backupInfo.effective_role;
  }
  if (isBackupRole(selectedBackup?.effective_role)) {
    return selectedBackup.effective_role;
  }
  if (user?.is_instance_admin === true) {
    return 'instance_admin';
  }
  return 'viewer';
}

export function getEffectiveRoleLevel(
  user?: User | null,
  backupInfo?: BackupInfo | null,
  selectedBackup?: BackupInfo | null
): number {
  if (typeof backupInfo?.role_level === 'number') {
    return backupInfo.role_level;
  }
  if (typeof selectedBackup?.role_level === 'number') {
    return selectedBackup.role_level;
  }
  return getRoleLevel(getEffectiveRole(user, backupInfo, selectedBackup));
}

export function formatRoleLabel(role: BackupRole): string {
  return ROLE_LABELS[role] || 'Viewer';
}

export function safeDiscordUrl(url?: string | null): string | null {
  if (!url || typeof url !== 'string') return null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:') return null;
    const host = parsed.hostname.toLowerCase();
    if (
      host === 'discord.com' ||
      host === 'ptb.discord.com' ||
      host === 'canary.discord.com' ||
      host === 'discordapp.com'
    ) {
      return parsed.toString();
    }
    return null;
  } catch {
    return null;
  }
}

export function safeDiscordAvatarUrl(user?: User | null): string | null {
  if (!user?.avatar) return null;
  const userId = String(user.sub || user.id || '').trim();
  const avatar = String(user.avatar).trim();
  if (!/^\d{15,22}$/.test(userId)) return null;
  if (!/^(a_)?[a-fA-F0-9]{1,64}$/.test(avatar)) return null;
  return `https://cdn.discordapp.com/avatars/${userId}/${avatar}.png`;
}

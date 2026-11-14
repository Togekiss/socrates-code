import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  CheckCircle,
  Eye,
  Plus,
  RefreshCw,
  Shield,
  Trash2,
  UserX,
} from 'lucide-react';
import { api, getErrorMessage } from '../api';
import type {
  DiscordRole,
  RbacConfig,
  WriterDetailed,
} from '../types';
import { AuditLogViewer } from './AuditLogViewer';
import { Button, PanelSurface } from './ui';

interface UsersTabProps {
  backupId: string;
  onRefreshSummary?: () => void;
}

const EMPTY_RBAC: RbacConfig = {
  adminRoleIds: [],
  curatorRoleIds: [],
  participantRoleIds: [],
  restrictedUserIds: [],
  blockedUserIds: [],
};

const SNOWFLAKE_RE = /^\d{15,22}$/;

type RoleBucketKey = 'adminRoleIds' | 'curatorRoleIds' | 'participantRoleIds';
type UserBucketKey = 'restrictedUserIds' | 'blockedUserIds';

export const UsersTab = ({ backupId, onRefreshSummary }: UsersTabProps) => {
  const [rbac, setRbac] = useState<RbacConfig>(EMPTY_RBAC);
  const [discordRoles, setDiscordRoles] = useState<DiscordRole[]>([]);
  const [botAvailable, setBotAvailable] = useState<boolean>(false);
  const [writers, setWriters] = useState<WriterDetailed[]>([]);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const [manualRoleInputs, setManualRoleInputs] = useState<Record<RoleBucketKey, string>>({
    adminRoleIds: '',
    curatorRoleIds: '',
    participantRoleIds: '',
  });
  const [manualUserInputs, setManualUserInputs] = useState<Record<UserBucketKey, string>>({
    restrictedUserIds: '',
    blockedUserIds: '',
  });

  const loadData = useCallback(async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const [rbacRes, rolesRes, writersRes] = await Promise.all([
        api.getBackupRbac(backupId),
        api.getBackupDiscordRoles(backupId).catch(() => ({ roles: [], bot_available: false })),
        api.getWritersDetailed(backupId).catch(() => [] as WriterDetailed[]),
      ]);
      setRbac({
        adminRoleIds: rbacRes.adminRoleIds || [],
        curatorRoleIds: rbacRes.curatorRoleIds || [],
        participantRoleIds: rbacRes.participantRoleIds || [],
        restrictedUserIds: rbacRes.restrictedUserIds || [],
        blockedUserIds: rbacRes.blockedUserIds || [],
      });
      setDiscordRoles(rolesRes.roles || []);
      setBotAvailable(Boolean(rolesRes.bot_available));
      setWriters(Array.isArray(writersRes) ? writersRes : []);
    } catch (err) {
      setErrorMsg(getErrorMessage(err, 'Failed to load RBAC configuration.'));
    } finally {
      setLoading(false);
    }
  }, [backupId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const roleNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const r of discordRoles) {
      map.set(String(r.id), r.name);
    }
    return map;
  }, [discordRoles]);

  const writerOptions = useMemo(
    () =>
      writers.filter(w => Boolean(w.discord_user_id)).map(w => ({
        id: String(w.discord_user_id),
        label: `${w.display_name} (${w.discord_user_id})`,
        name: w.display_name,
      })),
    [writers]
  );

  const writerNameByDiscordId = useMemo(() => {
    const map = new Map<string, string>();
    for (const opt of writerOptions) {
      map.set(opt.id, opt.name);
    }
    return map;
  }, [writerOptions]);

  const addManualId = (
    kind: 'role' | 'user',
    bucket: RoleBucketKey | UserBucketKey,
    rawValue: string
  ) => {
    const trimmed = rawValue.trim();
    if (!trimmed) return;
    if (!SNOWFLAKE_RE.test(trimmed)) {
      setErrorMsg(`Invalid Discord snowflake ID "${trimmed}". Expected 15-22 digits.`);
      return;
    }
    setErrorMsg(null);
    setSuccessMsg(null);
    setRbac(prev => {
      const list = prev[bucket];
      if (list.includes(trimmed)) return prev;
      return { ...prev, [bucket]: [...list, trimmed] };
    });
    if (kind === 'role') {
      setManualRoleInputs(prev => ({ ...prev, [bucket]: '' }));
    } else {
      setManualUserInputs(prev => ({ ...prev, [bucket]: '' }));
    }
  };

  const removeIdFromBucket = (bucket: RoleBucketKey | UserBucketKey, idToRemove: string) => {
    setSuccessMsg(null);
    setErrorMsg(null);
    setRbac(prev => ({
      ...prev,
      [bucket]: prev[bucket].filter(id => id !== idToRemove),
    }));
  };

  const handleSave = async () => {
    setSaving(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      const saved = await api.updateBackupRbac(backupId, rbac);
      setRbac({
        adminRoleIds: saved.adminRoleIds || [],
        curatorRoleIds: saved.curatorRoleIds || [],
        participantRoleIds: saved.participantRoleIds || [],
        restrictedUserIds: saved.restrictedUserIds || [],
        blockedUserIds: saved.blockedUserIds || [],
      });
      setSuccessMsg('Access control settings saved.');
      onRefreshSummary?.();
    } catch (err) {
      setErrorMsg(getErrorMessage(err, 'Failed to save access control settings.'));
    } finally {
      setSaving(false);
    }
  };

  const roleSections: Array<{
    key: RoleBucketKey;
    title: string;
    description: string;
  }> = [
    {
      key: 'adminRoleIds',
      title: 'Server Admin Roles',
      description: 'Full control over this backup: pipeline runs, server configuration, logs, and user access rules.',
    },
    {
      key: 'curatorRoleIds',
      title: 'Curator Roles',
      description: 'Can manage writers, characters, scenes, events, scene issues, and flagged messages.',
    },
    {
      key: 'participantRoleIds',
      title: 'Participant Roles',
      description: 'Can edit their own linked writer profile and manage their own assigned characters.',
    },
  ];

  const userSections: Array<{
    key: UserBucketKey;
    title: string;
    description: string;
    icon: typeof Eye;
  }> = [
    {
      key: 'restrictedUserIds',
      title: 'Restricted Users (Viewer Lock)',
      description: 'Forced to read-only Viewer access on this backup regardless of Discord server roles.',
      icon: Eye,
    },
    {
      key: 'blockedUserIds',
      title: 'Blocked Users (403 Denied)',
      description: 'Completely blocked from viewing or modifying this backup.',
      icon: UserX,
    },
  ];

  return (
    <div className="space-y-6">
      {errorMsg && (
        <div className="banner-danger flex items-center gap-2 text-sm">
          <AlertCircle size={16} />
          <span>{errorMsg}</span>
        </div>
      )}

      {successMsg && (
        <div className="banner-success flex items-center gap-2 text-sm">
          <CheckCircle size={16} />
          <span>{successMsg}</span>
        </div>
      )}

      {/* Card 1: Discord Server Role Mapping */}
      <PanelSurface className="flex-col gap-md">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <Shield size={18} className="mt-0.5 shrink-0" style={{ color: 'var(--accent-primary)' }} />
            <div>
              <h2 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--text-primary)' }}>
                Discord Server Role Mapping
              </h2>
              <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)', margin: 0 }}>
                Map Discord server roles to Socrates permission tiers for this backup.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void loadData()}
              disabled={loading || saving}
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              Refresh
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => void handleSave()}
              disabled={loading || saving}
            >
              {saving ? 'Saving...' : 'Save Access Rules'}
            </Button>
          </div>
        </div>
        {!botAvailable && (
          <div
            className="text-xs px-3 py-2 rounded mb-4"
            style={{
              backgroundColor: 'var(--bg-elevated)',
              border: '1px solid var(--border-subtle)',
              color: 'var(--text-secondary)',
            }}
          >
            Discord Bot role list is currently unavailable. You can still add or remove Discord Role IDs manually below.
          </div>
        )}

        <div className="space-y-5">
          {roleSections.map(section => {
            const selectedIds = rbac[section.key];
            const availableDiscordRoles = discordRoles.filter(
              role => !selectedIds.includes(String(role.id))
            );
            return (
              <div
                key={section.key}
                className="p-4 rounded-lg space-y-3"
                style={{
                  backgroundColor: 'var(--bg-elevated)',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                <div>
                  <h4 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                    {section.title}
                  </h4>
                  <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                    {section.description}
                  </p>
                </div>

                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                  {discordRoles.length > 0 && (
                    <select
                      aria-label={`${section.title} Discord role selector`}
                      className="form-control text-xs sm:w-64"
                      value=""
                      disabled={availableDiscordRoles.length === 0}
                      onChange={e => {
                        if (e.target.value) {
                          addManualId('role', section.key, e.target.value);
                        }
                      }}
                    >
                      <option value="">
                        {availableDiscordRoles.length > 0
                          ? 'Select a Discord server role...'
                          : 'All server roles selected'}
                      </option>
                      {availableDiscordRoles.map(role => (
                        <option key={`${section.key}-${role.id}`} value={String(role.id)}>
                          {role.name}
                        </option>
                      ))}
                    </select>
                  )}

                  <div className="flex items-center gap-2 flex-1">
                    <input
                      type="text"
                      className="form-control text-xs"
                      placeholder="Add Discord Role ID (15-22 digits)"
                      value={manualRoleInputs[section.key]}
                      onChange={e =>
                        setManualRoleInputs(prev => ({ ...prev, [section.key]: e.target.value }))
                      }
                      onKeyDown={e => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          addManualId('role', section.key, manualRoleInputs[section.key]);
                        }
                      }}
                    />
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => addManualId('role', section.key, manualRoleInputs[section.key])}
                    >
                      <Plus size={14} />
                      Add ID
                    </Button>
                  </div>
                </div>

                {selectedIds.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {selectedIds.map(id => {
                      const label = roleNameById.get(id);
                      return (
                        <span
                          key={`${section.key}-selected-${id}`}
                          className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-mono"
                          style={{
                            backgroundColor: 'var(--bg-surface)',
                            border: '1px solid var(--border-subtle)',
                            color: 'var(--text-secondary)',
                          }}
                        >
                          <span>{label ? `${label} (${id})` : id}</span>
                          <button
                            type="button"
                            onClick={() => removeIdFromBucket(section.key, id)}
                            className="hover:opacity-80"
                            aria-label={`Remove role ${id}`}
                            style={{ color: 'var(--danger)' }}
                          >
                            <Trash2 size={12} />
                          </button>
                        </span>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-xs italic" style={{ color: 'var(--text-muted)' }}>
                    No Discord roles assigned to this tier.
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </PanelSurface>

      {/* Card 2: User Restrictions & Blocks */}
      <PanelSurface className="flex-col gap-md">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <UserX size={18} className="mt-0.5 shrink-0" style={{ color: 'var(--warning)' }} />
            <div>
              <h2 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--text-primary)' }}>
                User Restrictions &amp; Blocks
              </h2>
              <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)', margin: 0 }}>
                Restrict specific Discord users to read-only Viewer access or block them completely.
              </p>
            </div>
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={() => void handleSave()}
            disabled={loading || saving}
          >
            {saving ? 'Saving...' : 'Save User Rules'}
          </Button>
        </div>
        <div className="space-y-5">
          {userSections.map(section => {
            const Icon = section.icon;
            const selectedIds = rbac[section.key];
            const availableWriterOpts = writerOptions.filter(opt => !selectedIds.includes(opt.id));
            return (
              <div
                key={section.key}
                className="p-4 rounded-lg space-y-3"
                style={{
                  backgroundColor: 'var(--bg-elevated)',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                <div className="flex items-start gap-2">
                  <Icon size={16} className="mt-0.5 shrink-0" style={{ color: 'var(--text-secondary)' }} />
                  <div>
                    <h4 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                      {section.title}
                    </h4>
                    <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                      {section.description}
                    </p>
                  </div>
                </div>

                {selectedIds.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {selectedIds.map(id => {
                      const writerName = writerNameByDiscordId.get(id);
                      return (
                        <span
                          key={`${section.key}-${id}`}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs"
                          style={{
                            backgroundColor: 'var(--bg-surface)',
                            border: '1px solid var(--border-subtle)',
                            color: 'var(--text-primary)',
                          }}
                        >
                          <span className="font-mono">
                            {writerName ? `${writerName} (${id})` : id}
                          </span>
                          <button
                            type="button"
                            onClick={() => removeIdFromBucket(section.key, id)}
                            className="hover:opacity-80"
                            aria-label={`Remove user ${id}`}
                            style={{ color: 'var(--danger)' }}
                          >
                            <Trash2 size={12} />
                          </button>
                        </span>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-xs italic" style={{ color: 'var(--text-muted)' }}>
                    No users in this list.
                  </p>
                )}

                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                  {availableWriterOpts.length > 0 && (
                    <select
                      className="form-control text-xs"
                      value=""
                      onChange={e => {
                        if (e.target.value) {
                          addManualId('user', section.key, e.target.value);
                        }
                      }}
                    >
                      <option value="">Quick-add linked writer...</option>
                      {availableWriterOpts.map(opt => (
                        <option key={`${section.key}-opt-${opt.id}`} value={opt.id}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  )}

                  <div className="flex items-center gap-2 flex-1">
                    <input
                      type="text"
                      className="form-control text-xs"
                      placeholder="Add Discord User ID (15-22 digits)"
                      value={manualUserInputs[section.key]}
                      onChange={e =>
                        setManualUserInputs(prev => ({ ...prev, [section.key]: e.target.value }))
                      }
                      onKeyDown={e => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          addManualId('user', section.key, manualUserInputs[section.key]);
                        }
                      }}
                    />
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => addManualId('user', section.key, manualUserInputs[section.key])}
                    >
                      <Plus size={14} />
                      Add ID
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </PanelSurface>

      {/* Card 3: Backup Audit Log Viewer */}
      <AuditLogViewer
        title="Backup Audit Log"
        description="Security-relevant backup actions, curation edits, RBAC changes, and denied requests (UTC)."
        fetchLogs={params => api.getBackupAuditLogs(backupId, params)}
        refreshKey={backupId}
      />
    </div>
  );
};

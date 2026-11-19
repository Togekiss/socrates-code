import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  CheckCircle,
  Eye,
  Info,
  RefreshCw,
  Shield,
  UserX,
} from 'lucide-react';
import { api, getErrorMessage } from '../api';
import type {
  DiscordRole,
  RbacConfig,
  WriterDetailed,
} from '../types';
import { AuditLogViewer } from './AuditLogViewer';
import { RbacBucketCard } from './users/RbacBucketCard';
import { Button, PanelSurface, type BadgeVariant, type DataCardAccent } from './ui';

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

const ROLE_SECTIONS: Array<{
  key: RoleBucketKey;
  title: string;
  description: string;
  accent: DataCardAccent;
  chipVariant: BadgeVariant;
}> = [
  {
    key: 'adminRoleIds',
    title: 'Server Admin Roles',
    description: 'Full control over this backup: pipeline runs, server configuration, logs, and user access rules.',
    accent: 'accent',
    chipVariant: 'accent',
  },
  {
    key: 'curatorRoleIds',
    title: 'Curator Roles',
    description: 'Can manage writers, characters, scenes, events, scene issues, and flagged messages.',
    accent: 'success',
    chipVariant: 'info',
  },
  {
    key: 'participantRoleIds',
    title: 'Participant Roles',
    description: 'Can edit their own linked writer profile and manage their own assigned characters.',
    accent: 'resolved',
    chipVariant: 'success',
  },
];

const USER_SECTIONS: Array<{
  key: UserBucketKey;
  title: string;
  description: string;
  accent: DataCardAccent;
  chipVariant: BadgeVariant;
  icon: typeof Eye;
}> = [
  {
    key: 'restrictedUserIds',
    title: 'Restricted Users (Viewer Lock)',
    description: 'Forced to read-only Viewer access on this backup regardless of Discord server roles.',
    accent: 'warning',
    chipVariant: 'warning',
    icon: Eye,
  },
  {
    key: 'blockedUserIds',
    title: 'Blocked Users (403 Denied)',
    description: 'Completely blocked from viewing or modifying this backup.',
    accent: 'danger',
    chipVariant: 'danger',
    icon: UserX,
  },
];

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
      writers
        .filter(w => Boolean(w.discord_user_id))
        .map(w => ({
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

  return (
    <div className="flex-col gap-xl">
      {errorMsg && (
        <div className="banner-danger mb-0" role="alert">
          <div className="banner-content text-sm">
            <AlertCircle size={16} className="shrink-0" />
            <span>{errorMsg}</span>
          </div>
        </div>
      )}

      {successMsg && (
        <div className="banner-success mb-0" role="status">
          <div className="banner-content text-sm">
            <CheckCircle size={16} className="shrink-0" />
            <span>{successMsg}</span>
          </div>
        </div>
      )}

      {/* Card 1: Discord Server Role Mapping */}
      <PanelSurface className="flex-col gap-lg">
        <div className="section-header">
          <div className="section-header-title-row">
            <Shield size={18} className="section-header-icon section-header-icon--accent" />
            <div>
              <h2 className="section-header-title">Discord Server Role Mapping</h2>
              <p className="section-header-desc">
                Map Discord server roles to Socrates permission tiers for this backup.
              </p>
            </div>
          </div>
          <div className="flex-row items-center gap-sm flex-wrap">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void loadData()}
              disabled={loading || saving}
              icon={<RefreshCw size={14} className={loading ? 'animate-spin' : ''} />}
            >
              Refresh
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => void handleSave()}
              disabled={loading || saving}
              loading={saving}
            >
              {saving ? 'Saving...' : 'Save Access Rules'}
            </Button>
          </div>
        </div>

        {!botAvailable && (
          <div className="banner-info mb-0">
            <div className="banner-content text-sm">
              <Info size={16} className="shrink-0" />
              <span>
                Discord Bot role list is currently unavailable. You can still add or remove Discord Role IDs manually below.
              </span>
            </div>
          </div>
        )}

        <div className="flex-col gap-lg">
          {ROLE_SECTIONS.map(section => {
            const selectedIds = rbac[section.key];
            const availableDiscordRoles = discordRoles
              .filter(role => !selectedIds.includes(String(role.id)))
              .map(role => ({ id: String(role.id), label: role.name }));

            return (
              <RbacBucketCard
                key={section.key}
                title={section.title}
                description={section.description}
                accent={section.accent}
                chipVariant={section.chipVariant}
                chipIcon={<Shield size={12} />}
                selectedIds={selectedIds}
                options={availableDiscordRoles}
                getDisplayLabel={id => {
                  const label = roleNameById.get(id);
                  return label ? `${label} (${id})` : id;
                }}
                selectPlaceholder="Select a Discord server role..."
                selectAriaLabel={`${section.title} Discord role selector`}
                emptySelectText={discordRoles.length > 0 ? 'All server roles selected' : undefined}
                manualInputPlaceholder="Add Discord Role ID (15-22 digits)"
                manualInputValue={manualRoleInputs[section.key]}
                onManualInputChange={val =>
                  setManualRoleInputs(prev => ({ ...prev, [section.key]: val }))
                }
                onAddId={id => addManualId('role', section.key, id)}
                onRemoveId={id => removeIdFromBucket(section.key, id)}
                emptyText="No Discord roles assigned to this tier."
                removeAriaPrefix="Remove role"
              />
            );
          })}
        </div>
      </PanelSurface>

      {/* Card 2: User Restrictions & Blocks */}
      <PanelSurface className="flex-col gap-lg">
        <div className="section-header">
          <div className="section-header-title-row">
            <UserX size={18} className="section-header-icon section-header-icon--warning" />
            <div>
              <h2 className="section-header-title">User Restrictions &amp; Blocks</h2>
              <p className="section-header-desc">
                Restrict specific Discord users to read-only Viewer access or block them completely.
              </p>
            </div>
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={() => void handleSave()}
            disabled={loading || saving}
            loading={saving}
          >
            {saving ? 'Saving...' : 'Save User Rules'}
          </Button>
        </div>

        <div className="flex-col gap-lg">
          {USER_SECTIONS.map(section => {
            const Icon = section.icon;
            const selectedIds = rbac[section.key];
            const availableWriterOpts = writerOptions
              .filter(opt => !selectedIds.includes(opt.id))
              .map(opt => ({ id: opt.id, label: opt.label }));

            return (
              <RbacBucketCard
                key={section.key}
                title={section.title}
                description={section.description}
                icon={<Icon size={16} />}
                accent={section.accent}
                chipVariant={section.chipVariant}
                chipIcon={<Icon size={12} />}
                selectedIds={selectedIds}
                options={availableWriterOpts}
                getDisplayLabel={id => {
                  const writerName = writerNameByDiscordId.get(id);
                  return writerName ? `${writerName} (${id})` : id;
                }}
                selectPlaceholder="Quick-add linked writer..."
                selectAriaLabel={`${section.title} linked writer selector`}
                manualInputPlaceholder="Add Discord User ID (15-22 digits)"
                manualInputValue={manualUserInputs[section.key]}
                onManualInputChange={val =>
                  setManualUserInputs(prev => ({ ...prev, [section.key]: val }))
                }
                onAddId={id => addManualId('user', section.key, id)}
                onRemoveId={id => removeIdFromBucket(section.key, id)}
                emptyText="No users in this list."
                removeAriaPrefix="Remove user"
              />
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

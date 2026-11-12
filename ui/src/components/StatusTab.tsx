import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import {
  Database,
  Folder,
  Hash,
  MessageSquare,
  Calendar,
  Users,
  Clock,
  AlertCircle,
  CheckCircle,
  AlertTriangle,
  UserCheck,
  MessageSquareCode,
  ExternalLink,
} from 'lucide-react';
import type { BackupInfo, CurationSummary } from '../types';
import type { TabType } from './Sidebar';
import { AiDisclosure } from './AiDisclosure';
import { PanelSurface, StatCard, DataCard, Badge, Button } from './ui';

interface StatusTabProps {
  backupId: string | null;
  setTab: (tab: TabType) => void;
  curationSummary?: CurationSummary | null;
  backupInfo?: BackupInfo | null;
  onUpgrade?: () => void;
  isUpgrading?: boolean;
}

const getCount = (numVal?: number, fallback?: number | unknown[]): number => {
  if (typeof numVal === 'number') return numVal;
  if (typeof fallback === 'number') return fallback;
  if (Array.isArray(fallback)) return fallback.length;
  return 0;
};

export const StatusTab = ({
  backupId,
  setTab,
  curationSummary: parentSummary,
  backupInfo: parentInfo,
  onUpgrade,
  isUpgrading,
}: StatusTabProps) => {
  const navigate = useNavigate();
  const [info, setInfo] = useState<BackupInfo | null>(parentInfo || null);
  const [summary, setSummary] = useState<CurationSummary | null>(parentSummary || null);
  const [numWriters, setNumWriters] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!backupId) return;
    setError(null);
    if (!parentInfo) setInfo(null);

    Promise.all([
      api.getBackupInfo(backupId).then(setInfo),
      api.getCurationSummary(backupId).then(setSummary).catch(() => null),
      api.getWriters(backupId).then(w => setNumWriters(Array.isArray(w) ? w.length : 0)).catch(() => 0),
    ]).catch(err => setError(err.message));
  }, [backupId, parentInfo]);

  useEffect(() => {
    if (parentInfo) setInfo(parentInfo);
  }, [parentInfo]);

  useEffect(() => {
    if (parentSummary) setSummary(parentSummary);
  }, [parentSummary]);

  if (!backupId) {
    return (
      <div className="empty-state">
        <Database size={48} className="empty-state-icon" />
        <h2 className="empty-state-title">Please select a backup</h2>
        <p className="empty-state-desc">
          Please select a backup from the dropdown menu to view its status.
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="banner-danger">
        <div className="banner-content">
          <AlertCircle size={28} className="flex-shrink-0" />
          <div>
            <h3 className="banner-title">Error Loading Backup</h3>
            <p className="banner-subtitle">{error}</p>
          </div>
        </div>
      </div>
    );
  }

  if (!info) {
    return (
      <PanelSurface className="text-secondary" style={{ padding: '2rem' }}>
        Loading status...
      </PanelSurface>
    );
  }

  const title = info.name || info.server_name || backupId;
  const numScenes = getCount(info.number_of_scenes, info.scenes);
  const numSessions = info.number_of_sessions ?? 0;
  const numEvents = info.number_of_events ?? 0;
  const numCharacters = getCount(info.number_of_characters, info.characters);
  const numWritersVal = info.number_of_writers ?? numWriters;
  const numCategories = getCount(info.number_of_categories, info.categories);
  const numChannels = getCount(info.number_of_channels, info.channels);
  const numThreads = getCount(info.number_of_threads, info.threads);

  return (
    <div className="status-tab flex-col gap-lg">
      <PanelSurface className="flex-col gap-lg">
        {/* Header */}
        <div className="flex-row items-center justify-between flex-wrap gap-md">
          <div>
            <h2 style={{ fontSize: '1.5rem', margin: 0, color: 'var(--text-primary)' }}>{title}</h2>
            <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>ID: {backupId}</span>
          </div>

          <div className="flex-row items-center gap-sm flex-wrap">
            {info.schema_version !== undefined && info.schema_version !== null && (
              <Badge variant={info.is_schema_outdated ? 'danger' : 'success'}>
                <Database size={14} />
                <span>
                  {info.is_schema_outdated
                    ? `Schema v${info.schema_version} (Outdated)`
                    : `Schema v${info.schema_version}`}
                </span>
              </Badge>
            )}

            {info.is_schema_outdated && onUpgrade && (
              <Button
                variant="danger"
                size="sm"
                onClick={onUpgrade}
                loading={isUpgrading}
              >
                Upgrade Database
              </Button>
            )}

            <Badge
              variant={
                info.status === 'success'
                  ? 'success'
                  : info.status === 'failed'
                  ? 'danger'
                  : 'warning'
              }
            >
              {info.status === 'success' ? (
                <CheckCircle size={14} />
              ) : info.status === 'failed' ? (
                <AlertCircle size={14} />
              ) : (
                <Clock size={14} />
              )}
              <span>
                {info.status === 'success' ? 'Ready' : info.status === 'failed' ? 'Failed' : 'Pending / Running'}
              </span>
            </Badge>
          </div>
        </div>

        {/* Dataset Statistics */}
        <div>
          <h3 className="sidebar-group-title" style={{ padding: 0, marginBottom: '0.75rem' }}>
            Dataset Overview
          </h3>
          <div className="stat-cards-grid">
            <StatCard
              label="Categories"
              value={numCategories}
              icon={<Folder size={18} />}
            />
            <StatCard
              label="Channels"
              value={numChannels}
              icon={<Hash size={18} />}
            />
            <StatCard
              label="Threads"
              value={numThreads}
              icon={<MessageSquare size={18} />}
            />
            <StatCard
              label="Scenes"
              value={numScenes}
              icon={<Database size={18} />}
              onClick={numScenes > 0 ? () => setTab('scenes') : undefined}
            />
            <StatCard
              label="Chat Sessions"
              value={numSessions}
              icon={<MessageSquare size={18} />}
              onClick={numSessions > 0 ? () => setTab('chat_sessions') : undefined}
            />
            <StatCard
              label="Events"
              value={numEvents}
              icon={<Calendar size={18} />}
              onClick={numEvents > 0 ? () => setTab('events') : undefined}
            />
            <StatCard
              label="Characters"
              value={numCharacters}
              icon={<Users size={18} />}
              onClick={numCharacters > 0 ? () => setTab('characters') : undefined}
            />
            <StatCard
              label="Writers"
              value={numWritersVal}
              icon={<UserCheck size={18} />}
              onClick={numWritersVal > 0 ? () => setTab('writers') : undefined}
            />
          </div>
        </div>

        {/* Curation & Review Queues Dashboard */}
        {summary && (
          <div>
            <h3 className="sidebar-group-title" style={{ padding: 0, marginBottom: '0.75rem' }}>
              Curation &amp; Review Queues
            </h3>
            <div className="curation-summary-grid">
              <DataCard
                accent="danger"
                onClick={() => setTab('scene_issues')}
                tabIndex={0}
                role="button"
                style={{ cursor: 'pointer' }}
              >
                <div className="flex-row items-center justify-between" style={{ color: 'var(--danger-text)', marginBottom: '0.5rem', fontSize: '0.9rem', fontWeight: 600 }}>
                  <span className="flex-row items-center gap-xs">
                    <AlertTriangle size={16} /> Scene Issues
                  </span>
                  <ExternalLink size={14} />
                </div>
                <div style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--danger-text)' }}>
                  {summary.unresolved_issues}
                </div>
                <div className="stat-card-subtext" style={{ marginTop: '0.25rem' }}>
                  {summary.unresolved_issues === 1 ? '1 unresolved issue' : `${summary.unresolved_issues} unresolved issues`}
                </div>
              </DataCard>

              <DataCard
                accent="warning"
                onClick={() => setTab('flagged_messages')}
                tabIndex={0}
                role="button"
                style={{ cursor: 'pointer' }}
              >
                <div className="flex-row items-center justify-between" style={{ color: 'var(--warning-text)', marginBottom: '0.5rem', fontSize: '0.9rem', fontWeight: 600 }}>
                  <span className="flex-row items-center gap-xs">
                    <MessageSquareCode size={16} /> Flagged Messages
                  </span>
                  <ExternalLink size={14} />
                </div>
                <div style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--warning-text)' }}>
                  {summary.flagged_messages}
                </div>
                <div className="stat-card-subtext" style={{ marginTop: '0.25rem' }}>
                  Non-tupper dialogue to review
                </div>
              </DataCard>

              <DataCard
                accent="accent"
                onClick={() => setTab('writers')}
                tabIndex={0}
                role="button"
                style={{ cursor: 'pointer' }}
              >
                <div className="flex-row items-center justify-between" style={{ color: 'var(--accent-secondary)', marginBottom: '0.5rem', fontSize: '0.9rem', fontWeight: 600 }}>
                  <span className="flex-row items-center gap-xs">
                    <UserCheck size={16} /> Unlinked Writers
                  </span>
                  <ExternalLink size={14} />
                </div>
                <div style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--accent-secondary)' }}>
                  {summary.unlinked_writers}
                </div>
                <div className="stat-card-subtext" style={{ marginTop: '0.25rem' }}>
                  Writers with no Discord ID linked
                </div>
              </DataCard>

              <DataCard
                accent="accent"
                onClick={() => navigate('/characters?unassigned=1')}
                tabIndex={0}
                role="button"
                style={{ cursor: 'pointer' }}
              >
                <div className="flex-row items-center justify-between" style={{ color: 'var(--text-primary)', marginBottom: '0.5rem', fontSize: '0.9rem', fontWeight: 600 }}>
                  <span className="flex-row items-center gap-xs">
                    <Users size={16} /> Unassigned Chars
                  </span>
                  <ExternalLink size={14} />
                </div>
                <div style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                  {summary.unassigned_characters}
                </div>
                <div className="stat-card-subtext" style={{ marginTop: '0.25rem' }}>
                  Characters without a writer
                </div>
              </DataCard>
            </div>
          </div>
        )}

        <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', textAlign: 'right' }}>
          Exported at: {info.last_run ? new Date(info.last_run).toLocaleString() : info.updated_at ? new Date(info.updated_at).toLocaleString() : 'Unknown'}
        </div>
      </PanelSurface>

      <AiDisclosure />
    </div>
  );
};

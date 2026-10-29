import { useEffect, useState } from 'react';
import { api } from '../api';
import {
  Database,
  Folder,
  Hash,
  MessageSquare,
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

interface StatusTabProps {
  backupId: string | null;
  setTab: (tab: TabType) => void;
  curationSummary?: CurationSummary | null;
}

export const StatusTab = ({ backupId, setTab, curationSummary: parentSummary }: StatusTabProps) => {
  const [info, setInfo] = useState<BackupInfo | null>(null);
  const [summary, setSummary] = useState<CurationSummary | null>(parentSummary || null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!backupId) return;
    setError(null);
    setInfo(null);

    Promise.all([
      api.getBackupInfo(backupId).then(setInfo),
      api.getCurationSummary(backupId).then(setSummary).catch(() => null),
    ]).catch(err => setError(err.message));
  }, [backupId]);

  useEffect(() => {
    if (parentSummary) {
      setSummary(parentSummary);
    }
  }, [parentSummary]);

  if (!backupId) {
    return (
      <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
        <Database size={48} style={{ opacity: 0.5, marginBottom: '1rem' }} />
        <h2>Please select a backup</h2>
        <p style={{ color: 'var(--text-secondary)' }}>
          Please select a backup from the dropdown menu to view its status.
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
        <AlertCircle size={48} style={{ color: 'var(--danger)', marginBottom: '1rem' }} />
        <h2>Error Loading Backup</h2>
        <p style={{ color: 'var(--text-secondary)' }}>{error}</p>
      </div>
    );
  }

  if (!info) {
    return <div style={{ color: 'var(--text-secondary)', padding: '2rem' }}>Loading status...</div>;
  }

  const title = info.name || info.server_name || backupId;
  const numScenes =
    typeof info.number_of_scenes === 'number'
      ? info.number_of_scenes
      : typeof info.scenes === 'number'
      ? info.scenes
      : Array.isArray(info.scenes)
      ? info.scenes.length
      : 0;

  const numCharacters =
    typeof info.number_of_characters === 'number'
      ? info.number_of_characters
      : typeof info.characters === 'number'
      ? info.characters
      : Array.isArray(info.characters)
      ? info.characters.length
      : 0;

  const numCategories =
    typeof info.number_of_categories === 'number'
      ? info.number_of_categories
      : Array.isArray(info.categories)
      ? info.categories.length
      : typeof info.categories === 'number'
      ? info.categories
      : 0;

  const numChannels =
    typeof info.number_of_channels === 'number'
      ? info.number_of_channels
      : Array.isArray(info.channels)
      ? info.channels.length
      : typeof info.channels === 'number'
      ? info.channels
      : 0;

  const numThreads =
    typeof info.number_of_threads === 'number'
      ? info.number_of_threads
      : Array.isArray(info.threads)
      ? info.threads.length
      : typeof info.threads === 'number'
      ? info.threads
      : 0;

  return (
    <div>
      <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <h2 style={{ fontSize: '1.5rem', margin: 0, color: 'var(--text-primary)' }}>{title}</h2>
            <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>ID: {backupId}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            {info.schema_version !== undefined && info.schema_version !== null && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  padding: '0.4rem 0.8rem',
                  borderRadius: '20px',
                  background: 'var(--bg-tertiary)',
                  color: info.is_schema_outdated ? 'var(--danger)' : 'var(--success)',
                }}
              >
                <Database size={18} />
                <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                  {info.is_schema_outdated
                    ? `Schema v${info.schema_version} (Outdated)`
                    : `Schema v${info.schema_version}`}
                </span>
              </div>
            )}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.4rem 0.8rem',
                borderRadius: '20px',
                background: 'var(--bg-tertiary)',
                color:
                  info.status === 'success'
                    ? 'var(--success)'
                    : info.status === 'failed'
                    ? 'var(--danger)'
                    : 'var(--warning)',
              }}
            >
              {info.status === 'success' ? (
                <CheckCircle size={18} />
              ) : info.status === 'failed' ? (
                <AlertCircle size={18} />
              ) : (
                <Clock size={18} />
              )}
              <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                {info.status === 'success'
                  ? 'Ready'
                  : info.status === 'failed'
                  ? 'Failed'
                  : 'Pending / Running'}
              </span>
            </div>
          </div>
        </div>

        {/* Dataset Statistics */}
        <div>
          <h3 style={{ fontSize: '0.95rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
            Dataset Overview
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem' }}>
            <div className="stat-card" style={{ background: 'var(--bg-tertiary)', padding: '1.25rem', borderRadius: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', marginBottom: '0.5rem', fontSize: '0.9rem' }}>
                <Folder size={16} /> Categories
              </div>
              <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>{numCategories}</div>
            </div>

            <div className="stat-card" style={{ background: 'var(--bg-tertiary)', padding: '1.25rem', borderRadius: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', marginBottom: '0.5rem', fontSize: '0.9rem' }}>
                <Hash size={16} /> Channels
              </div>
              <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>{numChannels}</div>
            </div>

            <div className="stat-card" style={{ background: 'var(--bg-tertiary)', padding: '1.25rem', borderRadius: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', marginBottom: '0.5rem', fontSize: '0.9rem' }}>
                <MessageSquare size={16} /> Threads
              </div>
              <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>{numThreads}</div>
            </div>

            <div
              className="stat-card"
              style={{
                background: 'var(--bg-tertiary)',
                padding: '1.25rem',
                borderRadius: '10px',
                cursor: numScenes > 0 ? 'pointer' : 'default',
                border: '1px solid transparent',
                transition: 'border-color 0.2s ease',
              }}
              onClick={() => {
                if (numScenes > 0) setTab('scenes');
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--text-secondary)', marginBottom: '0.5rem', fontSize: '0.9rem' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <Database size={16} /> Scenes
                </span>
                {numScenes > 0 && <ExternalLink size={14} />}
              </div>
              <div style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--accent-secondary)' }}>
                {numScenes}
              </div>
            </div>

            <div
              className="stat-card"
              style={{
                background: 'var(--bg-tertiary)',
                padding: '1.25rem',
                borderRadius: '10px',
                cursor: numCharacters > 0 ? 'pointer' : 'default',
                border: '1px solid transparent',
                transition: 'border-color 0.2s ease',
              }}
              onClick={() => {
                if (numCharacters > 0) setTab('characters');
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--text-secondary)', marginBottom: '0.5rem', fontSize: '0.9rem' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <Users size={16} /> Characters
                </span>
                {numCharacters > 0 && <ExternalLink size={14} />}
              </div>
              <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>{numCharacters}</div>
            </div>
          </div>
        </div>

        {/* Curation & Review Queues Dashboard */}
        {summary && (
          <div>
            <h3 style={{ fontSize: '0.95rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
              Curation & Review Queues
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
              <div
                className="stat-card"
                onClick={() => setTab('scene_issues')}
                style={{
                  background: 'rgba(239, 68, 68, 0.08)',
                  border: '1px solid rgba(239, 68, 68, 0.25)',
                  padding: '1.25rem',
                  borderRadius: '10px',
                  cursor: 'pointer',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--danger)', marginBottom: '0.5rem', fontSize: '0.9rem', fontWeight: 600 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <AlertTriangle size={16} /> Scene Issues
                  </span>
                  <ExternalLink size={14} />
                </div>
                <div style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--danger)' }}>
                  {summary.unresolved_issues}
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                  {summary.unresolved_issues === 1 ? '1 unresolved issue' : `${summary.unresolved_issues} unresolved issues`}
                </div>
              </div>

              <div
                className="stat-card"
                onClick={() => setTab('flagged_messages')}
                style={{
                  background: 'rgba(245, 158, 11, 0.08)',
                  border: '1px solid rgba(245, 158, 11, 0.25)',
                  padding: '1.25rem',
                  borderRadius: '10px',
                  cursor: 'pointer',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--warning)', marginBottom: '0.5rem', fontSize: '0.9rem', fontWeight: 600 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <MessageSquareCode size={16} /> Flagged Messages
                  </span>
                  <ExternalLink size={14} />
                </div>
                <div style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--warning)' }}>
                  {summary.flagged_messages}
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                  Non-tupper dialogue to review
                </div>
              </div>

              <div
                className="stat-card"
                onClick={() => setTab('writers')}
                style={{
                  background: 'rgba(139, 92, 246, 0.08)',
                  border: '1px solid rgba(139, 92, 246, 0.25)',
                  padding: '1.25rem',
                  borderRadius: '10px',
                  cursor: 'pointer',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--accent-secondary)', marginBottom: '0.5rem', fontSize: '0.9rem', fontWeight: 600 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <UserCheck size={16} /> Unlinked Writers
                  </span>
                  <ExternalLink size={14} />
                </div>
                <div style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--accent-secondary)' }}>
                  {summary.unlinked_writers}
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                  Writers with no Discord ID linked
                </div>
              </div>

              <div
                className="stat-card"
                onClick={() => setTab('writers')}
                style={{
                  background: 'rgba(148, 163, 184, 0.08)',
                  border: '1px solid rgba(148, 163, 184, 0.25)',
                  padding: '1.25rem',
                  borderRadius: '10px',
                  cursor: 'pointer',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--text-secondary)', marginBottom: '0.5rem', fontSize: '0.9rem', fontWeight: 600 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <UserCheck size={16} /> Unassigned Chars
                  </span>
                  <ExternalLink size={14} />
                </div>
                <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>
                  {summary.unassigned_characters}
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                  Characters without a writer
                </div>
              </div>


            </div>
          </div>
        )}

        <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', textAlign: 'right' }}>
          Exported at: {info.last_run ? new Date(info.last_run).toLocaleString() : info.updated_at ? new Date(info.updated_at).toLocaleString() : 'Unknown'}
        </div>
      </div>

      <AiDisclosure />
    </div>
  );
};

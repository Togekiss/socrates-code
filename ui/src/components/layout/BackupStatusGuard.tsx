import React from 'react';
import { Loader2, PauseCircle, AlertTriangle } from 'lucide-react';
import type { BackupStatusGuardState } from '../../hooks/useBackupStatusGuard';

interface BackupStatusGuardProps {
  title: string;
  guard: BackupStatusGuardState;
}

export const BackupStatusGuard: React.FC<BackupStatusGuardProps> = ({ title, guard }) => {
  const {
    effectiveBackupInfo,
    effectiveBackupError,
    effectiveBackupLoading,
    isSchemaOutdated,
    isSyncing,
    isPaused,
    isFailed,
    syncProgressLabel,
    canRead,
  } = guard;

  if (effectiveBackupLoading && !effectiveBackupInfo) {
    return (
      <div className="glass-panel p-lg">
        <h2>{title}</h2>
        <p className="text-secondary">Loading backup status...</p>
      </div>
    );
  }

  if (effectiveBackupError) {
    return (
      <div className="glass-panel p-lg">
        <h2>{title}</h2>
        <div className="banner-danger mt-md">
          <span className="text-md">{effectiveBackupError}</span>
        </div>
      </div>
    );
  }

  if (isSchemaOutdated) {
    return (
      <div className="glass-panel p-lg">
        <h2>{title}</h2>
        <div className="banner-danger mt-md">
          <span className="text-md">
            This backup database uses an outdated schema (v{effectiveBackupInfo?.schema_version ?? '?'}) and cannot be queried until it is upgraded from the Status tab.
          </span>
        </div>
      </div>
    );
  }

  if (!canRead) {
    return (
      <div className="glass-panel opacity-75 p-lg">
        <h2>{title}</h2>
        <p className="text-secondary">
          {isSyncing
            ? 'Initial backup sync is running. Content will unlock as soon as the first channel commits.'
            : 'Backup has no committed data yet. Run a sync from the Pipeline & Run tab first.'}
        </p>
      </div>
    );
  }

  if (isSyncing) {
    return (
      <div className="banner-info" style={{ padding: '0.55rem 0.9rem', marginBottom: '0.5rem' }}>
        <div className="flex-row items-center gap-sm flex-wrap">
          <Loader2 size={16} className="animate-spin shrink-0" />
          <span className="text-sm font-semibold">
            {syncProgressLabel || 'Sync in progress — displaying committed data.'}
          </span>
          <span className="text-sm text-secondary">
            Curation and metadata edits are temporarily locked until sync finishes.
          </span>
        </div>
      </div>
    );
  }

  if (isPaused) {
    return (
      <div className="banner-warning" style={{ padding: '0.55rem 0.9rem', marginBottom: '0.5rem' }}>
        <div className="flex-row items-center gap-sm flex-wrap">
          <PauseCircle size={16} className="shrink-0" />
          <span className="text-sm font-semibold">
            {syncProgressLabel || 'Sync is paused — displaying committed data.'}
          </span>
          <span className="text-sm text-secondary">
            Resume sync from the Pipeline &amp; Run tab to fetch remaining channels.
          </span>
        </div>
      </div>
    );
  }

  if (isFailed) {
    return (
      <div className="banner-warning" style={{ padding: '0.55rem 0.9rem', marginBottom: '0.5rem' }}>
        <div className="flex-row items-center gap-sm flex-wrap">
          <AlertTriangle size={16} className="shrink-0" />
          <span className="text-sm font-semibold">
            {syncProgressLabel || 'Last sync failed — displaying committed data.'}
          </span>
        </div>
      </div>
    );
  }

  return null;
};

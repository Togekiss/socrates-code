import React from 'react';
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
    isRunning,
    isReady,
  } = guard;

  if (effectiveBackupLoading) {
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

  if (!isReady) {
    return (
      <div className="glass-panel opacity-50 pointer-events-none p-lg">
        <h2>{title}</h2>
        <p className="text-secondary">
          {isRunning
            ? 'Backup pipeline is currently running. Please wait for it to finish.'
            : 'Backup is not ready. Run the pipeline first.'}
        </p>
      </div>
    );
  }

  return null;
};

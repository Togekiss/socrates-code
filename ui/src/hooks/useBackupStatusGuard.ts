import { useEffect, useState } from 'react';
import { api, getErrorMessage } from '../api';
import type { BackupInfo } from '../types';

interface UseBackupStatusGuardOptions {
  backupId: string;
  backupStatus?: string;
  backupInfo?: BackupInfo | null;
  backupError?: string | null;
  backupLoading?: boolean;
}

export interface BackupStatusGuardState {
  effectiveBackupInfo: BackupInfo | null;
  effectiveBackupError: string | null;
  effectiveBackupLoading: boolean;
  isSchemaOutdated: boolean;
  isRunning: boolean;
  isReady: boolean;
}

export function useBackupStatusGuard({
  backupId,
  backupStatus,
  backupInfo,
  backupError,
  backupLoading,
}: UseBackupStatusGuardOptions): BackupStatusGuardState {
  const [fetchedStatus, setFetchedStatus] = useState<string | null>(backupInfo?.status ?? backupStatus ?? null);
  const [localBackupInfo, setLocalBackupInfo] = useState<BackupInfo | null>(null);
  const [localBackupError, setLocalBackupError] = useState<string | null>(null);
  const [localBackupLoading, setLocalBackupLoading] = useState(false);

  useEffect(() => {
    if (backupInfo !== undefined || backupError !== undefined) {
      setFetchedStatus(backupInfo?.status ?? backupStatus ?? null);
      setLocalBackupInfo(backupInfo ?? null);
      setLocalBackupError(null);
      setLocalBackupLoading(false);
      return;
    }

    if (backupStatus) {
      setFetchedStatus(backupStatus);
      setLocalBackupError(null);
      return;
    }

    let cancelled = false;
    setLocalBackupLoading(true);
    setLocalBackupError(null);
    api
      .getBackupInfo(backupId)
      .then(res => {
        if (cancelled) return;
        setLocalBackupInfo(res);
        setFetchedStatus(res.status);
      })
      .catch(err => {
        if (cancelled) return;
        console.error(err);
        setFetchedStatus(null);
        setLocalBackupError(getErrorMessage(err, 'Failed to load backup information.'));
      })
      .finally(() => {
        if (!cancelled) setLocalBackupLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [backupId, backupStatus, backupInfo, backupError]);

  const effectiveBackupInfo = backupInfo ?? localBackupInfo;
  const effectiveBackupError = backupError ?? localBackupError;
  const effectiveBackupLoading = backupLoading ?? localBackupLoading;
  const isSchemaOutdated = Boolean(effectiveBackupInfo?.is_schema_outdated);
  const hasRunningStep = Boolean(
    effectiveBackupInfo?.steps && Object.values(effectiveBackupInfo.steps).some(step => step === 'running')
  );
  const isRunning = fetchedStatus === 'pending' || fetchedStatus === 'running' || hasRunningStep;
  const isReady =
    !effectiveBackupError &&
    !isSchemaOutdated &&
    !isRunning &&
    (fetchedStatus === 'success' || fetchedStatus === 'ready' || fetchedStatus === 'READY');

  return {
    effectiveBackupInfo,
    effectiveBackupError,
    effectiveBackupLoading,
    isSchemaOutdated,
    isRunning,
    isReady,
  };
}

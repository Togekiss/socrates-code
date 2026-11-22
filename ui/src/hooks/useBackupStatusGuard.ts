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
  isSyncing: boolean;
  isPaused: boolean;
  isFailed: boolean;
  hasCommittedData: boolean;
  syncProgressLabel: string | null;
  canRead: boolean;
  canMutate: boolean;
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
  const syncStatus = effectiveBackupInfo?.sync_status;
  const isSyncing =
    syncStatus === 'syncing' || fetchedStatus === 'running' || hasRunningStep;
  const isPaused = syncStatus === 'paused';
  const isFailed = !isSyncing && !isPaused && (syncStatus === 'failed' || fetchedStatus === 'failed');

  const channelsDone = effectiveBackupInfo?.channels_done ?? 0;
  const channelsTotal = effectiveBackupInfo?.channels_total ?? 0;
  const hasCommittedData = Boolean(
    effectiveBackupInfo &&
      (channelsDone > 0 ||
        (effectiveBackupInfo.number_of_scenes ?? 0) > 0 ||
        (effectiveBackupInfo.number_of_sessions ?? 0) > 0 ||
        (effectiveBackupInfo.number_of_events ?? 0) > 0 ||
        (effectiveBackupInfo.number_of_channels ?? 0) > 0 ||
        (syncStatus === 'idle' && Boolean(effectiveBackupInfo.last_synced_at)) ||
        fetchedStatus === 'success' ||
        fetchedStatus === 'ready' ||
        fetchedStatus === 'READY')
  );

  const syncProgressLabel = isSyncing
    ? channelsTotal > 0
      ? `Syncing ${channelsDone}/${channelsTotal} channels — displaying committed data`
      : 'Sync in progress — displaying committed data'
    : isPaused
    ? channelsTotal > 0
      ? `Sync paused (${channelsDone}/${channelsTotal} channels committed)`
      : 'Sync paused — displaying committed data'
    : isFailed
    ? channelsTotal > 0
      ? `Last sync failed (${channelsDone}/${channelsTotal} channels committed)`
      : 'Last sync failed — displaying committed data'
    : null;

  const canRead = Boolean(!effectiveBackupError && !isSchemaOutdated && hasCommittedData);
  const canMutate = Boolean(canRead && !isSyncing);

  return {
    effectiveBackupInfo,
    effectiveBackupError,
    effectiveBackupLoading,
    isSchemaOutdated,
    isSyncing,
    isPaused,
    isFailed,
    hasCommittedData,
    syncProgressLabel,
    canRead,
    canMutate,
    isRunning: isSyncing,
    isReady: canRead,
  };
}

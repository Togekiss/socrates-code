import { useEffect, useState, useCallback, useRef } from 'react';
import { api, getErrorMessage } from '../api';
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Database,
  FileJson,
  HardDrive,
  PauseCircle,
  Play,
  RefreshCw,
  RotateCw,
  Sliders,
  StopCircle,
  XCircle,
} from 'lucide-react';
import { BackupForm } from './BackupForm';
import { PanelSurface, Button, Badge, LogConsole } from './ui';
import type { BackupConfig, BackupInfo, GlobalConfig } from '../types';
import { getRoleLevel, ROLE_LEVELS } from '../utils/rbac';
import { calcCompletionPct } from '../utils/formatters';

interface RunTabProps {
  backupId: string;
  backupInfo?: BackupInfo | null;
  roleLevel?: number;
  statusPollTick?: number;
  onPollStatus?: () => void;
  onRefreshSummary?: () => void;
  onBackupInfoChange?: (info: BackupInfo) => void;
}

export const RunTab = ({
  backupId,
  backupInfo: propBackupInfo,
  roleLevel: propRoleLevel,
  statusPollTick = 0,
  onPollStatus,
  onRefreshSummary,
  onBackupInfoChange,
}: RunTabProps) => {
  const [globalConfig, setGlobalConfig] = useState<GlobalConfig | null>(null);
  const [localBackupInfo, setLocalBackupInfo] = useState<BackupInfo | null>(null);
  const [backupConfig, setBackupConfig] = useState<BackupConfig | null>(null);
  const [isFormOpen, setIsFormOpen] = useState<boolean>(false);
  const [backupLogs, setBackupLogs] = useState<string[]>([]);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [isUpgrading, setIsUpgrading] = useState(false);
  const [activeAction, setActiveAction] = useState<
    'sync' | 'resume' | 'rescan_discord' | 'rescan_local_json' | 'reindex' | null
  >(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const wasRunningRef = useRef(false);
  const activeBackupIdRef = useRef(backupId);
  const logsInFlightRef = useRef(false);

  const backupInfo = propBackupInfo !== undefined ? propBackupInfo : localBackupInfo;
  const effectiveRoleLevel = propRoleLevel ?? backupInfo?.role_level ?? getRoleLevel(backupInfo?.effective_role);
  const canManageBackup = effectiveRoleLevel >= ROLE_LEVELS.server_admin;

  useEffect(() => {
    activeBackupIdRef.current = backupId;
    wasRunningRef.current = false;
    setLocalBackupInfo(null);
    setBackupLogs([]);
    setIsFormOpen(false);
    setActiveAction(null);
    setActionError(null);
  }, [backupId]);

  const fetchConfig = useCallback(() => {
    api.getGlobalConfig().then(setGlobalConfig).catch(console.error);
  }, []);

  const fetchBackupConfig = useCallback(() => {
    if (!backupId) return;
    const requestedId = backupId;
    api
      .getBackupConfig(requestedId)
      .then(res => {
        if (activeBackupIdRef.current === requestedId) {
          setBackupConfig(res);
        }
      })
      .catch(() => {
        // Keep existing config on transient errors
      });
  }, [backupId]);

  const fetchBackupInfoStandalone = useCallback(() => {
    if (!backupId || propBackupInfo !== undefined) return;
    const requestedId = backupId;
    api
      .getBackupInfo(requestedId)
      .then(res => {
        if (activeBackupIdRef.current !== requestedId) return;
        setLocalBackupInfo(res);
        onBackupInfoChange?.(res);
      })
      .catch(() => {
        // Preserve previous backupInfo on transient errors
      });
  }, [backupId, propBackupInfo, onBackupInfoChange]);

  const fetchLogs = useCallback(
    (showLoading: boolean = true) => {
      if (!backupId || logsInFlightRef.current) return;
      const requestedId = backupId;
      logsInFlightRef.current = true;
      if (showLoading) setLoadingLogs(true);
      api
        .getBackupLogs(requestedId, 50)
        .then(res => {
          if (activeBackupIdRef.current === requestedId) {
            setBackupLogs(res.lines || []);
          }
        })
        .catch(console.error)
        .finally(() => {
          logsInFlightRef.current = false;
          if (showLoading) setLoadingLogs(false);
        });
    },
    [backupId]
  );

  const clearLogs = () => {
    if (!backupId) return;
    api.clearBackupLogs(backupId).then(() => setBackupLogs([])).catch(console.error);
  };

  const downloadLogs = async () => {
    if (!backupId) return;
    try {
      const text = await api.getBackupRawLogs(backupId);
      const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `backup-${backupId}-execution.log`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to download raw backup logs:', err);
    }
  };

  useEffect(() => {
    if (canManageBackup) {
      fetchConfig();
    }
  }, [canManageBackup, fetchConfig]);

  useEffect(() => {
    fetchBackupConfig();
    fetchBackupInfoStandalone();
    fetchLogs(true);
  }, [fetchBackupConfig, fetchBackupInfoStandalone, fetchLogs]);

  const syncStatus = backupInfo?.sync_status ?? (backupInfo?.status === 'running' ? 'syncing' : backupInfo?.status === 'failed' ? 'failed' : 'idle');
  const isSyncing =
    syncStatus === 'syncing' ||
    backupInfo?.status === 'running' ||
    Boolean(backupInfo?.steps && Object.values(backupInfo.steps).some(s => s === 'running'));
  const isAnyRunning = isUpgrading || isSyncing;

  useEffect(() => {
    if (isAnyRunning) {
      wasRunningRef.current = true;
      if (statusPollTick > 0) {
        fetchLogs(false);
      }
      return;
    }

    if (wasRunningRef.current) {
      wasRunningRef.current = false;
      setActiveAction(null);
      fetchLogs(false);
    }
  }, [isAnyRunning, statusPollTick, fetchLogs]);

  const refreshStatus = useCallback(() => {
    if (onPollStatus) {
      onPollStatus();
    } else {
      fetchBackupInfoStandalone();
    }
  }, [onPollStatus, fetchBackupInfoStandalone]);

  const markOptimisticSyncing = useCallback(() => {
    wasRunningRef.current = true;
    if (!backupInfo) return;
    const newInfo: BackupInfo = {
      ...backupInfo,
      status: 'running',
      sync_status: 'syncing',
      sync_error: null,
    };
    if (propBackupInfo === undefined) {
      setLocalBackupInfo(newInfo);
    }
    if (onBackupInfoChange) {
      onBackupInfoChange(newInfo);
    }
  }, [backupInfo, propBackupInfo, onBackupInfoChange]);

  const handleSyncMode = (mode: 'incremental' | 'resume' | 'rescan_discord' | 'rescan_local_json') => {
    if (!backupId || isAnyRunning) return;
    setActionError(null);
    setActiveAction(
      mode === 'incremental'
        ? 'sync'
        : mode === 'resume'
        ? 'resume'
        : mode
    );
    markOptimisticSyncing();

    api
      .syncBackup(backupId, { mode })
      .then(() => {
        fetchLogs(false);
        setTimeout(refreshStatus, 1000);
      })
      .catch(err => {
        console.error(`Failed to start sync (${mode}):`, err);
        setActionError(getErrorMessage(err, `Failed to start sync (${mode}).`));
        wasRunningRef.current = false;
        setActiveAction(null);
        refreshStatus();
        fetchLogs(false);
      });
  };

  const handleOfflineReindex = () => {
    if (!backupId || isAnyRunning) return;
    setActionError(null);
    setActiveAction('reindex');
    markOptimisticSyncing();

    api
      .reindexBackup(backupId, { rescan_json: false })
      .then(() => {
        fetchLogs(false);
        setTimeout(refreshStatus, 1000);
      })
      .catch(err => {
        console.error('Failed to start offline re-index:', err);
        setActionError(getErrorMessage(err, 'Failed to start offline re-index.'));
        wasRunningRef.current = false;
        setActiveAction(null);
        refreshStatus();
        fetchLogs(false);
      });
  };

  const handleUpgradeDatabase = async () => {
    if (!backupId || isUpgrading || isAnyRunning) return;
    setActionError(null);
    setIsUpgrading(true);
    try {
      await api.upgradeBackup(backupId);
      refreshStatus();
      if (onRefreshSummary) {
        onRefreshSummary();
      }
      fetchLogs(false);
    } catch (err) {
      console.error('Failed to upgrade database:', err);
      setActionError(getErrorMessage(err, 'Failed to upgrade database.'));
      refreshStatus();
    } finally {
      setIsUpgrading(false);
    }
  };

  const cancelRun = () => {
    setActionError(null);
    api
      .cancelRun(backupId)
      .then(() => {
        wasRunningRef.current = false;
        setActiveAction(null);
        refreshStatus();
        if (onRefreshSummary) {
          onRefreshSummary();
        }
        fetchLogs(false);
      })
      .catch(err => {
        console.error('Failed to cancel run:', err);
        setActionError(getErrorMessage(err, 'Failed to cancel sync.'));
        refreshStatus();
      });
  };

  if (!backupInfo) {
    return (
      <div className="empty-state">
        <p className="empty-state-desc">Select a backup to view sync &amp; pipeline controls.</p>
      </div>
    );
  }

  const title = backupInfo.name || backupInfo.server_name || backupId;
  const storageMode = backupInfo.storage_mode || 'backupless';
  const channelsTotal = backupInfo.channels_total ?? 0;
  const channelsDone = backupInfo.channels_done ?? 0;
  const progressPct = calcCompletionPct(channelsDone, channelsTotal);
  const canResume =
    syncStatus === 'paused' ||
    (syncStatus === 'failed' && channelsTotal > 0 && channelsDone < channelsTotal);

  const renderSyncBadge = () => {
    if (isSyncing) {
      return (
        <Badge variant="accent">
          <Clock size={14} className="animate-spin" />
          <span>SYNCING</span>
        </Badge>
      );
    }
    if (syncStatus === 'paused') {
      return (
        <Badge variant="warning">
          <PauseCircle size={14} />
          <span>PAUSED</span>
        </Badge>
      );
    }
    if (syncStatus === 'failed') {
      return (
        <Badge variant="danger">
          <XCircle size={14} />
          <span>FAILED</span>
        </Badge>
      );
    }
    if (backupInfo.last_synced_at || backupInfo.status === 'success') {
      return (
        <Badge variant="success">
          <CheckCircle size={14} />
          <span>IDLE (SYNCED)</span>
        </Badge>
      );
    }
    return (
      <Badge variant="neutral">
        <AlertTriangle size={14} />
        <span>NOT SYNCED</span>
      </Badge>
    );
  };

  return (
    <div className="flex-col gap-xl">
      <PanelSurface className="flex-col gap-lg">
        {/* Header */}
        <div className="flex-row items-center justify-between flex-wrap gap-lg">
          <div>
            <h2 style={{ margin: 0, fontSize: '1.35rem', color: 'var(--text-primary)' }}>{title}</h2>
            <div className="flex-row items-center gap-xs flex-wrap" style={{ marginTop: '0.35rem' }}>
              {renderSyncBadge()}
              <Badge variant={storageMode === 'full' ? 'info' : 'accent'}>
                {storageMode === 'full' ? <HardDrive size={13} /> : <Database size={13} />}
                <span>{storageMode === 'full' ? 'Full Backup' : 'Backupless'}</span>
              </Badge>
              {backupInfo.is_schema_outdated && (
                <Badge variant="danger">
                  Schema v{backupInfo.schema_version ?? '?'} (Outdated)
                </Badge>
              )}
            </div>
          </div>

          {canManageBackup && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setIsFormOpen(true)}
              icon={<Sliders size={15} />}
            >
              Edit Configuration
            </Button>
          )}
        </div>

        {/* Sync Progress & Timestamps */}
        <div
          style={{
            background: 'var(--bg-tertiary)',
            border: '1px solid var(--border-color)',
            borderRadius: '8px',
            padding: '0.9rem 1rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.6rem',
          }}
        >
          <div className="flex-row items-center justify-between flex-wrap gap-sm">
            <span className="text-sm font-semibold text-primary">
              Channel Sync Progress:{' '}
              {channelsTotal > 0 ? `${channelsDone} / ${channelsTotal} channels (${progressPct}%)` : 'No channels tracked yet'}
            </span>
            <span className="text-sm text-secondary">
              Last synced:{' '}
              {backupInfo.last_synced_at
                ? new Date(backupInfo.last_synced_at).toLocaleString()
                : 'Never'}
            </span>
          </div>

          <div
            role="progressbar"
            aria-valuenow={progressPct}
            aria-valuemin={0}
            aria-valuemax={100}
            style={{
              width: '100%',
              height: '8px',
              borderRadius: '999px',
              background: 'rgba(255, 255, 255, 0.08)',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${progressPct}%`,
                height: '100%',
                background:
                  syncStatus === 'failed'
                    ? 'var(--danger)'
                    : syncStatus === 'paused'
                    ? 'var(--warning)'
                    : 'var(--accent-primary)',
                transition: 'width 0.25s ease',
              }}
            />
          </div>

          {backupInfo.sync_started_at && isSyncing && (
            <div className="text-sm text-muted">
              Started at: {new Date(backupInfo.sync_started_at).toLocaleString()}
            </div>
          )}
        </div>

        {/* Error Notices */}
        {(actionError || (backupInfo.sync_error && (syncStatus === 'failed' || syncStatus === 'paused'))) && (
          <div className="banner-danger">
            <span className="text-md">{actionError || backupInfo.sync_error}</span>
          </div>
        )}

        {/* Action Buttons Toolbar */}
        {canManageBackup && (
          <div className="flex-row items-center gap-sm flex-wrap" style={{ marginTop: '0.25rem' }}>
            <Button
              variant={canResume ? 'warning' : 'primary'}
              size="sm"
              onClick={() => handleSyncMode(canResume ? 'resume' : 'incremental')}
              disabled={isAnyRunning}
              loading={isSyncing && (activeAction === 'sync' || activeAction === 'resume' || activeAction === null)}
              icon={<Play size={15} />}
            >
              {isSyncing ? 'Syncing...' : canResume ? 'Resume Sync' : 'Sync Updates'}
            </Button>

            {isSyncing && (
              <Button
                variant="danger"
                size="sm"
                onClick={cancelRun}
                icon={<StopCircle size={15} />}
              >
                Cancel
              </Button>
            )}

            <div
              className="flex-row items-center gap-xs flex-wrap"
              style={{
                paddingLeft: '0.75rem',
                borderLeft: '1px solid var(--border-color)',
              }}
            >
              <span className="form-hint" style={{ marginRight: '0.25rem' }}>Maintenance:</span>

              <Button
                variant="secondary"
                size="xs"
                onClick={handleOfflineReindex}
                disabled={isAnyRunning}
                loading={isSyncing && activeAction === 'reindex'}
                icon={<RotateCw size={12} />}
                title="Recompute scenes, sessions, and events offline from skeletons.sqlite"
              >
                Offline Re-index
              </Button>

              <Button
                variant="secondary"
                size="xs"
                onClick={() => handleSyncMode('rescan_discord')}
                disabled={isAnyRunning}
                loading={isSyncing && activeAction === 'rescan_discord'}
                icon={<RefreshCw size={12} />}
                title="Refresh skeleton bitmasks across active Discord channels while preserving deleted history"
              >
                Full Discord Rescan
              </Button>

              {storageMode === 'full' && (
                <Button
                  variant="secondary"
                  size="xs"
                  onClick={() => handleSyncMode('rescan_local_json')}
                  disabled={isAnyRunning}
                  loading={isSyncing && activeAction === 'rescan_local_json'}
                  icon={<FileJson size={12} />}
                  title="Rebuild skeletons.sqlite bitmasks offline from local Data/*.json files"
                >
                  Rescan Local JSONs
                </Button>
              )}

              <Button
                variant={backupInfo.is_schema_outdated ? 'danger' : 'secondary'}
                size="xs"
                onClick={handleUpgradeDatabase}
                disabled={isAnyRunning}
                loading={isUpgrading}
                icon={<Database size={12} />}
              >
                Upgrade Database
              </Button>
            </div>
          </div>
        )}
      </PanelSurface>

      {/* Execution Log Console */}
      <LogConsole
        logs={backupLogs}
        loading={loadingLogs}
        onRefresh={() => fetchLogs(true)}
        onClear={canManageBackup ? clearLogs : undefined}
        onDownload={downloadLogs}
        downloadFilename={`backup-${backupId}-execution.log`}
        title="Live Execution Console"
        emptyMessage="No execution log entries recorded."
      />

      {/* Configuration Modal */}
      {canManageBackup && isFormOpen && (
        <BackupForm
          backupId={backupId}
          initialConfig={backupConfig}
          globalConfig={globalConfig}
          hasDataFiles={Boolean(backupInfo?.has_data_files)}
          isModal={true}
          onStart={() => {
            setIsFormOpen(false);
            markOptimisticSyncing();
            fetchBackupConfig();
            fetchLogs(false);
            setTimeout(refreshStatus, 1000);
          }}
          onSave={savedConfig => {
            setBackupConfig(savedConfig);
            setIsFormOpen(false);
            refreshStatus();
          }}
          onCancel={() => setIsFormOpen(false)}
        />
      )}
    </div>
  );
};

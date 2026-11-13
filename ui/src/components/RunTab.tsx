import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../api';
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  XCircle,
  Play,
  RotateCw,
  Sliders,
  StopCircle,
} from 'lucide-react';
import { BackupForm } from './BackupForm';
import { PanelSurface, DataCard, Button, Badge, LogConsole } from './ui';
import type { BackupConfig, BackupInfo, GlobalConfig } from '../types';

interface RunTabProps {
  backupId: string;
  backupInfo?: BackupInfo | null;
  statusPollTick?: number;
  onPollStatus?: () => void;
  onRefreshSummary?: () => void;
  onBackupInfoChange?: (info: BackupInfo) => void;
}

export const RunTab = ({
  backupId,
  backupInfo: propBackupInfo,
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
  const wasRunningRef = useRef(false);
  const activeBackupIdRef = useRef(backupId);
  const logsInFlightRef = useRef(false);

  const backupInfo = propBackupInfo !== undefined ? propBackupInfo : localBackupInfo;

  useEffect(() => {
    activeBackupIdRef.current = backupId;
    wasRunningRef.current = false;
    setLocalBackupInfo(null);
    setBackupLogs([]);
    setIsFormOpen(false);
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
    fetchConfig();
  }, [fetchConfig]);

  useEffect(() => {
    fetchBackupConfig();
    fetchBackupInfoStandalone();
    fetchLogs(true);
  }, [fetchBackupConfig, fetchBackupInfoStandalone, fetchLogs]);

  const isAnyRunning =
    isUpgrading ||
    backupInfo?.status === 'pending' ||
    backupInfo?.status === 'running' ||
    Boolean(backupInfo?.steps && Object.values(backupInfo.steps).some(s => s === 'running'));

  // Automatically refresh logs whenever App's lightweight status poll completes while running,
  // and once more when the pipeline transitions from running to finished.
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
      fetchLogs(false);
    }
  }, [isAnyRunning, statusPollTick, fetchLogs]);

  const renderStatusIcon = (status?: string) => {
    if (status === 'success') return <CheckCircle size={16} className="text-success" />;
    if (status === 'failed') return <XCircle size={16} style={{ color: 'var(--danger)' }} />;
    if (status === 'pending' || status === 'running')
      return (
        <Clock
          size={16}
          style={{ color: 'var(--accent-secondary)' }}
          className={status === 'running' ? 'animate-spin' : ''}
        />
      );
    return <AlertTriangle size={16} style={{ color: 'var(--warning)' }} />;
  };

  const refreshStatus = useCallback(() => {
    if (onPollStatus) {
      onPollStatus();
    } else {
      fetchBackupInfoStandalone();
    }
  }, [onPollStatus, fetchBackupInfoStandalone]);

  const markOptimisticRunning = useCallback(
    (stepKey: 'assign_ids' | 'fix_messages' | 'index_scenes' | 'update') => {
      wasRunningRef.current = true;
      if (!backupInfo) return;
      const newInfo: BackupInfo = {
        ...backupInfo,
        status: 'running',
        steps: { ...backupInfo.steps, [stepKey]: 'running' },
      };
      if (propBackupInfo === undefined) {
        setLocalBackupInfo(newInfo);
      }
      if (onBackupInfoChange) {
        onBackupInfoChange(newInfo);
      }
    },
    [backupInfo, propBackupInfo, onBackupInfoChange]
  );

  const handleAction = (action: string) => {
    if (action === 'reapply_characters') markOptimisticRunning('assign_ids');
    else if (action === 'fix_messages') markOptimisticRunning('fix_messages');
    else if (action === 'reindex') markOptimisticRunning('index_scenes');

    api
      .rerunAction(backupId, action)
      .then(() => {
        fetchLogs(false);
        setTimeout(refreshStatus, 1000);
      })
      .catch(err => {
        console.error('Failed to rerun action:', err);
        wasRunningRef.current = false;
        refreshStatus();
        fetchLogs(false);
      });
  };

  const handleUpdate = () => {
    markOptimisticRunning('update');

    api
      .runBackup(backupId)
      .then(() => {
        fetchLogs(false);
        setTimeout(refreshStatus, 1000);
      })
      .catch(err => {
        console.error('Failed to run backup:', err);
        wasRunningRef.current = false;
        refreshStatus();
        fetchLogs(false);
      });
  };

  const handleUpgradeDatabase = async () => {
    if (!backupId || isUpgrading || isAnyRunning) return;
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
      refreshStatus();
    } finally {
      setIsUpgrading(false);
    }
  };

  const cancelRun = () => {
    api
      .cancelRun(backupId)
      .then(() => {
        wasRunningRef.current = false;
        refreshStatus();
        if (onRefreshSummary) {
          onRefreshSummary();
        }
        fetchLogs(false);
      })
      .catch(err => {
        console.error('Failed to cancel run:', err);
        refreshStatus();
      });
  };

  const isUpdateRunning = backupInfo?.steps?.update === 'running';
  const isAssignIdsRunning = !isUpdateRunning && backupInfo?.steps?.assign_ids === 'running';
  const isFixMessagesRunning = !isUpdateRunning && backupInfo?.steps?.fix_messages === 'running';
  const isIndexScenesRunning = !isUpdateRunning && backupInfo?.steps?.index_scenes === 'running';

  if (!backupInfo) {
    return (
      <div className="empty-state">
        <p className="empty-state-desc">Select a backup to view pipeline execution.</p>
      </div>
    );
  }

  const title = backupInfo.name || backupInfo.server_name || backupId;

  return (
    <div className="flex-col gap-lg">
      <PanelSurface className="flex-col gap-md">
        {/* Header */}
        <div className="flex-row items-center justify-between flex-wrap gap-md">
          <div>
            <h2 style={{ margin: 0, fontSize: '1.35rem', color: 'var(--text-primary)' }}>{title}</h2>
            <div className="flex-row items-center gap-xs" style={{ marginTop: '0.25rem' }}>
              {renderStatusIcon(backupInfo.status)}
              <Badge
                variant={
                  backupInfo.status === 'success'
                    ? 'success'
                    : backupInfo.status === 'failed'
                    ? 'danger'
                    : 'warning'
                }
              >
                {isUpdateRunning ? 'UPDATING...' : backupInfo.status.toUpperCase()}
              </Badge>
            </div>
          </div>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => setIsFormOpen(true)}
            icon={<Sliders size={15} />}
          >
            Edit Configuration
          </Button>
        </div>

        {/* Pipeline Step Indicators Grid */}
        {backupInfo.steps && (
          <div className="flex-col gap-xs" style={{ marginTop: '0.5rem' }}>
            <span className="sidebar-group-title" style={{ padding: 0 }}>Pipeline Steps</span>
            <div className="stat-cards-grid">
              {Object.entries(backupInfo.steps).map(([step, status]) => (
                <DataCard
                  key={step}
                  accent={
                    status === 'success'
                      ? 'success'
                      : status === 'failed'
                      ? 'danger'
                      : status === 'running'
                      ? 'accent'
                      : undefined
                  }
                  className="flex-row items-center gap-sm"
                  style={{ padding: '0.65rem 0.85rem' }}
                >
                  {renderStatusIcon(status)}
                  <div className="flex-col">
                    <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--text-primary)' }}>
                      {step.replace(/_/g, ' ')}
                    </span>
                    <span className="form-hint" style={{ textTransform: 'uppercase', fontSize: '0.7rem' }}>
                      {status}
                    </span>
                  </div>
                </DataCard>
              ))}
            </div>
          </div>
        )}

        {/* Action Buttons Toolbar */}
        <div className="flex-row items-center gap-sm flex-wrap" style={{ marginTop: '0.5rem' }}>
          {/* Cancel button */}
          <Button
            variant="danger"
            size="sm"
            onClick={cancelRun}
            disabled={!isAnyRunning && backupInfo.status !== 'failed'}
            icon={<StopCircle size={15} />}
          >
            Cancel pipeline
          </Button>

          {/* Update / Run button */}
          <Button
            variant={backupInfo.steps?.update === 'failed' ? 'danger' : 'primary'}
            size="sm"
            onClick={handleUpdate}
            disabled={isAnyRunning}
            loading={isUpdateRunning}
            icon={<Play size={15} />}
          >
            {isUpdateRunning
              ? 'Updating...'
              : backupInfo.steps?.update === 'failed'
              ? 'Retry update'
              : 'Update now'}
          </Button>

          {/* Granular Step Re-run Buttons */}
          <div
            className="flex-row items-center gap-xs flex-wrap"
            style={{
              paddingLeft: '0.75rem',
              borderLeft: '1px solid var(--border-color)',
            }}
          >
            <span className="form-hint" style={{ marginRight: '0.25rem' }}>Re-run step:</span>

            <Button
              variant={isAssignIdsRunning ? 'primary' : 'secondary'}
              size="xs"
              onClick={() => handleAction('reapply_characters')}
              disabled={isAnyRunning}
              loading={isAssignIdsRunning}
              icon={<RotateCw size={12} />}
            >
              Reapply characters
            </Button>

            <Button
              variant={isFixMessagesRunning ? 'primary' : 'secondary'}
              size="xs"
              onClick={() => handleAction('fix_messages')}
              disabled={isAnyRunning}
              loading={isFixMessagesRunning}
              icon={<RotateCw size={12} />}
            >
              Fix messages
            </Button>

            <Button
              variant={isUpgrading ? 'primary' : 'secondary'}
              size="xs"
              onClick={handleUpgradeDatabase}
              disabled={isAnyRunning}
              loading={isUpgrading}
              icon={<RotateCw size={12} />}
            >
              Upgrade database
            </Button>

            <Button
              variant={isIndexScenesRunning ? 'primary' : 'secondary'}
              size="xs"
              onClick={() => handleAction('reindex')}
              disabled={isAnyRunning}
              loading={isIndexScenesRunning}
              icon={<RotateCw size={12} />}
            >
              Reindex scenes
            </Button>
          </div>
        </div>
      </PanelSurface>

      {/* Execution Log Console */}
      <LogConsole
        logs={backupLogs}
        loading={loadingLogs}
        onRefresh={() => fetchLogs(true)}
        onClear={clearLogs}
        onDownload={downloadLogs}
        downloadFilename={`backup-${backupId}-execution.log`}
        title="Live Execution Console"
        emptyMessage="No execution log entries recorded."
      />

      {/* Configuration Modal */}
      {isFormOpen && (
        <BackupForm
          backupId={backupId}
          initialConfig={backupConfig}
          globalConfig={globalConfig}
          isModal={true}
          onStart={() => {
            setIsFormOpen(false);
            markOptimisticRunning('update');
            fetchLogs(false);
            setTimeout(refreshStatus, 1000);
          }}
          onSave={savedConfig => {
            setBackupConfig(savedConfig);
            setIsFormOpen(false);
          }}
          onCancel={() => setIsFormOpen(false)}
        />
      )}
    </div>
  );
};

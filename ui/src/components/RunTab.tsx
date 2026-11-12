import { useEffect, useState, useCallback } from 'react';
import { api, API_BASE } from '../api';
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
  onRefreshSummary?: () => void;
}

export const RunTab = ({ backupId, onRefreshSummary }: RunTabProps) => {
  const [globalConfig, setGlobalConfig] = useState<GlobalConfig | null>(null);
  const [backupInfo, setBackupInfo] = useState<BackupInfo | null>(null);
  const [backupConfig, setBackupConfig] = useState<BackupConfig | null>(null);
  const [isFormOpen, setIsFormOpen] = useState<boolean>(false);
  const [backupLogs, setBackupLogs] = useState<string[]>([]);
  const [streamActive, setStreamActive] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [isUpgrading, setIsUpgrading] = useState(false);

  const fetchConfig = useCallback(() => {
    api.getGlobalConfig().then(setGlobalConfig).catch(console.error);
  }, []);

  const fetchBackupData = useCallback(() => {
    if (!backupId) return;
    api
      .getBackupInfo(backupId)
      .then(res => {
        setBackupInfo(res);
        const hasStepRunning = res?.steps
          ? Object.values(res.steps).some(s => s === 'running')
          : false;
        if (res && res.status !== 'running' && !hasStepRunning) {
          setIsPolling(false);
        }
      })
      .catch(() => setBackupInfo(null));

    api
      .getBackupConfig(backupId)
      .then(setBackupConfig)
      .catch(() => setBackupConfig(null));
  }, [backupId]);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  useEffect(() => {
    fetchBackupData();
    setIsFormOpen(false);
  }, [backupId, fetchBackupData]);

  const isAnyRunning =
    isUpgrading ||
    backupInfo?.status === 'pending' ||
    backupInfo?.status === 'running' ||
    Boolean(backupInfo?.steps && Object.values(backupInfo.steps).some(s => s === 'running'));

  useEffect(() => {
    if (backupInfo && isAnyRunning) {
      setStreamActive(true);
    }
  }, [backupInfo, isAnyRunning]);

  // Poll for backup info updates while a task is running
  useEffect(() => {
    if (!isAnyRunning && !isPolling) return;
    const interval = setInterval(() => {
      fetchBackupData();
    }, 1500);
    return () => clearInterval(interval);
  }, [isAnyRunning, isPolling, fetchBackupData]);

  // Handle EventSource for live log stream
  useEffect(() => {
    if (!backupId || !streamActive) return;

    const es = new EventSource(`${API_BASE}/backups/${backupId}/logs/stream`);
    es.onmessage = e => {
      setBackupLogs(prev => {
        const newLogs = [...prev, e.data];
        if (newLogs.length > 50) return newLogs.slice(newLogs.length - 50);
        return newLogs;
      });
      if (
        e.data.includes('Backup complete') ||
        e.data.includes('fatal') ||
        e.data.includes('error')
      ) {
        fetchBackupData();
      }
    };
    es.onerror = () => {
      es.close();
      setStreamActive(false);
    };

    return () => es.close();
  }, [backupId, streamActive, fetchBackupData]);

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

  const handleAction = (action: string) => {
    setBackupInfo(prev => {
      if (!prev) return prev;
      const newInfo: BackupInfo = { ...prev, status: 'running' };
      if (!newInfo.steps) newInfo.steps = {};
      if (action === 'reapply_characters') newInfo.steps.assign_ids = 'running';
      if (action === 'fix_messages') newInfo.steps.fix_messages = 'running';
      if (action === 'reindex') newInfo.steps.index_scenes = 'running';
      return newInfo;
    });
    setStreamActive(true);
    setIsPolling(true);

    api
      .rerunAction(backupId, action)
      .then(() => {
        setTimeout(fetchBackupData, 1000);
      })
      .catch(err => {
        console.error('Failed to rerun action:', err);
        fetchBackupData();
        setIsPolling(false);
      });
  };

  const handleUpdate = () => {
    setBackupInfo(prev => {
      if (!prev) return prev;
      return {
        ...prev,
        status: 'running',
        steps: { ...prev.steps, update: 'running' },
      };
    });
    setStreamActive(true);
    setIsPolling(true);

    api
      .runBackup(backupId)
      .then(() => {
        setTimeout(fetchBackupData, 1000);
      })
      .catch(err => {
        console.error('Failed to run backup:', err);
        fetchBackupData();
        setIsPolling(false);
      });
  };

  const handleUpgradeDatabase = async () => {
    if (!backupId || isUpgrading || isAnyRunning) return;
    setIsUpgrading(true);
    setStreamActive(true);
    try {
      await api.upgradeBackup(backupId);
      fetchBackupData();
      if (onRefreshSummary) {
        onRefreshSummary();
      }
      api.getBackupLogs(backupId, 100).then(res => setBackupLogs(res.lines || [])).catch(() => {});
    } catch (err) {
      console.error('Failed to upgrade database:', err);
      fetchBackupData();
    } finally {
      setIsUpgrading(false);
    }
  };

  const cancelRun = () => {
    api
      .cancelRun(backupId)
      .then(() => {
        fetchBackupData();
        setStreamActive(false);
      })
      .catch(err => {
        console.error('Failed to cancel run:', err);
        fetchBackupData();
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

      {/* Live Stream / Execution Log Console */}
      <LogConsole
        logs={backupLogs}
        title="Live Execution Console"
        downloadFilename={`backup-${backupId}-execution.log`}
        onClear={() => setBackupLogs([])}
        emptyMessage={streamActive ? 'Waiting for pipeline output...' : 'Console idle. Start an update or step to view live logs.'}
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
            setStreamActive(true);
            setIsPolling(true);
            setBackupInfo(prev =>
              prev
                ? {
                    ...prev,
                    status: 'running',
                    steps: { ...prev.steps, update: 'running' },
                  }
                : prev
            );
            setTimeout(fetchBackupData, 1000);
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

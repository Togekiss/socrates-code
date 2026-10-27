import { useEffect, useState, useRef, useCallback } from 'react';
import { api, API_BASE } from '../api';
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  XCircle,
  Terminal,
  Play,
  RotateCw,
  Sliders,
  StopCircle,
} from 'lucide-react';
import { BackupForm } from './BackupForm';
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

  const backupLogsEndRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    backupLogsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [backupLogs]);

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
        if (newLogs.length > 20) return newLogs.slice(newLogs.length - 20);
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
    if (status === 'success') return <CheckCircle size={16} style={{ color: 'var(--success)' }} />;
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

  const renderLogLine = (log: string, index: number) => {
    const match = log.match(/^\[(.*?)\](.*?):\s*(.*)$/);
    if (!match) {
      return (
        <div key={index} style={{ color: '#94a3b8', marginBottom: '0.2rem' }}>
          {log}
        </div>
      );
    }

    const [, time, level, msg] = match;
    let color = '#94a3b8';
    if (level === 'error') color = '#ef4444';
    else if (level === 'base') color = '#10b981';
    else if (level === 'info') color = '#38bdf8';
    else if (level === 'debug') color = '#a855f7';
    else if (level === 'console' || level === 'log') color = '#64748b';

    return (
      <div
        key={index}
        style={{
          marginBottom: '0.2rem',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        <span style={{ color: '#64748b', marginRight: '0.5rem' }}>[{time}]</span>
        <span style={{ color, fontWeight: level === 'base' || level === 'error' ? 'bold' : 'normal' }}>
          {msg}
        </span>
      </div>
    );
  };

  if (!backupInfo) {
    return (
      <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
        <p style={{ color: 'var(--text-secondary)' }}>Select a backup to view pipeline execution.</p>
      </div>
    );
  }

  const title = backupInfo.name || backupInfo.server_name || backupId;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div className="glass-panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.4rem', color: 'var(--text-primary)' }}>{title}</h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.25rem' }}>
              {renderStatusIcon(backupInfo.status)}
              <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 600 }}>
                {isUpdateRunning ? 'UPDATING...' : backupInfo.status.toUpperCase()}
              </span>
            </div>
          </div>

          <button
            onClick={() => setIsFormOpen(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.5rem 1rem',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-primary)',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '0.9rem',
              fontWeight: 500,
            }}
          >
            <Sliders size={16} /> Edit Configuration
          </button>
        </div>

        {/* Pipeline Step Indicators */}
        {backupInfo.steps && (
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: '0.75rem',
              marginBottom: '1.5rem',
              background: 'var(--bg-tertiary)',
              padding: '1rem',
              borderRadius: '8px',
              border: '1px solid var(--border-color)',
            }}
          >
            {Object.entries(backupInfo.steps).map(([step, status]) => (
              <div
                key={step}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                  fontSize: '0.85rem',
                  padding: '0.25rem 0.6rem',
                  background: 'var(--bg-secondary)',
                  borderRadius: '6px',
                  border: '1px solid var(--border-color)',
                }}
              >
                {renderStatusIcon(status)}
                <span style={{ color: 'var(--text-secondary)', textTransform: 'capitalize' }}>
                  {step.replace(/_/g, ' ')}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Live Stream Console */}
        {streamActive && (
          <div style={{ marginBottom: '1.5rem' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '0.5rem',
              }}
            >
              <strong
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  color: 'var(--accent-secondary)',
                  fontSize: '0.9rem',
                }}
              >
                <Terminal size={16} /> Live Execution Stream
              </strong>
              <button
                onClick={() => {
                  window.open(`${API_BASE}/backups/${backupId}/logs/raw`, '_blank');
                }}
                style={{
                  padding: '0.25rem 0.75rem',
                  background: 'var(--bg-tertiary)',
                  color: 'white',
                  border: '1px solid var(--border-color)',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '0.8rem',
                }}
              >
                View full raw log
              </button>
            </div>
            <div
              style={{
                background: '#090a0f',
                padding: '1rem',
                borderRadius: '8px',
                fontFamily: 'monospace',
                fontSize: '0.8rem',
                height: '200px',
                overflowY: 'auto',
                border: '1px solid var(--border-color)',
              }}
            >
              {backupLogs.map((log, i) => renderLogLine(log, i))}
              <div ref={backupLogsEndRef} />
            </div>
          </div>
        )}

        {/* Action Buttons Bar */}
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
          {/* Cancel button */}
          <button
            onClick={cancelRun}
            title="Cancel the running pipeline subprocess"
            disabled={!isAnyRunning && backupInfo.status !== 'failed'}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.5rem 1rem',
              background: backupInfo.status === 'failed' ? 'var(--danger)' : 'var(--bg-tertiary)',
              color: 'white',
              border: '1px solid var(--border-color)',
              borderRadius: '6px',
              cursor: backupInfo.status === 'failed' || isAnyRunning ? 'pointer' : 'not-allowed',
              opacity: backupInfo.status === 'failed' || isAnyRunning ? 1 : 0.45,
              fontSize: '0.9rem',
            }}
          >
            <StopCircle size={16} /> Cancel pipeline
          </button>

          {/* Update / Run button */}
          <button
            onClick={handleUpdate}
            disabled={isAnyRunning}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.5rem 1.25rem',
              background: backupInfo.steps?.update === 'failed' ? 'var(--danger)' : 'var(--accent-primary)',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              cursor: isAnyRunning ? 'not-allowed' : 'pointer',
              fontWeight: 600,
              fontSize: '0.9rem',
              opacity: isAnyRunning ? 0.6 : 1,
            }}
          >
            <Play size={16} />
            {isUpdateRunning
              ? 'Updating...'
              : backupInfo.steps?.update === 'failed'
              ? 'Retry update'
              : 'Update now'}
          </button>

          {/* Granular Step Re-run Buttons */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              paddingLeft: '1rem',
              borderLeft: '1px solid var(--border-color)',
              flexWrap: 'wrap',
            }}
          >
            <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Re-run step:</span>
            <button
              onClick={() => handleAction('reapply_characters')}
              disabled={isAnyRunning}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                padding: '0.35rem 0.75rem',
                fontSize: '0.8rem',
                background: isAssignIdsRunning ? 'var(--accent-primary)' : 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-primary)',
                borderRadius: '6px',
                cursor: isAnyRunning ? 'not-allowed' : 'pointer',
                opacity: isAnyRunning && !isAssignIdsRunning ? 0.45 : 1,
                fontWeight: isAssignIdsRunning ? 700 : 500,
              }}
            >
              <RotateCw size={12} className={isAssignIdsRunning ? 'animate-spin' : ''} />
              {isAssignIdsRunning ? 'Reapplying...' : 'Reapply characters'}
            </button>

            <button
              onClick={() => handleAction('fix_messages')}
              disabled={isAnyRunning}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                padding: '0.35rem 0.75rem',
                fontSize: '0.8rem',
                background: isFixMessagesRunning ? 'var(--accent-primary)' : 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-primary)',
                borderRadius: '6px',
                cursor: isAnyRunning ? 'not-allowed' : 'pointer',
                opacity: isAnyRunning && !isFixMessagesRunning ? 0.45 : 1,
                fontWeight: isFixMessagesRunning ? 700 : 500,
              }}
            >
              <RotateCw size={12} className={isFixMessagesRunning ? 'animate-spin' : ''} />
              {isFixMessagesRunning ? 'Fixing...' : 'Fix messages'}
            </button>

            <button
              onClick={handleUpgradeDatabase}
              disabled={isAnyRunning}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                padding: '0.35rem 0.75rem',
                fontSize: '0.8rem',
                background: isUpgrading ? 'var(--accent-primary)' : 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-primary)',
                borderRadius: '6px',
                cursor: isAnyRunning ? 'not-allowed' : 'pointer',
                opacity: isAnyRunning && !isUpgrading ? 0.45 : 1,
                fontWeight: isUpgrading ? 700 : 500,
              }}
            >
              <RotateCw size={12} className={isUpgrading ? 'animate-spin' : ''} />
              {isUpgrading ? 'Upgrading...' : 'Upgrade database'}
            </button>

            <button
              onClick={() => handleAction('reindex')}
              disabled={isAnyRunning}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                padding: '0.35rem 0.75rem',
                fontSize: '0.8rem',
                background: isIndexScenesRunning ? 'var(--accent-primary)' : 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-primary)',
                borderRadius: '6px',
                cursor: isAnyRunning ? 'not-allowed' : 'pointer',
                opacity: isAnyRunning && !isIndexScenesRunning ? 0.45 : 1,
                fontWeight: isIndexScenesRunning ? 700 : 500,
              }}
            >
              <RotateCw size={12} className={isIndexScenesRunning ? 'animate-spin' : ''} />
              {isIndexScenesRunning ? 'Reindexing...' : 'Reindex scenes'}
            </button>
          </div>
        </div>
      </div>

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

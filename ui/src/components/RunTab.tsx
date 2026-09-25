import { useEffect, useState, useRef } from 'react';
import { api, API_BASE } from '../api';
import { AlertTriangle, CheckCircle, Clock, XCircle, Terminal } from 'lucide-react';
import { BackupForm } from './BackupForm';

export const RunTab = ({ backupId }: { backupId: string }) => {
  const [globalConfig, setGlobalConfig] = useState<any>(null);
  const [backupInfo, setBackupInfo] = useState<any>(null);
  const [backupConfig, setBackupConfig] = useState<any>(null);
  const [isFormOpen, setIsFormOpen] = useState<boolean>(false);
  const [backupLogs, setBackupLogs] = useState<string[]>([]);
  const [streamActive, setStreamActive] = useState(false);

  const [isPolling, setIsPolling] = useState(false);

  const backupLogsEndRef = useRef<HTMLDivElement>(null);

  const fetchConfig = () => {
    api.getGlobalConfig().then(res => setGlobalConfig(res)).catch(console.error);
  };

  const fetchBackupData = () => {
    if (backupId) {
      api.getBackupInfo(backupId).then(res => {
        setBackupInfo(res);
        if (res && res.status !== 'pending' && res.status !== 'running') {
          setIsPolling(false);
        }
      }).catch(() => setBackupInfo(null));
      api.getBackupConfig(backupId).then(res => setBackupConfig(res)).catch(() => setBackupConfig(null));
    }
  };

  useEffect(() => {
    fetchConfig();
  }, []);

  useEffect(() => {
    fetchBackupData();
    setIsFormOpen(false);
  }, [backupId]);

  useEffect(() => {
    backupLogsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [backupLogs]);

  const isAnyRunning = backupInfo?.status === 'pending' || backupInfo?.status === 'running' || (backupInfo?.steps && Object.values(backupInfo.steps).includes('running'));

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
  }, [isAnyRunning, isPolling, backupId]);

  // Handle EventSource for backup logs stream
  useEffect(() => {
    if (!backupId || !streamActive) return;
    
    const es = new EventSource(`${API_BASE}/backups/${backupId}/logs/stream`);
    es.onmessage = (e) => {
      setBackupLogs((prev) => {
        const newLogs = [...prev, e.data];
        if (newLogs.length > 10) return newLogs.slice(newLogs.length - 10);
        return newLogs;
      });
      // Optionally re-fetch backup info to see if status changed
      if (e.data.includes("Backup complete") || e.data.includes("fatal") || e.data.includes("error")) {
        fetchBackupData();
      }
    };
    es.onerror = () => {
      es.close();
      setStreamActive(false);
    };
    
    return () => es.close();
  }, [backupId, streamActive]);

  const renderStatusIcon = (status: string) => {
    if (status === 'success') return <CheckCircle size={16} color="var(--success)" />;
    if (status === 'failed') return <XCircle size={16} color="var(--danger)" />;
    if (status === 'pending' || status === 'running') return <Clock size={16} color="var(--accent-primary)" className={status === 'running' ? 'spin' : ''} />;
    return <AlertTriangle size={16} color="var(--warning)" />;
  };

  const handleAction = (action: string) => {
    // Optimistically update state so polling doesn't immediately abort
    setBackupInfo((prev: any) => {
      if (!prev) return prev;
      const newInfo = { ...prev, status: 'running' };
      if (!newInfo.steps) newInfo.steps = {};
      if (action === 'reapply_characters') newInfo.steps.assign_ids = 'running';
      if (action === 'fix_messages') newInfo.steps.fix_messages = 'running';
      if (action === 'reindex') newInfo.steps.index_scenes = 'running';
      return newInfo;
    });
    setStreamActive(true);
    setIsPolling(true);
    
    api.rerunAction(backupId, action).then(() => {
      setTimeout(fetchBackupData, 1000);
    });
  };

  const cancelRun = () => {
    api.cancelRun(backupId).then(() => {
      fetchBackupData();
      setStreamActive(false);
    });
  };

  const isUpdateRunning = backupInfo?.steps?.update === 'running';
  const isAssignIdsRunning = !isUpdateRunning && backupInfo?.steps?.assign_ids === 'running';
  const isFixMessagesRunning = !isUpdateRunning && backupInfo?.steps?.fix_messages === 'running';
  const isIndexScenesRunning = !isUpdateRunning && backupInfo?.steps?.index_scenes === 'running';

  const renderLogLine = (log: string, index: number) => {
    // Format: [HH:MM:SS]level: message
    const match = log.match(/^\[(.*?)\](.*?):\s*(.*)$/);
    if (!match) return <div key={index} style={{ color: '#a4b0be', marginBottom: '0.2rem' }}>{log}</div>;
    
    const [, time, level, msg] = match;
    let color = '#a4b0be';
    if (level === 'error') color = '#ff6b6b';
    else if (level === 'base') color = '#1dd1a1';
    else if (level === 'info') color = '#00d2d3';
    else if (level === 'debug') color = '#54a0ff';
    else if (level === 'console' || level === 'consolelog' || level === 'log') color = '#576574';
    
    return (
      <div key={index} style={{ marginBottom: '0.2rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        <span style={{ color: '#576574', marginRight: '0.5rem' }}>[{time}]</span>
        <span style={{ color, fontWeight: level === 'base' || level === 'error' ? 'bold' : 'normal' }}>{msg}</span>
      </div>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      <div className="glass-panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h2 style={{ margin: 0, color: 'var(--text-primary)' }}>Run backup</h2>
        </div>
        


        {!backupInfo ? (
          <div>
            <p>Select a backup from the top menu to view its status.</p>
          </div>
        ) : (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
              <h3 style={{ margin: 0, color: 'var(--accent-primary)' }}>{backupInfo.name || backupId}</h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                {renderStatusIcon(backupInfo.status)}
                <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>{isUpdateRunning ? 'UPDATING...' : backupInfo.status.toUpperCase()}</span>
              </div>
            </div>
            
            <p style={{ margin: '0 0 1rem 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              Last export: {new Date(backupInfo.exported_at).toLocaleString()}
            </p>

            {/* Steps list */}
            {backupInfo.steps && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem', marginBottom: '1.5rem', background: 'var(--bg-tertiary)', padding: '1rem', borderRadius: '4px' }}>
                {Object.entries(backupInfo.steps).map(([step, status]: [string, any]) => (
                  <div key={step} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.85rem' }}>
                    {renderStatusIcon(status)}
                    <span style={{ color: 'var(--text-secondary)', textTransform: 'capitalize' }}>{step.replace('_', ' ')}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Stream Console */}
            {streamActive && (
              <div style={{ marginBottom: '1.5rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                  <strong style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--accent-primary)' }}>
                    <Terminal size={16} /> Console output (last 10 lines)
                  </strong>
                  <button 
                    onClick={() => {
                      const apiBase = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
                      window.open(`${apiBase}/backups/${backupId}/logs/raw`, '_blank')
                    }} 
                    style={{ padding: '0.25rem 0.75rem', background: 'var(--bg-tertiary)', color: 'white', border: '1px solid var(--border-color)', borderRadius: '4px', cursor: 'pointer', fontSize: '0.8rem' }}
                  >
                    See full log
                  </button>
                </div>
                <div style={{ background: '#0a0a0a', padding: '1rem', borderRadius: '4px', fontFamily: 'monospace', fontSize: '0.8rem', height: '170px', overflowY: 'hidden', border: '1px solid #333' }}>
                  {backupLogs.map((log, i) => renderLogLine(log, i))}
                  <div ref={backupLogsEndRef} />
                </div>
              </div>
            )}

            {/* Contextual Action Buttons */}
            {isFormOpen !== true ? (
              <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
                <button 
                  onClick={cancelRun}
                  title="Canceling won't delete any files, but it might break the backup!"
                  style={{ 
                    padding: '0.5rem 1rem', 
                    background: backupInfo.status === 'failed' ? 'var(--error-color)' : 'var(--bg-tertiary)', 
                    color: 'white', 
                    border: '1px solid var(--border-color)', 
                    borderRadius: '4px', 
                    cursor: backupInfo.status === 'failed' ? 'pointer' : (isAnyRunning ? 'pointer' : 'not-allowed'),
                    opacity: backupInfo.status === 'failed' || isAnyRunning ? 1 : 0.5
                  }}
                  disabled={!isAnyRunning && backupInfo.status !== 'failed'}
                >
                  Cancel backup
                </button>
                
                {isAnyRunning && !streamActive && (
                  <button onClick={() => setStreamActive(true)} style={{ padding: '0.5rem 1rem', background: 'var(--accent-primary)', color: '#000', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>
                    Backup in progress... (View stream)
                  </button>
                )}
                
                <button 
                  onClick={() => setIsFormOpen(true)} 
                  style={{ 
                    padding: '0.5rem 1rem', 
                    background: backupInfo.steps?.update === 'failed' ? 'var(--error-color)' : 'var(--accent-primary)', 
                    color: backupInfo.steps?.update === 'failed' ? 'white' : '#000', 
                    border: 'none', 
                    borderRadius: '4px', 
                    cursor: isAnyRunning ? 'not-allowed' : 'pointer', 
                    fontWeight: 'bold',
                    opacity: isAnyRunning ? (isUpdateRunning ? 1 : 0.5) : 1,
                    boxShadow: isUpdateRunning ? '0 0 8px var(--accent-primary)' : 'none'
                  }}
                  disabled={isAnyRunning}
                >
                  {isUpdateRunning ? 'Updating...' : (backupInfo.steps?.update === 'failed' ? 'Retry update' : 'Update now')}
                </button>
                
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', paddingLeft: '1rem', borderLeft: '1px solid var(--border-color)' }}>
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Rerun steps:</span>
                  <button 
                    onClick={() => handleAction('reapply_characters')} 
                    style={{ 
                      padding: '0.3rem 0.6rem', 
                      fontSize: '0.8rem', 
                      background: isAssignIdsRunning ? 'var(--accent-primary)' : 'transparent', 
                      border: '1px solid var(--border-color)', 
                      color: isAssignIdsRunning ? '#000' : 'var(--text-primary)', 
                      borderRadius: '4px', 
                      cursor: isAnyRunning ? 'not-allowed' : 'pointer',
                      opacity: isAnyRunning ? (isAssignIdsRunning ? 1 : 0.5) : 1,
                      fontWeight: isAssignIdsRunning ? 'bold' : 'normal'
                    }}
                    disabled={isAnyRunning}
                  >
                    {isAssignIdsRunning ? 'Reapplying...' : 'Reapply characters'}
                  </button>
                  <button 
                    onClick={() => handleAction('fix_messages')} 
                    style={{ 
                      padding: '0.3rem 0.6rem', 
                      fontSize: '0.8rem', 
                      background: isFixMessagesRunning ? 'var(--accent-primary)' : 'transparent', 
                      border: '1px solid var(--border-color)', 
                      color: isFixMessagesRunning ? '#000' : 'var(--text-primary)', 
                      borderRadius: '4px', 
                      cursor: isAnyRunning ? 'not-allowed' : 'pointer',
                      opacity: isAnyRunning ? (isFixMessagesRunning ? 1 : 0.5) : 1,
                      fontWeight: isFixMessagesRunning ? 'bold' : 'normal'
                    }}
                    disabled={isAnyRunning}
                  >
                    {isFixMessagesRunning ? 'Fixing...' : 'Fix messages'}
                  </button>
                  <button 
                    onClick={() => handleAction('reindex')} 
                    style={{ 
                      padding: '0.3rem 0.6rem', 
                      fontSize: '0.8rem', 
                      background: isIndexScenesRunning ? 'var(--accent-primary)' : 'transparent', 
                      border: '1px solid var(--border-color)', 
                      color: isIndexScenesRunning ? '#000' : 'var(--text-primary)', 
                      borderRadius: '4px', 
                      cursor: isAnyRunning ? 'not-allowed' : 'pointer',
                      opacity: isAnyRunning ? (isIndexScenesRunning ? 1 : 0.5) : 1,
                      fontWeight: isIndexScenesRunning ? 'bold' : 'normal'
                    }}
                    disabled={isAnyRunning}
                  >
                    {isIndexScenesRunning ? 'Reindexing...' : 'Reindex scenes'}
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ marginTop: '1rem' }}>
                <BackupForm 
                  backupId={backupId} 
                  initialConfig={backupConfig} 
                  globalConfig={globalConfig} 
                  onStart={() => { 
                    setIsFormOpen(false); 
                    setStreamActive(true); 
                    setIsPolling(true);
                    setBackupInfo((prev: any) => prev ? { ...prev, status: 'running', steps: { ...prev.steps, update: 'running' } } : prev);
                    setTimeout(fetchBackupData, 1000);
                  }} 
                  onCancel={() => setIsFormOpen(false)} 
                />
              </div>
            )}
            
          </div>
        )}
      </div>
    </div>
  );
};

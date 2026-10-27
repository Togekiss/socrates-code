import { useEffect, useState, useRef } from 'react';
import { api } from '../api';
import {
  RefreshCw,
  Download,
  Trash2,
  RotateCcw,
  Database,
  Play,
  Loader2,
  CheckCircle,
  XCircle,
  FlaskConical,
} from 'lucide-react';
import type { AdminTestActionResponse, GlobalConfig } from '../types';

interface AdminTabProps {
  onRefreshSummary?: () => void;
}

export const AdminTab = ({ onRefreshSummary }: AdminTabProps) => {
  const [globalConfig, setGlobalConfig] = useState<GlobalConfig | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [loadingLogs, setLoadingLogs] = useState(false);

  const [activeTestAction, setActiveTestAction] = useState<'reset' | 'migrate' | 'suite' | 'upgrade-all' | null>(null);
  const [testResult, setTestResult] = useState<AdminTestActionResponse | null>(null);

  const logsEndRef = useRef<HTMLDivElement>(null);

  const fetchLogs = () => {
    setLoadingLogs(true);
    api.getGlobalLogs(100)
      .then(res => setLogs(res.logs || []))
      .catch(console.error)
      .finally(() => setLoadingLogs(false));
  };

  const fetchConfig = () => {
    api.getGlobalConfig().then(res => setGlobalConfig(res)).catch(console.error);
  };

  useEffect(() => {
    fetchLogs();
    fetchConfig();
  }, []);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const downloadLogs = () => {
    const blob = new Blob([logs.join('\n')], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'global-log.txt';
    a.click();
    URL.revokeObjectURL(url);
  };

  const clearLogs = () => {
    api.clearGlobalLogs().then(() => setLogs([])).catch(console.error);
  };

  const updateVerbosity = (key: string, value: boolean) => {
    if (!globalConfig || !globalConfig.admin) return;
    const newConfig: GlobalConfig = {
      ...globalConfig,
      admin: {
        ...globalConfig.admin,
        verbosity: {
          ...globalConfig.admin.verbosity,
          [key]: value,
        },
      },
    };
    setGlobalConfig(newConfig);
    api.updateGlobalConfig(newConfig).catch(console.error);
  };

  const handleTestAction = async (action: 'reset' | 'migrate' | 'suite' | 'upgrade-all') => {
    if (activeTestAction) return;
    setActiveTestAction(action);
    setTestResult(null);

    try {
      let res: AdminTestActionResponse;
      if (action === 'reset') {
        res = await api.resetTestingBackup();
      } else if (action === 'migrate') {
        res = await api.migrateTestingBackup();
      } else if (action === 'upgrade-all') {
        res = await api.upgradeAllDatabases();
      } else {
        res = await api.runPythonTests();
      }
      setTestResult(res);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Action failed';
      setTestResult({
        status: 'failed',
        message: errorMsg,
      });
    } finally {
      setActiveTestAction(null);
      fetchLogs();
      onRefreshSummary?.();
    }
  };

  const isTestBusy = activeTestAction !== null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      {/* Testing & Verification Section */}
      <div className="glass-panel">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.5rem' }}>
          <FlaskConical size={20} style={{ color: 'var(--accent-secondary)' }} />
          <h2 style={{ margin: 0, color: 'var(--text-primary)' }}>Testing & Verification</h2>
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '1.25rem' }}>
          Manage the reversible testing dataset (<code>Elysium-sql-tests</code>) and run the automated Python test suite.
        </p>

        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
          <button
            onClick={() => handleTestAction('reset')}
            disabled={isTestBusy}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.55rem 1.1rem',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-primary)',
              borderRadius: '6px',
              cursor: isTestBusy ? 'not-allowed' : 'pointer',
              opacity: isTestBusy && activeTestAction !== 'reset' ? 0.5 : 1,
              fontSize: '0.9rem',
              fontWeight: 500,
            }}
          >
            {activeTestAction === 'reset' ? (
              <Loader2 size={16} className="animate-spin" style={{ color: 'var(--accent-secondary)' }} />
            ) : (
              <RotateCcw size={16} />
            )}
            {activeTestAction === 'reset' ? 'Resetting...' : 'Reset Testing Backup'}
          </button>

          <button
            onClick={() => handleTestAction('migrate')}
            disabled={isTestBusy}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.55rem 1.1rem',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-primary)',
              borderRadius: '6px',
              cursor: isTestBusy ? 'not-allowed' : 'pointer',
              opacity: isTestBusy && activeTestAction !== 'migrate' ? 0.5 : 1,
              fontSize: '0.9rem',
              fontWeight: 500,
            }}
          >
            {activeTestAction === 'migrate' ? (
              <Loader2 size={16} className="animate-spin" style={{ color: 'var(--accent-secondary)' }} />
            ) : (
              <Database size={16} />
            )}
            {activeTestAction === 'migrate' ? 'Migrating...' : 'Migrate Testing Backup'}
          </button>

          <button
            onClick={() => handleTestAction('upgrade-all')}
            disabled={isTestBusy}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.55rem 1.1rem',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-primary)',
              borderRadius: '6px',
              cursor: isTestBusy ? 'not-allowed' : 'pointer',
              opacity: isTestBusy && activeTestAction !== 'upgrade-all' ? 0.5 : 1,
              fontSize: '0.9rem',
              fontWeight: 500,
            }}
          >
            {activeTestAction === 'upgrade-all' ? (
              <Loader2 size={16} className="animate-spin" style={{ color: 'var(--accent-secondary)' }} />
            ) : (
              <Database size={16} />
            )}
            {activeTestAction === 'upgrade-all' ? 'Upgrading...' : 'Upgrade all databases'}
          </button>

          <button
            onClick={() => handleTestAction('suite')}
            disabled={isTestBusy}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.55rem 1.25rem',
              background: 'var(--accent-primary)',
              border: 'none',
              color: '#fff',
              borderRadius: '6px',
              cursor: isTestBusy ? 'not-allowed' : 'pointer',
              opacity: isTestBusy && activeTestAction !== 'suite' ? 0.5 : 1,
              fontSize: '0.9rem',
              fontWeight: 600,
            }}
          >
            {activeTestAction === 'suite' ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Play size={16} />
            )}
            {activeTestAction === 'suite' ? 'Running Test Suite...' : 'Run Python Test Suite'}
          </button>
        </div>

        {testResult && (
          <div style={{ marginTop: '1.25rem' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.6rem',
                padding: '0.75rem 1rem',
                borderRadius: '6px',
                background:
                  testResult.status === 'success'
                    ? 'rgba(16, 185, 129, 0.12)'
                    : 'rgba(239, 68, 68, 0.12)',
                border: `1px solid ${
                  testResult.status === 'success'
                    ? 'rgba(16, 185, 129, 0.35)'
                    : 'rgba(239, 68, 68, 0.35)'
                }`,
                color: testResult.status === 'success' ? 'var(--success)' : 'var(--danger)',
                fontSize: '0.9rem',
                fontWeight: 500,
              }}
            >
              {testResult.status === 'success' ? <CheckCircle size={18} /> : <XCircle size={18} />}
              <span>{testResult.message}</span>
            </div>

            {testResult.output && (
              <div
                style={{
                  marginTop: '0.75rem',
                  background: '#1a1a1a',
                  padding: '1rem',
                  borderRadius: '6px',
                  fontFamily: 'monospace',
                  fontSize: '0.8rem',
                  maxHeight: '320px',
                  overflowY: 'auto',
                  border: '1px solid #333',
                  whiteSpace: 'pre-wrap',
                  lineHeight: 1.45,
                  color: '#c8d6e5',
                }}
              >
                {testResult.output}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Activity and Logs Section */}
      <div className="glass-panel">
        <h2 style={{ margin: '0 0 1rem 0', color: 'var(--text-primary)' }}>Activity and logs</h2>
        
        {globalConfig && globalConfig.admin && (
          <div style={{ display: 'flex', gap: '2rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
            <div>
              <strong style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>Verbosity levels</strong>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                {['info', 'debug', 'console', 'log'].map(key => (
                  <label key={key} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                    <input 
                      type="checkbox" 
                      checked={Boolean(globalConfig.admin?.verbosity?.[key])} 
                      onChange={e => updateVerbosity(key, e.target.checked)}
                    />
                    Show {key} messages
                  </label>
                ))}
              </div>
            </div>
            <div>
              <strong style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>Other settings</strong>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                  <input 
                    type="checkbox" 
                    checked={Boolean(globalConfig.admin?.verbosity?.debugFiles)} 
                    onChange={e => updateVerbosity('debugFiles', e.target.checked)}
                  />
                  Keep debug files
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                  <input 
                    type="checkbox" 
                    checked={Boolean(globalConfig.admin?.verbosity?.dryRun)} 
                    onChange={e => updateVerbosity('dryRun', e.target.checked)}
                  />
                  Dry run mode
                </label>
              </div>
            </div>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
          <strong style={{ color: 'var(--text-secondary)' }}>Global API & Init Logs</strong>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button onClick={fetchLogs} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', padding: '0.2rem 0.5rem', fontSize: '0.8rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px', cursor: 'pointer' }}>
              <RefreshCw size={12} className={loadingLogs ? 'spin' : ''} /> Refresh
            </button>
            <button onClick={downloadLogs} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', padding: '0.2rem 0.5rem', fontSize: '0.8rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px', cursor: 'pointer' }}>
              <Download size={12} /> Download
            </button>
            <button onClick={clearLogs} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', padding: '0.2rem 0.5rem', fontSize: '0.8rem', background: 'var(--error-color)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px', cursor: 'pointer' }}>
              <Trash2 size={12} /> Clear
            </button>
          </div>
        </div>

        <div style={{ 
          background: '#1a1a1a', 
          padding: '1rem', 
          borderRadius: '4px', 
          fontFamily: 'monospace', 
          fontSize: '0.8rem', 
          height: '250px', 
          overflowY: 'auto',
          border: '1px solid #333'
        }}>
          {logs.length === 0 ? (
            <span style={{ color: 'var(--text-secondary)' }}>No logs available.</span>
          ) : (
            logs.map((log, i) => (
              <div key={i} style={{ 
                color: log.includes('error') || log.includes('Exception') ? '#ff6b6b' : 
                       log.includes('warning') ? '#feca57' : '#c8d6e5',
                marginBottom: '0.2rem',
                lineHeight: 1.4
              }}>
                {log}
              </div>
            ))
          )}
          <div ref={logsEndRef} />
        </div>
      </div>
    </div>
  );
};


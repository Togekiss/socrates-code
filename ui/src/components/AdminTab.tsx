import React, { useEffect, useState, useRef } from 'react';
import { api } from '../api';
import { RefreshCw, Download, Trash2 } from 'lucide-react';

export const AdminTab = () => {
  const [globalConfig, setGlobalConfig] = useState<any>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [loadingLogs, setLoadingLogs] = useState(false);
  
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
    if (!globalConfig) return;
    const newConfig = { ...globalConfig };
    newConfig.admin.verbosity[key] = value;
    setGlobalConfig(newConfig);
    api.updateGlobalConfig(newConfig).catch(console.error);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      
      {/* Activity and Logs Section */}
      <div className="glass-panel">
        <h2 style={{ margin: '0 0 1rem 0', color: 'var(--text-primary)' }}>Activity and logs</h2>
        
        {globalConfig && (
          <div style={{ display: 'flex', gap: '2rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
            <div>
              <strong style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>Verbosity levels</strong>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                {['info', 'debug', 'console', 'log'].map(key => (
                  <label key={key} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                    <input 
                      type="checkbox" 
                      checked={globalConfig.admin.verbosity[key]} 
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
                    checked={globalConfig.admin.verbosity.debugFiles} 
                    onChange={e => updateVerbosity('debugFiles', e.target.checked)}
                  />
                  Keep debug files
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                  <input 
                    type="checkbox" 
                    checked={globalConfig.admin.verbosity.dryRun} 
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

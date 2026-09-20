import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { RefreshCw, Download } from 'lucide-react';

export const GlobalLogs = () => {
  const [logs, setLogs] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchLogs = () => {
    setLoading(true);
    api.getGlobalLogs(100)
      .then(res => setLogs(res.logs || []))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchLogs();
  }, []);

  const downloadLogs = () => {
    const blob = new Blob([logs.join('\n')], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'global-log.txt';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="glass-panel" style={{ marginTop: '2rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h3 style={{ margin: 0, fontSize: '1rem', color: 'var(--text-secondary)' }}>Global API & Init Logs</h3>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button onClick={fetchLogs} disabled={loading} style={{ padding: '0.25rem 0.5rem', display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8rem' }}>
            <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
          </button>
          <button onClick={downloadLogs} disabled={logs.length === 0} style={{ padding: '0.25rem 0.5rem', display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8rem' }}>
            <Download size={14} /> Download
          </button>
        </div>
      </div>

      <div style={{ 
        background: '#1a1a1a', 
        padding: '1rem', 
        borderRadius: '4px', 
        fontFamily: 'monospace', 
        fontSize: '0.85rem',
        color: '#d4d4d4',
        height: '200px',
        overflowY: 'auto',
        whiteSpace: 'pre-wrap'
      }}>
        {logs.length === 0 ? (
          <div style={{ color: '#666', textAlign: 'center', marginTop: '4rem' }}>No global logs found.</div>
        ) : (
          logs.map((line, i) => {
            const isError = line.includes(']error:');
            return (
              <div key={i} style={{ color: isError ? '#ff6b6b' : 'inherit', marginBottom: '2px' }}>
                {line}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

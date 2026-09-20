import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { Database, Folder, Hash, MessageSquare, Users, Clock, AlertCircle, CheckCircle } from 'lucide-react';

export const StatusTab = ({ backupId, setTab }: { backupId: string | null, setTab: (tab: string) => void }) => {
  const [info, setInfo] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!backupId) return;
    setError(null);
    setInfo(null);
    
    api.getBackupInfo(backupId)
      .then(setInfo)
      .catch(err => setError(err.message));
  }, [backupId]);

  if (!backupId) {
    return (
      <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
        <Database size={48} style={{ opacity: 0.5, marginBottom: '1rem' }} />
        <h2>Please select a backup</h2>
        <p style={{ color: 'var(--text-secondary)' }}>Please select a backup from the dropdown menu to view its status.</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
        <AlertCircle size={48} style={{ color: 'var(--error-color)', marginBottom: '1rem' }} />
        <h2>Error Loading Backup</h2>
        <p style={{ color: 'var(--text-secondary)' }}>{error}</p>
      </div>
    );
  }

  if (!info) {
    return <div>Loading status...</div>;
  }

  return (
    <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>{info.server_name}</h2>
        <div style={{ 
          display: 'flex', alignItems: 'center', gap: '0.5rem', 
          color: info.status === 'success' ? 'var(--accent-primary)' : 
                 info.status === 'failed' ? 'var(--error-color)' : 'var(--accent-secondary)' 
        }}>
          {info.status === 'success' ? <CheckCircle size={18} /> : 
           info.status === 'failed' ? <AlertCircle size={18} /> : <Clock size={18} />}
          <span style={{ fontWeight: 600 }}>
            {info.status === 'success' ? 'Ready!' : 
             info.status === 'failed' ? 'Failed' : 'Pending / Running'}
          </span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
        
        <div className="stat-card" style={{ background: 'var(--bg-tertiary)', padding: '1rem', borderRadius: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
            <Folder size={16} /> Categories
          </div>
          <div style={{ fontSize: '1.5rem', fontWeight: 600 }}>{info.number_of_categories || 0}</div>
        </div>

        <div className="stat-card" style={{ background: 'var(--bg-tertiary)', padding: '1rem', borderRadius: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
            <Hash size={16} /> Channels
          </div>
          <div style={{ fontSize: '1.5rem', fontWeight: 600 }}>{info.number_of_channels || 0}</div>
        </div>

        <div className="stat-card" style={{ background: 'var(--bg-tertiary)', padding: '1rem', borderRadius: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
            <MessageSquare size={16} /> Threads
          </div>
          <div style={{ fontSize: '1.5rem', fontWeight: 600 }}>{info.number_of_threads || 0}</div>
        </div>

        <div 
          className="stat-card" 
          style={{ 
            background: 'var(--bg-tertiary)', padding: '1rem', borderRadius: '8px', 
            cursor: (info.status === 'success' && info.number_of_scenes > 0) ? 'pointer' : 'not-allowed',
            opacity: (info.status === 'success' && info.number_of_scenes > 0) ? 1 : 0.5
          }}
          onClick={() => { if (info.status === 'success' && info.number_of_scenes > 0) setTab('scenes') }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
            <Database size={16} /> Scenes
          </div>
          <div style={{ fontSize: '1.5rem', fontWeight: 600 }}>{info.number_of_scenes || 0}</div>
        </div>

        <div 
          className="stat-card" 
          style={{ 
            background: 'var(--bg-tertiary)', padding: '1rem', borderRadius: '8px',
            cursor: info.number_of_characters > 0 ? 'pointer' : 'not-allowed',
            opacity: info.number_of_characters > 0 ? 1 : 0.5
          }}
          onClick={() => { if (info.number_of_characters > 0) setTab('characters') }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
            <Users size={16} /> Characters
          </div>
          <div style={{ fontSize: '1.5rem', fontWeight: 600 }}>{info.number_of_characters || 0}</div>
        </div>

      </div>

      <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', textAlign: 'right' }}>
        Exported at: {info.updated_at ? new Date(info.updated_at).toLocaleString() : 'Unknown'}
      </div>
    </div>
  );
};

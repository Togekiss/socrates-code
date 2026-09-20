import { useState, useEffect } from 'react';
import { api } from '../api';
import { Settings, Save } from 'lucide-react';

export function Configuration() {
  const [config, setConfig] = useState<any>(null);
  const [servers, setServers] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.getConfig().then(setConfig).catch(console.error);
    api.getServers().then(setServers).catch(console.error);
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateConfig(config);
      alert('Configuration saved successfully!');
    } catch (e) {
      alert('Failed to save configuration');
    }
    setSaving(false);
  };

  if (!config) return <div className="glass-panel">Loading config...</div>;

  return (
    <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2><Settings style={{ verticalAlign: 'middle', marginRight: '0.5rem' }} /> Configuration</h2>
        <button onClick={handleSave} disabled={saving} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'var(--accent-primary)', borderColor: 'var(--accent-primary)' }}>
          <Save size={16} /> {saving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
        {/* Admin Settings */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <h3>Admin Settings</h3>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            Server Name
            <select 
              value={config.admin.serverName} 
              onChange={e => setConfig({...config, admin: {...config.admin, serverName: e.target.value}})}
              style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', padding: '0.75rem', borderRadius: '4px' }}
            >
              <option value="" disabled>Select a backup</option>
              {servers.map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            Server ID
            <input 
              type="text" 
              value={config.admin.serverId} 
              onChange={e => setConfig({...config, admin: {...config.admin, serverId: e.target.value}})}
              style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', padding: '0.75rem', borderRadius: '4px' }}
            />
          </label>
        </div>

        {/* User Settings */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <h3>User Settings</h3>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            Target Character
            <input 
              type="text" 
              value={config.user.character} 
              onChange={e => setConfig({...config, user: {...config.user, character: e.target.value}})}
              style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', padding: '0.75rem', borderRadius: '4px' }}
            />
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.5rem' }}>
            <input 
              type="checkbox" 
              checked={config.user.includeAlterEgos} 
              onChange={e => setConfig({...config, user: {...config.user, includeAlterEgos: e.target.checked}})}
              style={{ width: '18px', height: '18px', accentColor: 'var(--accent-primary)' }}
            />
            Include Alter Egos
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <input 
              type="checkbox" 
              checked={config.user.includeFamiliars} 
              onChange={e => setConfig({...config, user: {...config.user, includeFamiliars: e.target.checked}})}
              style={{ width: '18px', height: '18px', accentColor: 'var(--accent-primary)' }}
            />
            Include Familiars
          </label>
        </div>
      </div>
    </div>
  );
}

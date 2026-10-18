import { useState, useEffect } from 'react';
import { api } from '../api';
import { ChevronDown, ChevronRight, X, Loader2 } from 'lucide-react';
import type { BackupConfig, GlobalConfig } from '../types';

export const BackupForm = ({ 
  backupId, 
  initialConfig, 
  globalConfig, 
  onStart, 
  onCancel,
  onSave,
  isModal = false
}: { 
  backupId: string; 
  initialConfig: any; 
  globalConfig: GlobalConfig | null; 
  onStart: () => void; 
  onCancel: () => void; 
  onSave?: (savedConfig: BackupConfig) => void;
  isModal?: boolean;
}) => {
  const [config, setConfig] = useState<any>(() => {
    const cfg = initialConfig || globalConfig;
    if (cfg && cfg.admin && !cfg.admin.backupName) {
      return { ...cfg, admin: { ...cfg.admin, backupName: cfg.admin.serverName } };
    }
    return cfg;
  });
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (initialConfig) {
      const cfg = { ...initialConfig };
      if (cfg && cfg.admin && !cfg.admin.backupName) {
        cfg.admin = { ...cfg.admin, backupName: cfg.admin.serverName };
      }
      setConfig(cfg);
    }
  }, [initialConfig]);

  const [showExtra, setShowExtra] = useState(false);
  const [serverCategories, setServerCategories] = useState<{ id: string; name: string }[] | null>(null);
  const [loadingCategories, setLoadingCategories] = useState(true);
  const [categoriesError, setCategoriesError] = useState<string | null>(null);
  
  const [matchBackupName, setMatchBackupName] = useState(backupId === 'New Backup');
  const [allPaths, setAllPaths] = useState<string[]>([]);
  const [pathConflict, setPathConflict] = useState(false);

  useEffect(() => {
    api.getAllBackupPaths().then(res => setAllPaths(res.filter(Boolean))).catch(console.error);
  }, []);

  const admin = config?.admin || {};
  const currentPath = admin.path || ('Backups/' + (admin.backupName || admin.serverName || 'Unnamed').replace(/[^a-zA-Z0-9_-]/g, '_'));

  useEffect(() => {
    if (matchBackupName) {
      const safe = 'Backups/' + (admin.backupName || admin.serverName || 'Unnamed').replace(/[^a-zA-Z0-9_-]/g, '_');
      if (admin.path !== safe) {
        setConfig((prev: any) => ({ ...prev, admin: { ...prev.admin, path: safe } }));
      }
    }
  }, [matchBackupName, admin.backupName, admin.serverName, admin.path]);

  useEffect(() => {
    if (backupId === 'New Backup' && allPaths.some(p => p.toLowerCase() === currentPath.toLowerCase())) {
      setPathConflict(true);
    } else {
      setPathConflict(false);
    }
  }, [currentPath, allPaths, backupId]);

  useEffect(() => {
    if (!admin.serverId) {
      setLoadingCategories(false);
      return;
    }
    setLoadingCategories(true);
    setCategoriesError(null);
    api.getServerCategories(admin.serverId)
      .then(res => {
        if (Array.isArray(res)) {
          setServerCategories(res);
        } else if (typeof res === 'object' && res !== null) {
          const catArray = Object.entries(res).map(([id, name]) => ({ id, name: String(name) }));
          setServerCategories(catArray);
        }
      })
      .catch((err: any) => {
        console.error(err);
        setCategoriesError('Failed to fetch server categories');
      })
      .finally(() => {
        setLoadingCategories(false);
      });
  }, [admin.serverId]);

  const handleSaveOnly = async () => {
    setIsSaving(true);
    setSaveError(null);
    try {
      await api.updateBackupConfig(backupId, config);
      if (onSave) {
        onSave(config);
      } else {
        onCancel();
      }
    } catch (err: any) {
      console.error('Failed to save config:', err);
      setSaveError(err.message || 'Failed to save configuration');
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveAndRun = async () => {
    setIsSaving(true);
    setSaveError(null);
    try {
      if (backupId === 'New Backup') {
        await api.createNewBackup(config);
      } else {
        await api.runBackup(backupId, config);
      }
      onStart();
    } catch (err: any) {
      console.error('Failed to start backup:', err);
      setSaveError(err.message || 'Failed to start backup');
      setIsSaving(false);
    }
  };

  const isKeepMode = admin.keepMode || false;
  const categoriesList = isKeepMode ? (admin.categoriesToKeep || []) : (admin.categoriesToIgnore || []);

  const addCategory = (value: string) => {
    if (value.trim()) {
      if (categoriesList.includes(value.trim())) return;
      const list = [...categoriesList, value.trim()];
      setConfig({
        ...config,
        admin: {
          ...admin,
          [isKeepMode ? 'categoriesToKeep' : 'categoriesToIgnore']: list
        }
      });
    }
  };

  const removeCategory = (cat: string) => {
    const list = categoriesList.filter((c: string) => c !== cat);
    setConfig({
      ...config,
      admin: {
        ...admin,
        [isKeepMode ? 'categoriesToKeep' : 'categoriesToIgnore']: list
      }
    });
  };

  const toggleKeepMode = (keep: boolean) => {
    setConfig({
      ...config,
      admin: {
        ...admin,
        keepMode: keep
      }
    });
  };

  const updateVerbosity = (key: string, val: boolean) => {
    setConfig({
      ...config,
      admin: {
        ...admin,
        verbosity: {
          ...(admin.verbosity || {}),
          [key]: val
        }
      }
    });
  };

  const formFields = (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '1rem' }}>
        <div>
          <label style={{ display: 'block', marginBottom: '0.25rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Backup Name</label>
          <input 
            type="text" 
            value={admin.backupName || ''} 
            onChange={e => setConfig({ ...config, admin: { ...admin, backupName: e.target.value } })}
            style={{ width: '100%', padding: '0.5rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px' }}
          />
        </div>

        <div>
          <label style={{ display: 'block', marginBottom: '0.25rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Server ID</label>
          <input 
            type="text" 
            disabled 
            value={admin.serverId || ''} 
            style={{ width: '100%', padding: '0.5rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'gray', borderRadius: '4px' }}
          />
        </div>
      </div>

      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
          <label style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Output Path</label>
          <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
            <input 
              type="checkbox" 
              checked={matchBackupName} 
              onChange={e => setMatchBackupName(e.target.checked)}
            />
            Match backup name
          </label>
        </div>
        <input 
          type="text" 
          disabled={matchBackupName}
          value={currentPath} 
          onChange={e => setConfig({ ...config, admin: { ...admin, path: e.target.value } })}
          style={{ width: '100%', padding: '0.5rem', background: 'var(--bg-tertiary)', border: `1px solid ${pathConflict ? 'var(--danger)' : 'var(--border-color)'}`, color: matchBackupName ? 'gray' : 'white', borderRadius: '4px' }}
        />
        {pathConflict && (
          <span style={{ color: 'var(--danger)', fontSize: '0.8rem', marginTop: '0.25rem', display: 'block' }}>
            Warning: A backup at this path already exists.
          </span>
        )}
      </div>

      <div>
        <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Categories Filter Mode</label>
        <div style={{ display: 'flex', gap: '1rem', marginBottom: '0.5rem' }}>
          <label style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <input 
              type="radio" 
              name={`catMode_${backupId}`}
              checked={!isKeepMode} 
              onChange={() => toggleKeepMode(false)}
            />
            Ignore categories
          </label>
          <label style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <input 
              type="radio" 
              name={`catMode_${backupId}`}
              checked={isKeepMode} 
              onChange={() => toggleKeepMode(true)}
            />
            Keep only categories
          </label>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
          {loadingCategories ? (
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Loading categories...</div>
          ) : categoriesError ? (
            <div style={{ color: 'var(--danger)', fontSize: '0.85rem' }}>{categoriesError}</div>
          ) : serverCategories && serverCategories.length > 0 ? (
            <select 
              onChange={e => {
                if (e.target.value) {
                  addCategory(e.target.value);
                  e.target.value = '';
                }
              }}
              defaultValue=""
              style={{ flex: 1, padding: '0.5rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px' }}
            >
              <option value="" disabled>-- Select a category to add --</option>
              {serverCategories.map(cat => (
                <option key={cat.id} value={cat.name} disabled={categoriesList.includes(cat.name)}>
                  {cat.name} {categoriesList.includes(cat.name) ? '(Added)' : ''}
                </option>
              ))}
            </select>
          ) : (
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No categories found</div>
          )}
        </div>

        {categoriesList.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.5rem' }}>
            {categoriesList.map((cat: string) => (
              <span key={cat} style={{ background: 'var(--bg-tertiary)', padding: '0.25rem 0.5rem', borderRadius: '4px', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.4rem', border: '1px solid var(--border-color)' }}>
                {cat}
                <X size={14} style={{ cursor: 'pointer' }} onClick={() => removeCategory(cat)} />
              </span>
            ))}
          </div>
        )}
      </div>

      <div>
        <button 
          type="button" 
          onClick={() => setShowExtra(!showExtra)}
          style={{ background: 'transparent', border: 'none', color: 'var(--accent-secondary)', display: 'flex', alignItems: 'center', gap: '0.25rem', padding: 0, cursor: 'pointer', fontSize: '0.9rem' }}
        >
          {showExtra ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          Advanced settings
        </button>

        {showExtra && (
          <div style={{ padding: '1rem', background: 'var(--bg-tertiary)', borderRadius: '8px', border: '1px solid var(--border-color)', marginTop: '0.5rem' }}>
            <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>
              <div>
                <strong style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Verbosity levels</strong>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.85rem' }}>
                  {['info', 'debug', 'console', 'log'].map(key => (
                    <label key={key} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                      <input 
                        type="checkbox" 
                        checked={admin.verbosity?.[key] || false} 
                        onChange={e => updateVerbosity(key, e.target.checked)}
                      />
                      Show {key} messages
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <strong style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Other settings</strong>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.85rem' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                    <input 
                      type="checkbox" 
                      checked={admin.verbosity?.debugFiles || false} 
                      onChange={e => updateVerbosity('debugFiles', e.target.checked)}
                    />
                    Keep debug files
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                    <input 
                      type="checkbox" 
                      checked={admin.verbosity?.dryRun || false} 
                      onChange={e => updateVerbosity('dryRun', e.target.checked)}
                    />
                    Dry run mode
                  </label>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );

  if (isModal) {
    return (
      <div 
        style={{ 
          position: 'fixed', 
          top: 0, 
          left: 0, 
          right: 0, 
          bottom: 0, 
          background: 'rgba(0, 0, 0, 0.75)', 
          zIndex: 1000, 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          padding: '1rem',
          backdropFilter: 'blur(4px)',
        }}
        onClick={(e) => {
          if (e.target === e.currentTarget && !isSaving) {
            onCancel();
          }
        }}
      >
        <div style={{ 
          background: 'var(--bg-primary)', 
          width: '720px', 
          maxWidth: '95vw', 
          maxHeight: '90vh', 
          borderRadius: '12px', 
          border: '1px solid var(--border-color)', 
          display: 'flex', 
          flexDirection: 'column',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.6)'
        }}>
          {/* Modal Header */}
          <div style={{ 
            padding: '1rem 1.5rem', 
            borderBottom: '1px solid var(--border-color)', 
            display: 'flex', 
            justifyContent: 'space-between', 
            alignItems: 'center',
            background: 'var(--bg-secondary)',
            borderRadius: '12px 12px 0 0'
          }}>
            <h3 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--text-primary)' }}>
              Configure Backup: {admin.backupName || admin.serverName || backupId} <span style={{ fontSize: '0.8em', color: 'var(--text-secondary)', fontWeight: 'normal' }}>({admin.serverId})</span>
            </h3>
            <button 
              onClick={onCancel} 
              disabled={isSaving}
              style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', display: 'flex', padding: 0 }}
            >
              <X size={20} />
            </button>
          </div>

          {/* Modal Body */}
          <div style={{ padding: '1.5rem', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            {saveError && (
              <div style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid var(--danger)', color: 'var(--danger)', padding: '0.75rem', borderRadius: '4px', fontSize: '0.85rem' }}>
                {saveError}
              </div>
            )}
            {formFields}
          </div>

          {/* Modal Footer */}
          <div style={{ 
            padding: '1rem 1.5rem', 
            borderTop: '1px solid var(--border-color)', 
            display: 'flex', 
            justifyContent: 'flex-end', 
            gap: '0.75rem',
            background: 'var(--bg-secondary)',
            borderRadius: '0 0 12px 12px'
          }}>
            <button 
              onClick={onCancel}
              disabled={isSaving}
              style={{ padding: '0.5rem 1rem', background: 'transparent', color: 'var(--text-primary)', border: '1px solid var(--border-color)', borderRadius: '6px', cursor: 'pointer' }}
            >
              Cancel
            </button>
            <button 
              onClick={handleSaveOnly}
              disabled={isSaving}
              style={{ 
                padding: '0.5rem 1.25rem', 
                background: 'var(--bg-tertiary)', 
                color: 'white', 
                border: '1px solid var(--border-color)', 
                borderRadius: '6px', 
                fontWeight: 600, 
                cursor: isSaving ? 'not-allowed' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem'
              }}
            >
              {isSaving && <Loader2 size={14} className="animate-spin" />}
              Save configuration
            </button>
            <button 
              onClick={handleSaveAndRun}
              disabled={isSaving}
              style={{ 
                padding: '0.5rem 1.25rem', 
                background: 'var(--accent-primary)', 
                color: '#fff', 
                border: 'none', 
                borderRadius: '6px', 
                fontWeight: 600, 
                cursor: isSaving ? 'not-allowed' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem'
              }}
            >
              {isSaving && <Loader2 size={14} className="animate-spin" />}
              Save & Update now
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ background: 'var(--bg-secondary)', padding: '1.5rem', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
      <h3 style={{ margin: '0 0 1rem 0' }}>
        Configure Backup: {admin.serverName} <span style={{ fontSize: '0.75em', color: 'var(--text-secondary)', fontWeight: 'normal' }}>({admin.serverId})</span>
      </h3>
      
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        {saveError && (
          <div style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid var(--danger)', color: 'var(--danger)', padding: '0.75rem', borderRadius: '4px', fontSize: '0.85rem' }}>
            {saveError}
          </div>
        )}
        {formFields}

        <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem' }}>
          <button 
            onClick={handleSaveAndRun}
            disabled={isSaving}
            style={{ padding: '0.5rem 1.5rem', background: 'var(--accent-primary)', color: '#fff', border: 'none', borderRadius: '6px', fontWeight: 600, cursor: isSaving ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
          >
            {isSaving && <Loader2 size={16} className="animate-spin" />}
            Start backup
          </button>
          <button 
            onClick={onCancel}
            disabled={isSaving}
            style={{ padding: '0.5rem 1.5rem', background: 'transparent', color: 'var(--text-primary)', border: '1px solid var(--border-color)', borderRadius: '6px', cursor: 'pointer' }}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

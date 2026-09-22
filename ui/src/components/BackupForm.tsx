import { useState, useEffect } from 'react';
import { api } from '../api';
import { ChevronDown, ChevronRight, X, Loader2 } from 'lucide-react';

export const BackupForm = ({ 
  backupId, 
  initialConfig, 
  globalConfig, 
  onStart, 
  onCancel 
}: { 
  backupId: string; 
  initialConfig: any; 
  globalConfig: any; 
  onStart: () => void; 
  onCancel: () => void; 
}) => {
  const [config, setConfig] = useState<any>(() => {
    const cfg = initialConfig || globalConfig;
    if (cfg && cfg.admin && !cfg.admin.backupName) {
      return { ...cfg, admin: { ...cfg.admin, backupName: cfg.admin.serverName } };
    }
    return cfg;
  });
  const [showExtra, setShowExtra] = useState(false);
  
  const [serverCategories, setServerCategories] = useState<{id: string, name: string}[] | null>(null);
  const [loadingCategories, setLoadingCategories] = useState(true);
  const [categoriesError, setCategoriesError] = useState<string | null>(null);
  
  const [matchBackupName, setMatchBackupName] = useState(backupId === "New Backup");
  const [allPaths, setAllPaths] = useState<string[]>([]);
  const [pathConflict, setPathConflict] = useState(false);

  useEffect(() => {
    api.getAllBackupPaths().then(res => setAllPaths(res.filter(Boolean))).catch(console.error);
  }, []);

  const admin = config.admin || {};
  const currentPath = admin.path || ('Backups/' + (admin.backupName || admin.serverName || "Unnamed").replace(/[^a-zA-Z0-9_-]/g, '_'));

  useEffect(() => {
    if (matchBackupName) {
      const safe = 'Backups/' + (admin.backupName || admin.serverName || "Unnamed").replace(/[^a-zA-Z0-9_-]/g, '_');
      if (admin.path !== safe) {
        setConfig((prev: any) => ({ ...prev, admin: { ...prev.admin, path: safe } }));
      }
    }
  }, [matchBackupName, admin.backupName, admin.serverName, admin.path]);

  useEffect(() => {
    if (backupId === "New Backup" && allPaths.some(p => p.toLowerCase() === currentPath.toLowerCase())) {
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
      .then((res: any) => {
        const catArray = Object.entries(res).map(([id, name]) => ({ id, name: name as string }));
        setServerCategories(catArray);
      })
      .catch((err: any) => {
        console.error(err);
        setCategoriesError("Failed to fetch server categories");
      })
      .finally(() => {
        setLoadingCategories(false);
      });
  }, [admin.serverId]);
  


  const handleRun = () => {
    if (backupId === "New Backup") {
      api.createNewBackup(config).then(() => {
        onStart();
      }).catch(console.error);
    } else {
      api.runBackup(backupId, config).then(() => {
        onStart();
      }).catch(console.error);
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
  
  const addDmCategory = (value: string) => {
    if (value.trim()) {
      const currentList = admin.dmCategories || [];
      if (currentList.includes(value.trim())) return;
      const list = [...currentList, value.trim()];
      setConfig({
        ...config,
        admin: { ...admin, dmCategories: list }
      });
    }
  };

  const removeDmCategory = (cat: string) => {
    const list = (admin.dmCategories || []).filter((c: string) => c !== cat);
    setConfig({
      ...config,
      admin: { ...admin, dmCategories: list }
    });
  };
  
  const updateVerbosity = (key: string, value: boolean) => {
    setConfig({
      ...config,
      admin: {
        ...admin,
        verbosity: {
          ...(admin.verbosity || {}),
          [key]: value
        }
      }
    });
  };

  return (
    <div style={{ background: 'var(--bg-secondary)', padding: '1.5rem', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
      <h3 style={{ margin: '0 0 1rem 0' }}>
        Configure Backup: {admin.serverName} <span style={{ fontSize: '0.75em', color: 'var(--text-secondary)', fontWeight: 'normal' }}>({admin.serverId})</span>
      </h3>
      
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        
        {/* Server Info */}
        <div style={{ display: 'flex', gap: '1rem' }}>
          <div style={{ flex: 1 }}>
            <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Backup name</label>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.5rem', minHeight: '30px' }}>
              A server can have more than one backup, so the name doesn't need to match.
            </div>
            <input 
              type="text" 
              value={admin.backupName || ''} 
              disabled={backupId !== "New Backup"}
              onChange={e => setConfig({ ...config, admin: { ...admin, backupName: e.target.value } })}
              style={{ width: '100%', padding: '0.5rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px' }}
            />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.25rem' }}>
              <label style={{ display: 'block', fontSize: '0.85rem', color: pathConflict ? 'var(--danger)' : 'var(--text-secondary)' }}>Path</label>
            </div>
            <div style={{ marginBottom: '0.5rem', minHeight: '30px', display: 'flex', alignItems: 'flex-start' }}>
              {backupId === "New Backup" && (
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.75rem', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                  <div style={{ 
                    position: 'relative', 
                    width: '32px', 
                    height: '18px', 
                    background: matchBackupName ? 'var(--accent-primary)' : 'var(--bg-tertiary)', 
                    borderRadius: '9px', 
                    border: '1px solid var(--border-color)',
                    transition: 'background 0.2s'
                  }}>
                    <div style={{ 
                      position: 'absolute', 
                      top: '1px', 
                      left: matchBackupName ? '15px' : '1px', 
                      width: '14px', 
                      height: '14px', 
                      background: 'white', 
                      borderRadius: '50%', 
                      transition: 'left 0.2s'
                    }} />
                  </div>
                  <input 
                    type="checkbox" 
                    checked={matchBackupName} 
                    onChange={e => setMatchBackupName(e.target.checked)}
                    style={{ display: 'none' }}
                  />
                  Match backup name
                </label>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'stretch', opacity: (backupId !== "New Backup" || matchBackupName) ? 0.6 : 1 }}>
              <span style={{ 
                background: 'var(--bg-tertiary)', 
                border: `1px solid ${pathConflict ? 'var(--danger)' : 'var(--border-color)'}`, 
                borderRight: 'none', 
                padding: '0.5rem 0.25rem 0.5rem 0.75rem', 
                color: 'var(--text-secondary)', 
                borderRadius: '4px 0 0 4px',
                fontSize: '0.85rem',
                display: 'flex',
                alignItems: 'center'
              }}>
                Backups/
              </span>
              <input 
                type="text" 
                value={currentPath.replace(/^Backups\//, '')} 
                disabled={backupId !== "New Backup" || matchBackupName}
                onChange={e => setConfig({ ...config, admin: { ...admin, path: 'Backups/' + e.target.value } })}
                style={{ 
                  flex: 1, 
                  padding: '0.5rem', 
                  paddingLeft: '0.25rem',
                  background: 'var(--bg-tertiary)', 
                  border: `1px solid ${pathConflict ? 'var(--danger)' : 'var(--border-color)'}`, 
                  color: 'white', 
                  borderRadius: '0 4px 4px 0',
                  outline: 'none'
                }}
              />
            </div>
            {pathConflict && (
              <div style={{ color: 'var(--danger)', fontSize: '0.75rem', marginTop: '0.25rem' }}>
                This path conflicts with an existing backup.
              </div>
            )}
          </div>
        </div>
        
        {/* Categories Filter */}
        <div>
          <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Category filters</label>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
            Choose which categories will be downloaded. If updating an existing backup, review if the current list is still correct.
          </div>
          
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.5rem' }}>
            <button 
              onClick={() => setConfig({ ...config, admin: { ...admin, keepMode: !isKeepMode } })}
              style={{ padding: '0.3rem 0.6rem', fontSize: '0.8rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px', cursor: 'pointer' }}
            >
              Mode: {isKeepMode ? "Keep only these categories" : "Ignore these categories"}
            </button>
          </div>
          
          {loadingCategories ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '0.5rem', padding: '0.5rem', background: 'var(--bg-tertiary)', borderRadius: '4px' }}>
              <Loader2 size={16} className="animate-spin" /> Fetching the server's categories...
            </div>
          ) : categoriesError ? (
            <div style={{ color: 'var(--danger)', fontSize: '0.85rem', marginBottom: '0.5rem' }}>{categoriesError}</div>
          ) : (
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
              <select 
                value="" 
                onChange={e => addCategory(e.target.value)}
                style={{ flex: 1, padding: '0.5rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px' }}
              >
                <option value="">-- Select a category to add --</option>
                {serverCategories?.map(cat => (
                  <option key={cat.id} value={cat.name}>{cat.name}</option>
                ))}
              </select>
            </div>
          )}
          
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            {categoriesList.map((cat: string) => (
              <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', background: 'var(--accent-secondary)', color: '#000', padding: '0.2rem 0.5rem', borderRadius: '12px', fontSize: '0.8rem' }}>
                {cat}
                <button type="button" onClick={() => removeCategory(cat)} style={{ background: 'transparent', border: 'none', color: '#000', padding: 0, cursor: 'pointer', display: 'flex' }}><X size={12} /></button>
              </div>
            ))}
          </div>
        </div>

        {/* DM Categories */}
        <div>
          <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>DM-like categories</label>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
            Which categories should be tagged as DMs, text, calls, etc? Channels in these categories will be processed with a different method.
          </div>
          
          {loadingCategories ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '0.5rem', padding: '0.5rem', background: 'var(--bg-tertiary)', borderRadius: '4px' }}>
              <Loader2 size={16} className="animate-spin" /> Fetching the server's categories...
            </div>
          ) : categoriesError ? (
            <div style={{ color: 'var(--danger)', fontSize: '0.85rem', marginBottom: '0.5rem' }}>{categoriesError}</div>
          ) : (
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
              <select 
                value="" 
                onChange={e => addDmCategory(e.target.value)}
                style={{ flex: 1, padding: '0.5rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px' }}
              >
                <option value="">-- Select a category to add --</option>
                {serverCategories?.map(cat => (
                  <option key={cat.id} value={cat.name}>{cat.name}</option>
                ))}
              </select>
            </div>
          )}
          
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            {(admin.dmCategories || []).map((cat: string) => (
              <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', background: 'var(--accent-secondary)', color: '#000', padding: '0.2rem 0.5rem', borderRadius: '12px', fontSize: '0.8rem' }}>
                {cat}
                <button type="button" onClick={() => removeDmCategory(cat)} style={{ background: 'transparent', border: 'none', color: '#000', padding: 0, cursor: 'pointer', display: 'flex' }}><X size={12} /></button>
              </div>
            ))}
          </div>
        </div>

        {/* Extra Settings */}
        <div>
          <div 
            onClick={() => setShowExtra(!showExtra)}
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', color: 'var(--text-primary)', marginBottom: '0.5rem' }}
          >
            {showExtra ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            <strong style={{ fontSize: '0.9rem' }}>Extra settings</strong>
          </div>
          
          {showExtra && (
            <div style={{ padding: '1rem', background: 'var(--bg-tertiary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
              <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>
                <div>
                  <strong style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>Verbosity levels</strong>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
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
                  <strong style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>Other settings</strong>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
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

        {/* Actions */}
        <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem' }}>
          <button 
            onClick={handleRun}
            style={{ padding: '0.5rem 1.5rem', background: 'var(--accent-primary)', color: '#000', border: 'none', borderRadius: '4px', fontWeight: 'bold', cursor: 'pointer' }}
          >
            Start backup
          </button>
          <button 
            onClick={onCancel}
            style={{ padding: '0.5rem 1.5rem', background: 'transparent', color: 'var(--text-primary)', border: '1px solid var(--border-color)', borderRadius: '4px', cursor: 'pointer' }}
          >
            Cancel
          </button>
        </div>

      </div>
    </div>
  );
};

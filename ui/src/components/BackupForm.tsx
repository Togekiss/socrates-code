import { useState, useEffect } from 'react';
import { api } from '../api';
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { BackupCategorySelector } from './BackupCategorySelector';
import { BackupFormModal } from './BackupFormModal';
import type { BackupConfig, GlobalConfig } from '../types';

export const BackupForm = ({
  backupId,
  initialConfig,
  globalConfig,
  onStart,
  onCancel,
  onSave,
  isModal = false,
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
  const [showExtra, setShowExtra] = useState(false);
  const [serverCategories, setServerCategories] = useState<{ id: string; name: string }[] | null>(null);
  const [loadingCategories, setLoadingCategories] = useState(true);
  const [categoriesError, setCategoriesError] = useState<string | null>(null);
  const [matchBackupName, setMatchBackupName] = useState(backupId === 'New Backup');
  const [allPaths, setAllPaths] = useState<string[]>([]);
  const [pathConflict, setPathConflict] = useState(false);

  useEffect(() => {
    if (initialConfig) {
      const cfg = { ...initialConfig };
      if (cfg && cfg.admin && !cfg.admin.backupName) {
        cfg.admin = { ...cfg.admin, backupName: cfg.admin.serverName };
      }
      setConfig(cfg);
    }
  }, [initialConfig]);

  useEffect(() => {
    api.getAllBackupPaths().then(res => setAllPaths(res.filter(Boolean))).catch(console.error);
  }, []);

  const admin = config?.admin || {};
  const currentPath = admin.path || 'Backups/' + (admin.backupName || admin.serverName || 'Unnamed').replace(/[^a-zA-Z0-9_-]/g, '_');

  useEffect(() => {
    if (matchBackupName) {
      const safe = 'Backups/' + (admin.backupName || admin.serverName || 'Unnamed').replace(/[^a-zA-Z0-9_-]/g, '_');
      if (admin.path !== safe) {
        setConfig((prev: any) => ({ ...prev, admin: { ...prev.admin, path: safe } }));
      }
    }
  }, [matchBackupName, admin.backupName, admin.serverName, admin.path]);

  useEffect(() => {
    setPathConflict(backupId === 'New Backup' && allPaths.some(p => p.toLowerCase() === currentPath.toLowerCase()));
  }, [currentPath, allPaths, backupId]);

  useEffect(() => {
    if (!admin.serverId) {
      setLoadingCategories(false);
      return;
    }
    setLoadingCategories(true);
    setCategoriesError(null);
    api
      .getServerCategories(admin.serverId)
      .then(res => {
        if (Array.isArray(res)) {
          setServerCategories(res);
        } else if (typeof res === 'object' && res !== null) {
          setServerCategories(Object.entries(res).map(([id, name]) => ({ id, name: String(name) })));
        }
      })
      .catch((err: any) => {
        console.error(err);
        setCategoriesError('Failed to fetch server categories');
      })
      .finally(() => setLoadingCategories(false));
  }, [admin.serverId]);

  const handleSaveOnly = async () => {
    setIsSaving(true);
    setSaveError(null);
    try {
      await api.updateBackupConfig(backupId, config);
      if (onSave) onSave(config);
      else onCancel();
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
      if (backupId === 'New Backup') await api.createNewBackup(config);
      else await api.runBackup(backupId, config);
      onStart();
    } catch (err: any) {
      console.error('Failed to start backup:', err);
      setSaveError(err.message || 'Failed to start backup');
      setIsSaving(false);
    }
  };

  const isKeepMode = admin.keepMode || false;
  const categoriesList = isKeepMode ? admin.categoriesToKeep || [] : admin.categoriesToIgnore || [];
  const chatroomCategoriesList = admin.chatroomCategories || [];
  const eventCategoriesList = admin.eventCategories || [];

  const addCategory = (value: string) => {
    const val = value.trim();
    if (val && !categoriesList.includes(val)) {
      const list = [...categoriesList, val];
      setConfig({
        ...config,
        admin: { ...admin, [isKeepMode ? 'categoriesToKeep' : 'categoriesToIgnore']: list },
      });
    }
  };

  const removeCategory = (cat: string) => {
    const list = categoriesList.filter((c: string) => c !== cat);
    setConfig({
      ...config,
      admin: { ...admin, [isKeepMode ? 'categoriesToKeep' : 'categoriesToIgnore']: list },
    });
  };

  const addChatroomCategory = (value: string) => {
    const val = value.trim();
    if (val && !chatroomCategoriesList.includes(val)) {
      const newChatList = [...chatroomCategoriesList, val];
      const newIgnore = (admin.categoriesToIgnore || []).filter((c: string) => c !== val);
      const newKeep =
        isKeepMode && !(admin.categoriesToKeep || []).includes(val)
          ? [...(admin.categoriesToKeep || []), val]
          : admin.categoriesToKeep || [];
      setConfig({
        ...config,
        admin: {
          ...admin,
          chatroomCategories: newChatList,
          categoriesToIgnore: newIgnore,
          categoriesToKeep: newKeep,
        },
      });
    }
  };

  const removeChatroomCategory = (cat: string) => {
    setConfig({
      ...config,
      admin: { ...admin, chatroomCategories: chatroomCategoriesList.filter((c: string) => c !== cat) },
    });
  };

  const addEventCategory = (value: string) => {
    const val = value.trim();
    if (val && !eventCategoriesList.includes(val)) {
      const newEventList = [...eventCategoriesList, val];
      const newIgnore = (admin.categoriesToIgnore || []).filter((c: string) => c !== val);
      const baseKeep = admin.categoriesToKeep || [];
      const nextKeep = isKeepMode
        ? Array.from(new Set([...baseKeep, val, 'Events']))
        : baseKeep;
      setConfig({
        ...config,
        admin: {
          ...admin,
          eventCategories: newEventList,
          categoriesToIgnore: newIgnore,
          categoriesToKeep: nextKeep,
        },
      });
    }
  };

  const removeEventCategory = (cat: string) => {
    setConfig({
      ...config,
      admin: { ...admin, eventCategories: eventCategoriesList.filter((c: string) => c !== cat) },
    });
  };

  const toggleKeepMode = (keep: boolean) => {
    setConfig({ ...config, admin: { ...admin, keepMode: keep } });
  };

  const updateVerbosity = (key: string, val: boolean) => {
    setConfig({
      ...config,
      admin: { ...admin, verbosity: { ...(admin.verbosity || {}), [key]: val } },
    });
  };

  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '0.5rem',
    background: 'var(--bg-tertiary)',
    border: '1px solid var(--border-color)',
    color: 'white',
    borderRadius: '4px',
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
            style={inputStyle}
          />
        </div>

        <div>
          <label style={{ display: 'block', marginBottom: '0.25rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Server ID</label>
          <input type="text" disabled value={admin.serverId || ''} style={{ ...inputStyle, color: 'gray' }} />
        </div>
      </div>

      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
          <label style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Output Path</label>
          <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
            <input type="checkbox" checked={matchBackupName} onChange={e => setMatchBackupName(e.target.checked)} />
            Match backup name
          </label>
        </div>
        <input
          type="text"
          disabled={matchBackupName}
          value={currentPath}
          onChange={e => setConfig({ ...config, admin: { ...admin, path: e.target.value } })}
          style={{
            ...inputStyle,
            border: `1px solid ${pathConflict ? 'var(--danger)' : 'var(--border-color)'}`,
            color: matchBackupName ? 'gray' : 'white',
          }}
        />
        {pathConflict && (
          <span style={{ color: 'var(--danger)', fontSize: '0.8rem', marginTop: '0.25rem', display: 'block' }}>
            Warning: A backup at this path already exists.
          </span>
        )}
      </div>

      <BackupCategorySelector
        backupId={backupId}
        isKeepMode={isKeepMode}
        toggleKeepMode={toggleKeepMode}
        categoriesList={categoriesList}
        addCategory={addCategory}
        removeCategory={removeCategory}
        chatroomCategoriesList={chatroomCategoriesList}
        addChatroomCategory={addChatroomCategory}
        removeChatroomCategory={removeChatroomCategory}
        eventCategoriesList={eventCategoriesList}
        addEventCategory={addEventCategory}
        removeEventCategory={removeEventCategory}
        serverCategories={serverCategories}
        loadingCategories={loadingCategories}
        categoriesError={categoriesError}
      />

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
                      <input type="checkbox" checked={admin.verbosity?.[key] || false} onChange={e => updateVerbosity(key, e.target.checked)} />
                      Show {key} messages
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <strong style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Other settings</strong>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.85rem' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                    <input type="checkbox" checked={admin.verbosity?.debugFiles || false} onChange={e => updateVerbosity('debugFiles', e.target.checked)} />
                    Keep debug files
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                    <input type="checkbox" checked={admin.verbosity?.dryRun || false} onChange={e => updateVerbosity('dryRun', e.target.checked)} />
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
      <BackupFormModal
        backupId={backupId}
        admin={admin}
        isSaving={isSaving}
        saveError={saveError}
        onCancel={onCancel}
        handleSaveOnly={handleSaveOnly}
        handleSaveAndRun={handleSaveAndRun}
      >
        {formFields}
      </BackupFormModal>
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

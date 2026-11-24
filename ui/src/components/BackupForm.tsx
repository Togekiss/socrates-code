import { useState, useEffect } from 'react';
import { api } from '../api';
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { BackupCategorySelector } from './BackupCategorySelector';
import { BackupFormModal, BackupStorageModeModalSection } from './BackupFormModal';
import type { BackupConfig, GlobalConfig, StorageMode } from '../types';

export const BackupForm = ({
  backupId,
  initialConfig,
  globalConfig,
  hasDataFiles = false,
  onStart,
  onCancel,
  onSave,
  isModal = false,
}: {
  backupId: string;
  initialConfig: BackupConfig | null;
  globalConfig: GlobalConfig | null;
  hasDataFiles?: boolean;
  onStart?: (backupId?: string) => void;
  onCancel: () => void;
  onSave?: (savedConfig: BackupConfig) => void;
  isModal?: boolean;
}) => {
  const [config, setConfig] = useState<BackupConfig | null>(() => {
    const cfg = initialConfig || globalConfig;
    if (cfg && cfg.admin && !cfg.admin.backupName) {
      return { ...cfg, admin: { ...cfg.admin, backupName: cfg.admin.serverName } };
    }
    return cfg;
  });
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [showExtra, setShowExtra] = useState(false);
  const [showConvertWarning, setShowConvertWarning] = useState(false);
  const [confirmModeConversion, setConfirmModeConversion] = useState(false);
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
      setShowConvertWarning(false);
      setConfirmModeConversion(false);
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
        setConfig((prev: BackupConfig | null) => ({ ...(prev || {}), admin: { ...(prev?.admin || {}), path: safe } }));
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
        const stripCatPrefix = (val: string) => val.replace(/^\d+#\s*/, '').trim();
        if (Array.isArray(res)) {
          setServerCategories(
            res.map(cat =>
              typeof cat === 'object' && cat !== null && 'name' in cat
                ? { ...cat, name: stripCatPrefix(String((cat as { name?: unknown }).name ?? '')) }
                : cat
            )
          );
        } else if (typeof res === 'object' && res !== null) {
          setServerCategories(
            Object.entries(res).map(([id, name]) => ({
              id,
              name: stripCatPrefix(String(name)),
            }))
          );
        }
      })
      .catch((err: unknown) => {
        console.error(err);
        setCategoriesError('Failed to fetch server categories');
      })
      .finally(() => setLoadingCategories(false));
  }, [admin.serverId]);

  useEffect(() => {
    if (!serverCategories || serverCategories.length === 0) return;
    const nameToId = new Map<string, string>();
    for (const cat of serverCategories) {
      nameToId.set(cat.name.toLowerCase(), cat.id);
    }
    const normalizeList = (list?: string[]): string[] | undefined => {
      if (!list) return list;
      return Array.from(
        new Set(
          list.map(ref => {
            const stripped = ref.replace(/^\d+#\s*/, '').trim();
            return nameToId.get(ref.toLowerCase()) || nameToId.get(stripped.toLowerCase()) || ref;
          })
        )
      );
    };

    setConfig(prev => {
      if (!prev?.admin) return prev;
      const a = prev.admin;
      const nextKeep = normalizeList(a.categoriesToKeep);
      const nextIgnore = normalizeList(a.categoriesToIgnore);
      const nextChat = normalizeList(a.chatroomCategories);
      const nextEvent = normalizeList(a.eventCategories);

      const arraysEqual = (x?: string[], y?: string[]) =>
        x === y || (Boolean(x && y) && x!.length === y!.length && x!.every((v, i) => v === y![i]));

      if (
        arraysEqual(a.categoriesToKeep, nextKeep) &&
        arraysEqual(a.categoriesToIgnore, nextIgnore) &&
        arraysEqual(a.chatroomCategories, nextChat) &&
        arraysEqual(a.eventCategories, nextEvent)
      ) {
        return prev;
      }

      return {
        ...prev,
        admin: {
          ...a,
          categoriesToKeep: nextKeep,
          categoriesToIgnore: nextIgnore,
          chatroomCategories: nextChat,
          eventCategories: nextEvent,
        },
      };
    });
  }, [serverCategories, initialConfig]);

  const handleSaveOnly = async () => {
    if (!config) return;
    setIsSaving(true);
    setSaveError(null);
    try {
      await api.updateBackupConfig(backupId, config);
      if (onSave) onSave(config);
      else onCancel();
    } catch (err: unknown) {
      console.error('Failed to save config:', err);
      setSaveError(err instanceof Error ? err.message : 'Failed to save configuration');
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveAndRun = async () => {
    if (!config) return;
    setIsSaving(true);
    setSaveError(null);
    try {
      if (backupId === 'New Backup') {
        const created = await api.createNewBackup(config);
        if (onStart) onStart(created?.backup_id);
        return;
      } else if (isModal && confirmModeConversion) {
        const currentMode: StorageMode = admin.storageMode === 'full' ? 'full' : 'backupless';
        const targetMode: StorageMode = currentMode === 'full' ? 'backupless' : 'full';
        const convertedConfig: BackupConfig = {
          ...config,
          admin: { ...admin, storageMode: targetMode },
        };
        await api.syncBackup(backupId, { mode: 'rescan_discord', config: convertedConfig });
      } else {
        await api.syncBackup(backupId, { mode: 'incremental', config });
      }
      if (onStart) onStart();
    } catch (err: unknown) {
      console.error('Failed to start backup:', err);
      setSaveError(err instanceof Error ? err.message : 'Failed to start backup');
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
        ? Array.from(new Set([...baseKeep, val]))
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
    padding: '0.5rem 0.75rem',
    background: 'var(--bg-tertiary)',
    border: '1px solid var(--border-color)',
    color: 'var(--text-primary)',
    borderRadius: 'var(--radius-sm)',
    fontSize: '0.875rem',
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
          <input type="text" disabled value={admin.serverId || ''} style={{ ...inputStyle, color: 'var(--text-muted)' }} />
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
            color: matchBackupName ? 'var(--text-muted)' : 'var(--text-primary)',
          }}
        />
        {pathConflict && (
          <span style={{ color: 'var(--danger)', fontSize: '0.8rem', marginTop: '0.25rem', display: 'block' }}>
            Warning: A backup at this path already exists.
          </span>
        )}
      </div>

      {isModal ? (
        <BackupStorageModeModalSection
          currentMode={admin.storageMode === 'full' ? 'full' : 'backupless'}
          hasDataFiles={hasDataFiles}
          showConvertWarning={showConvertWarning}
          confirmModeConversion={confirmModeConversion}
          onToggleConvertWarning={() => {
            setShowConvertWarning(prev => {
              if (prev) setConfirmModeConversion(false);
              return !prev;
            });
          }}
          onConfirmChange={setConfirmModeConversion}
        />
      ) : (
        <div>
          <label style={{ display: 'block', marginBottom: '0.35rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Storage Mode
          </label>
          <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
            <label style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.875rem' }}>
              <input
                type="radio"
                name={`storageMode_${backupId}`}
                checked={(admin.storageMode || 'backupless') === 'backupless'}
                onChange={() =>
                  setConfig({
                    ...config,
                    admin: { ...admin, storageMode: 'backupless' },
                  })
                }
              />
              <span>
                <strong>Backupless</strong> <span className="text-muted">(lightweight SQLite skeletons, on-demand message hydration)</span>
              </span>
            </label>
            <label style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.875rem' }}>
              <input
                type="radio"
                name={`storageMode_${backupId}`}
                checked={admin.storageMode === 'full'}
                onChange={() =>
                  setConfig({
                    ...config,
                    admin: { ...admin, storageMode: 'full' },
                  })
                }
              />
              <span>
                <strong>Full Backup</strong> <span className="text-muted">(also stores full DCE-compatible Data/*.json files)</span>
              </span>
            </label>
          </div>
        </div>
      )}

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
        disableSaveOnly={confirmModeConversion}
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
          <div className="banner-danger">
            {saveError}
          </div>
        )}
        {formFields}

        <div className="flex-row gap-sm items-center mt-md">
          <button
            type="button"
            onClick={handleSaveAndRun}
            disabled={isSaving}
            className="btn btn-primary"
          >
            {isSaving && <Loader2 size={16} className="animate-spin" />}
            Start backup
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={isSaving}
            className="btn btn-secondary"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

import { useState, useEffect, useRef, useCallback } from 'react';
import { BrowserRouter, Routes, Route, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from './api';
import { Database, LogIn, Loader2, AlertCircle, AlertTriangle } from 'lucide-react';
import { Sidebar, type TabType } from './components/Sidebar';
import { StatusTab } from './components/StatusTab';
import { RunTab } from './components/RunTab';
import { WritersTab } from './components/WritersTab';
import { CharactersTab } from './components/CharactersTab';
import { ScenesTab } from './components/ScenesTab';
import { SceneIssuesTab } from './components/SceneIssuesTab';
import { FlaggedMessagesTab } from './components/FlaggedMessagesTab';
import { AdminTab } from './components/AdminTab';
import { BackupForm } from './components/BackupForm';
import { ErrorBoundary } from './components/ErrorBoundary';
import type { BackupInfo, CurationSummary, GlobalConfig, MyWriter, User } from './types';

function AuthCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const hasRequested = useRef(false);

  useEffect(() => {
    const code = searchParams.get('code');
    if (!code) {
      setError('No authorization code provided by Discord.');
      return;
    }

    if (hasRequested.current) return;
    hasRequested.current = true;

    api
      .authDiscord(code)
      .then(res => {
        if (res.status === 'success') {
          navigate('/', { replace: true });
        } else {
          setError('Authentication failed. Please try again.');
        }
      })
      .catch(err => {
        console.error(err);
        setError(err.message || 'Authentication failed or you are not in the required servers.');
      });
  }, [searchParams, navigate]);

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '80vh', padding: '2rem' }}>
      <div className="glass-panel" style={{ maxWidth: '460px', width: '100%', textAlign: 'center', padding: '3.5rem 2.5rem' }}>
        {error ? (
          <>
            <AlertCircle size={48} style={{ color: 'var(--danger)', marginBottom: '1.25rem' }} />
            <h2 style={{ fontSize: '1.35rem', marginBottom: '0.75rem', color: 'var(--text-primary)' }}>Authentication Failed</h2>
            <p style={{ color: 'var(--text-secondary)', lineHeight: '1.5', marginBottom: '1.75rem', fontSize: '0.95rem' }}>{error}</p>
            <button
              onClick={() => navigate('/', { replace: true })}
              style={{
                padding: '0.65rem 1.5rem',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                borderRadius: '6px',
                color: 'white',
                fontWeight: 500,
              }}
            >
              Return to Home
            </button>
          </>
        ) : (
          <>
            <div style={{ display: 'inline-flex', position: 'relative', marginBottom: '1.5rem' }}>
              <div
                style={{
                  width: '64px',
                  height: '64px',
                  borderRadius: '50%',
                  background: 'rgba(109, 40, 217, 0.15)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  border: '1px solid var(--border-color)',
                }}
              >
                <Loader2 size={32} className="animate-spin" style={{ color: 'var(--accent-secondary)' }} />
              </div>
            </div>
            <h2 style={{ fontSize: '1.35rem', marginBottom: '0.5rem', color: 'var(--text-primary)' }}>Authenticating with Discord</h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', margin: 0, lineHeight: '1.5' }}>
              Verifying server memberships and setting up your session...
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function NewBackupTab({ user, onStart, onCancel }: { user: User; onStart: () => void; onCancel: () => void }) {
  const [globalConfig, setGlobalConfig] = useState<GlobalConfig | null>(null);
  const [selectedServer, setSelectedServer] = useState<string>('');

  useEffect(() => {
    api.getGlobalConfig().then(setGlobalConfig).catch(console.error);
  }, []);

  if (!globalConfig) {
    return (
      <div className="glass-panel" style={{ textAlign: 'center', padding: '4rem 2rem' }}>
        <Loader2 size={36} className="animate-spin" style={{ color: 'var(--accent-secondary)', margin: '0 auto 1.25rem auto' }} />
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>Loading configuration...</p>
      </div>
    );
  }

  const servers = user?.authorized_guilds || [];
  const serverInfo = servers.find(s => s.id === selectedServer);

  const initialConfigForServer = selectedServer && serverInfo ? {
    ...globalConfig,
    admin: {
      ...((globalConfig.admin as Record<string, unknown>) || {}),
      serverId: serverInfo.id,
      serverName: serverInfo.name,
      categoriesToKeep: [],
      categoriesToIgnore: [],
      dmCategories: [],
    },
  } : globalConfig;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div className="glass-panel">
        <h2 style={{ marginTop: 0, color: 'var(--text-primary)', marginBottom: '1.5rem' }}>Create a New Backup</h2>

        <div style={{ marginBottom: '1.5rem' }}>
          <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Select a Server to Backup
          </label>
          <select
            value={selectedServer}
            onChange={e => setSelectedServer(e.target.value)}
            style={{
              width: '100%',
              padding: '0.65rem',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-color)',
              color: 'white',
              borderRadius: '6px',
              fontSize: '0.95rem',
            }}
          >
            <option value="">-- Select a Server --</option>
            {servers.map(s => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>

        {selectedServer && (
          <div style={{ marginTop: '1rem' }}>
            <BackupForm
              key={selectedServer}
              backupId="New Backup"
              initialConfig={initialConfigForServer}
              globalConfig={globalConfig}
              onStart={onStart}
              onCancel={onCancel}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function Dashboard() {
  const [activeTab, setActiveTab] = useState<TabType>('status');
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [selectedBackupId, setSelectedBackupId] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [isLoadingAuth, setIsLoadingAuth] = useState<boolean>(true);

  // Real-time metadata states
  const [curationSummary, setCurationSummary] = useState<CurationSummary | null>(null);
  const [backupInfo, setBackupInfo] = useState<BackupInfo | null>(null);
  const [myWriter, setMyWriter] = useState<MyWriter | null>(null);
  const [isUpgrading, setIsUpgrading] = useState(false);

  const refreshSummary = useCallback(() => {
    if (!selectedBackupId) {
      setCurationSummary(null);
      setBackupInfo(null);
      setMyWriter(null);
      return;
    }

    Promise.all([
      api.getCurationSummary(selectedBackupId).catch(() => null),
      api.getBackupInfo(selectedBackupId).catch(() => null),
      api.getMyWriter(selectedBackupId).catch(() => null),
    ]).then(([summaryRes, infoRes, writerRes]) => {
      setCurationSummary(summaryRes);
      setBackupInfo(infoRes);
      setMyWriter(writerRes);
    });
  }, [selectedBackupId]);

  const handleUpgradeDatabase = async () => {
    if (!selectedBackupId || isUpgrading) return;
    setIsUpgrading(true);
    try {
      await api.upgradeBackup(selectedBackupId);
      refreshSummary();
    } catch (err) {
      console.error('Failed to upgrade database:', err);
    } finally {
      setIsUpgrading(false);
    }
  };

  useEffect(() => {
    refreshSummary();
  }, [selectedBackupId, refreshSummary]);

  useEffect(() => {
    api
      .getMe()
      .then(res => {
        if (res && res.user) {
          setUser(res.user);
          api
            .getBackups()
            .then(data => {
              const list = Array.isArray(data) ? data : [];
              setBackups(list);
              if (list.length > 0 && !selectedBackupId) {
                const firstId = list[0].id || list[0].backup_id || '';
                setSelectedBackupId(firstId);
              }
            })
            .catch(console.error);
        } else {
          setUser(null);
          setBackups([]);
        }
      })
      .catch(() => {
        setUser(null);
        setBackups([]);
      })
      .finally(() => {
        setIsLoadingAuth(false);
      });
  }, []);

  const handleLogin = () => {
    api
      .getLoginUrl()
      .then(res => {
        if (res.url) {
          window.location.href = res.url;
        }
      })
      .catch(console.error);
  };

  const handleLogout = () => {
    api
      .logout()
      .then(() => {
        setUser(null);
        setBackups([]);
        setSelectedBackupId(null);
        setCurationSummary(null);
        setBackupInfo(null);
        setMyWriter(null);
      })
      .catch(console.error);
  };

  if (isLoadingAuth) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <div className="glass-panel" style={{ textAlign: 'center', padding: '4rem 2rem' }}>
          <Loader2 size={36} className="animate-spin" style={{ color: 'var(--accent-secondary)', margin: '0 auto 1.25rem auto' }} />
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>Checking session...</p>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh', padding: '2rem' }}>
        <div className="glass-panel" style={{ maxWidth: '540px', width: '100%', textAlign: 'center', padding: '4rem 2.5rem' }}>
          <Database size={56} style={{ color: 'var(--accent-secondary)', marginBottom: '1.5rem', opacity: 0.8 }} />
          <h1 style={{ fontSize: '1.8rem', marginBottom: '0.75rem', color: 'var(--text-primary)' }}>Welcome to Socrates</h1>
          <p style={{ color: 'var(--text-secondary)', lineHeight: '1.6', marginBottom: '2rem', fontSize: '0.95rem' }}>
            Discord chatlog download, parsing, and analysis platform. Please sign in with Discord to access backups and curation queues.
          </p>
          <button
            onClick={handleLogin}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.75rem',
              background: 'var(--accent-primary)',
              color: '#fff',
              fontWeight: 600,
              padding: '0.75rem 1.75rem',
              fontSize: '1rem',
              borderRadius: '8px',
              border: 'none',
              cursor: 'pointer',
            }}
          >
            <LogIn size={20} /> Log in with Discord
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', gap: '1.25rem', minHeight: '100vh', position: 'relative' }}>
      {/* Side Menu Navigation */}
      <Sidebar
        user={user}
        backups={backups}
        selectedBackupId={selectedBackupId}
        onSelectBackup={id => setSelectedBackupId(id)}
        activeTab={activeTab}
        onSelectTab={tab => setActiveTab(tab)}
        curationSummary={curationSummary}
        backupInfo={backupInfo}
        onNewBackup={() => setActiveTab('new_backup')}
        onLogout={handleLogout}
      />

      {/* Main Content View Area */}
      <main style={{ flex: 1, minWidth: 0, paddingBottom: '2rem' }}>
        {backupInfo?.is_schema_outdated && (
          <div
            style={{
              marginBottom: '1.25rem',
              padding: '1rem 1.25rem',
              backgroundColor: 'rgba(239, 68, 68, 0.15)',
              border: '1px solid var(--danger)',
              borderRadius: '8px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '1rem',
              flexWrap: 'wrap',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', color: 'var(--text-primary)' }}>
              <AlertTriangle size={24} style={{ color: 'var(--danger)', flexShrink: 0 }} />
              <div>
                <strong>Database schema is outdated:</strong> Backup database is schema v{backupInfo.schema_version ?? 0}, but the application requires v{backupInfo.current_schema_version ?? 2}. Please upgrade the database.
              </div>
            </div>
            <button
              onClick={handleUpgradeDatabase}
              disabled={isUpgrading}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.5rem',
                backgroundColor: 'var(--danger)',
                color: '#fff',
                border: 'none',
                padding: '0.5rem 1rem',
                borderRadius: '6px',
                fontWeight: 600,
                cursor: isUpgrading ? 'not-allowed' : 'pointer',
                opacity: isUpgrading ? 0.7 : 1,
              }}
            >
              {isUpgrading && <Loader2 size={16} className="animate-spin" />}
              {isUpgrading ? 'Upgrading Database...' : 'Upgrade Database Now'}
            </button>
          </div>
        )}
        <ErrorBoundary fallbackTab={() => setActiveTab('status')}>
          {activeTab === 'new_backup' && (
            <NewBackupTab
              user={user}
              onStart={() => {
                setTimeout(() => {
                  api
                    .getBackups()
                    .then(data => {
                      if (Array.isArray(data)) setBackups(data);
                    })
                    .catch(console.error);
                }, 1000);
                setActiveTab('status');
              }}
              onCancel={() => setActiveTab('status')}
            />
          )}

          {activeTab === 'status' && (
            <StatusTab
              backupId={selectedBackupId}
              setTab={t => setActiveTab(t)}
              curationSummary={curationSummary}
            />
          )}

          {activeTab === 'run' && selectedBackupId && <RunTab backupId={selectedBackupId} onRefreshSummary={refreshSummary} />}

          {activeTab === 'writers' && selectedBackupId && (
            <WritersTab backupId={selectedBackupId} onRefreshSummary={refreshSummary} />
          )}

          {activeTab === 'characters' && selectedBackupId && (
            <CharactersTab
              backupId={selectedBackupId}
              myWriter={myWriter}
              onNavigateToWriters={() => setActiveTab('writers')}
            />
          )}

          {activeTab === 'scenes' && selectedBackupId && (
            <ScenesTab
              backupId={selectedBackupId}
              myWriter={myWriter}
              onNavigateToWriters={() => setActiveTab('writers')}
            />
          )}

          {activeTab === 'scene_issues' && selectedBackupId && (
            <SceneIssuesTab backupId={selectedBackupId} onRefreshSummary={refreshSummary} />
          )}

          {activeTab === 'flagged_messages' && selectedBackupId && (
            <FlaggedMessagesTab backupId={selectedBackupId} onRefreshSummary={refreshSummary} />
          )}

          {activeTab === 'admin' && <AdminTab onRefreshSummary={refreshSummary} />}
        </ErrorBoundary>
      </main>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/auth/callback" element={<AuthCallback />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;

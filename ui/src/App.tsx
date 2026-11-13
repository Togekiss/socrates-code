import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  useNavigate,
  useSearchParams,
} from 'react-router-dom';
import { api } from './api';
import {
  Database,
  LogIn,
  Loader2,
  AlertCircle,
  AlertTriangle,
  PlusCircle,
} from 'lucide-react';
import { AppShell } from './components/layout/AppShell';
import type { TabType } from './components/Sidebar';
import { StatusTab } from './components/StatusTab';
import { RunTab } from './components/RunTab';
import { WritersTab } from './components/WritersTab';
import { CharactersTab } from './components/CharactersTab';
import { ScenesTab } from './components/ScenesTab';
import { ChatSessionsTab } from './components/ChatSessionsTab';
import { EventsTab } from './components/EventsTab';
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
        if (res.status === 'success') navigate('/', { replace: true });
        else setError('Authentication failed. Please try again.');
      })
      .catch(err => {
        console.error(err);
        setError(err.message || 'Authentication failed or you are not in the required servers.');
      });
  }, [searchParams, navigate]);

  return (
    <div className="login-container">
      <div className="glass-panel login-card">
        {error ? (
          <>
            <AlertCircle size={48} className="text-danger" style={{ marginBottom: '1.25rem' }} />
            <h2 className="login-title">Authentication Failed</h2>
            <p className="login-desc">{error}</p>
            <button
              type="button"
              onClick={() => navigate('/', { replace: true })}
              className="btn btn-secondary"
            >
              Return to Home
            </button>
          </>
        ) : (
          <>
            <div style={{ display: 'inline-flex', marginBottom: '1.5rem' }}>
              <div
                style={{
                  width: '64px',
                  height: '64px',
                  borderRadius: '50%',
                  background: 'var(--accent-subtle)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  border: '1px solid var(--border-color)',
                }}
              >
                <Loader2 size={32} className="animate-spin" style={{ color: 'var(--accent-secondary)' }} />
              </div>
            </div>
            <h2 className="login-title">Authenticating with Discord</h2>
            <p className="login-desc" style={{ marginBottom: 0 }}>
              Verifying server memberships and setting up your session...
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function NewBackupTab({
  user,
  onStart,
  onCancel,
}: {
  user: User;
  onStart: () => void;
  onCancel: () => void;
}) {
  const [globalConfig, setGlobalConfig] = useState<GlobalConfig | null>(null);
  const [selectedServer, setSelectedServer] = useState<string>('');

  useEffect(() => {
    api.getGlobalConfig().then(setGlobalConfig).catch(console.error);
  }, []);

  if (!globalConfig) {
    return (
      <div className="panel-surface login-card" style={{ margin: '2rem auto' }}>
        <Loader2
          size={36}
          className="animate-spin"
          style={{ color: 'var(--accent-secondary)', marginBottom: '1.25rem' }}
        />
        <p className="banner-subtitle">Loading configuration...</p>
      </div>
    );
  }

  // Deduplicate user.authorized_guilds by s.id to prevent duplicate React keys
  const servers = Array.from(
    new Map((user?.authorized_guilds || []).map(g => [String(g.id), g])).values()
  );

  const serverInfo = servers.find(s => s.id === selectedServer);
  const initialConfigForServer =
    selectedServer && serverInfo
      ? {
          ...globalConfig,
          admin: {
            ...((globalConfig.admin as Record<string, unknown>) || {}),
            serverId: serverInfo.id,
            serverName: serverInfo.name,
            categoriesToKeep: [],
            categoriesToIgnore: [],
            dmCategories: [],
          },
        }
      : globalConfig;

  return (
    <div className="flex-col gap-md">
      <div className="glass-panel">
        <h2 style={{ marginTop: 0, color: 'var(--text-primary)', marginBottom: '1.5rem' }}>
          Create a New Backup
        </h2>
        <div style={{ marginBottom: '1.5rem' }}>
          <label
            htmlFor="new-backup-server-select"
            style={{
              display: 'block',
              marginBottom: '0.5rem',
              color: 'var(--text-secondary)',
              fontSize: '0.9rem',
            }}
          >
            Select a Server to Backup
          </label>
          <select
            id="new-backup-server-select"
            name="new_backup_server"
            className="select"
            value={selectedServer}
            onChange={e => setSelectedServer(e.target.value)}
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

function RequireBackup({
  backupId,
  backups,
  onSelectBackup,
  children,
}: {
  backupId: string | null;
  backups: BackupInfo[];
  onSelectBackup: (id: string | null) => void;
  children: React.ReactNode;
}) {
  const navigate = useNavigate();

  if (!backupId) {
    return (
      <div className="empty-state">
        <Database size={48} className="empty-state-icon" />
        <h3 className="empty-state-title">No Backup Selected</h3>
        <p className="empty-state-desc">
          Please select an active backup to explore this section, or create a new backup if you
          have not set one up yet.
        </p>
        {backups.length > 0 ? (
          <div className="flex-row items-center gap-sm">
            <select
              className="select select-sm"
              value=""
              onChange={e => onSelectBackup(e.target.value || null)}
            >
              <option value="">-- Choose a Backup --</option>
              {backups.map(b => {
                const id = b.id || b.backup_id;
                const label = b.name || b.backup_name || b.server_name || id;
                return (
                  <option key={id} value={id}>
                    {label}
                  </option>
                );
              })}
            </select>
          </div>
        ) : (
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => navigate('/backups/new')}
          >
            <PlusCircle size={16} /> Create New Backup
          </button>
        )}
      </div>
    );
  }

  return <>{children}</>;
}

function AppContent() {
  const navigate = useNavigate();

  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [selectedBackupId, setSelectedBackupId] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [isLoadingAuth, setIsLoadingAuth] = useState<boolean>(true);
  const [curationSummary, setCurationSummary] = useState<CurationSummary | null>(null);
  const [backupInfo, setBackupInfo] = useState<BackupInfo | null>(null);
  const [backupError, setBackupError] = useState<string | null>(null);
  const [isLoadingBackup, setIsLoadingBackup] = useState<boolean>(false);
  const [myWriter, setMyWriter] = useState<MyWriter | null>(null);
  const [isUpgrading, setIsUpgrading] = useState(false);
  const [statusPollTick, setStatusPollTick] = useState(0);
  const activeBackupIdRef = useRef<string | null>(selectedBackupId);
  const lastLoadedBackupIdRef = useRef<string | null>(null);
  const statusPollInFlightRef = useRef(false);
  const wasBackupRunningRef = useRef(false);

  useEffect(() => {
    activeBackupIdRef.current = selectedBackupId;
    wasBackupRunningRef.current = false;
    statusPollInFlightRef.current = false;
  }, [selectedBackupId]);

  const handleSelectBackup = useCallback((id: string | null) => {
    activeBackupIdRef.current = id;
    setSelectedBackupId(id);
    if (id) {
      sessionStorage.setItem('socrates_selected_backup', id);
    } else {
      sessionStorage.removeItem('socrates_selected_backup');
    }
  }, []);

  const refreshSummary = useCallback(() => {
    const targetId = selectedBackupId;
    if (!targetId) {
      lastLoadedBackupIdRef.current = null;
      setCurationSummary(null);
      setBackupInfo(null);
      setBackupError(null);
      setIsLoadingBackup(false);
      setMyWriter(null);
      return;
    }

    const isBackupSwitch = lastLoadedBackupIdRef.current !== targetId;
    if (isBackupSwitch) {
      lastLoadedBackupIdRef.current = targetId;
      setCurationSummary(null);
      setBackupInfo(null);
      setBackupError(null);
      setMyWriter(null);
      setIsLoadingBackup(true);
    }

    let infoErrorMsg: string | null = null;

    Promise.all([
      api.getCurationSummary(targetId).catch(() => null),
      api.getBackupInfo(targetId).catch((err: unknown) => {
        infoErrorMsg =
          err && typeof err === 'object' && 'message' in err && typeof (err as Error).message === 'string'
            ? (err as Error).message
            : 'Failed to load backup state.';
        return null;
      }),
      api.getMyWriter(targetId).catch(() => null),
    ]).then(([summaryRes, infoRes, writerRes]) => {
      if (activeBackupIdRef.current !== targetId) return;
      setCurationSummary(summaryRes);
      setBackupInfo(infoRes);
      setBackupError(infoRes ? null : infoErrorMsg);
      setMyWriter(writerRes);
      setIsLoadingBackup(false);
    });
  }, [selectedBackupId]);

  const handleBackupInfoChange = useCallback(
    (updatedInfo: BackupInfo) => {
      if (activeBackupIdRef.current === selectedBackupId) {
        setBackupInfo(updatedInfo);
        setBackupError(null);
      }
    },
    [selectedBackupId]
  );

  const pollBackupStatus = useCallback(() => {
    const targetId = activeBackupIdRef.current;
    if (!targetId || statusPollInFlightRef.current) return;

    statusPollInFlightRef.current = true;
    api
      .getBackupInfo(targetId)
      .then(infoRes => {
        if (activeBackupIdRef.current !== targetId) return;
        setBackupInfo(infoRes);
        setBackupError(null);
        setStatusPollTick(prev => prev + 1);
      })
      .catch(err => {
        // Keep previous backupInfo intact on transient 429/network errors
        console.warn('Lightweight backup status poll failed:', err);
      })
      .finally(() => {
        statusPollInFlightRef.current = false;
      });
  }, []);

  const isBackupRunning = Boolean(
    backupInfo &&
      (backupInfo.status === 'pending' ||
        backupInfo.status === 'running' ||
        Object.values(backupInfo.steps ?? {}).some(s => s === 'running'))
  );

  // Guard against closing/reloading browser tab while a Cloud Run pipeline step is executing
  useEffect(() => {
    if (!isBackupRunning && !isUpgrading) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [isBackupRunning, isUpgrading]);

  useEffect(() => {
    if (!selectedBackupId) {
      wasBackupRunningRef.current = false;
      return;
    }

    if (isBackupRunning) {
      wasBackupRunningRef.current = true;
      const interval = setInterval(() => {
        pollBackupStatus();
      }, 3000);
      return () => clearInterval(interval);
    }

    if (wasBackupRunningRef.current) {
      wasBackupRunningRef.current = false;
      refreshSummary();
    }
  }, [selectedBackupId, isBackupRunning, pollBackupStatus, refreshSummary]);

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

  // Initial user authentication and backup validation guard
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

              // Strictly validate stored backup ID against authorized backups
              const storedId = sessionStorage.getItem('socrates_selected_backup');
              const isValidStored = storedId && list.some(b => (b.id || b.backup_id) === storedId);

              if (isValidStored) {
                setSelectedBackupId(storedId);
              } else if (list.length > 0) {
                const fallbackId = list[0].id || list[0].backup_id || null;
                setSelectedBackupId(fallbackId);
                if (fallbackId) {
                  sessionStorage.setItem('socrates_selected_backup', fallbackId);
                }
              } else {
                setSelectedBackupId(null);
                sessionStorage.removeItem('socrates_selected_backup');
              }
            })
            .catch(console.error);
        } else {
          setUser(null);
          setBackups([]);
          setSelectedBackupId(null);
          sessionStorage.removeItem('socrates_selected_backup');
        }
      })
      .catch(() => {
        setUser(null);
        setBackups([]);
        setSelectedBackupId(null);
        sessionStorage.removeItem('socrates_selected_backup');
      })
      .finally(() => setIsLoadingAuth(false));
  }, []);

  const handleLogin = () => {
    api.getLoginUrl().then(res => res.url && (window.location.href = res.url)).catch(console.error);
  };

  const handleDevLogin = () => {
    setIsLoadingAuth(true);
    api
      .devLogin()
      .then(res => {
        if (res && res.user) {
          setUser(res.user);
          window.location.reload();
        }
      })
      .catch(console.error)
      .finally(() => setIsLoadingAuth(false));
  };

  const handleLogout = () => {
    api
      .logout()
      .then(() => {
        setUser(null);
        setBackups([]);
        setSelectedBackupId(null);
        sessionStorage.removeItem('socrates_selected_backup');
        setCurationSummary(null);
        setBackupInfo(null);
        setMyWriter(null);
      })
      .catch(console.error);
  };

  // Map legacy TabType to new router URL paths
  const handleNavigateTab = (tab: TabType) => {
    const pathToTab: Record<TabType, string> = {
      status: '/',
      run: '/system/pipeline',
      writers: '/writers',
      characters: '/characters',
      scenes: '/scenes',
      chat_sessions: '/sessions',
      events: '/events',
      scene_issues: '/curation/issues',
      flagged_messages: '/curation/flagged',
      admin: '/system/admin',
      new_backup: '/backups/new',
    };
    navigate(pathToTab[tab] || '/');
  };

  // 1. Loading screen guard
  if (isLoadingAuth) {
    return (
      <div className="loading-screen">
        <div className="panel-surface login-card">
          <Loader2
            size={36}
            className="animate-spin"
            style={{ color: 'var(--accent-secondary)', marginBottom: '1.25rem' }}
          />
          <p className="banner-subtitle">Checking session...</p>
        </div>
      </div>
    );
  }

  // 3. Login gate: unauthenticated users cannot access any protected view
  if (!user) {
    return (
      <div className="login-container">
        <div className="glass-panel login-card">
          <Database
            size={56}
            style={{ color: 'var(--accent-secondary)', marginBottom: '1.5rem', opacity: 0.8 }}
          />
          <h1 className="login-title">Welcome to Socrates</h1>
          <p className="login-desc">
            Discord chatlog download, parsing, and analysis platform. Please sign in with Discord to
            access backups and curation queues.
          </p>
          <div className="flex-col items-center gap-sm">
            <button
              type="button"
              onClick={handleLogin}
              className="btn btn-primary"
            >
              <LogIn size={20} /> Log in with Discord
            </button>
            {import.meta.env.DEV && (
              <button
                type="button"
                onClick={handleDevLogin}
                className="btn btn-secondary btn-sm"
              >
                Dev Login (Localhost)
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // 4. Authenticated application shell with full URL routing
  return (
    <AppShell
      user={user}
      backups={backups}
      selectedBackupId={selectedBackupId}
      onSelectBackup={handleSelectBackup}
      curationSummary={curationSummary}
      backupInfo={backupInfo}
      onLogout={handleLogout}
      onNewBackup={() => navigate('/backups/new')}
    >
      {backupInfo?.is_schema_outdated && (
        <div className="banner-danger">
          <div className="banner-content">
            <AlertTriangle size={22} className="flex-shrink-0" />
            <div>
              <strong>Database schema is outdated:</strong> Backup database is schema v
              {backupInfo.schema_version ?? 0}, but the application requires v
              {backupInfo.current_schema_version ?? 5}. Please upgrade the database.
            </div>
          </div>
          <button
            type="button"
            className="btn btn-danger btn-sm"
            onClick={handleUpgradeDatabase}
            disabled={isUpgrading}
          >
            {isUpgrading && <Loader2 size={16} className="animate-spin" />}
            {isUpgrading ? 'Upgrading Database...' : 'Upgrade Database Now'}
          </button>
        </div>
      )}

      <ErrorBoundary fallbackTab={() => navigate('/')}>
        <Routes>
          <Route
            path="/"
            element={
              <RequireBackup
                backupId={selectedBackupId}
                backups={backups}
                onSelectBackup={handleSelectBackup}
              >
                <StatusTab
                  backupId={selectedBackupId}
                  setTab={handleNavigateTab}
                  curationSummary={curationSummary}
                  backupInfo={backupInfo}
                  backupError={backupError}
                  isLoading={isLoadingBackup}
                  onUpgrade={handleUpgradeDatabase}
                  isUpgrading={isUpgrading}
                />
              </RequireBackup>
            }
          />
          <Route path="/status" element={<Navigate to="/" replace />} />
          <Route
            path="/characters"
            element={
              <RequireBackup
                backupId={selectedBackupId}
                backups={backups}
                onSelectBackup={handleSelectBackup}
              >
                <CharactersTab
                  backupId={selectedBackupId!}
                  backupInfo={backupInfo}
                  backupError={backupError}
                  backupLoading={isLoadingBackup}
                  myWriter={myWriter}
                  onNavigateToWriters={() => navigate('/writers')}
                />
              </RequireBackup>
            }
          />
          <Route
            path="/writers"
            element={
              <RequireBackup
                backupId={selectedBackupId}
                backups={backups}
                onSelectBackup={handleSelectBackup}
              >
                <WritersTab
                  backupId={selectedBackupId!}
                  backupInfo={backupInfo}
                  backupError={backupError}
                  backupLoading={isLoadingBackup}
                  onRefreshSummary={refreshSummary}
                />
              </RequireBackup>
            }
          />
          <Route
            path="/scenes"
            element={
              <RequireBackup
                backupId={selectedBackupId}
                backups={backups}
                onSelectBackup={handleSelectBackup}
              >
                <ScenesTab
                  backupId={selectedBackupId!}
                  backupInfo={backupInfo}
                  backupError={backupError}
                  backupLoading={isLoadingBackup}
                  myWriter={myWriter}
                  onNavigateToWriters={() => navigate('/writers')}
                />
              </RequireBackup>
            }
          />
          <Route
            path="/sessions"
            element={
              <RequireBackup
                backupId={selectedBackupId}
                backups={backups}
                onSelectBackup={handleSelectBackup}
              >
                <ChatSessionsTab
                  backupId={selectedBackupId!}
                  backupInfo={backupInfo}
                  backupError={backupError}
                  backupLoading={isLoadingBackup}
                  myWriter={myWriter}
                  onNavigateToWriters={() => navigate('/writers')}
                />
              </RequireBackup>
            }
          />
          <Route
            path="/events"
            element={
              <RequireBackup
                backupId={selectedBackupId}
                backups={backups}
                onSelectBackup={handleSelectBackup}
              >
                <EventsTab
                  backupId={selectedBackupId!}
                  backupInfo={backupInfo}
                  backupError={backupError}
                  backupLoading={isLoadingBackup}
                  myWriter={myWriter}
                  onNavigateToWriters={() => navigate('/writers')}
                  onRefreshSummary={refreshSummary}
                />
              </RequireBackup>
            }
          />
          <Route
            path="/curation/issues"
            element={
              <RequireBackup
                backupId={selectedBackupId}
                backups={backups}
                onSelectBackup={handleSelectBackup}
              >
                <SceneIssuesTab
                  backupId={selectedBackupId!}
                  backupInfo={backupInfo}
                  backupError={backupError}
                  backupLoading={isLoadingBackup}
                  onRefreshSummary={refreshSummary}
                />
              </RequireBackup>
            }
          />
          <Route
            path="/curation/flagged"
            element={
              <RequireBackup
                backupId={selectedBackupId}
                backups={backups}
                onSelectBackup={handleSelectBackup}
              >
                <FlaggedMessagesTab
                  backupId={selectedBackupId!}
                  backupInfo={backupInfo}
                  backupError={backupError}
                  backupLoading={isLoadingBackup}
                  onRefreshSummary={refreshSummary}
                />
              </RequireBackup>
            }
          />
          <Route
            path="/system/pipeline"
            element={
              <RequireBackup
                backupId={selectedBackupId}
                backups={backups}
                onSelectBackup={handleSelectBackup}
              >
                <RunTab
                  backupId={selectedBackupId!}
                  backupInfo={backupInfo}
                  statusPollTick={statusPollTick}
                  onPollStatus={pollBackupStatus}
                  onRefreshSummary={refreshSummary}
                  onBackupInfoChange={handleBackupInfoChange}
                />
              </RequireBackup>
            }
          />
          <Route
            path="/system/admin"
            element={
              user.admin !== false ? (
                <AdminTab onRefreshSummary={refreshSummary} />
              ) : (
                <div className="empty-state">
                  <AlertTriangle
                    size={48}
                    className="empty-state-icon"
                    style={{ color: 'var(--warning)' }}
                  />
                  <h3 className="empty-state-title">Administrator Access Required</h3>
                  <p className="empty-state-desc">
                    You must be an administrator to access system admin operations and global logs.
                  </p>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => navigate('/')}
                  >
                    Return to Status
                  </button>
                </div>
              )
            }
          />
          <Route
            path="/backups/new"
            element={
              <NewBackupTab
                user={user}
                onStart={() => {
                  setTimeout(() => {
                    api
                      .getBackups()
                      .then(data => {
                        if (Array.isArray(data)) {
                          setBackups(data);
                        }
                      })
                      .catch(console.error);
                  }, 1000);
                  navigate('/');
                }}
                onCancel={() => navigate('/')}
              />
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ErrorBoundary>
    </AppShell>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route path="/*" element={<AppContent />} />
      </Routes>
    </BrowserRouter>
  );
}

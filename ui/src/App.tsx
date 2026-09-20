import { useState, useEffect, useRef } from 'react'
import { BrowserRouter, Routes, Route, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from './api'
import { Database, LogIn, LogOut, Loader2, AlertCircle } from 'lucide-react'
import { StatusTab } from './components/StatusTab'
import { CharactersTab } from './components/CharactersTab'
import { ScenesTab } from './components/ScenesTab'
import { AdminTab } from './components/AdminTab'
import { RunTab } from './components/RunTab'
import { BackupForm } from './components/BackupForm'

function AuthCallback() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const hasRequested = useRef(false)

  useEffect(() => {
    const code = searchParams.get('code')
    if (!code) {
      setError('No authorization code provided by Discord.')
      return
    }

    // Prevent double-execution in React StrictMode (OAuth codes are single-use)
    if (hasRequested.current) return
    hasRequested.current = true

    api.authDiscord(code)
      .then(res => {
        if (res.status === 'success') {
          navigate('/', { replace: true })
        } else {
          setError('Authentication failed. Please try again.')
        }
      })
      .catch(err => {
        console.error(err)
        setError(err.message || 'Authentication failed or you are not in the required servers.')
      })
  }, [searchParams, navigate])

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
              style={{ padding: '0.65rem 1.5rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', borderRadius: '6px', color: 'white', fontWeight: 500 }}
            >
              Return to Home
            </button>
          </>
        ) : (
          <>
            <div style={{ display: 'inline-flex', position: 'relative', marginBottom: '1.5rem' }}>
              <div style={{
                width: '64px',
                height: '64px',
                borderRadius: '50%',
                background: 'rgba(109, 40, 217, 0.15)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                border: '1px solid var(--border-color)'
              }}>
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
  )
}

function NewBackupTab({ user, onStart, onCancel }: { user: any, onStart: () => void, onCancel: () => void }) {
  const [globalConfig, setGlobalConfig] = useState<any>(null);
  const [selectedServer, setSelectedServer] = useState<string>('');

  useEffect(() => {
    api.getGlobalConfig().then(res => setGlobalConfig(res)).catch(console.error);
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
  const serverInfo = servers.find((s: any) => s.id === selectedServer);

  const initialConfigForServer = selectedServer && serverInfo ? {
    ...globalConfig,
    admin: {
      ...globalConfig.admin,
      serverId: serverInfo.id,
      serverName: serverInfo.name,
      categoriesToKeep: [],
      categoriesToIgnore: [],
      dmCategories: []
    }
  } : globalConfig;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      <div className="glass-panel">
        <h2 style={{ marginTop: 0, color: 'var(--text-primary)', marginBottom: '1.5rem' }}>Create a New Backup</h2>
        
        <div style={{ marginBottom: '2rem' }}>
          <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>Select a Server to Backup</label>
          <select
            value={selectedServer}
            onChange={e => setSelectedServer(e.target.value)}
            style={{ width: '100%', padding: '0.75rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px', fontSize: '1rem' }}
          >
            <option value="">-- Select a Server --</option>
            {servers.map((s: any) => (
              <option key={s.id} value={s.id}>{s.name}</option>
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
  const [activeTab, setActiveTab] = useState<'status' | 'characters' | 'scenes' | 'run' | 'admin' | 'new_backup'>('status')
  const [backups, setBackups] = useState<any[]>([])
  const [selectedBackupId, setSelectedBackupId] = useState<string | null>(null)
  const [user, setUser] = useState<any>(null)
  const [isLoadingAuth, setIsLoadingAuth] = useState<boolean>(true)

  useEffect(() => {
    // Check if user is logged in
    api.getMe()
      .then(res => {
        if (res && res.user) {
          setUser(res.user)
          // Fetch backups only after authentication is confirmed
          api.getBackups()
            .then(data => {
              if (Array.isArray(data)) {
                setBackups(data)
              } else {
                setBackups([])
              }
            })
            .catch(console.error)
        } else {
          setUser(null)
          setBackups([])
        }
      })
      .catch(() => {
        // Not logged in, that's fine
        setUser(null)
        setBackups([])
      })
      .finally(() => {
        setIsLoadingAuth(false)
      })
  }, [])

  const handleLogin = () => {
    api.getLoginUrl().then(res => {
      if (res.url) {
        window.location.href = res.url
      }
    }).catch(console.error)
  }

  const handleLogout = () => {
    api.logout().then(() => {
      setUser(null)
      setBackups([])
      setSelectedBackupId(null)
    }).catch(console.error)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', gap: '1rem' }}>
      
      {/* Top Navigation Bar */}
      <div className="glass-panel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '1rem 2rem', borderRadius: 0, borderTop: 'none', borderLeft: 'none', borderRight: 'none' }}>
        <h1 style={{ fontSize: '1.5rem', margin: 0, color: 'var(--accent-secondary)' }}>Socrates</h1>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '2rem' }}>
          
          {/* Backup Selector */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Database size={18} color="var(--text-secondary)" />
            <select 
              value={selectedBackupId || ''}
              onChange={e => {
                setSelectedBackupId(e.target.value || null)
                setActiveTab('status')
              }}
              disabled={!user || backups.length === 0}
              style={{ 
                background: 'var(--bg-tertiary)', 
                border: '1px solid var(--border-color)', 
                color: 'white', 
                padding: '0.5rem 1rem', 
                borderRadius: '4px', 
                fontSize: '0.95rem', 
                minWidth: '200px',
                opacity: !user ? 0.6 : 1,
                cursor: !user ? 'not-allowed' : 'pointer'
              }}
            >
              <option value="">
                {!user ? 'Log in to view backups...' : backups.length === 0 ? 'No backups available' : 'Select a backup...'}
              </option>
              {Array.isArray(backups) && backups.map(b => (
                <option key={b.backup_id} value={b.backup_id}>
                  {b.backup_name}
                </option>
              ))}
            </select>
            {user && (
              <button 
                onClick={() => {
                  setSelectedBackupId(null)
                  setActiveTab('new_backup')
                }}
                style={{ padding: '0.5rem 1rem', background: 'var(--bg-tertiary)', color: 'var(--text-primary)', border: '1px solid var(--border-color)', borderRadius: '4px', cursor: 'pointer', fontSize: '0.95rem', whiteSpace: 'nowrap' }}
              >
                + New backup
              </button>
            )}
          </div>

          {user ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                {user.avatar && (
                  <img src={`https://cdn.discordapp.com/avatars/${user.sub}/${user.avatar}.png`} alt="avatar" style={{ width: '32px', height: '32px', borderRadius: '50%' }} />
                )}
                <span style={{ fontWeight: 'bold' }}>{user.username}</span>
              </div>
              <button onClick={handleLogout} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'transparent', border: '1px solid var(--border-color)', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                <LogOut size={16} /> Logout
              </button>
            </div>
          ) : (
            <button onClick={handleLogin} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'var(--accent-primary)', color: '#000', fontWeight: 'bold', cursor: 'pointer' }}>
              <LogIn size={16} /> Log in
            </button>
          )}
        </div>
      </div>

      {/* Main Content Area */}
      <div style={{ flex: 1, maxWidth: '1200px', margin: '0 auto', width: '100%', padding: '2rem' }}>
        
        {isLoadingAuth ? (
          <div className="glass-panel" style={{ textAlign: 'center', padding: '4rem 2rem', marginTop: '2rem' }}>
            <Loader2 size={36} className="animate-spin" style={{ color: 'var(--accent-secondary)', margin: '0 auto 1.25rem auto' }} />
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>Checking session...</p>
          </div>
        ) : !user ? (
          <div className="glass-panel" style={{ textAlign: 'center', padding: '4rem 2rem', marginTop: '2rem' }}>
            <Database size={56} style={{ color: 'var(--accent-secondary)', marginBottom: '1.5rem', opacity: 0.8 }} />
            <h2 style={{ fontSize: '1.8rem', marginBottom: '1rem', color: 'var(--accent-secondary)' }}>Welcome to Socrates</h2>
            <p style={{ color: 'var(--text-secondary)', maxWidth: '520px', margin: '0 auto 2rem auto', lineHeight: '1.6' }}>
              Discord chatlog download, parsing, and analysis tool. Please sign in with Discord to view and manage backups for your authorized servers.
            </p>
            <button 
              onClick={handleLogin} 
              style={{ 
                display: 'inline-flex', 
                alignItems: 'center', 
                gap: '0.75rem', 
                background: 'var(--accent-primary)', 
                color: '#000', 
                fontWeight: 'bold', 
                padding: '0.75rem 1.75rem', 
                fontSize: '1rem', 
                borderRadius: '6px',
                border: 'none',
                cursor: 'pointer'
              }}
            >
              <LogIn size={20} /> Log in with Discord
            </button>
          </div>
        ) : (
          <>
            {/* Tabs */}
            {selectedBackupId && (
              <div style={{ display: 'flex', gap: '1rem', marginBottom: '2rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '1rem' }}>
                {['status', 'characters', 'scenes', 'run', 'admin'].map(tab => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab as any)}
                    style={{
                      background: activeTab === tab ? 'var(--bg-secondary)' : 'transparent',
                      border: 'none',
                      borderBottom: activeTab === tab ? '2px solid var(--accent-primary)' : '2px solid transparent',
                      borderRadius: '4px 4px 0 0',
                      padding: '0.5rem 1.5rem',
                      textTransform: 'capitalize',
                      fontSize: '1.05rem',
                      color: activeTab === tab ? 'var(--text-primary)' : 'var(--text-secondary)',
                      cursor: 'pointer'
                    }}
                  >
                    {tab}
                  </button>
                ))}
              </div>
            )}

            {/* Tab Content */}
            {activeTab === 'new_backup' && (
              <NewBackupTab 
                user={user} 
                onStart={() => {
                  // Reload backups list after a second and switch back to status
                  setTimeout(() => {
                    api.getBackups().then(data => {
                      if (Array.isArray(data)) setBackups(data);
                    }).catch(console.error);
                  }, 1000);
                  setActiveTab('status');
                }}
                onCancel={() => setActiveTab('status')}
              />
            )}
            {activeTab === 'status' && (!selectedBackupId ? (
              <div className="glass-panel" style={{ textAlign: 'center', padding: '4rem 2rem' }}>
                <p style={{ color: 'var(--text-secondary)' }}>Select a backup from the top menu or create a new one.</p>
              </div>
            ) : (
              <StatusTab backupId={selectedBackupId} setTab={(t) => setActiveTab(t as any)} />
            ))}
            {activeTab === 'characters' && selectedBackupId && <CharactersTab backupId={selectedBackupId} />}
            {activeTab === 'scenes' && selectedBackupId && <ScenesTab backupId={selectedBackupId} />}
            {activeTab === 'run' && selectedBackupId && <RunTab backupId={selectedBackupId} />}
            {activeTab === 'admin' && selectedBackupId && <AdminTab />}
          </>
        )}

      </div>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/auth/callback" element={<AuthCallback />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App

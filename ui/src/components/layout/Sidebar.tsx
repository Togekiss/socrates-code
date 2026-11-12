import React, { useState, useEffect } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import {
  Database,
  Users,
  UserCheck,
  Film,
  MessageSquare,
  Calendar,
  AlertTriangle,
  MessageSquareCode,
  PlayCircle,
  Settings,
  PlusCircle,
  Plus,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Sun,
  Moon,
  Loader2,
  X,
} from 'lucide-react';
import type { BackupInfo, CurationSummary, User } from '../../types';

export interface SidebarProps {
  user: User | null;
  backups: BackupInfo[];
  selectedBackupId: string | null;
  onSelectBackup: (id: string | null) => void;
  curationSummary: CurationSummary | null;
  backupInfo: BackupInfo | null;
  onNewBackup?: () => void;
  onLogout: () => void;
  mobileOpen?: boolean;
  onCloseMobile?: () => void;
  activeTab?: string;
  onSelectTab?: (tab: string) => void;
}

interface NavItem {
  id: string;
  label: string;
  path: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  badge?: string | number | null;
  badgeVariant?: 'warning' | 'accent' | 'danger' | 'success';
  isPulsing?: boolean;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

function getBackupInitials(name?: string | null): string {
  if (!name) return '--';
  const trimmed = name.trim();
  const words = trimmed.split(/[\s-_]+/);
  if (words.length >= 2 && words[0].length > 0 && words[1].length > 0) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  return trimmed.slice(0, 2).toUpperCase();
}

export const Sidebar: React.FC<SidebarProps> = ({
  user,
  backups,
  selectedBackupId,
  onSelectBackup,
  curationSummary,
  backupInfo,
  onNewBackup,
  onLogout,
  mobileOpen = false,
  onCloseMobile,
}) => {
  const navigate = useNavigate();

  const [collapsed, setCollapsed] = useState<boolean>(() => {
    return localStorage.getItem('socrates_sidebar_collapsed') === 'true';
  });

  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const saved = localStorage.getItem('socrates_theme');
    return saved === 'light' ? 'light' : 'dark';
  });

  useEffect(() => {
    if (theme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem('socrates_theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => (prev === 'light' ? 'dark' : 'light'));
  };

  const toggleCollapsed = () => {
    setCollapsed(prev => {
      const next = !prev;
      localStorage.setItem('socrates_sidebar_collapsed', String(next));
      return next;
    });
  };

  const isAnyRunning =
    backupInfo?.status === 'running' ||
    Object.values(backupInfo?.steps || {}).some(s => s === 'running');

  // 5 Confirmed Navigation Groups (Roster BEFORE Archive!)
  const navGroups: NavGroup[] = [
    {
      title: 'Overview',
      items: [
        {
          id: 'status',
          label: 'Status',
          path: '/status',
          icon: Database,
        },
      ],
    },
    {
      title: 'Roster',
      items: [
        {
          id: 'characters',
          label: 'Characters',
          path: '/characters',
          icon: Users,
          badge: (curationSummary?.unassigned_characters ?? 0) > 0 ? curationSummary?.unassigned_characters : null,
          badgeVariant: 'warning',
        },
        {
          id: 'writers',
          label: 'Writers',
          path: '/writers',
          icon: UserCheck,
          badge: (curationSummary?.link_suggestions ?? 0) > 0 ? curationSummary?.link_suggestions : null,
          badgeVariant: 'accent',
        },
      ],
    },
    {
      title: 'Archive',
      items: [
        {
          id: 'scenes',
          label: 'Scenes',
          path: '/scenes',
          icon: Film,
        },
        {
          id: 'sessions',
          label: 'Chat Sessions',
          path: '/sessions',
          icon: MessageSquare,
        },
        {
          id: 'events',
          label: 'Events',
          path: '/events',
          icon: Calendar,
        },
      ],
    },
    {
      title: 'Curation',
      items: [
        {
          id: 'scene_issues',
          label: 'Scene Issues',
          path: '/curation/issues',
          icon: AlertTriangle,
          badge: (curationSummary?.unresolved_issues ?? 0) > 0 ? curationSummary?.unresolved_issues : null,
          badgeVariant: 'danger',
        },
        {
          id: 'flagged_messages',
          label: 'Flagged Messages',
          path: '/curation/flagged',
          icon: MessageSquareCode,
          badge: (curationSummary?.flagged_messages ?? 0) > 0 ? curationSummary?.flagged_messages : null,
          badgeVariant: 'warning',
        },
      ],
    },
    {
      title: 'System',
      items: [
        {
          id: 'pipeline',
          label: 'Pipeline & Run',
          path: '/system/pipeline',
          icon: PlayCircle,
          badge: isAnyRunning ? 'Running' : null,
          badgeVariant: 'success',
          isPulsing: isAnyRunning,
        },
        {
          id: 'admin',
          label: 'Admin & Logs',
          path: '/system/admin',
          icon: Settings,
        },
      ],
    },
  ];

  const activeBackup = backups.find(b => (b.id || b.backup_id) === selectedBackupId);
  const activeBackupName = activeBackup
    ? activeBackup.name || activeBackup.backup_name || activeBackup.server_name || activeBackup.id
    : '';
  const activeBackupInitials = getBackupInitials(activeBackupName);

  const handleNavLinkClick = () => {
    if (onCloseMobile) {
      onCloseMobile();
    }
  };

  const handleCreateNewBackup = () => {
    if (onNewBackup) {
      onNewBackup();
    } else {
      navigate('/backups/new');
    }
    if (onCloseMobile) {
      onCloseMobile();
    }
  };

  return (
    <aside
      className={`app-sidebar ${collapsed ? 'is-collapsed' : ''} ${mobileOpen ? 'is-open' : ''}`}
      aria-label="Sidebar navigation"
    >
      {/* Sidebar Header: Brand & Collapse Toggle */}
      <div className="sidebar-header">
        {!collapsed && (
          <NavLink to="/status" className="sidebar-brand" onClick={handleNavLinkClick}>
            <span>Socrates</span>
          </NavLink>
        )}
        <div className="flex-row items-center gap-xs">
          {/* Mobile close button (only visible when mobileOpen is active) */}
          {mobileOpen && (
            <button
              type="button"
              className="btn btn-ghost btn-icon btn-sm"
              onClick={onCloseMobile}
              title="Close sidebar"
              aria-label="Close sidebar"
            >
              <X size={18} />
            </button>
          )}
          {/* Desktop collapse rail toggle */}
          <button
            type="button"
            className="btn btn-ghost btn-icon btn-sm desktop-only-collapse-btn"
            onClick={toggleCollapsed}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </button>
        </div>
      </div>

      {/* Active Backup Header Section */}
      <div className="sidebar-backup-section">
        {collapsed ? (
          <>
            <div
              className="sidebar-backup-badge"
              title={activeBackupName ? `Active Backup: ${activeBackupName}` : 'No backup selected'}
            >
              {activeBackupInitials}
            </div>
            {user && (
              <button
                type="button"
                className="btn btn-ghost btn-icon btn-sm"
                onClick={handleCreateNewBackup}
                title="Create New Backup"
                aria-label="Create New Backup"
              >
                <Plus size={16} />
              </button>
            )}
          </>
        ) : (
          <>
            <label htmlFor="active-backup-select" className="sidebar-backup-label">
              Active Backup
            </label>
            <select
              id="active-backup-select"
              name="active_backup"
              className="select select-sm"
              value={selectedBackupId || ''}
              onChange={e => {
                onSelectBackup(e.target.value || null);
                if (onCloseMobile) onCloseMobile();
              }}
              disabled={!user || backups.length === 0}
            >
              <option value="">
                {!user ? 'Log in to select...' : backups.length === 0 ? 'No backups found' : '-- Select Backup --'}
              </option>
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
            {user && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleCreateNewBackup}
              >
                <PlusCircle size={14} /> New Backup
              </button>
            )}
          </>
        )}
      </div>

      {/* Navigation Groups */}
      <nav className="sidebar-nav">
        {navGroups.map((group, groupIdx) => (
          <React.Fragment key={group.title}>
            {collapsed && groupIdx > 0 && (
              <div className="sidebar-group-separator" aria-hidden="true" />
            )}
            <div className="sidebar-group">
              {!collapsed && <div className="sidebar-group-title">{group.title}</div>}
              <div className="sidebar-group-items">
                {group.items.map(item => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.id}
                    to={item.path}
                    className={({ isActive }) =>
                      `sidebar-nav-item ${isActive ? 'is-active' : ''}`
                    }
                    title={item.label}
                    onClick={handleNavLinkClick}
                  >
                    <div className="sidebar-nav-item-left">
                      <div className="sidebar-nav-icon-wrapper">
                        <Icon size={18} className="flex-shrink-0" />
                        {collapsed && item.badge != null && (
                          <span
                            className={`sidebar-nav-dot sidebar-nav-dot--${item.badgeVariant || 'accent'}`}
                            title={`${item.label}: ${item.badge}`}
                          />
                        )}
                      </div>
                      {!collapsed && <span className="sidebar-nav-label">{item.label}</span>}
                    </div>

                    {!collapsed && item.badge != null && (
                      <span
                        className={`badge badge-${item.badgeVariant || 'neutral'} sidebar-nav-badge`}
                        data-sidebar-badge
                      >
                        {item.isPulsing && <Loader2 size={10} className="animate-spin" />}
                        {item.badge}
                      </span>
                    )}
                  </NavLink>
                );
              })}
            </div>
          </div>
        </React.Fragment>
      ))}
      </nav>

      {/* Footer Controls: Theme Switch, User Profile & Logout */}
      <div className="sidebar-footer">
        {collapsed ? (
          <>
            <button
              type="button"
              className="btn btn-ghost btn-icon btn-sm"
              onClick={toggleTheme}
              title={theme === 'light' ? 'Switch to Dark Mode' : 'Switch to Light Mode'}
              aria-label={theme === 'light' ? 'Switch to Dark Mode' : 'Switch to Light Mode'}
            >
              {theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}
            </button>
            {user && (
              <>
                {user.avatar ? (
                  <img
                    src={`https://cdn.discordapp.com/avatars/${user.sub || user.id}/${user.avatar}.png`}
                    alt={user.username}
                    className="sidebar-avatar"
                    title={user.username}
                  />
                ) : (
                  <div className="sidebar-avatar-fallback" title={user.username}>
                    {user.username.charAt(0).toUpperCase()}
                  </div>
                )}
                <button
                  type="button"
                  className="btn btn-ghost btn-icon btn-sm"
                  onClick={onLogout}
                  title="Logout"
                  aria-label="Logout"
                >
                  <LogOut size={16} />
                </button>
              </>
            )}
          </>
        ) : (
          <>
            {user ? (
              <div className="sidebar-footer-row">
                <div className="sidebar-user">
                  {user.avatar ? (
                    <img
                      src={`https://cdn.discordapp.com/avatars/${user.sub || user.id}/${user.avatar}.png`}
                      alt={user.username}
                      className="sidebar-avatar"
                    />
                  ) : (
                    <div className="sidebar-avatar-fallback">
                      {user.username.charAt(0).toUpperCase()}
                    </div>
                  )}
                  <span className="sidebar-username">{user.username}</span>
                </div>
                <div className="flex-row items-center gap-xs">
                  <button
                    type="button"
                    className="btn btn-ghost btn-icon btn-sm"
                    onClick={toggleTheme}
                    title={theme === 'light' ? 'Switch to Dark Mode' : 'Switch to Light Mode'}
                    aria-label={theme === 'light' ? 'Switch to Dark Mode' : 'Switch to Light Mode'}
                  >
                    {theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-icon btn-sm"
                    onClick={onLogout}
                    title="Logout"
                    aria-label="Logout"
                  >
                    <LogOut size={16} />
                  </button>
                </div>
              </div>
            ) : (
              <div className="sidebar-footer-row">
                <span className="sidebar-backup-label">Theme</span>
                <button
                  type="button"
                  className="btn btn-ghost btn-icon btn-sm"
                  onClick={toggleTheme}
                  title={theme === 'light' ? 'Switch to Dark Mode' : 'Switch to Light Mode'}
                  aria-label={theme === 'light' ? 'Switch to Dark Mode' : 'Switch to Light Mode'}
                >
                  {theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  );
};

export default Sidebar;

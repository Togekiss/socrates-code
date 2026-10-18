import React, { useState } from 'react';
import {
  Database,
  PlayCircle,
  UserCheck,
  Users,
  Film,
  AlertTriangle,
  MessageSquareCode,
  Settings,
  PlusCircle,
  LogOut,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import type { BackupInfo, CurationSummary, User } from '../types';
import { SidebarNavItem, type NavItemConfig } from './SidebarNavItem';

export type TabType =
  | 'status'
  | 'run'
  | 'writers'
  | 'characters'
  | 'scenes'
  | 'scene_issues'
  | 'flagged_messages'
  | 'admin'
  | 'new_backup';

interface SidebarProps {
  user: User | null;
  backups: BackupInfo[];
  selectedBackupId: string | null;
  onSelectBackup: (id: string | null) => void;
  activeTab: TabType;
  onSelectTab: (tab: TabType) => void;
  curationSummary: CurationSummary | null;
  backupInfo: BackupInfo | null;
  onNewBackup: () => void;
  onLogout: () => void;
}

interface NavGroup {
  title: string;
  items: NavItemConfig[];
}

export const Sidebar: React.FC<SidebarProps> = ({
  user,
  backups,
  selectedBackupId,
  onSelectBackup,
  activeTab,
  onSelectTab,
  curationSummary,
  backupInfo,
  onNewBackup,
  onLogout,
}) => {
  const [collapsed, setCollapsed] = useState(false);

  const isAnyRunning =
    backupInfo?.status === 'running' ||
    Object.values(backupInfo?.steps || {}).some(s => s === 'running');

  const navGroups: NavGroup[] = [
    {
      title: 'Overview',
      items: [
        { id: 'status', label: 'Status', icon: Database },
        {
          id: 'run',
          label: 'Pipeline & Run',
          icon: PlayCircle,
          badge: isAnyRunning ? 'Running' : null,
          badgeColor: 'var(--success)',
          isPulsing: isAnyRunning,
        },
      ],
    },
    {
      title: 'Writers & Characters',
      items: [
        {
          id: 'writers',
          label: 'Writers',
          icon: UserCheck,
          badge: curationSummary?.link_suggestions
            ? `${curationSummary.link_suggestions}`
            : null,
          badgeColor: 'var(--accent-secondary)',
        },
        { id: 'characters', label: 'Characters', icon: Users },
      ],
    },
    {
      title: 'Scenes & Messages',
      items: [
        { id: 'scenes', label: 'Scenes', icon: Film },
        {
          id: 'scene_issues',
          label: 'Scene Issues',
          icon: AlertTriangle,
          badge: curationSummary?.unresolved_issues ? `${curationSummary.unresolved_issues}` : null,
          badgeColor: 'var(--danger)',
        },
        {
          id: 'flagged_messages',
          label: 'Flagged Messages',
          icon: MessageSquareCode,
          badge: curationSummary?.flagged_messages ? `${curationSummary.flagged_messages}` : null,
          badgeColor: 'var(--warning-dark)',
        },
      ],
    },
    {
      title: 'System',
      items: [{ id: 'admin', label: 'Admin & Logs', icon: Settings }],
    },
  ];

  return (
    <aside
      className="glass-panel"
      style={{
        width: collapsed ? '74px' : '260px',
        minWidth: collapsed ? '74px' : '260px',
        transition: 'width 0.2s ease, min-width 0.2s ease',
        display: 'flex',
        flexDirection: 'column',
        height: 'calc(100vh - 2rem)',
        position: 'sticky',
        top: '1rem',
        padding: '1.25rem 0.75rem',
        borderRadius: '16px',
        overflow: 'hidden',
        zIndex: 50,
      }}
    >
      {/* Brand & Collapse Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: collapsed ? 'center' : 'space-between',
          padding: '0 0.5rem 1rem 0.5rem',
          borderBottom: '1px solid var(--border-color)',
          marginBottom: '1rem',
        }}
      >
        {!collapsed && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span
              style={{
                fontSize: '1.35rem',
                fontWeight: 700,
                color: 'var(--accent-secondary)',
                letterSpacing: '-0.02em',
              }}
            >
              Socrates
            </span>
          </div>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          style={{
            background: 'transparent',
            border: 'none',
            padding: '0.4rem',
            color: 'var(--text-secondary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            borderRadius: '6px',
          }}
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
        </button>
      </div>

      {/* Backup Selector */}
      {!collapsed ? (
        <div style={{ padding: '0 0.5rem 1rem 0.5rem', borderBottom: '1px solid var(--border-color)', marginBottom: '0.75rem' }}>
          <label style={{ display: 'block', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.4rem', fontWeight: 600 }}>
            Active Backup
          </label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <select
              value={selectedBackupId || ''}
              onChange={e => {
                onSelectBackup(e.target.value || null);
                onSelectTab('status');
              }}
              disabled={!user || backups.length === 0}
              style={{
                width: '100%',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                color: 'white',
                padding: '0.5rem 0.65rem',
                borderRadius: '6px',
                fontSize: '0.85rem',
                cursor: !user ? 'not-allowed' : 'pointer',
              }}
            >
              <option value="">
                {!user
                  ? 'Log in to select...'
                  : backups.length === 0
                  ? 'No backups found'
                  : '-- Select Backup --'}
              </option>
              {backups.map(b => (
                <option key={b.id || b.backup_id} value={b.id || b.backup_id}>
                  {b.name || b.backup_name || b.server_name || b.id}
                </option>
              ))}
            </select>
            {user && (
              <button
                onClick={onNewBackup}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '0.4rem',
                  padding: '0.4rem 0.6rem',
                  fontSize: '0.8rem',
                  background: 'rgba(109, 40, 217, 0.15)',
                  border: '1px solid var(--accent-glow)',
                  color: 'var(--accent-secondary)',
                  borderRadius: '6px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                <PlusCircle size={14} /> New Backup
              </button>
            )}
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '0.75rem', paddingBottom: '0.75rem', borderBottom: '1px solid var(--border-color)' }}>
          <button
            onClick={onNewBackup}
            title="Create New Backup"
            style={{
              background: 'transparent',
              border: 'none',
              padding: '0.4rem',
              color: 'var(--accent-secondary)',
              cursor: 'pointer',
            }}
          >
            <PlusCircle size={20} />
          </button>
        </div>
      )}

      {/* Navigation Groups */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '1rem', paddingRight: '2px' }}>
        {navGroups.map(group => (
          <div key={group.title}>
            {!collapsed && (
              <div
                style={{
                  fontSize: '0.7rem',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  color: 'var(--text-muted)',
                  padding: '0 0.5rem 0.35rem 0.5rem',
                  fontWeight: 600,
                }}
              >
                {group.title}
              </div>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
              {group.items.map(item => (
                <SidebarNavItem
                  key={item.id}
                  item={item}
                  isActive={activeTab === item.id}
                  isDisabled={!selectedBackupId && item.id !== 'admin'}
                  collapsed={collapsed}
                  onSelect={onSelectTab}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* User & Logout Footer */}
      <div
        style={{
          borderTop: '1px solid var(--border-color)',
          paddingTop: '0.75rem',
          marginTop: '0.5rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
        }}
      >
        {user ? (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: collapsed ? 'center' : 'space-between',
              padding: '0.25rem 0.5rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: 0 }}>
              {user.avatar ? (
                <img
                  src={`https://cdn.discordapp.com/avatars/${user.sub || user.id}/${user.avatar}.png`}
                  alt="avatar"
                  style={{ width: '28px', height: '28px', borderRadius: '50%', flexShrink: 0 }}
                />
              ) : (
                <div
                  style={{
                    width: '28px',
                    height: '28px',
                    borderRadius: '50%',
                    background: 'var(--bg-tertiary)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '0.8rem',
                    fontWeight: 'bold',
                    flexShrink: 0,
                  }}
                >
                  {user.username.charAt(0).toUpperCase()}
                </div>
              )}
              {!collapsed && (
                <span
                  style={{
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {user.username}
                </span>
              )}
            </div>
            {!collapsed && (
              <button
                onClick={onLogout}
                title="Logout"
                style={{
                  background: 'transparent',
                  border: 'none',
                  padding: '0.35rem',
                  color: 'var(--text-secondary)',
                  cursor: 'pointer',
                  borderRadius: '4px',
                }}
              >
                <LogOut size={16} />
              </button>
            )}
          </div>
        ) : null}
      </div>
    </aside>
  );
};

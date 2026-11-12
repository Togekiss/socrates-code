import React, { useState } from 'react';
import { Menu } from 'lucide-react';
import { Sidebar } from './Sidebar';
import type { BackupInfo, CurationSummary, User } from '../../types';

export interface AppShellProps {
  user: User | null;
  backups: BackupInfo[];
  selectedBackupId: string | null;
  onSelectBackup: (id: string | null) => void;
  curationSummary: CurationSummary | null;
  backupInfo: BackupInfo | null;
  onLogout: () => void;
  onNewBackup?: () => void;
  children: React.ReactNode;
}

export const AppShell: React.FC<AppShellProps> = ({
  user,
  backups,
  selectedBackupId,
  onSelectBackup,
  curationSummary,
  backupInfo,
  onLogout,
  onNewBackup,
  children,
}) => {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="app-shell">
      {/* Mobile Topbar (Visible <= 768px via CSS) */}
      <header className="app-topbar">
        <div className="flex-row items-center gap-sm">
          <button
            type="button"
            className="btn btn-ghost btn-icon btn-sm"
            onClick={() => setMobileOpen(true)}
            title="Open navigation menu"
            aria-label="Open navigation menu"
          >
            <Menu size={20} />
          </button>
          <span className="app-topbar-brand">Socrates</span>
        </div>

        <div className="flex-row items-center gap-sm">
          <select
            id="mobile-backup-select"
            name="mobile_backup"
            className="select select-sm mobile-backup-select"
            value={selectedBackupId || ''}
            onChange={e => {
              onSelectBackup(e.target.value || null);
            }}
            disabled={!user || backups.length === 0}
          >
            <option value="">
              {!user ? 'Log in...' : backups.length === 0 ? 'No backups' : '-- Select Backup --'}
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
        </div>
      </header>

      {/* Mobile Sidebar Slide-Over Backdrop */}
      <div
        className={`sidebar-backdrop ${mobileOpen ? 'is-open' : ''}`}
        onClick={() => setMobileOpen(false)}
        aria-hidden="true"
      />

      {/* 5-Group Responsive Collapsible Sidebar */}
      <Sidebar
        user={user}
        backups={backups}
        selectedBackupId={selectedBackupId}
        onSelectBackup={onSelectBackup}
        curationSummary={curationSummary}
        backupInfo={backupInfo}
        onLogout={onLogout}
        onNewBackup={onNewBackup}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />

      {/* Main View Area */}
      <main className="app-main">{children}</main>
    </div>
  );
};

export default AppShell;

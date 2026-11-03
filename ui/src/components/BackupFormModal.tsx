import React from 'react';
import { X, Loader2 } from 'lucide-react';

interface BackupFormModalProps {
  backupId: string;
  admin: Record<string, unknown>;
  isSaving: boolean;
  saveError: string | null;
  onCancel: () => void;
  handleSaveOnly: () => void;
  handleSaveAndRun: () => void;
  children: React.ReactNode;
}

export const BackupFormModal: React.FC<BackupFormModalProps> = ({
  backupId,
  admin,
  isSaving,
  saveError,
  onCancel,
  handleSaveOnly,
  handleSaveAndRun,
  children,
}) => {
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
      <div
        style={{
          background: 'var(--bg-primary)',
          width: '720px',
          maxWidth: '95vw',
          maxHeight: '90vh',
          borderRadius: '12px',
          border: '1px solid var(--border-color)',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.6)',
        }}
      >
        {/* Modal Header */}
        <div
          style={{
            padding: '1rem 1.5rem',
            borderBottom: '1px solid var(--border-color)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: 'var(--bg-secondary)',
            borderRadius: '12px 12px 0 0',
          }}
        >
          <h3 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--text-primary)' }}>
            Configure Backup: {(admin.backupName as string) || (admin.serverName as string) || backupId}{' '}
            <span style={{ fontSize: '0.8em', color: 'var(--text-secondary)', fontWeight: 'normal' }}>
              ({(admin.serverId as string) || ''})
            </span>
          </h3>
          <button
            onClick={onCancel}
            disabled={isSaving}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              display: 'flex',
              padding: 0,
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Modal Body */}
        <div
          style={{
            padding: '1.5rem',
            overflowY: 'auto',
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            gap: '1.25rem',
          }}
        >
          {saveError && (
            <div
              style={{
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid var(--danger)',
                color: 'var(--danger)',
                padding: '0.75rem',
                borderRadius: '4px',
                fontSize: '0.85rem',
              }}
            >
              {saveError}
            </div>
          )}
          {children}
        </div>

        {/* Modal Footer */}
        <div
          style={{
            padding: '1rem 1.5rem',
            borderTop: '1px solid var(--border-color)',
            display: 'flex',
            justifyContent: 'flex-end',
            gap: '0.75rem',
            background: 'var(--bg-secondary)',
            borderRadius: '0 0 12px 12px',
          }}
        >
          <button
            onClick={onCancel}
            disabled={isSaving}
            style={{
              padding: '0.5rem 1rem',
              background: 'transparent',
              color: 'var(--text-primary)',
              border: '1px solid var(--border-color)',
              borderRadius: '6px',
              cursor: 'pointer',
            }}
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
              gap: '0.5rem',
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
              gap: '0.5rem',
            }}
          >
            {isSaving && <Loader2 size={14} className="animate-spin" />}
            Save & Update now
          </button>
        </div>
      </div>
    </div>
  );
};

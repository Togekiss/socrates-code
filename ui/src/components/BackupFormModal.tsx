import React from 'react';
import { AlertTriangle } from 'lucide-react';
import { Modal, Button, Badge } from './ui';
import type { StorageMode } from '../types';

export interface BackupStorageModeModalSectionProps {
  currentMode: StorageMode;
  hasDataFiles?: boolean;
  showConvertWarning: boolean;
  confirmModeConversion: boolean;
  onToggleConvertWarning: () => void;
  onConfirmChange: (checked: boolean) => void;
}

export const BackupStorageModeModalSection: React.FC<BackupStorageModeModalSectionProps> = ({
  currentMode,
  hasDataFiles = false,
  showConvertWarning,
  confirmModeConversion,
  onToggleConvertWarning,
  onConfirmChange,
}) => {
  const isFull = currentMode === 'full';
  const convertButtonLabel = isFull ? 'Convert to Backupless' : 'Convert to Full backup';
  const modeDescription = isFull
    ? 'Converting to Backupless stops updating Data/*.json files on sync and relies on lightweight SQLite skeletons with on-demand Discord message hydration.'
    : 'Converting to Full backup downloads full DCE-compatible Data/*.json message archives alongside SQLite skeletons during sync.';

  return (
    <div className="flex-col gap-sm">
      <label style={{ display: 'block', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
        Storage Mode
      </label>
      <div
        className="flex-row items-center justify-between flex-wrap gap-sm"
        style={{
          padding: '0.75rem 0.9rem',
          background: 'var(--bg-tertiary)',
          border: '1px solid var(--border-color)',
          borderRadius: 'var(--radius-sm)',
        }}
      >
        <div className="flex-col gap-xs" style={{ flex: '1 1 280px' }}>
          <div className="flex-row items-center gap-xs flex-wrap">
            <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>Current mode:</span>
            <Badge variant={isFull ? 'accent' : 'neutral'}>
              {isFull ? 'Full Backup' : 'Backupless'}
            </Badge>
          </div>
          <span className="text-muted" style={{ fontSize: '0.8rem' }}>
            {modeDescription}
          </span>
        </div>

        <Button
          type="button"
          variant={showConvertWarning ? 'ghost' : 'secondary'}
          size="sm"
          onClick={onToggleConvertWarning}
        >
          {showConvertWarning ? 'Cancel conversion' : convertButtonLabel}
        </Button>
      </div>

      {showConvertWarning && (
        <div className="banner-danger mb-0 flex-col items-start gap-sm" role="alert">
          <div className="flex-row items-start gap-xs" style={{ fontWeight: 600, fontSize: '0.875rem' }}>
            <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
            <span>
              {isFull
                ? 'Warning: Converting Full Backup → Backupless'
                : 'Warning: Converting Backupless → Full Backup'}
            </span>
          </div>

          <div style={{ fontSize: '0.825rem', lineHeight: 1.45 }}>
            {isFull ? (
              <>
                <p style={{ margin: '0 0 0.4rem 0' }}>
                  Existing <code>Data/*.json</code> files will stop updating and go stale, and
                  on-demand message hydration will query live Discord instead of local JSON files.
                </p>
                <p style={{ margin: 0 }}>
                  If the local JSON files were modified externally or belong to a deleted or heavily
                  pruned server, converting and syncing may require a full re-index and risk
                  mismatched channels or messages being tagged as deleted. Clicking &ldquo;Save &amp;
                  Update now&rdquo; will run a Full Discord Rescan.
                </p>
              </>
            ) : (
              <>
                <p style={{ margin: '0 0 0.4rem 0' }}>
                  Saving this conversion will automatically trigger a{' '}
                  <strong>Full Discord Rescan</strong> to download complete channel histories into{' '}
                  <code>Data/*.json</code>.
                </p>
                {hasDataFiles && (
                  <p style={{ margin: 0, fontWeight: 600 }}>
                    An existing <code>Data/</code> folder was detected for this backup. This will
                    overwrite all previous <code>Data/*.json</code> files. If you want to keep the old
                    JSON files, move them to a safe location before proceeding. Are you sure to
                    proceed?
                  </p>
                )}
              </>
            )}
          </div>

          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.45rem',
              cursor: 'pointer',
              fontSize: '0.85rem',
              fontWeight: 600,
            }}
          >
            <input
              type="checkbox"
              checked={confirmModeConversion}
              onChange={e => onConfirmChange(e.target.checked)}
            />
            <span>I understand, proceed</span>
          </label>
        </div>
      )}
    </div>
  );
};

interface BackupFormModalProps {
  backupId: string;
  admin: Record<string, unknown>;
  isSaving: boolean;
  saveError: string | null;
  disableSaveOnly?: boolean;
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
  disableSaveOnly = false,
  onCancel,
  handleSaveOnly,
  handleSaveAndRun,
  children,
}) => {
  const backupTitle =
    (admin.backupName as string) || (admin.serverName as string) || backupId;
  const serverId = (admin.serverId as string) || '';

  const modalTitle = (
    <div className="flex-row items-center gap-xs flex-wrap">
      <span>Configure Backup: {backupTitle}</span>
      {serverId && (
        <span className="text-secondary" style={{ fontSize: '0.85em', fontWeight: 'normal' }}>
          ({serverId})
        </span>
      )}
    </div>
  );

  const modalFooter = (
    <div className="flex-row items-center justify-end gap-sm">
      <Button variant="ghost" onClick={onCancel} disabled={isSaving}>
        Cancel
      </Button>
      <Button
        variant="secondary"
        onClick={handleSaveOnly}
        disabled={isSaving || disableSaveOnly}
        loading={isSaving && !disableSaveOnly}
        title={disableSaveOnly ? 'Storage mode conversion requires clicking "Save & Update now"' : undefined}
      >
        Save configuration
      </Button>
      <Button
        variant="primary"
        onClick={handleSaveAndRun}
        loading={isSaving}
      >
        Save &amp; Update now
      </Button>
    </div>
  );

  return (
    <Modal
      isOpen={true}
      onClose={onCancel}
      title={modalTitle}
      size="lg"
      footer={modalFooter}
    >
      <div className="flex-col gap-lg">
        {saveError && (
          <div className="banner-danger">
            <span>{saveError}</span>
          </div>
        )}
        {children}
      </div>
    </Modal>
  );
};

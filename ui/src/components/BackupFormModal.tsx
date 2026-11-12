import React from 'react';
import { Modal, Button } from './ui';

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
        loading={isSaving}
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
      <div className="flex-col gap-md">
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

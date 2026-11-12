import React, { useState } from 'react';
import { UserCheck } from 'lucide-react';
import { api } from '../../api';
import type { UnassignedCharacter, WriterDetailed } from '../../types';
import { Modal, Button, Badge } from '../ui';

interface AssignWriterModalProps {
  backupId: string;
  character: UnassignedCharacter | null;
  writers: WriterDetailed[];
  onClose: () => void;
  onAssigned: () => void;
}

export const AssignWriterModal: React.FC<AssignWriterModalProps> = ({
  backupId,
  character,
  writers,
  onClose,
  onAssigned,
}) => {
  const [selectedWriterId, setSelectedWriterId] = useState<number | ''>('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!character) return null;

  const handleAssign = async () => {
    if (selectedWriterId === '') {
      setError('Please select a writer.');
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await api.assignCharacterWriter(backupId, character.id, selectedWriterId);
      onAssigned();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to assign writer.');
      setSaving(false);
    }
  };

  const charDisplayName = character.name || character.names?.[0] || `Character #${character.id}`;

  const modalFooter = (
    <div className="flex-row items-center justify-end gap-sm">
      <Button variant="ghost" onClick={onClose} disabled={saving}>
        Cancel
      </Button>
      <Button
        variant="primary"
        onClick={handleAssign}
        loading={saving}
        disabled={selectedWriterId === ''}
        icon={<UserCheck size={14} />}
      >
        Confirm Assignment
      </Button>
    </div>
  );

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      title="Assign Writer to Character"
      size="sm"
      footer={modalFooter}
    >
      <div className="flex-col gap-md">
        {error && (
          <div className="banner-danger">
            <span>{error}</span>
          </div>
        )}

        <div className="form-group">
          <label className="form-label">Selected Character</label>
          <div className="panel-surface flex-col gap-xs" style={{ padding: '0.65rem 0.85rem' }}>
            <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.95rem' }}>
              {charDisplayName}
            </div>
            <div className="flex-row items-center gap-xs">
              <Badge variant="neutral">ID: #{character.id}</Badge>
              {character.origin && <span className="form-hint">• {character.origin}</span>}
            </div>
          </div>
        </div>

        <div className="form-group">
          <label htmlFor="assign-writer-select" className="form-label">
            Assign to Writer
          </label>
          <select
            id="assign-writer-select"
            className="select"
            value={selectedWriterId}
            onChange={e => setSelectedWriterId(e.target.value ? Number(e.target.value) : '')}
          >
            <option value="">-- Choose Writer --</option>
            {writers.map(w => (
              <option key={w.id} value={w.id}>
                {w.display_name} ({w.characters?.length || 0} characters)
              </option>
            ))}
          </select>
        </div>
      </div>
    </Modal>
  );
};

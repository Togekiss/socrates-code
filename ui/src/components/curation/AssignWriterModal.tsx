import React, { useState } from 'react';
import { X, UserCheck, Loader2 } from 'lucide-react';
import { api } from '../../api';
import type { UnassignedCharacter, WriterDetailed } from '../../types';

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

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0, 0, 0, 0.75)',
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backdropFilter: 'blur(4px)',
      }}
      onClick={e => {
        if (e.target === e.currentTarget && !saving) onClose();
      }}
    >
      <div
        style={{
          background: 'var(--bg-primary)',
          width: '460px',
          maxWidth: '92vw',
          borderRadius: '12px',
          border: '1px solid var(--border-color)',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '1rem 1.25rem',
            borderBottom: '1px solid var(--border-color)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <h2 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--text-primary)' }}>
            Assign Writer to Character
          </h2>
          <button
            onClick={onClose}
            disabled={saving}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              display: 'flex',
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {error && (
            <div
              style={{
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid var(--danger)',
                color: 'var(--danger)',
                padding: '0.65rem 0.85rem',
                borderRadius: '6px',
                fontSize: '0.85rem',
              }}
            >
              {error}
            </div>
          )}

          <div>
            <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.25rem' }}>
              Selected Character
            </label>
            <div
              style={{
                background: 'var(--bg-tertiary)',
                padding: '0.65rem 0.85rem',
                borderRadius: '6px',
                border: '1px solid var(--border-color)',
              }}
            >
              <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.95rem' }}>
                {charDisplayName}
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                ID: #{character.id} {character.origin ? `• ${character.origin}` : ''}
              </div>
            </div>
          </div>

          <div>
            <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 600, display: 'block', marginBottom: '0.35rem' }}>
              Assign to Writer
            </label>
            <select
              value={selectedWriterId}
              onChange={e => setSelectedWriterId(e.target.value ? Number(e.target.value) : '')}
              style={{
                width: '100%',
                padding: '0.55rem 0.75rem',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                borderRadius: '6px',
                color: 'white',
                fontSize: '0.9rem',
              }}
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

        {/* Footer */}
        <div
          style={{
            padding: '1rem 1.25rem',
            borderTop: '1px solid var(--border-color)',
            display: 'flex',
            justifyContent: 'flex-end',
            gap: '0.5rem',
            background: 'var(--bg-secondary)',
            borderRadius: '0 0 12px 12px',
          }}
        >
          <button
            onClick={onClose}
            disabled={saving}
            style={{
              padding: '0.45rem 1rem',
              background: 'transparent',
              border: '1px solid var(--border-color)',
              color: 'var(--text-primary)',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '0.85rem',
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleAssign}
            disabled={saving || selectedWriterId === ''}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.45rem 1.25rem',
              background: 'var(--accent-primary)',
              border: 'none',
              color: '#fff',
              borderRadius: '6px',
              fontWeight: 600,
              cursor: saving || selectedWriterId === '' ? 'not-allowed' : 'pointer',
              opacity: selectedWriterId === '' ? 0.5 : 1,
              fontSize: '0.85rem',
            }}
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <UserCheck size={14} />}
            Confirm Assignment
          </button>
        </div>
      </div>
    </div>
  );
};

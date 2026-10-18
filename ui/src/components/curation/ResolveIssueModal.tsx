import React, { useState } from 'react';
import { X, Check, Loader2 } from 'lucide-react';
import { api } from '../../api';
import type { SceneIssue } from '../../types';

interface ResolveIssueModalProps {
  backupId: string;
  issue: SceneIssue | null;
  onClose: () => void;
  onResolved: () => void;
}

export const ResolveIssueModal: React.FC<ResolveIssueModalProps> = ({
  backupId,
  issue,
  onClose,
  onResolved,
}) => {
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!issue) return null;

  const handleResolve = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.resolveSceneIssue(backupId, issue.id, note.trim() || undefined);
      onResolved();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to resolve issue.');
      setSaving(false);
    }
  };

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
            Resolve Issue #{issue.id}
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

          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            Marking issue for scene <strong style={{ color: 'var(--text-primary)' }}>{issue.scene_key}</strong> (
            <code>{issue.kind}</code>) in <strong>#{issue.channel_name}</strong> as resolved.
          </div>

          <div>
            <label
              style={{
                fontSize: '0.85rem',
                color: 'var(--text-secondary)',
                fontWeight: 600,
                display: 'block',
                marginBottom: '0.35rem',
              }}
            >
              Reviewer Note (optional)
            </label>
            <input
              type="text"
              placeholder="e.g. Verified intentional non-tupper dialogue"
              value={note}
              onChange={e => setNote(e.target.value)}
              style={{
                width: '100%',
                padding: '0.55rem 0.75rem',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                borderRadius: '6px',
                color: 'white',
                fontSize: '0.9rem',
              }}
            />
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
            onClick={handleResolve}
            disabled={saving}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.45rem 1.25rem',
              background: 'var(--success)',
              border: 'none',
              color: '#fff',
              borderRadius: '6px',
              fontWeight: 600,
              cursor: saving ? 'not-allowed' : 'pointer',
              fontSize: '0.85rem',
            }}
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            Confirm Resolution
          </button>
        </div>
      </div>
    </div>
  );
};

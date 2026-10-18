import React, { useState } from 'react';
import { X, Trash2, Loader2 } from 'lucide-react';
import { api } from '../../api';
import type { WriterDetailed } from '../../types';

interface WriterEditModalProps {
  backupId: string;
  writer?: WriterDetailed | null;
  onClose: () => void;
  onSaved: () => void;
}

export const WriterEditModal: React.FC<WriterEditModalProps> = ({
  backupId,
  writer,
  onClose,
  onSaved,
}) => {
  const isNew = !writer || !writer.id;
  const [displayName, setDisplayName] = useState(writer?.display_name || '');
  const [aliases, setAliases] = useState((writer?.aliases || []).join(', '));
  const [discordUserId, setDiscordUserId] = useState(writer?.discord_user_id || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    if (!displayName.trim()) {
      setError('Display name is required.');
      return;
    }

    const aliasesArray = aliases
      .split(',')
      .map(s => s.trim())
      .filter(Boolean);

    setSaving(true);
    setError(null);
    try {
      if (isNew) {
        await api.createWriter(backupId, {
          display_name: displayName.trim(),
          aliases: aliasesArray,
          discord_user_id: discordUserId.trim() || undefined,
        });
      } else {
        await api.updateWriter(backupId, writer.id, {
          display_name: displayName.trim(),
          aliases: aliasesArray,
          discord_user_id: discordUserId.trim() || null,
        });
      }
      onSaved();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || `Failed to ${isNew ? 'create' : 'update'} writer.`);
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (isNew || !writer?.id) return;
    if (
      !window.confirm(
        `Are you sure you want to delete writer "${writer.display_name}"? Characters written by them will become unassigned.`
      )
    ) {
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await api.deleteWriter(backupId, writer.id);
      onSaved();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to delete writer.');
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
          width: '500px',
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
          <h2 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--text-primary)' }}>
            {isNew ? 'Create New Writer' : `Edit Writer: ${writer.display_name}`}
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

        {/* Body */}
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
            <label
              style={{
                display: 'block',
                fontSize: '0.85rem',
                fontWeight: 600,
                color: 'var(--text-secondary)',
                marginBottom: '0.35rem',
              }}
            >
              Display Name *
            </label>
            <input
              type="text"
              value={displayName}
              onChange={e => setDisplayName(e.target.value)}
              placeholder="e.g. Stephen King"
              style={{
                width: '100%',
                padding: '0.5rem 0.75rem',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                borderRadius: '6px',
                color: 'white',
                fontSize: '0.9rem',
              }}
            />
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.85rem',
                fontWeight: 600,
                color: 'var(--text-secondary)',
                marginBottom: '0.35rem',
              }}
            >
              Aliases (comma-separated)
            </label>
            <input
              type="text"
              value={aliases}
              onChange={e => setAliases(e.target.value)}
              placeholder="e.g. Richard Bachman, SK"
              style={{
                width: '100%',
                padding: '0.5rem 0.75rem',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                borderRadius: '6px',
                color: 'white',
                fontSize: '0.9rem',
              }}
            />
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem', display: 'block' }}>
              Used for matching character credits and heuristics.
            </span>
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.85rem',
                fontWeight: 600,
                color: 'var(--text-secondary)',
                marginBottom: '0.35rem',
              }}
            >
              Linked Discord User ID (Snowflake)
            </label>
            <input
              type="text"
              value={discordUserId}
              onChange={e => setDiscordUserId(e.target.value)}
              placeholder="e.g. 123456789012345678"
              style={{
                width: '100%',
                padding: '0.5rem 0.75rem',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                borderRadius: '6px',
                color: 'white',
                fontSize: '0.9rem',
              }}
            />
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem', display: 'block' }}>
              Enables &quot;★ By Me&quot; filtering for this Discord account.
            </span>
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '1rem 1.25rem',
            borderTop: '1px solid var(--border-color)',
            display: 'flex',
            justifyContent: isNew ? 'flex-end' : 'space-between',
            alignItems: 'center',
            background: 'var(--bg-secondary)',
            borderRadius: '0 0 12px 12px',
          }}
        >
          {!isNew && (
            <button
              onClick={handleDelete}
              disabled={saving}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.4rem',
                padding: '0.45rem 0.85rem',
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid var(--danger)',
                color: 'var(--danger)',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '0.85rem',
              }}
            >
              <Trash2 size={14} /> Delete Writer
            </button>
          )}

          <div style={{ display: 'flex', gap: '0.5rem' }}>
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
              onClick={handleSave}
              disabled={saving}
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
                cursor: saving ? 'not-allowed' : 'pointer',
                fontSize: '0.85rem',
              }}
            >
              {saving && <Loader2 size={14} className="animate-spin" />}
              {isNew ? 'Create Writer' : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

import React, { useState } from 'react';
import { X, Split, Loader2 } from 'lucide-react';
import { api } from '../../api';

interface ManualSplitModalProps {
  backupId: string;
  onClose: () => void;
  onSuccess: () => void;
}

export const ManualSplitModal: React.FC<ManualSplitModalProps> = ({
  backupId,
  onClose,
  onSuccess,
}) => {
  const [discordLink, setDiscordLink] = useState('');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!discordLink.trim()) {
      setError('Please provide a Discord message link.');
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await api.createManualSceneSplit(backupId, {
        discord_link: discordLink.trim(),
        note: note.trim() || undefined,
      });
      onSuccess();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to create manual scene split.');
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
          width: '520px',
          maxWidth: '92vw',
          borderRadius: '12px',
          border: '1px solid var(--border-color)',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
        }}
      >
        <div
          style={{
            padding: '1.25rem',
            borderBottom: '1px solid var(--border-color)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <Split size={20} color="var(--accent-secondary)" />
            <h3 style={{ margin: 0, fontSize: '1.1rem', color: 'var(--text-primary)' }}>
              Manual Scene Split
            </h3>
          </div>
          <button
            onClick={onClose}
            disabled={saving}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              padding: '0.25rem',
            }}
          >
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {error && (
            <div
              style={{
                padding: '0.65rem 0.85rem',
                borderRadius: '6px',
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                color: 'var(--danger)',
                fontSize: '0.85rem',
              }}
            >
              {error}
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>
              Discord Message Link <span style={{ color: 'var(--danger)' }}>*</span>
            </label>
            <input
              type="text"
              required
              placeholder="https://discord.com/channels/123.../456.../789..."
              value={discordLink}
              onChange={e => setDiscordLink(e.target.value)}
              style={{
                width: '100%',
                padding: '0.6rem 0.75rem',
                borderRadius: '6px',
                border: '1px solid var(--border-color)',
                background: 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                fontSize: '0.85rem',
              }}
            />
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              The scene containing this message will be split in two, with this message becoming the start of Scene 2.
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>
              Curator Note (Optional)
            </label>
            <input
              type="text"
              placeholder="e.g. Timeskip or new arc start"
              value={note}
              onChange={e => setNote(e.target.value)}
              style={{
                width: '100%',
                padding: '0.6rem 0.75rem',
                borderRadius: '6px',
                border: '1px solid var(--border-color)',
                background: 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                fontSize: '0.85rem',
              }}
            />
          </div>

          <div
            style={{
              display: 'flex',
              justifyContent: 'flex-end',
              gap: '0.75rem',
              marginTop: '0.5rem',
              paddingTop: '0.75rem',
              borderTop: '1px solid var(--border-color)',
            }}
          >
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              style={{
                padding: '0.5rem 1rem',
                borderRadius: '6px',
                border: '1px solid var(--border-color)',
                background: 'var(--bg-secondary)',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                fontSize: '0.85rem',
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || !discordLink.trim()}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.45rem',
                padding: '0.5rem 1.25rem',
                borderRadius: '6px',
                border: 'none',
                background: 'var(--accent-secondary)',
                color: '#fff',
                cursor: saving || !discordLink.trim() ? 'not-allowed' : 'pointer',
                opacity: saving || !discordLink.trim() ? 0.6 : 1,
                fontWeight: 600,
                fontSize: '0.85rem',
              }}
            >
              {saving ? <Loader2 size={16} className="spin" /> : <Split size={16} />}
              Split Scene
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

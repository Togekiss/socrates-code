import React, { useState } from 'react';
import { X, Check, Loader2 } from 'lucide-react';
import { api } from '../../api';
import type { FlaggedMessage } from '../../types';

interface PromoteMessageModalProps {
  backupId: string;
  message: FlaggedMessage | null;
  onClose: () => void;
  onPromoted: () => void;
}

export const PromoteMessageModal: React.FC<PromoteMessageModalProps> = ({
  backupId,
  message,
  onClose,
  onPromoted,
}) => {
  const [content, setContent] = useState(message?.content || '');
  const [authorName, setAuthorName] = useState(message?.author?.name || message?.author?.nickname || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!message) return null;

  const handlePromote = async () => {
    setSaving(true);
    setError(null);
    try {
      const authorPayload = {
        ...message.author,
        name: authorName.trim() || message.author?.name,
      };

      await api.promoteFlaggedMessage(backupId, message.message_id, {
        content: content.trim(),
        author: authorPayload,
      });
      onPromoted();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to promote message.');
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
          width: '540px',
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
            Promote Message #{message.message_id}
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

          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            Promoting registers this message as a permanent <code>message_override</code> so scene indexing and attribution pipelines treat it as legitimate roleplay dialogue.
          </p>

          <div>
            <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 600, display: 'block', marginBottom: '0.35rem' }}>
              Author Name
            </label>
            <input
              type="text"
              value={authorName}
              onChange={e => setAuthorName(e.target.value)}
              placeholder="e.g. Character / Pen Name"
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

          <div>
            <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 600, display: 'block', marginBottom: '0.35rem' }}>
              Dialogue Content
            </label>
            <textarea
              rows={4}
              value={content}
              onChange={e => setContent(e.target.value)}
              style={{
                width: '100%',
                padding: '0.65rem 0.75rem',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                borderRadius: '6px',
                color: 'white',
                fontSize: '0.9rem',
                resize: 'vertical',
                lineHeight: 1.5,
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
            onClick={handlePromote}
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
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            Confirm Promotion
          </button>
        </div>
      </div>
    </div>
  );
};

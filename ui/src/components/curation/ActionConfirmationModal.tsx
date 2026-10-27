import React, { useState } from 'react';
import { X, GitMerge, Split, Loader2 } from 'lucide-react';
import { api } from '../../api';
import type { SceneIssue, IssueResolution } from '../../types';

interface ActionConfirmationModalProps {
  backupId: string;
  issue: SceneIssue;
  action: 'merge' | 'split';
  onClose: () => void;
  onResolved: () => void;
}

export const ActionConfirmationModal: React.FC<ActionConfirmationModalProps> = ({
  backupId,
  issue,
  action,
  onClose,
  onResolved,
}) => {
  const [actionNotes, setActionNotes] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resolution: IssueResolution = action === 'merge' ? 'merged' : 'split';

  const handleConfirm = async () => {
    setLoading(true);
    setError(null);
    try {
      await api.resolveSceneIssue(
        backupId,
        issue.id,
        resolution,
        actionNotes.trim() || undefined
      );
      onResolved();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || `Failed to ${action} scene.`);
      setLoading(false);
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
        if (e.target === e.currentTarget && !loading) onClose();
      }}
    >
      <div
        style={{
          background: 'var(--bg-primary)',
          width: '480px',
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
            padding: '1rem 1.25rem',
            borderBottom: '1px solid var(--border-color)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <h2
            style={{
              margin: 0,
              fontSize: '1.15rem',
              color: 'var(--text-primary)',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
            }}
          >
            {action === 'merge' ? (
              <>
                <GitMerge size={18} style={{ color: 'var(--accent-secondary)' }} />
                Confirm Scene Merge
              </>
            ) : (
              <>
                <Split size={18} style={{ color: '#3b82f6' }} />
                Confirm Scene Split
              </>
            )}
          </h2>
          <button
            onClick={onClose}
            disabled={loading}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: loading ? 'not-allowed' : 'pointer',
              display: 'flex',
            }}
          >
            <X size={20} />
          </button>
        </div>

        <div style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {error && (
            <div
              style={{
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid var(--danger)',
                color: 'var(--danger)',
                padding: '0.6rem 0.85rem',
                borderRadius: '6px',
                fontSize: '0.85rem',
              }}
            >
              {error}
            </div>
          )}

          <div style={{ fontSize: '0.9rem', color: 'var(--text-primary)', lineHeight: '1.5' }}>
            {action === 'merge' ? (
              <>
                Merge <strong style={{ color: 'var(--accent-secondary)' }}>Scene {issue.scene_key}</strong>
                {issue.next_scene_key && (
                  <> and <strong style={{ color: 'var(--accent-secondary)' }}>Scene {issue.next_scene_key}</strong></>
                )}{' '}
                in <strong>#{issue.channel_name}</strong> into a single continuous scene?
              </>
            ) : (
              <>
                Split <strong style={{ color: '#60a5fa' }}>Scene {issue.scene_key}</strong> in{' '}
                <strong>#{issue.channel_name}</strong> into two distinct scenes at message{' '}
                <code>{issue.candidate_message_id}</code>?
              </>
            )}
          </div>

          <div
            style={{
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-secondary)',
              padding: '0.75rem 1rem',
              borderRadius: '6px',
              fontSize: '0.85rem',
              lineHeight: '1.45',
            }}
          >
            {action === 'merge' ? (
              <>
                This will unite both scenes, combine their character participants, and preserve this merge decision across future re-indexing scans.
              </>
            ) : (
              <>
                This will truncate the current scene before the split point, start the second scene at message{' '}
                <code>{issue.candidate_message_id}</code>, and partition participants between both parts.
              </>
            )}
          </div>

          {issue.candidate_excerpt && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>
                {action === 'merge' ? 'Boundary message excerpt' : 'New scene starting message'}
              </span>
              <div
                style={{
                  fontSize: '0.8rem',
                  color: 'var(--text-secondary)',
                  fontStyle: 'italic',
                  background: 'rgba(0, 0, 0, 0.25)',
                  padding: '0.5rem 0.75rem',
                  borderRadius: '6px',
                  lineHeight: '1.4',
                  border: '1px solid var(--border-color)',
                }}
              >
                "{issue.candidate_excerpt}"
              </div>
            </div>
          )}

          {/* Resolution Notes Input */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}>
              Resolution Notes (optional)
            </label>
            <textarea
              value={actionNotes}
              onChange={e => setActionNotes(e.target.value)}
              placeholder={
                action === 'merge'
                  ? `e.g. Merged Scene ${issue.scene_key} and ${issue.next_scene_key || 'subsequent scene'}...`
                  : `e.g. Split at message ${issue.candidate_message_id}...`
              }
              rows={2}
              style={{
                width: '100%',
                padding: '0.5rem 0.75rem',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                borderRadius: '6px',
                color: 'var(--text-primary)',
                fontSize: '0.85rem',
                fontFamily: 'inherit',
                resize: 'vertical',
                boxSizing: 'border-box',
              }}
            />
          </div>
        </div>

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
            disabled={loading}
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
            onClick={handleConfirm}
            disabled={loading}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.45rem 1.25rem',
              background: action === 'merge' ? 'var(--accent-secondary)' : '#3b82f6',
              border: 'none',
              color: '#fff',
              borderRadius: '6px',
              fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: '0.85rem',
            }}
          >
            {loading ? (
              <Loader2 size={14} className="animate-spin" />
            ) : action === 'merge' ? (
              <GitMerge size={14} />
            ) : (
              <Split size={14} />
            )}
            {action === 'merge' ? 'Confirm Merge' : 'Confirm Split'}
          </button>
        </div>
      </div>
    </div>
  );
};

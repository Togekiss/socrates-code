import React from 'react';
import { Trash2, Loader2 } from 'lucide-react';
import type { MessageOverride } from '../../types';

interface MessageOverrideCardProps {
  override: MessageOverride;
  isDeleting: boolean;
  onDelete: (messageId: string) => void;
}

export const MessageOverrideCard: React.FC<MessageOverrideCardProps> = ({
  override,
  isDeleting,
  onDelete,
}) => {
  return (
    <div
      className="glass-panel"
      style={{
        padding: '1.25rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.75rem',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <strong style={{ fontSize: '0.95rem', color: 'var(--text-primary)' }}>
            Override #{override.message_id} in #{override.channel_name}
          </strong>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
            Author: {override.author?.name || 'Unknown'} (ID: {override.author?.id || 'N/A'})
          </div>
        </div>

        <button
          onClick={() => onDelete(override.message_id)}
          disabled={isDeleting}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.3rem',
            padding: '0.35rem 0.75rem',
            fontSize: '0.8rem',
            background: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid var(--danger)',
            color: 'var(--danger)',
            borderRadius: '6px',
            cursor: isDeleting ? 'not-allowed' : 'pointer',
          }}
        >
          {isDeleting ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Trash2 size={12} />
          )}
          Remove Override
        </button>
      </div>

      <div
        style={{
          background: 'var(--bg-tertiary)',
          padding: '0.85rem 1rem',
          borderRadius: '6px',
          fontSize: '0.9rem',
          color: 'var(--text-primary)',
          whiteSpace: 'pre-wrap',
          border: '1px solid var(--border-color)',
        }}
      >
        {override.content}
      </div>
    </div>
  );
};

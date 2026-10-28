import React from 'react';
import { ExternalLink, Check, RotateCcw, Loader2, Sparkles, EyeOff, CheckCheck, ArrowRight } from 'lucide-react';
import type { FlaggedMessage, FlaggedResolution } from '../../types';

interface FlaggedMessageCardProps {
  message: FlaggedMessage;
  isResolving: boolean;
  isReopening: boolean;
  onPromote: (msg: FlaggedMessage) => void;
  onResolve: (msg: FlaggedMessage, resolution: FlaggedResolution) => void;
  onReopen: (messageId: string) => void;
}

export const FlaggedMessageCard: React.FC<FlaggedMessageCardProps> = ({
  message,
  isResolving,
  isReopening,
  onPromote,
  onResolve,
  onReopen,
}) => {
  const [isExpanded, setIsExpanded] = React.useState(false);
  const isResolved = message.resolved_at !== null && message.resolved_at !== undefined;
  const isOverridden = message.resolution === 'override' && !!message.override_author;
  const currentAuthor = isOverridden ? message.override_author : message.author || {};
  const currentAuthorName = currentAuthor?.name || currentAuthor?.nickname || 'Unknown Author';
  const originalAuthor = message.author || {};
  const originalAuthorName = originalAuthor?.nickname || originalAuthor?.name || 'Unknown Author';
  const isMessageOverridden = isOverridden && message.content !== message.override_content;
  const suggested = message.suggested_character;

  const getKindBadge = (kind: string) => {
    switch (kind) {
      case 'failed_tupper':
        return { label: 'Failed Tupper', bg: '#f59e0b', color: '#000' };
      case 'ooc_boundary':
        return { label: 'OOC Boundary', bg: '#8b5cf6', color: '#fff' };
      case 'ooc_message':
        return { label: 'OOC Message', bg: '#3b82f6', color: '#fff' };
      case 'manual':
        return { label: 'Manual', bg: '#06b6d4', color: '#000' };
      default:
        return { label: kind.replace(/_/g, ' '), bg: 'var(--text-muted)', color: '#fff' };
    }
  };

  const getResolutionBadge = (res?: string | null) => {
    switch (res) {
      case 'override':
        return { label: 'Overridden', bg: 'rgba(139, 92, 246, 0.2)', border: '#8b5cf6', color: '#c4b5fd' };
      case 'ignored':
        return { label: 'Ignored (OOC)', bg: 'rgba(239, 68, 68, 0.15)', border: 'rgba(239, 68, 68, 0.5)', color: '#fca5a5' };
      case 'kept':
        return { label: 'Kept As-Is', bg: 'rgba(16, 185, 129, 0.15)', border: 'rgba(16, 185, 129, 0.5)', color: '#6ee7b7' };
      default:
        return null;
    }
  };

  const kindBadge = getKindBadge(message.kind);
  const resBadge = getResolutionBadge(message.resolution);

  return (
    <div
      className="glass-panel"
      style={{
        padding: '1.25rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.75rem',
        borderLeft: isResolved
          ? '4px solid var(--success)'
          : message.kind === 'failed_tupper'
          ? '4px solid #f59e0b'
          : '4px solid var(--accent-secondary)',
      }}
    >
      {/* Header Row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span
              style={{
                background: kindBadge.bg,
                color: kindBadge.color,
                padding: '0.15rem 0.5rem',
                borderRadius: '4px',
                fontSize: '0.75rem',
                fontWeight: 700,
                textTransform: 'uppercase',
              }}
            >
              {kindBadge.label}
            </span>

            {resBadge && (
              <span
                style={{
                  background: resBadge.bg,
                  border: `1px solid ${resBadge.border}`,
                  color: resBadge.color,
                  padding: '0.15rem 0.5rem',
                  borderRadius: '4px',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                }}
              >
                ✓ {resBadge.label}
              </span>
            )}

            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              #{message.channel_name || 'unknown-channel'}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.5rem', fontSize: '0.85rem', color: 'var(--text-muted)', flexWrap: 'wrap' }}>
            
            
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              {isOverridden && originalAuthorName !== currentAuthorName && (    
                <><span style={{ color: 'var(--text-secondary)' }}>Original Author:</span><span style={{ color: 'var(--text-primary)' }}>{originalAuthorName}</span> <ArrowRight size={14}/>
                <strong style={{ color: 'var(--text-secondary)' }}>New: </strong></>
              )}
              <strong style={{ color: 'var(--text-secondary)' }}>Author:</strong><strong style={{ color: 'var(--text-primary)' }}>{currentAuthorName}</strong>
            </span>

            {message.flagged_at && (
              <span>• Flagged on {new Date(message.flagged_at).toLocaleDateString()}</span>
            )}
          </div>
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          {message.discord_link && (
            <a
              href={message.discord_link}
              target="_blank"
              rel="noopener noreferrer"
              className="action-btn"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
                padding: '0.35rem 0.65rem',
                fontSize: '0.8rem',
                background: 'var(--bg-tertiary)',
                color: 'var(--text-secondary)',
                borderRadius: '6px',
                textDecoration: 'none',
                border: '1px solid var(--border-color)',
              }}
            >
              <ExternalLink size={14} /> Discord
            </a>
          )}

          {isResolved ? (
            <button
              onClick={() => onReopen(message.message_id)}
              disabled={isReopening}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
                padding: '0.35rem 0.75rem',
                fontSize: '0.8rem',
                background: 'rgba(239, 68, 68, 0.15)',
                color: 'var(--danger)',
                border: '1px solid rgba(239, 68, 68, 0.4)',
                borderRadius: '6px',
                cursor: isReopening ? 'not-allowed' : 'pointer',
                fontWeight: 600,
              }}
            >
              {isReopening ? <Loader2 size={14} className="spin" /> : <RotateCcw size={14} />}
              Reopen
            </button>
          ) : (
            <>
              <button
                onClick={() => onPromote(message)}
                disabled={isResolving}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  padding: '0.35rem 0.75rem',
                  fontSize: '0.8rem',
                  background: 'rgba(109, 40, 217, 0.25)',
                  color: '#fff',
                  border: '1px solid var(--accent-secondary)',
                  borderRadius: '6px',
                  cursor: isResolving ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                }}
              >
                <Check size={14} /> Override
              </button>

              <button
                onClick={() => onResolve(message, 'ignored')}
                disabled={isResolving}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  padding: '0.35rem 0.75rem',
                  fontSize: '0.8rem',
                  background: 'rgba(234, 179, 8, 0.15)',
                  color: '#fde047',
                  border: '1px solid rgba(234, 179, 8, 0.4)',
                  borderRadius: '6px',
                  cursor: isResolving ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                }}
              >
                <EyeOff size={14} /> Ignore (OOC)
              </button>

              <button
                onClick={() => onResolve(message, 'kept')}
                disabled={isResolving}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  padding: '0.35rem 0.75rem',
                  fontSize: '0.8rem',
                  background: 'rgba(16, 185, 129, 0.15)',
                  color: '#6ee7b7',
                  border: '1px solid rgba(16, 185, 129, 0.4)',
                  borderRadius: '6px',
                  cursor: isResolving ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                }}
              >
                <CheckCheck size={14} /> Keep As-Is
              </button>
            </>
          )}
        </div>
      </div>

      {/* Suggested Character Quick Pill */}
      {!isResolved && suggested && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'rgba(139, 92, 246, 0.12)',
            border: '1px solid rgba(139, 92, 246, 0.3)',
            borderRadius: '6px',
            padding: '0.4rem 0.75rem',
            fontSize: '0.825rem',
            flexWrap: 'wrap',
            gap: '0.5rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <Sparkles size={14} color="#c4b5fd" />
            <span style={{ color: 'var(--text-secondary)' }}>
              Suggested:{' '}
              <strong style={{ color: '#c4b5fd' }}>{suggested.name}</strong>
              {suggested.writer_name ? ` (${suggested.writer_name})` : ''} — <em>{suggested.reason}</em>
            </span>
          </div>
          <button
            onClick={() => onPromote(message)}
            style={{
              padding: '0.2rem 0.55rem',
              borderRadius: '4px',
              border: '1px solid #8b5cf6',
              background: '#8b5cf6',
              color: '#fff',
              fontSize: '0.75rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Apply Suggestion
          </button>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.8rem', color: '#c4b5fd', fontWeight: 600 }}>
        {isMessageOverridden ? 'Original message content ' : 'Message content:'} {isMessageOverridden ? <ArrowRight size={14} /> : null} {isMessageOverridden ? 'New message content:' : ''}
      </div>

      {/* Message Content */}
      <div
        style={{
          background: 'var(--bg-tertiary)',
          padding: '0.75rem 1rem',
          borderRadius: '6px',
          fontSize: '0.85rem',
          border: '1px solid var(--border-color)',
          display: 'grid',
          gridAutoFlow: 'column',
          gridTemplateColumns: '1fr 1fr',
          gap: '0.5rem',
        }}
      >
        <div
          onClick={() => setIsExpanded(prev => !prev)}
          title={isExpanded ? 'Click to collapse' : 'Click to expand'}
          style={{
            cursor: 'pointer',
            fontStyle: 'italic',
            color: isMessageOverridden? 'var(--text-secondary)' : 'var(--text-primary)',
            whiteSpace: 'pre-wrap',
            lineHeight: '1.4',
            display: isExpanded ? 'block' : '-webkit-box',
            WebkitLineClamp: isExpanded ? undefined : 3,
            WebkitBoxOrient: 'vertical',
            overflow: isExpanded ? 'visible' : 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {message.content}
        </div>
        
        {/* Override Comparison (if Overridden) */}
        {message.resolution === 'override' && isMessageOverridden && (
          <div
            onClick={() => setIsExpanded(prev => !prev)}
            title={isExpanded ? 'Click to collapse' : 'Click to expand'}
            style={{
              cursor: 'pointer',
              fontStyle: 'italic',
              color: 'var(--text-primary)',
              borderLeft: '1px solid var(--border-color)',
              paddingLeft: '0.5rem',
              whiteSpace: 'pre-wrap',
              lineHeight: '1.4',
              display: isExpanded ? 'block' : '-webkit-box',
              WebkitLineClamp: isExpanded ? undefined : 3,
              WebkitBoxOrient: 'vertical',
              overflow: isExpanded ? 'visible' : 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {message.override_content}
          </div>
        )}
        
      </div>

      {/* Resolved Banner */}
      {isResolved && (
        <div
          style={{
            fontSize: '0.8rem',
            color: 'var(--success)',
            background: 'rgba(16, 185, 129, 0.1)',
            border: '1px solid rgba(16, 185, 129, 0.25)',
            padding: '0.35rem 0.75rem',
            borderRadius: '6px',
          }}
        >
          ✓ Resolved on {new Date(message.resolved_at!).toLocaleString()}:{' '}
          <em>{message.resolved_note || `Resolved as ${message.resolution}`}</em>
        </div>
      )}
    </div>
  );
};

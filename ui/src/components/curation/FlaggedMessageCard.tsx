import React from 'react';
import { ExternalLink, Check, RotateCcw, Sparkles, EyeOff, CheckCheck, ArrowRight } from 'lucide-react';
import { DataCard, Badge, Button } from '../ui';
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

  const cardAccent = isResolved
    ? 'resolved'
    : message.kind === 'failed_tupper'
    ? 'warning'
    : 'accent';

  const getKindBadgeVariant = (kind: string): 'warning' | 'accent' | 'info' | 'neutral' => {
    switch (kind) {
      case 'failed_tupper':
        return 'warning';
      case 'ooc_boundary':
        return 'accent';
      case 'ooc_message':
        return 'info';
      default:
        return 'neutral';
    }
  };

  const getResolutionBadgeVariant = (res?: string | null): 'accent' | 'danger' | 'success' | null => {
    switch (res) {
      case 'override':
        return 'accent';
      case 'ignored':
        return 'danger';
      case 'kept':
        return 'success';
      default:
        return null;
    }
  };

  const kindVariant = getKindBadgeVariant(message.kind);
  const resVariant = getResolutionBadgeVariant(message.resolution);

  return (
    <DataCard accent={cardAccent} className="flex-col gap-sm">
      {/* Header Row */}
      <div className="flex-row justify-between items-start flex-wrap gap-sm">
        <div className="flex-col gap-xs">
          <div className="flex-row items-center gap-xs flex-wrap">
            <Badge variant={kindVariant} className="uppercase font-bold text-sm">
              {message.kind.replace(/_/g, ' ')}
            </Badge>

            {resVariant && (
              <Badge variant={resVariant} className="text-sm font-semibold">
                ✓ {message.resolution === 'override' ? 'Overridden' : message.resolution === 'ignored' ? 'Ignored (OOC)' : 'Kept As-Is'}
              </Badge>
            )}

            <span className="text-secondary text-md">
              #{message.channel_name || 'unknown-channel'}
            </span>
          </div>

          <div className="flex-row items-center gap-xs flex-wrap text-muted text-sm mt-xs">
            <span className="flex-row items-center gap-xs">
              {isOverridden && originalAuthorName !== currentAuthorName && (
                <>
                  <span className="text-secondary">Original Author:</span>
                  <span className="text-primary">{originalAuthorName}</span>
                  <ArrowRight size={13} className="text-muted" />
                  <strong className="text-secondary">New: </strong>
                </>
              )}
              <strong className="text-secondary">Author:</strong>
              <strong className="text-primary">{currentAuthorName}</strong>
            </span>

            {message.flagged_at && (
              <span>• Flagged on {new Date(message.flagged_at).toLocaleDateString()}</span>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex-row items-center gap-xs flex-wrap">
          {message.discord_link && (
            <a
              href={message.discord_link}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-secondary btn-xs"
              style={{ padding: '0.12rem 0.45rem', fontSize: '0.72rem' }}
            >
              <ExternalLink size={11} /> Discord
            </a>
          )}

          {isResolved ? (
            <Button
              variant="danger"
              size="sm"
              onClick={() => onReopen(message.message_id)}
              disabled={isReopening}
              loading={isReopening}
              icon={<RotateCcw size={12} />}
            >
              Reopen
            </Button>
          ) : (
            <>
              <Button
                variant="primary"
                size="sm"
                onClick={() => onPromote(message)}
                disabled={isResolving}
                icon={<Check size={13} />}
              >
                Override
              </Button>

              <Button
                variant="warning"
                size="sm"
                onClick={() => onResolve(message, 'ignored')}
                disabled={isResolving}
                icon={<EyeOff size={13} />}
              >
                Ignore (OOC)
              </Button>

              <Button
                variant="success"
                size="sm"
                onClick={() => onResolve(message, 'kept')}
                disabled={isResolving}
                icon={<CheckCheck size={13} />}
              >
                Keep As-Is
              </Button>
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
          <div className="flex-row items-center gap-xs">
            <Sparkles size={14} className="text-accent" />
            <span className="text-secondary">
              Suggested:{' '}
              <strong className="text-accent">{suggested.name}</strong>
              {suggested.writer_name ? ` (${suggested.writer_name})` : ''} —{' '}
              <em>{suggested.reason}</em>
            </span>
          </div>
          <Button
            variant="secondary"
            size="xs"
            onClick={() => onPromote(message)}
          >
            Apply Suggestion
          </Button>
        </div>
      )}

      <div className="flex-row items-center gap-xs text-sm font-semibold text-accent">
        {isMessageOverridden ? 'Original message content ' : 'Message content:'}{' '}
        {isMessageOverridden ? <ArrowRight size={13} /> : null}{' '}
        {isMessageOverridden ? 'New message content:' : ''}
      </div>

      {/* Message Content */}
      <div
        className="message-excerpt-grid"
        style={{
          background: 'var(--bg-tertiary)',
          padding: '0.75rem 1rem',
          borderRadius: '6px',
          fontSize: '0.85rem',
          border: '1px solid var(--border-color)',
        }}
      >
        <div
          onClick={() => setIsExpanded(prev => !prev)}
          title={isExpanded ? 'Click to collapse' : 'Click to expand'}
          style={{
            cursor: 'pointer',
            fontStyle: 'italic',
            color: isMessageOverridden ? 'var(--text-secondary)' : 'var(--text-primary)',
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
    </DataCard>
  );
};

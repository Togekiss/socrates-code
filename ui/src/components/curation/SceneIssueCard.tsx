import React from 'react';
import { ExternalLink, Check, RotateCcw, Loader2, ArrowRight, GitMerge, Split } from 'lucide-react';
import type { SceneIssue } from '../../types';

interface SceneIssueCardProps {
  issue: SceneIssue;
  isReopening: boolean;
  onResolve: (issue: SceneIssue) => void;
  onReopen: (issueId: number) => void;
  onOppositeAction?: (action: 'merge' | 'split', issue: SceneIssue) => void;
}

export const SceneIssueCard: React.FC<SceneIssueCardProps> = ({
  issue,
  isReopening,
  onResolve,
  onReopen,
  onOppositeAction,
}) => {
  const isResolved = issue.resolved_at !== null && issue.resolved_at !== undefined;

  const getKindBadgeColor = (kind: string) => {
    switch (kind) {
      case 'auto_split':
        return '#eab308';
      case 'soft_boundary':
        return '#8b5cf6';
      default:
        return 'var(--text-secondary)';
    }
  };

  const getReasonLabel = (reason: string) => {
    switch (reason) {
      case 'separate_roster':
        return 'The participants of each part are completely different';
      case 'start_tag_roster_change':
        return 'It found a start tag, and then some participants changed';
      case 'start_tag_same_roster':
        return 'It found a start tag, but the participants remained the same';
      case 'roster_change':
        return 'Some participants changed, but not all of them';
      default:
        return reason ? reason.replace(/_/g, ' ') : 'Boundary Anomaly';
    }
  };

  const formatParticipants = (names?: string[] | null, ids?: number[] | null) => {
    if (names && names.length > 0) {
      return names.join(', ');
    }
    if (ids && ids.length > 0) {
      return ids.map(id => `#${id}`).join(', ');
    }
    return 'none';
  };

  const hasCharacters =
    (issue.previous_chars && issue.previous_chars.length > 0) ||
    (issue.next_chars && issue.next_chars.length > 0) ||
    (issue.previous_char_names && issue.previous_char_names.length > 0) ||
    (issue.next_char_names && issue.next_char_names.length > 0);

  const prevDisplay = formatParticipants(issue.previous_char_names, issue.previous_chars);
  const nextDisplay = formatParticipants(issue.next_char_names, issue.next_chars);

  const handleOpposite = (action: 'merge' | 'split') => {
    if (onOppositeAction) {
      onOppositeAction(action, issue);
    }
  };

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
          : issue.kind === 'auto_split' ? '4px solid var(--warning)' : '4px solid var(--accent-secondary)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span
              style={{
                background: getKindBadgeColor(issue.kind),
                color: '#000',
                padding: '0.15rem 0.5rem',
                borderRadius: '4px',
                fontSize: '0.75rem',
                fontWeight: 700,
                textTransform: 'uppercase',
              }}
            >
              {issue.kind.replace(/_/g, ' ')}
            </span>
            {isResolved && issue.resolution && (
              <span
                style={{
                  background:
                    issue.resolution === 'merged'
                      ? 'rgba(109, 40, 217, 0.25)'
                      : issue.resolution === 'split'
                      ? 'rgba(59, 130, 246, 0.25)'
                      : 'rgba(16, 185, 129, 0.25)',
                  border:
                    issue.resolution === 'merged'
                      ? '1px solid var(--accent-secondary)'
                      : issue.resolution === 'split'
                      ? '1px solid #3b82f6'
                      : '1px solid var(--success)',
                  color: '#fff',
                  padding: '0.15rem 0.5rem',
                  borderRadius: '4px',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  textTransform: 'capitalize',
                }}
              >
                {issue.resolution}
              </span>
            )}
            <h4 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '1.05rem', display: 'flex', alignItems: 'center', gap: '0.35rem', flexWrap: 'wrap' }}>
              Scene <code style={{ color: getKindBadgeColor(issue.kind) }}>{issue.scene_key}</code>
              {issue.next_scene_key && (
                <>
                  <ArrowRight size={14} style={{ color: 'var(--text-muted)' }} />
                  <span>Split into Scene <code style={{ color: getKindBadgeColor(issue.kind) }}>{issue.next_scene_key}</code></span>
                </>
              )}
              <span style={{ color: 'var(--text-secondary)' }}>in #{issue.channel_name}</span>
            </h4>
          </div>

          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>
            Detected: {issue.created_at ? new Date(issue.created_at).toLocaleString() : 'N/A'}
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {isResolved ? (
            <button
              onClick={() => onReopen(issue.id)}
              disabled={isReopening}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.3rem',
                padding: '0.35rem 0.75rem',
                fontSize: '0.8rem',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-secondary)',
                borderRadius: '6px',
                cursor: 'pointer',
              }}
            >
              {isReopening ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <RotateCcw size={12} />
              )}
              Reopen Issue
            </button>
          ) : issue.kind === 'auto_split' ? (
            <>
              {/* Auto-Split Action 1: Opposite resolution (Merge) */}
              <button
                onClick={() => handleOpposite('merge')}
                title="Merge these two scenes back together"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  padding: '0.35rem 0.85rem',
                  fontSize: '0.8rem',
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-primary)',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontWeight: 500,
                  transition: 'all var(--transition-fast)',
                }}
              >
                <GitMerge size={14} style={{ color: 'var(--accent-secondary)' }} />
                Merge
              </button>

              {/* Auto-Split Action 2: Accept Socrates' proposed split */}
              <button
                onClick={() => onResolve(issue)}
                title="Accept Socrates' split into two scenes"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  padding: '0.35rem 0.85rem',
                  fontSize: '0.8rem',
                  background: 'var(--success)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontWeight: 600,
                  transition: 'all var(--transition-fast)',
                }}
              >
                <Check size={14} /> Accept Split
              </button>
            </>
          ) : issue.kind === 'soft_boundary' ? (
            <>
              {/* Possible-Split Action 1: Accept Socrates' proposed resolution (Keep Merged) */}
              <button
                onClick={() => onResolve(issue)}
                title="Accept keeping this as a single continuous scene"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  padding: '0.35rem 0.85rem',
                  fontSize: '0.8rem',
                  background: 'var(--success)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontWeight: 600,
                  transition: 'all var(--transition-fast)',
                }}
              >
                <Check size={14} /> Accept Merge
              </button>

              {/* Possible-Split Action 2: Opposite resolution (Split) */}
              <button
                onClick={() => handleOpposite('split')}
                title="Split this scene at the split point"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  padding: '0.35rem 0.85rem',
                  fontSize: '0.8rem',
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-primary)',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontWeight: 500,
                  transition: 'all var(--transition-fast)',
                }}
              >
                <Split size={14} style={{ color: 'var(--accent-secondary)' }} />
                Split
              </button>
            </>
          ) : (
            <>
              {/* Fallback buttons */}
              <button
                onClick={() => handleOpposite('merge')}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  padding: '0.35rem 0.85rem',
                  fontSize: '0.8rem',
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-primary)',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontWeight: 500,
                }}
              >
                <GitMerge size={14} /> Merge
              </button>
              <button
                onClick={() => onResolve(issue)}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  padding: '0.35rem 0.85rem',
                  fontSize: '0.8rem',
                  background: 'var(--success)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontWeight: 600,
                }}
              >
                <Split size={14} /> Split
              </button>
            </>
          )}
        </div>
      </div>

      {/* Issue Details / Actionable Views */}
      <div
        style={{
          background: 'var(--bg-tertiary)',
          padding: '0.75rem 1rem',
          borderRadius: '6px',
          fontSize: '0.85rem',
          color: 'var(--text-secondary)',
          maxHeight: '220px',
          overflowY: 'auto',
          border: '1px solid var(--border-color)',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
        }}
      >
        <div>
          <strong style={{ color: 'var(--text-primary)' }}>Trigger / Reason:</strong>{' '}
          <span style={{ color: issue.kind === 'auto_split' ? '#eab308' : '#c4b5fd', fontWeight: 600 }}>
            {getReasonLabel(issue.reason)}
          </span>
        </div>

        {hasCharacters && (
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            <strong style={{ color: 'var(--text-secondary)' }}>Participants:</strong>{' '}
            [{prevDisplay}] ➔ [{nextDisplay}]
          </div>
        )}

        {issue.candidate_excerpt && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', marginTop: '0.15rem' }}>
            <strong style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
              {issue.kind === 'auto_split'
                ? 'Start of the next scene:'
                : issue.kind === 'soft_boundary'
                ? 'Possible start of the next scene:'
                : 'Message excerpt:'}
            </strong>
            <div
              style={{
                fontSize: '0.8rem',
                color: 'var(--text-secondary)',
                fontStyle: 'italic',
                background: 'rgba(0, 0, 0, 0.25)',
                padding: '0.5rem 0.75rem',
                borderRadius: '6px',
                lineHeight: '1.4',
              }}
            >
              {issue.candidate_excerpt}
            </div>
          </div>
        )}

        {issue.candidate_discord_link && (
          <div style={{ marginTop: '0.2rem' }}>
            <a
              href={issue.candidate_discord_link}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.3rem',
                padding: '0.25rem 0.6rem',
                fontSize: '0.8rem',
                background: issue.kind === 'auto_split' ? 'rgba(234, 179, 8, 0.15)' : 'rgba(139, 92, 246, 0.2)',
                border: issue.kind === 'auto_split' ? '1px solid rgba(234, 179, 8, 0.5)' : '1px solid #8b5cf6',
                color: issue.kind === 'auto_split' ? '#fde047' : '#c4b5fd',
                borderRadius: '6px',
                textDecoration: 'none',
                fontWeight: 600,
              }}
            >
              <ExternalLink size={12} /> Jump to Split Point in Discord
            </a>
          </div>
        )}
      </div>

      {/* Resolved Note Banner */}
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
          ✓ Resolved on {new Date(issue.resolved_at!).toLocaleString()}:{' '}
          <em>{issue.resolved_note || 'Resolved by reviewer'}</em>
        </div>
      )}
    </div>
  );
};

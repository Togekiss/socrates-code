import React from 'react';
import { ExternalLink, Check, RotateCcw, Loader2 } from 'lucide-react';
import type { SceneIssue } from '../../types';

interface SceneIssueCardProps {
  issue: SceneIssue;
  isReopening: boolean;
  onResolve: (issue: SceneIssue) => void;
  onReopen: (issueId: number) => void;
}

export const SceneIssueCard: React.FC<SceneIssueCardProps> = ({
  issue,
  isReopening,
  onResolve,
  onReopen,
}) => {
  const isResolved = issue.resolved_at !== null && issue.resolved_at !== undefined;

  const getKindBadgeColor = (kind: string) => {
    switch (kind) {
      case 'gap_too_long':
        return 'var(--warning)';
      case 'consecutive_authors':
        return '#f97316';
      case 'non_tupper_dialogue':
        return 'var(--accent-secondary)';
      case 'unlinked_author':
        return 'var(--danger)';
      default:
        return 'var(--text-secondary)';
    }
  };

  const details = issue.details as { start?: { content?: string }; end?: { content?: string } } | null;

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
          : '4px solid var(--danger)',
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
            <h4 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '1.05rem' }}>
              Scene <code style={{ color: 'var(--accent-secondary)' }}>{issue.scene_key}</code> in #{issue.channel_name}
            </h4>
          </div>

          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>
            Detected: {issue.created_at ? new Date(issue.created_at).toLocaleString() : 'N/A'}
            {issue.discord_user_id && <> • Snowflake: <code>{issue.discord_user_id}</code></>}
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          {issue.discord_link && (
            <a
              href={issue.discord_link}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.3rem',
                padding: '0.35rem 0.75rem',
                fontSize: '0.8rem',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-primary)',
                borderRadius: '6px',
                textDecoration: 'none',
              }}
            >
              <ExternalLink size={12} /> View in Discord
            </a>
          )}

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
          ) : (
            <button
              onClick={() => onResolve(issue)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.3rem',
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
              <Check size={14} /> Resolve Issue
            </button>
          )}
        </div>
      </div>

      {/* Issue Details / Discarded Snippets */}
      {issue.details && (
        <div
          style={{
            background: 'var(--bg-tertiary)',
            padding: '0.75rem 1rem',
            borderRadius: '6px',
            fontSize: '0.85rem',
            color: 'var(--text-secondary)',
            maxHeight: '130px',
            overflowY: 'auto',
            border: '1px solid var(--border-color)',
          }}
        >
          {details?.start?.content && (
            <div>
              <strong style={{ color: 'var(--text-primary)' }}>Discarded Start:</strong>{' '}
              {details.start.content.slice(0, 250)}...
            </div>
          )}
          {details?.end?.content && (
            <div style={{ marginTop: '0.35rem' }}>
              <strong style={{ color: 'var(--text-primary)' }}>Discarded End:</strong>{' '}
              {details.end.content.slice(0, 250)}...
            </div>
          )}
          {!details?.start && !details?.end && (
            <pre style={{ margin: 0, fontSize: '0.75rem', overflowX: 'auto' }}>
              {JSON.stringify(issue.details, null, 2)}
            </pre>
          )}
        </div>
      )}

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

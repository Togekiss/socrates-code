import React from 'react';
import { ExternalLink, Check, RotateCcw, ArrowRight, GitMerge, Split } from 'lucide-react';
import { DataCard, Badge, Button } from '../ui';
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

  const cardAccent = isResolved
    ? 'resolved'
    : issue.kind === 'auto_split'
    ? 'warning'
    : 'accent';

  const getSceneKindLabel = (kind?: string) => {
    if (kind === 'event') return 'Event';
    if (kind === 'session') return 'Session';
    return 'Scene';
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
      case 'manual':
        return 'Manually split by curator';
      case 'inactivity_gap':
        return '48-hour inactivity gap between messages';
      case 'tupper_end_tag':
        return 'Tupperbox end tag, but conversation continued';
      default:
        return reason ? reason.replace(/_/g, ' ') : 'Boundary Anomaly';
    }
  };

  const formatParticipants = (names?: string[] | null, ids?: number[] | null) => {
    if (names && names.length > 0) return names.join(', ');
    if (ids && ids.length > 0) return ids.map(id => `#${id}`).join(', ');
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
    <DataCard accent={cardAccent} className="flex-col gap-sm">
      {/* Top Bar: Kind Badge & Actions */}
      <div className="flex-row justify-between items-start flex-wrap gap-sm">
        <div className="flex-col gap-xs">
          <div className="flex-row items-center gap-xs flex-wrap">
            <Badge
              variant={issue.kind === 'auto_split' ? 'warning' : 'accent'}
              className="uppercase font-bold text-sm"
            >
              {issue.kind.replace(/_/g, ' ')}
            </Badge>

            {isResolved && (
              <Badge variant="success" className="text-sm font-semibold">
                ✓ {issue.resolution === 'split' ? 'SPLIT' : issue.resolution === 'merged' ? 'MERGED' : 'RESOLVED'}
              </Badge>
            )}

            {issue.discord_link && (
              <a
                href={issue.discord_link}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-secondary btn-xs"
                style={{ padding: '0.12rem 0.45rem', fontSize: '0.72rem' }}
              >
                <ExternalLink size={11} /> Discord
              </a>
            )}
          </div>

          <div className="mt-xs">
            <h4
              className="text-primary flex-row items-center gap-xs flex-wrap m-0"
              style={{ fontSize: '1rem' }}
            >
              <span>
                {getSceneKindLabel(issue.scene_kind)}{' '}
                <code className="text-accent">{issue.scene_key}</code>
              </span>
              {issue.next_scene_key && (
                <>
                  <ArrowRight size={14} className="text-muted" />
                  <span>
                    Split into {getSceneKindLabel(issue.scene_kind)}{' '}
                    <code className="text-accent">{issue.next_scene_key}</code>
                  </span>
                </>
              )}
              <span className="text-secondary font-normal text-md">
                in #{issue.channel_name}
              </span>
            </h4>
          </div>

          <div className="text-muted text-sm">
            Detected: {issue.created_at ? new Date(issue.created_at).toLocaleString() : 'N/A'}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex-row items-center gap-xs flex-wrap">
          {isResolved ? (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => onReopen(issue.id)}
              disabled={isReopening}
              loading={isReopening}
              icon={<RotateCcw size={12} />}
            >
              Reopen Issue
            </Button>
          ) : issue.kind === 'auto_split' ? (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => handleOpposite('merge')}
                title="Merge these two scenes back together"
                icon={<GitMerge size={14} />}
              >
                Merge
              </Button>
              <Button
                variant="success"
                size="sm"
                onClick={() => onResolve(issue)}
                title="Accept Socrates' split into two scenes"
                icon={<Check size={14} />}
              >
                Accept Split
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="success"
                size="sm"
                onClick={() => onResolve(issue)}
                title="Accept keeping this as a single continuous scene"
                icon={<Check size={14} />}
              >
                Accept Merge
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => handleOpposite('split')}
                title="Split this scene at the split point"
                icon={<Split size={14} />}
              >
                Split
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Details Box */}
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
          <strong className="text-primary">Trigger / Reason:</strong>{' '}
          <span
            style={{
              color: issue.kind === 'auto_split' ? '#eab308' : '#c4b5fd',
              fontWeight: 600,
            }}
          >
            {getReasonLabel(issue.reason)}
          </span>
        </div>

        {hasCharacters && (
          <div className="text-secondary text-sm">
            <strong>Participants:</strong> [{prevDisplay}] ➔ [{nextDisplay}]
          </div>
        )}

        {issue.candidate_excerpt && (
          <div className="flex-col gap-xs mt-xs">
            <strong className="text-secondary text-sm">
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
          <div className="mt-xs">
            <a
              href={issue.candidate_discord_link}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-secondary btn-xs"
              style={{
                background:
                  issue.kind === 'auto_split'
                    ? 'rgba(234, 179, 8, 0.15)'
                    : 'rgba(139, 92, 246, 0.2)',
                border:
                  issue.kind === 'auto_split'
                    ? '1px solid rgba(234, 179, 8, 0.5)'
                    : '1px solid #8b5cf6',
                color: issue.kind === 'auto_split' ? '#fde047' : '#c4b5fd',
                fontWeight: 600,
              }}
            >
              <ExternalLink size={12} /> Jump to Split Point in Discord
            </a>
          </div>
        )}
      </div>

      {/* Resolved Banner */}
      {isResolved && (
        <div
          className="badge-success p-xs border-radius-sm text-sm"
          style={{
            background: 'rgba(16, 185, 129, 0.1)',
            border: '1px solid rgba(16, 185, 129, 0.25)',
            color: 'var(--success)',
            padding: '0.35rem 0.75rem',
            borderRadius: '6px',
          }}
        >
          ✓ Resolved on {new Date(issue.resolved_at!).toLocaleString()}:{' '}
          <em>{issue.resolved_note || 'Resolved by reviewer'}</em>
        </div>
      )}
    </DataCard>
  );
};

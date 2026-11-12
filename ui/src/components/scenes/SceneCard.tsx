import React from 'react';
import { Check, AlertCircle, Edit3 } from 'lucide-react';
import { DataCard, Badge, Button, FilterChip } from '../ui';
import { MessageExcerptAccordion } from './MessageExcerptAccordion';
import { resolveCharacterName } from '../../utils/characters';
import { formatTimestamp } from '../../utils/formatters';
import type { Character, Scene, SceneIssueRef } from '../../types';

interface SceneCardProps {
  scene: Scene;
  allCharacters: Character[];
  charactersFilter: number[];
  setCharactersFilter: (filter: number[]) => void;
  onEdit?: (scene: Scene) => void;
}

export const SceneCard: React.FC<SceneCardProps> = ({
  scene,
  allCharacters,
  charactersFilter,
  setCharactersFilter,
  onEdit,
}) => {
  const hasUnresolvedIssues =
    scene.issues &&
    scene.issues.some((i: SceneIssueRef) => !i.resolved && !i.resolved_at);

  const cardAccent = hasUnresolvedIssues
    ? 'warning'
    : scene.status === 'no_end_tag'
    ? 'danger'
    : undefined;

  const startTs = formatTimestamp(scene.start?.timestamp);
  const msgCount =
    scene.end && scene.start && typeof scene.end.index === 'number' && typeof scene.start.index === 'number'
      ? Math.max(0, scene.end.index - scene.start.index + 1)
      : 0;

  return (
    <DataCard accent={cardAccent} className="flex-col gap-sm">
      {/* Header Row */}
      <div className="flex-row justify-between items-start flex-wrap gap-sm">
        {/* Title and metadata */}
        <div className="flex-row items-baseline gap-xs flex-wrap">
          {scene.custom_name ? (
            <>
              <strong className="text-primary" style={{ fontSize: '1rem' }}>
                {scene.custom_name}
              </strong>
              <span className="text-secondary text-md">
                ({scene.category} &gt; #{scene.channel}
                {scene.type === 'thread' ? ` | ${scene.thread_name || 'Thread'}` : ''})
              </span>
            </>
          ) : (
            <>
              <strong className="text-primary" style={{ fontSize: '0.95rem' }}>
                {scene.category} &gt; #{scene.channel}
              </strong>
              {scene.type === 'thread' && (
                <span className="text-secondary text-md">
                  | {scene.thread_name || 'Thread'}
                </span>
              )}
            </>
          )}
          {startTs && (
            <span className="text-secondary text-sm" style={{ marginLeft: '0.25rem' }}>
              {startTs}
            </span>
          )}
        </div>

        {/* Status badges, counts, and FAR RIGHT Edit button */}
        <div className="flex-row items-center gap-xs flex-wrap">
          <Badge
            variant={scene.status === 'no_end_tag' ? 'danger' : 'neutral'}
            className="text-sm uppercase font-semibold"
          >
            {scene.status === 'no_end_tag' ? 'Split (Issues)' : scene.status}
          </Badge>

          {scene.issues &&
            scene.issues.map((issue: SceneIssueRef) => {
              const isResolved = issue.resolved || Boolean(issue.resolved_at);
              const kindLabel =
                issue.kind === 'auto_split'
                  ? 'Auto Split'
                  : issue.kind === 'soft_boundary'
                  ? 'Soft Boundary'
                  : (issue.kind || 'Issue').replace(/_/g, ' ');

              const tooltipText = isResolved
                ? `Resolved Issue: ${kindLabel}${issue.resolution ? ` (${issue.resolution})` : ''}${issue.resolved_note ? ` — ${issue.resolved_note}` : ''}`
                : `Unresolved Issue: ${kindLabel}${issue.reason ? ` (${issue.reason.replace(/_/g, ' ')})` : ''}`;

              return (
                <Badge
                  key={issue.id}
                  variant={isResolved ? 'success' : issue.kind === 'auto_split' ? 'warning' : 'accent'}
                  title={tooltipText}
                  className="flex-row items-center gap-xs text-sm font-semibold"
                >
                  {isResolved ? <Check size={11} /> : <AlertCircle size={11} />}
                  <span>{isResolved ? `${kindLabel} (Resolved)` : kindLabel}</span>
                </Badge>
              );
            })}

          <span className="text-secondary text-sm font-medium" style={{ margin: '0 0.25rem' }}>
            {msgCount} msgs
          </span>

          {/* EDIT BUTTON ALWAYS ON THE FAR RIGHT */}
          {onEdit && (
            <Button
              variant="secondary"
              size="xs"
              onClick={() => onEdit(scene)}
              icon={<Edit3 size={12} />}
              title="Edit custom name"
            >
              Edit
            </Button>
          )}
        </div>
      </div>

      {/* Character Pills */}
      <div className="flex-row flex-wrap gap-xs items-center">
        {(scene.characters || []).map((cid: number) => {
          const name = resolveCharacterName(cid, allCharacters);
          const isKnown = Boolean(name);
          const isSelected = charactersFilter.includes(cid);

          return (
            <FilterChip
              key={cid}
              active={isSelected}
              onClick={() => {
                if (isKnown) {
                  if (isSelected) {
                    setCharactersFilter(charactersFilter.filter(id => id !== cid));
                  } else {
                    setCharactersFilter([...charactersFilter, cid]);
                  }
                }
              }}
              title={
                isSelected
                  ? 'Remove character filter'
                  : isKnown
                  ? 'Filter by this character'
                  : `Unknown character ID #${cid}`
              }
              className={!isKnown ? 'opacity-50' : ''}
            >
              {name || `Unknown (${cid})`}
            </FilterChip>
          );
        })}
      </div>

      {/* Message Excerpt & Jump Links Accordion */}
      <MessageExcerptAccordion
        start={scene.start}
        end={scene.end}
        startExcerpt={scene.start_excerpt}
        endExcerpt={scene.end_excerpt}
        allCharacters={allCharacters}
      />
    </DataCard>
  );
};

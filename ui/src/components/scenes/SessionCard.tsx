import React from 'react';
import { Check, AlertCircle, Edit3 } from 'lucide-react';
import { DataCard, Badge, Button, FilterChip } from '../ui';
import { MessageExcerptAccordion } from './MessageExcerptAccordion';
import { resolveCharacterName } from '../../utils/characters';
import { formatTimestamp, getDurationInfo } from '../../utils/formatters';
import type { Character, ChatSession, Scene, SceneIssueRef, SceneParticipantDetail } from '../../types';

interface SessionCardProps {
  session: ChatSession | Scene;
  allCharacters: Character[];
  charactersFilter: number[];
  setCharactersFilter: (filter: number[]) => void;
  onEdit?: (session: ChatSession | Scene) => void;
}

export const SessionCard: React.FC<SessionCardProps> = ({
  session,
  allCharacters,
  charactersFilter,
  setCharactersFilter,
  onEdit,
}) => {
  const hasUnresolvedIssues =
    session.issues &&
    session.issues.some((i: SceneIssueRef) => !i.resolved && !i.resolved_at);

  const cardAccent = hasUnresolvedIssues
    ? 'warning'
    : session.status === 'no_end_tag'
    ? 'danger'
    : undefined;

  const startTs = formatTimestamp(session.start?.timestamp);
  const endTs = formatTimestamp(session.end?.timestamp);
  const duration = getDurationInfo(session.start?.timestamp, session.end?.timestamp);

  const messageCount =
    session.end &&
    session.start &&
    typeof session.end.index === 'number' &&
    typeof session.start.index === 'number'
      ? Math.max(0, session.end.index - session.start.index + 1)
      : 0;

  // Extract structured participants
  const rawParticipants = (session.participants || []) as SceneParticipantDetail[];
  const participantsList: SceneParticipantDetail[] = rawParticipants.map((p, idx) => {
    if (typeof p === 'object' && 'char_id' in p) {
      return p;
    }
    return {
      char_id: (p as unknown as { character_id: number }).character_id || 0,
      position: idx,
    };
  });

  return (
    <DataCard accent={cardAccent} className="flex-col gap-sm">
      {/* Header row: Category > Channel, Timestamps, Badges, Msg count, FAR RIGHT Edit */}
      <div className="flex-row justify-between items-start flex-wrap gap-sm">
        <div className="flex-row items-baseline gap-xs flex-wrap">
          {session.custom_name ? (
            <>
              <strong className="text-primary" style={{ fontSize: '1rem' }}>
                {session.custom_name}
              </strong>
              <span className="text-secondary text-md">
                ({session.category} &gt; #{session.channel})
              </span>
            </>
          ) : (
            <strong className="text-primary" style={{ fontSize: '0.95rem' }}>
              {session.category} &gt; #{session.channel}
            </strong>
          )}

          {duration && (
            <Badge variant="accent" title={duration.tooltip} className="text-sm font-semibold">
              {duration.label}
            </Badge>
          )}

          <span className="text-secondary text-sm" style={{ marginLeft: '0.25rem' }}>
            {startTs && endTs ? `${startTs} — ${endTs}` : startTs || endTs || 'N/A'}
          </span>
        </div>

        {/* Right action area */}
        <div className="flex-row items-center gap-xs flex-wrap">
          <Badge
            variant={session.status === 'no_end_tag' ? 'danger' : 'neutral'}
            className="text-sm uppercase font-semibold"
          >
            {session.status === 'no_end_tag' ? 'Split (Issues)' : session.status}
          </Badge>

          {session.issues &&
            session.issues.map((issue: SceneIssueRef) => {
              const isResolved = issue.resolved || Boolean(issue.resolved_at);
              const kindLabel =
                issue.kind === 'auto_split'
                  ? 'Split'
                  : issue.kind === 'soft_boundary'
                  ? 'Soft Boundary'
                  : (issue.kind || 'Issue').replace(/_/g, ' ');

              return (
                <Badge
                  key={issue.id}
                  variant={isResolved ? 'success' : issue.kind === 'auto_split' ? 'warning' : 'accent'}
                  title={
                    isResolved
                      ? `Resolved: ${kindLabel}${issue.resolution ? ` (${issue.resolution})` : ''}`
                      : `Issue: ${kindLabel}`
                  }
                  className="flex-row items-center gap-xs text-sm font-semibold"
                >
                  {isResolved ? <Check size={11} /> : <AlertCircle size={11} />}
                  <span>{kindLabel}</span>
                </Badge>
              );
            })}

          <span className="text-secondary text-sm font-medium" style={{ margin: '0 0.25rem' }}>
            {messageCount} msgs
          </span>

          {/* EDIT BUTTON ALWAYS ON THE FAR RIGHT */}
          {onEdit && (
            <Button
              variant="secondary"
              size="xs"
              onClick={() => onEdit(session)}
              icon={<Edit3 size={12} />}
              title="Edit custom name"
            >
              Edit
            </Button>
          )}
        </div>
      </div>

      {/* Participant Pills */}
      <div className="flex-row flex-wrap gap-xs items-center">
        {participantsList.map(p => {
          const cid = p.char_id;
          const name = resolveCharacterName(cid, allCharacters) || `Tupper #${cid}`;
          const isKnown = Boolean(resolveCharacterName(cid, allCharacters));
          const isSelected = charactersFilter.includes(cid);

          return (
            <FilterChip
              key={cid}
              active={isSelected}
              onClick={() => {
                if (isSelected) {
                  setCharactersFilter(charactersFilter.filter(id => id !== cid));
                } else {
                  setCharactersFilter([...charactersFilter, cid]);
                }
              }}
              title={
                isSelected
                  ? 'Remove character filter'
                  : isKnown
                  ? 'Filter by this character'
                  : `Unknown character #${cid}`
              }
              className={!isKnown ? 'opacity-50' : ''}
            >
              {name}
            </FilterChip>
          );
        })}
      </div>

      {/* Accordion with Excerpts, Jump Links & Ordered Participant Timeline */}
      <MessageExcerptAccordion
        start={session.start}
        end={session.end}
        startExcerpt={session.start_excerpt}
        endExcerpt={session.end_excerpt}
        participants={participantsList}
        allCharacters={allCharacters}
      />
    </DataCard>
  );
};

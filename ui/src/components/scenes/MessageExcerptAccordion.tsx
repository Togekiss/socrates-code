import React, { useState } from 'react';
import { ExternalLink, ChevronDown, ChevronRight, Users } from 'lucide-react';
import { formatTimestamp, getDurationInfo } from '../../utils/formatters';
import { resolveCharacterName } from '../../utils/characters';
import type { Character, SceneParticipantDetail } from '../../types';

export interface MessageExcerptMessage {
  timestamp?: string | null;
  content?: string | null;
  excerpt?: string | null;
  link?: string | null;
}

export interface MessageExcerptAccordionProps {
  start?: MessageExcerptMessage | null;
  end?: MessageExcerptMessage | null;
  startExcerpt?: string | null;
  endExcerpt?: string | null;
  participants?: SceneParticipantDetail[] | null;
  allCharacters?: Character[];
  defaultExpanded?: boolean;
  className?: string;
}

export const MessageExcerptAccordion: React.FC<MessageExcerptAccordionProps> = ({
  start,
  end,
  startExcerpt,
  endExcerpt,
  participants,
  allCharacters = [],
  defaultExpanded = false,
  className = '',
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const resolvedStartExcerpt =
    startExcerpt || start?.content || start?.excerpt || '';
  const resolvedEndExcerpt =
    endExcerpt || end?.content || end?.excerpt || '';

  const hasStartExcerpt = Boolean(resolvedStartExcerpt && resolvedStartExcerpt.trim());
  const hasEndExcerpt = Boolean(resolvedEndExcerpt && resolvedEndExcerpt.trim());

  const formattedStartTs = formatTimestamp(start?.timestamp);
  const formattedEndTs = formatTimestamp(end?.timestamp);

  const hasParticipants = Boolean(participants && participants.length > 0);

  return (
    <div className={`flex-col gap-xs ${className}`.trim()}>
      {/* Discord Jump Links */}
      <div className="flex-row items-center gap-sm flex-wrap mt-xs">
        {start?.link ? (
          <a
            href={start.link}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-secondary btn-xs"
            title="Open first message in Discord"
          >
            <ExternalLink size={12} /> Open first message in Discord
          </a>
        ) : (
          <span
            className="btn btn-secondary btn-xs"
            style={{ opacity: 0.5, cursor: 'not-allowed' }}
          >
            <ExternalLink size={12} /> Open first message in Discord
          </span>
        )}

        {end?.link ? (
          <a
            href={end.link}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-secondary btn-xs"
            title="Open last message in Discord"
          >
            <ExternalLink size={12} /> Open last message in Discord
          </a>
        ) : (
          <span
            className="btn btn-secondary btn-xs"
            style={{ opacity: 0.5, cursor: 'not-allowed' }}
          >
            <ExternalLink size={12} /> Open last message in Discord
          </span>
        )}
      </div>

      {/* Accordion Trigger & Body */}
      <div
        style={{
          borderTop: '1px solid var(--border-color)',
          marginTop: '0.5rem',
          paddingTop: '0.25rem',
        }}
      >
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="btn btn-ghost btn-xs w-full"
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            width: '100%',
            textAlign: 'left',
            padding: '0.35rem 0.5rem',
          }}
        >
          <div className="flex-row items-center gap-xs text-secondary">
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <span style={{ fontSize: '0.8rem', fontWeight: 500 }}>
              Message Previews {hasParticipants ? '& Timeline' : ''}
            </span>
          </div>
          {hasParticipants && (
            <span
              className="text-secondary flex-row items-center gap-xs"
              style={{ fontSize: '0.75rem' }}
            >
              <Users size={12} /> {participants!.length}
            </span>
          )}
        </button>

        {expanded && (
          <div
            style={{
              padding: '0.75rem 0.5rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.75rem',
            }}
          >
            {/* 2-column desktop, 1-column mobile collapse */}
            <div className="message-excerpt-grid">
              {/* First Message */}
              <div className="flex-col gap-xs">
                <div className="flex-row items-center justify-between">
                  <strong style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    First Message:
                  </strong>
                  {formattedStartTs && (
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {formattedStartTs}
                    </span>
                  )}
                </div>
                <div
                  style={{
                    fontSize: '0.8rem',
                    color: 'var(--text-secondary)',
                    fontStyle: 'italic',
                    background: 'rgba(0, 0, 0, 0.25)',
                    border: '1px solid var(--border-color)',
                    padding: '0.5rem 0.75rem',
                    borderRadius: '6px',
                    lineHeight: '1.4',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {hasStartExcerpt ? (
                    resolvedStartExcerpt
                  ) : (
                    <span style={{ opacity: 0.5, fontStyle: 'normal' }}>
                      No start message excerpt available.
                    </span>
                  )}
                </div>
              </div>

              {/* Last Message */}
              <div className="flex-col gap-xs">
                <div className="flex-row items-center justify-between">
                  <strong style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Last Message:
                  </strong>
                  {formattedEndTs && (
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {formattedEndTs}
                    </span>
                  )}
                </div>
                <div
                  style={{
                    fontSize: '0.8rem',
                    color: 'var(--text-secondary)',
                    fontStyle: 'italic',
                    background: 'rgba(0, 0, 0, 0.25)',
                    border: '1px solid var(--border-color)',
                    padding: '0.5rem 0.75rem',
                    borderRadius: '6px',
                    lineHeight: '1.4',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {hasEndExcerpt ? (
                    resolvedEndExcerpt
                  ) : (
                    <span style={{ opacity: 0.5, fontStyle: 'normal' }}>
                      No end message excerpt available.
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Participant Timeline & Hops */}
            {hasParticipants && (
              <div
                style={{
                  marginTop: '0.25rem',
                  paddingTop: '0.5rem',
                  borderTop: '1px solid var(--border-color)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.4rem',
                }}
              >
                <div
                  className="flex-row items-center gap-xs text-secondary"
                  style={{ fontSize: '0.8rem', fontWeight: 600 }}
                >
                  <Users size={13} />
                  <span>Participant Timeline ({participants!.length}):</span>
                </div>

                <div
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.35rem',
                    background: 'rgba(0, 0, 0, 0.2)',
                    borderRadius: '4px',
                    padding: '0.5rem 0.75rem',
                    border: '1px solid rgba(255, 255, 255, 0.05)',
                  }}
                >
                  {participants!.map((p, idx) => {
                    const charName =
                      resolveCharacterName(p.char_id, allCharacters) ||
                      `Tupper #${p.char_id}`;
                    const pFirst = formatTimestamp(p.first_timestamp);
                    const pLast = formatTimestamp(p.last_timestamp);
                    const pDur = getDurationInfo(p.first_timestamp, p.last_timestamp);

                    return (
                      <div
                        key={`${p.char_id}-${idx}`}
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          fontSize: '0.75rem',
                          padding: '0.3rem 0',
                          borderBottom:
                            idx < participants!.length - 1
                              ? '1px solid rgba(255, 255, 255, 0.04)'
                              : 'none',
                          flexWrap: 'wrap',
                          gap: '0.5rem',
                        }}
                      >
                        <div
                          style={{
                            display: 'flex',
                            gap: '0.5rem',
                            alignItems: 'center',
                            flexWrap: 'wrap',
                          }}
                        >
                          <span
                            style={{
                              color: 'var(--accent-secondary)',
                              fontWeight: 600,
                              minWidth: '1.5rem',
                            }}
                          >
                            #{idx + 1}
                          </span>
                          <strong style={{ color: 'var(--text-primary)' }}>{charName}</strong>
                          {pDur && (
                            <span
                              title={pDur.tooltip}
                              style={{
                                padding: '0.1rem 0.45rem',
                                borderRadius: '4px',
                                fontSize: '0.7rem',
                                fontWeight: 600,
                                background: 'rgba(255, 255, 255, 0.08)',
                                border: '1px solid rgba(139, 92, 246, 0.3)',
                                color: '#c4b5fd',
                              }}
                            >
                              {pDur.label}
                            </span>
                          )}
                        </div>

                        <div
                          style={{
                            display: 'flex',
                            gap: '0.75rem',
                            alignItems: 'center',
                            color: 'var(--text-secondary)',
                            flexWrap: 'wrap',
                          }}
                        >
                          {pFirst && (
                            <div
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '0.35rem',
                              }}
                            >
                              <span>First: {pFirst}</span>
                              {p.first_link && (
                                <a
                                  href={p.first_link}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="btn btn-secondary btn-xs"
                                  title="Open first message in Discord"
                                  style={{ padding: '0.1rem 0.35rem', fontSize: '0.7rem' }}
                                >
                                  <ExternalLink size={10} /> Discord
                                </a>
                              )}
                            </div>
                          )}
                          {pLast && (
                            <div
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '0.35rem',
                              }}
                            >
                              <span>Last: {pLast}</span>
                              {p.last_link && (
                                <a
                                  href={p.last_link}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="btn btn-secondary btn-xs"
                                  title="Open last message in Discord"
                                  style={{ padding: '0.1rem 0.35rem', fontSize: '0.7rem' }}
                                >
                                  <ExternalLink size={10} /> Discord
                                </a>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

import React, { useState } from 'react';
import { ExternalLink, ChevronDown, ChevronRight, Check, AlertCircle, Users, Edit3 } from 'lucide-react';
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
  const [expanded, setExpanded] = useState(false);

  const getCharName = (id: number): string | null => {
    const main = allCharacters.find(c => c.id === id);
    if (main && main.names && main.names.length > 0) return main.names[0];
    for (const c of allCharacters) {
      if (c.versions) {
        const nested = c.versions.find(v => v.id === id);
        if (nested && nested.name) return nested.name;
      }
    }
    return null;
  };

  const formatTimestamp = (ts?: string | null): string | null => {
    if (!ts) return null;
    try {
      const d = new Date(ts);
      return isNaN(d.getTime()) ? null : d.toLocaleString();
    } catch {
      return null;
    }
  };

  const getDurationHours = (
    startTs?: string | null,
    endTs?: string | null
  ): { label: string; tooltip: string } | null => {
    if (!startTs || !endTs) return null;
    try {
      const startTime = new Date(startTs).getTime();
      const endTime = new Date(endTs).getTime();
      if (isNaN(startTime) || isNaN(endTime) || endTime < startTime) return null;
      const diffMs = endTime - startTime;
      const totalHours = diffMs / (1000 * 60 * 60);
      const totalMinutes = Math.round(diffMs / (1000 * 60));

      if (diffMs === 0) {
        return { label: '0 hours', tooltip: 'Duration: 0 minutes' };
      }

      if (totalHours < 0.05) {
        return {
          label: '< 0.1 hours',
          tooltip: `Duration: ${totalMinutes} minute${totalMinutes === 1 ? '' : 's'}`,
        };
      }

      const formatted = totalHours.toFixed(1).replace(/\.0$/, '');
      const unit = formatted === '1' ? 'hour' : 'hours';
      return {
        label: `${formatted} ${unit}`,
        tooltip: `Duration: ${totalHours.toFixed(2)} hours (${totalMinutes} minute${totalMinutes === 1 ? '' : 's'})`,
      };
    } catch {
      return null;
    }
  };

  const startTs = formatTimestamp(session.start?.timestamp);
  const endTs = formatTimestamp(session.end?.timestamp);
  const duration = getDurationHours(session.start?.timestamp, session.end?.timestamp);
  const messageCount =
    session.end && session.start && typeof session.end.index === 'number' && typeof session.start.index === 'number'
      ? Math.max(0, session.end.index - session.start.index + 1)
      : 0;

  // Cast or extract participants
  const rawParticipants = (session.participants || []) as SceneParticipantDetail[];
  const participantsList: SceneParticipantDetail[] = rawParticipants.map((p, idx) => {
    if (typeof p === 'object' && 'char_id' in p) {
      return p;
    }
    // Fallback if structured as legacy SceneParticipant
    return {
      char_id: (p as unknown as { character_id: number }).character_id || 0,
      position: idx,
    };
  });

  return (
    <div
      style={{
        background: 'var(--bg-tertiary)',
        borderRadius: '6px',
        overflow: 'hidden',
        border: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div style={{ padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {/* Header row: Category > Channel, Timestamps, Badges, Msg count */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'baseline', flexWrap: 'wrap' }}>
              {session.custom_name ? (
                <>
                  <strong style={{ fontSize: '1rem', color: 'var(--text-primary)' }}>
                    {session.custom_name}
                  </strong>
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                    ({session.category} &gt; #{session.channel})
                  </span>
                </>
              ) : (
                <strong style={{ fontSize: '0.95rem', color: 'var(--text-primary)' }}>
                  {session.category} &gt; #{session.channel}
                </strong>
              )}
              {duration && (
                <span
                  title={duration.tooltip}
                  style={{
                    padding: '0.1rem 0.45rem',
                    borderRadius: '4px',
                    fontSize: '0.8rem',
                    fontWeight: 600,
                    background: 'rgba(255,255,255,0.08)',
                    border: '1px solid rgba(139, 92, 246, 0.3)',
                    color: '#c4b5fd',
                  }}
                >
                  {duration.label}
                </span>
              )}
              <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{startTs && endTs ? `${startTs} — ${endTs}` : startTs || endTs || 'N/A'}</span>
            </div>
            
          </div>

          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
            {onEdit && (
              <button
                type="button"
                onClick={() => onEdit(session)}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.25rem',
                  padding: '0.2rem 0.5rem',
                  background: 'rgba(255,255,255,0.08)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-primary)',
                  borderRadius: '4px',
                  fontSize: '0.75rem',
                  cursor: 'pointer',
                  fontWeight: 500,
                }}
                title="Edit custom name"
              >
                <Edit3 size={12} />
                <span>Edit</span>
              </button>
            )}
            <span
              style={{
                padding: '0.2rem 0.5rem',
                background: session.status === 'no_end_tag' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(255,255,255,0.08)',
                border: session.status === 'no_end_tag' ? '1px solid var(--danger)' : '1px solid var(--border-color)',
                color: session.status === 'no_end_tag' ? 'var(--danger)' : 'var(--text-secondary)',
                borderRadius: '4px',
                fontSize: '0.75rem',
                fontWeight: 600,
                textTransform: 'uppercase',
              }}
            >
              {session.status === 'no_end_tag' ? 'Split (Issues)' : session.status}
            </span>

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
                  <span
                    key={issue.id}
                    title={
                      isResolved
                        ? `Resolved: ${kindLabel}${issue.resolution ? ` (${issue.resolution})` : ''}`
                        : `Issue: ${kindLabel}`
                    }
                    style={{
                      padding: '0.2rem 0.5rem',
                      borderRadius: '4px',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.3rem',
                      background: isResolved ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                      border: isResolved ? '1px solid var(--success)' : '1px solid #f59e0b',
                      color: isResolved ? '#34d399' : '#fbbf24',
                    }}
                  >
                    {isResolved ? <Check size={12} /> : <AlertCircle size={12} />}
                    {kindLabel}
                  </span>
                );
              })}

            <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 500 }}>
              {messageCount} msgs
            </span>
          </div>
        </div>

        {/* Compacted Participant Pills (order of apparition) */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', alignItems: 'center' }}>
          
          {participantsList.map(p => {
            const cid = p.char_id;
            const name = getCharName(cid) || `Tupper #${cid}`;
            const isKnown = !!getCharName(cid);
            const isSelected = charactersFilter.includes(cid);

            return (
              <button
                key={cid}
                type="button"
                onClick={() => {
                  if (isSelected) {
                    setCharactersFilter(charactersFilter.filter(id => id !== cid));
                  } else {
                    setCharactersFilter([...charactersFilter, cid]);
                  }
                }}
                style={{
                  padding: '0.1rem 0.4rem',
                  background: isSelected ? 'var(--accent-primary)' : 'rgba(255,255,255,0.05)',
                  border: isSelected ? '1px solid var(--accent-primary)' : '1px solid var(--border-color)',
                  borderRadius: '12px',
                  fontSize: '0.75rem',
                  color: isSelected ? '#fff' : isKnown ? 'var(--text-primary)' : 'var(--text-secondary)',
                  cursor: 'pointer',
                  fontWeight: isSelected ? 600 : 500,
                }}
                title={isSelected ? 'Remove character filter' : 'Filter by this character'}
              >
                {name}
              </button>
            );
          })}
        </div>

        {/* Discord Jump Links */}
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap', marginTop: '0.25rem' }}>
          {session.start?.link ? (
            <a
              href={session.start.link}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.3rem',
                padding: '0.25rem 0.6rem',
                fontSize: '0.8rem',
                background: 'rgba(139, 92, 246, 0.2)',
                border: '1px solid #8b5cf6',
                color: '#c4b5fd',
                borderRadius: '6px',
                textDecoration: 'none',
                fontWeight: 600,
              }}
            >
              <ExternalLink size={12} /> Open first message in Discord
            </a>
          ) : (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.3rem',
                padding: '0.25rem 0.6rem',
                fontSize: '0.8rem',
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-secondary)',
                borderRadius: '6px',
                opacity: 0.5,
                cursor: 'not-allowed',
                fontWeight: 600,
              }}
            >
              <ExternalLink size={12} /> Open first message in Discord
            </span>
          )}

          {session.end?.link ? (
            <a
              href={session.end.link}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.3rem',
                padding: '0.25rem 0.6rem',
                fontSize: '0.8rem',
                background: 'rgba(139, 92, 246, 0.2)',
                border: '1px solid #8b5cf6',
                color: '#c4b5fd',
                borderRadius: '6px',
                textDecoration: 'none',
                fontWeight: 600,
              }}
            >
              <ExternalLink size={12} /> Open last message in Discord
            </a>
          ) : (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.3rem',
                padding: '0.25rem 0.6rem',
                fontSize: '0.8rem',
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-secondary)',
                borderRadius: '6px',
                opacity: 0.5,
                cursor: 'not-allowed',
                fontWeight: 600,
              }}
            >
              <ExternalLink size={12} /> Open last message in Discord
            </span>
          )}
        </div>

        

        {/* Expandable Ordered Participant Details Toggle */}
        {participantsList.length > 0 && (
          <div style={{ marginTop: '0.25rem' }}>
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
                background: 'transparent',
                border: 'none',
                color: 'var(--text-secondary)',
                fontSize: '0.8rem',
                cursor: 'pointer',
                padding: '0.2rem 0',
              }}
            >
              {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <Users size={14} />
              <span>
                {expanded ? 'Hide participant timeline' : `View detailed participants timeline (${participantsList.length})`}
              </span>
            </button>

            {expanded && (
              <div
                style={{
                  marginTop: '0.5rem',
                  background: 'rgba(0,0,0,0.2)',
                  borderRadius: '4px',
                  padding: '0.6rem 0.8rem',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.4rem',
                  border: '1px solid rgba(255,255,255,0.05)',
                }}
              >
                {participantsList.map((p, idx) => {
                  const name = getCharName(p.char_id) || `Tupper #${p.char_id}`;
                  const pFirst = formatTimestamp(p.first_timestamp);
                  const pLast = formatTimestamp(p.last_timestamp);
                  const pDuration = getDurationHours(p.first_timestamp, p.last_timestamp);

                  return (
                    <div
                      key={p.char_id}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: '0.75rem',
                        padding: '0.35rem 0',
                        borderBottom: idx < participantsList.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none',
                        flexWrap: 'wrap',
                        gap: '0.5rem',
                      }}
                    >
                      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                        <span style={{ color: 'var(--accent-secondary)', fontWeight: 600, minWidth: '1.5rem' }}>
                          #{idx + 1}
                        </span>
                        <strong style={{ color: 'var(--text-primary)' }}>{name}</strong>
                        {pDuration && (
                          <span
                            title={pDuration.tooltip}
                            style={{
                              padding: '0.1rem 0.45rem',
                              borderRadius: '4px',
                              fontSize: '0.7rem',
                              fontWeight: 600,
                              background: 'rgba(255,255,255,0.08)',
                              border: '1px solid rgba(139, 92, 246, 0.3)',
                              color: '#c4b5fd',
                            }}
                          >
                            {pDuration.label}
                          </span>
                        )}
                      </div>

                      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', color: 'var(--text-secondary)', flexWrap: 'wrap' }}>
                        {pFirst && (
                          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                            <span>First: {pFirst}</span>
                            {p.first_link && (
                              <a
                                href={p.first_link}
                                target="_blank"
                                rel="noopener noreferrer"
                                title="Open first message in Discord"
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '0.25rem',
                                  padding: '0.15rem 0.45rem',
                                  fontSize: '0.7rem',
                                  background: 'rgba(139, 92, 246, 0.2)',
                                  border: '1px solid #8b5cf6',
                                  color: '#c4b5fd',
                                  borderRadius: '4px',
                                  textDecoration: 'none',
                                  fontWeight: 600,
                                }}
                              >
                                <ExternalLink size={10} /> Discord
                              </a>
                            )}
                          </div>
                        )}
                        {pLast && (
                          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                            <span>Last: {pLast}</span>
                            {p.last_link && (
                              <a
                                href={p.last_link}
                                target="_blank"
                                rel="noopener noreferrer"
                                title="Open last message in Discord"
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '0.25rem',
                                  padding: '0.15rem 0.45rem',
                                  fontSize: '0.7rem',
                                  background: 'rgba(139, 92, 246, 0.2)',
                                  border: '1px solid #8b5cf6',
                                  color: '#c4b5fd',
                                  borderRadius: '4px',
                                  textDecoration: 'none',
                                  fontWeight: 600,
                                }}
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
            )}
          </div>
        )}
      </div>
    </div>
  );
};

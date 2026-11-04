import React, { useState } from 'react';
import {
  ExternalLink,
  ChevronDown,
  ChevronRight,
  Users,
  Edit3,
  Navigation,
  ArrowRight,
  Hash,
  MessageSquare,
} from 'lucide-react';
import type {
  Character,
  EventChannelEntry,
  EventMovementHop,
  EventRecord,
  SceneParticipantDetail,
} from '../../types';

interface EventCardProps {
  event: EventRecord;
  allCharacters: Character[];
  onEdit?: (event: EventRecord) => void;
}

const formatTimestamp = (ts?: string | null): string | null => {
  if (!ts) return null;
  try {
    const d = new Date(ts);
    return isNaN(d.getTime()) ? null : d.toLocaleString();
  } catch {
    return null;
  }
};

const getDurationLabel = (
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
    if (diffMs === 0) return { label: '0 hours', tooltip: 'Duration: 0 minutes' };
    if (totalHours < 0.05) {
      return { label: '< 0.1 hours', tooltip: `Duration: ${totalMinutes} min` };
    }
    if (totalHours >= 48) {
      const days = (totalHours / 24).toFixed(1).replace(/\.0$/, '');
      return { label: `${days} days`, tooltip: `Duration: ${totalHours.toFixed(1)} hours` };
    }
    const formatted = totalHours.toFixed(1).replace(/\.0$/, '');
    return {
      label: `${formatted} ${formatted === '1' ? 'hour' : 'hours'}`,
      tooltip: `Duration: ${totalHours.toFixed(2)} hours (${totalMinutes} mins)`,
    };
  } catch {
    return null;
  }
};

const linkBtnStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '0.25rem',
  padding: '0.18rem 0.5rem',
  fontSize: '0.75rem',
  background: 'rgba(139, 92, 246, 0.2)',
  border: '1px solid #8b5cf6',
  color: '#c4b5fd',
  borderRadius: '4px',
  textDecoration: 'none',
  fontWeight: 600,
};

export const EventCard: React.FC<EventCardProps> = ({ event, allCharacters, onEdit }) => {
  const [activeCharId, setActiveCharId] = useState<number | null>(null);
  const [expandedRowKey, setExpandedRowKey] = useState<string | null>(null);

  const getCharName = (id: number): string => {
    const main = allCharacters.find(c => c.id === id);
    if (main && main.names && main.names.length > 0) return main.names[0];
    if (main && main.name) return main.name;
    for (const c of allCharacters) {
      if (c.versions) {
        const nested = c.versions.find(v => v.id === id);
        if (nested && nested.name) return nested.name;
      }
    }
    return `Tupper #${id}`;
  };

  const rawStart = event.start_timestamp || event.start_at;
  const rawEnd = event.end_timestamp || event.end_at;
  const startTs = formatTimestamp(rawStart);
  const endTs = formatTimestamp(rawEnd);
  const duration = getDurationLabel(rawStart, rawEnd);
  const participantsList: SceneParticipantDetail[] = event.participants || [];
  const activeMovements: EventMovementHop[] =
    activeCharId !== null ? event.character_movements?.[String(activeCharId)] || [] : [];

  const renderParticipantsPanel = (participants: SceneParticipantDetail[]) => (
    <div style={{ marginTop: '0.4rem', background: 'rgba(0,0,0,0.25)', borderRadius: '4px', padding: '0.5rem 0.75rem', display: 'flex', flexDirection: 'column', gap: '0.35rem', border: '1px solid rgba(255,255,255,0.06)' }}>
      {participants.map((p, idx) => {
        const pFirst = formatTimestamp(p.first_timestamp);
        const pLast = formatTimestamp(p.last_timestamp);
        const pDur = getDurationLabel(p.first_timestamp, p.last_timestamp);
        return (
          <div key={`${p.char_id}-${idx}`} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.75rem', padding: '0.25rem 0', borderBottom: idx < participants.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none', flexWrap: 'wrap', gap: '0.5rem' }}>
            <div style={{ display: 'flex', gap: '0.45rem', alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ color: 'var(--accent-secondary)', fontWeight: 600 }}>#{idx + 1}</span>
              <strong style={{ color: 'var(--text-primary)' }}>{getCharName(p.char_id)}</strong>
              {pDur && (
                <span title={pDur.tooltip} style={{ padding: '0.08rem 0.4rem', borderRadius: '4px', fontSize: '0.7rem', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(139, 92, 246, 0.3)', color: '#c4b5fd' }}>
                  {pDur.label}
                </span>
              )}
            </div>
            <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', color: 'var(--text-secondary)', flexWrap: 'wrap' }}>
              {pFirst && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                  First: {pFirst}
                  {p.first_link && (
                    <a href={p.first_link} target="_blank" rel="noopener noreferrer" style={linkBtnStyle}>
                      <ExternalLink size={10} /> Discord
                    </a>
                  )}
                </span>
              )}
              {pLast && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                  Last: {pLast}
                  {p.last_link && (
                    <a href={p.last_link} target="_blank" rel="noopener noreferrer" style={linkBtnStyle}>
                      <ExternalLink size={10} /> Discord
                    </a>
                  )}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );

  const renderChannelRow = (entry: EventChannelEntry, isThread: boolean = false) => {
    const entryPk = entry.scene_pk ?? entry.pk ?? 0;
    const rowKey = entry.scene_key || `${entryPk}`;
    const isExpanded = expandedRowKey === rowKey;
    const displayLabel = entry.custom_name
      ? `${entry.custom_name} (${entry.channel_name})`
      : isThread
      ? entry.channel_name
      : `#${entry.channel_name}`;
    const rowParticipants = entry.participants || [];

    return (
      <div
        key={rowKey}
        style={{
          marginLeft: isThread ? '1.5rem' : 0,
          padding: '0.5rem 0.75rem',
          background: isThread ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.04)',
          borderLeft: isThread ? '2px solid rgba(139, 92, 246, 0.45)' : '1px solid var(--border-color)',
          borderRadius: '6px',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.25rem',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
            {isThread ? (
              <span style={{ color: 'var(--accent-secondary)', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                ↳ <MessageSquare size={13} />
              </span>
            ) : (
              <Hash size={14} style={{ color: 'var(--accent-secondary)' }} />
            )}
            <strong style={{ fontSize: '0.85rem', color: 'var(--text-primary)' }}>{displayLabel}</strong>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', background: 'rgba(255,255,255,0.06)', padding: '0.1rem 0.4rem', borderRadius: '4px' }}>
              {entry.message_count} msgs
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
            {entry.start?.link && (
              <a href={entry.start.link} target="_blank" rel="noopener noreferrer" style={linkBtnStyle}>
                <ExternalLink size={11} /> First msg
              </a>
            )}
            {entry.end?.link && (
              <a href={entry.end.link} target="_blank" rel="noopener noreferrer" style={linkBtnStyle}>
                <ExternalLink size={11} /> Last msg
              </a>
            )}
            {rowParticipants.length > 0 && (
              <button
                type="button"
                onClick={() => setExpandedRowKey(isExpanded ? null : rowKey)}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.25rem',
                  background: isExpanded ? 'rgba(139, 92, 246, 0.15)' : 'rgba(255,255,255,0.06)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-secondary)',
                  fontSize: '0.75rem',
                  padding: '0.18rem 0.5rem',
                  borderRadius: '4px',
                  cursor: 'pointer',
                }}
              >
                {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                <Users size={12} />
                <span>{rowParticipants.length}</span>
              </button>
            )}
          </div>
        </div>
        {isExpanded && renderParticipantsPanel(rowParticipants)}
      </div>
    );
  };

  return (
    <div style={{ background: 'var(--bg-tertiary)', borderRadius: '8px', border: '1px solid var(--border-color)', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
      {/* Header Row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem', flexWrap: 'wrap' }}>
          <strong style={{ fontSize: '1.05rem', color: 'var(--text-primary)' }}>{event.name || 'Unnamed Event'}</strong>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'monospace' }}>({event.id})</span>
          {duration && (
            <span title={duration.tooltip} style={{ padding: '0.1rem 0.45rem', borderRadius: '4px', fontSize: '0.78rem', fontWeight: 600, background: 'rgba(139, 92, 246, 0.15)', border: '1px solid rgba(139, 92, 246, 0.35)', color: '#c4b5fd' }}>
              {duration.label}
            </span>
          )}
          <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
            {startTs && endTs ? `${startTs} — ${endTs}` : startTs || endTs || 'N/A'}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <span
            style={{
              padding: '0.18rem 0.5rem',
              background: event.status === 'open' ? 'rgba(245, 158, 11, 0.15)' : 'rgba(16, 185, 129, 0.15)',
              border: event.status === 'open' ? '1px solid var(--warning)' : '1px solid var(--success)',
              color: event.status === 'open' ? '#fbbf24' : '#34d399',
              borderRadius: '4px',
              fontSize: '0.73rem',
              fontWeight: 600,
              textTransform: 'uppercase',
            }}
          >
            {event.status}
          </span>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 500 }}>{event.message_count} msgs</span>
          {onEdit && (
            <button
              type="button"
              onClick={() => onEdit(event)}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem', padding: '0.22rem 0.6rem', fontSize: '0.78rem', background: 'rgba(255,255,255,0.07)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', borderRadius: '5px', cursor: 'pointer', fontWeight: 500 }}
            >
              <Edit3 size={12} /> Edit
            </button>
          )}
        </div>
      </div>

      {/* Condensed Participant Pills (click to view Character Movement) */}
      {participantsList.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', alignItems: 'center' }}>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginRight: '0.2rem' }}>Participants (click for path):</span>
            {participantsList.map(p => {
              const cid = p.char_id;
              const isActive = activeCharId === cid;
              return (
                <button
                  key={cid}
                  type="button"
                  onClick={() => setActiveCharId(isActive ? null : cid)}
                  style={{
                    padding: '0.12rem 0.48rem',
                    background: isActive ? 'var(--accent-primary)' : 'rgba(255,255,255,0.05)',
                    border: isActive ? '1px solid var(--accent-primary)' : '1px solid var(--border-color)',
                    borderRadius: '12px',
                    fontSize: '0.75rem',
                    color: isActive ? '#fff' : 'var(--text-primary)',
                    cursor: 'pointer',
                    fontWeight: isActive ? 600 : 500,
                  }}
                  title="Toggle character movement path across event channels"
                >
                  {getCharName(cid)}
                </button>
              );
            })}
          </div>

          {/* Character Movement Section */}
          {activeCharId !== null && (
            <div style={{ background: 'rgba(139, 92, 246, 0.1)', border: '1px solid rgba(139, 92, 246, 0.35)', borderRadius: '6px', padding: '0.55rem 0.75rem', display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '0.4rem' }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.78rem', fontWeight: 600, color: '#c4b5fd', marginRight: '0.25rem' }}>
                <Navigation size={13} /> {getCharName(activeCharId)} movement:
              </span>
              {activeMovements.length === 0 ? (
                <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Only participated in event threads (no main channel hops).</span>
              ) : (
                activeMovements.map((hop, idx) => {
                  const hopLabel = hop.custom_name ? `${hop.custom_name} (${hop.channel_name})` : hop.channel_name;
                  return (
                    <React.Fragment key={`${hop.channel_id}-${hop.first_message_id}-${idx}`}>
                      {idx > 0 && <ArrowRight size={13} style={{ color: 'var(--text-muted)' }} />}
                      <a
                        href={hop.first_link}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={(hop.first_timestamp || hop.first_at) ? `First message at ${formatTimestamp(hop.first_timestamp || hop.first_at)}` : 'Open in Discord'}
                        style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem', padding: '0.18rem 0.55rem', borderRadius: '6px', background: 'rgba(0,0,0,0.35)', border: '1px solid #8b5cf6', color: '#e9d5ff', fontSize: '0.78rem', fontWeight: 600, textDecoration: 'none' }}
                      >
                        [{hopLabel}] <ExternalLink size={10} />
                      </a>
                    </React.Fragment>
                  );
                })
              )}
            </div>
          )}
        </div>
      )}

      {/* Event Channels & Indented Threads */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
        {(event.channels || []).map(ch => (
          <React.Fragment key={ch.scene_key || ch.scene_pk}>
            {renderChannelRow(ch, false)}
            {(ch.threads || []).map(th => renderChannelRow(th, true))}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
};

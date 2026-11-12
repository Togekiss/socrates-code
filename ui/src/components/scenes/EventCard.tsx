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
import { DataCard, Badge, Button, FilterChip } from '../ui';
import { resolveCharacterName } from '../../utils/characters';
import { formatTimestamp, getDurationInfo } from '../../utils/formatters';
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

export const EventCard: React.FC<EventCardProps> = ({ event, allCharacters, onEdit }) => {
  const [activeCharId, setActiveCharId] = useState<number | null>(null);
  const [expandedRowKey, setExpandedRowKey] = useState<string | null>(null);

  const rawStart = event.start_timestamp || event.start_at;
  const rawEnd = event.end_timestamp || event.end_at;
  const startTs = formatTimestamp(rawStart);
  const endTs = formatTimestamp(rawEnd);
  const duration = getDurationInfo(rawStart, rawEnd);

  const participantsList: SceneParticipantDetail[] = event.participants || [];
  const activeMovements: EventMovementHop[] =
    activeCharId !== null ? event.character_movements?.[String(activeCharId)] || [] : [];

  const getCharName = (id: number): string => {
    return resolveCharacterName(id, allCharacters) || `Tupper #${id}`;
  };

  const renderParticipantsPanel = (participants: SceneParticipantDetail[]) => (
    <div
      style={{
        marginTop: '0.4rem',
        background: 'rgba(0,0,0,0.25)',
        borderRadius: '4px',
        padding: '0.5rem 0.75rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.35rem',
        border: '1px solid rgba(255,255,255,0.06)',
      }}
    >
      {participants.map((p, idx) => {
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
              padding: '0.25rem 0',
              borderBottom:
                idx < participants.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none',
              flexWrap: 'wrap',
              gap: '0.5rem',
            }}
          >
            <div style={{ display: 'flex', gap: '0.45rem', alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ color: 'var(--accent-secondary)', fontWeight: 600 }}>#{idx + 1}</span>
              <strong className="text-primary">{getCharName(p.char_id)}</strong>
              {pDur && (
                <span
                  title={pDur.tooltip}
                  className="badge badge-neutral text-accent"
                  style={{ fontSize: '0.7rem' }}
                >
                  {pDur.label}
                </span>
              )}
            </div>

            <div
              style={{
                display: 'flex',
                gap: '0.6rem',
                alignItems: 'center',
                color: 'var(--text-secondary)',
                flexWrap: 'wrap',
              }}
            >
              {pFirst && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                  First: {pFirst}
                  {p.first_link && (
                    <a
                      href={p.first_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn-secondary btn-xs"
                      style={{ padding: '0.1rem 0.35rem', fontSize: '0.7rem' }}
                    >
                      <ExternalLink size={10} /> Discord
                    </a>
                  )}
                </span>
              )}
              {pLast && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                  Last: {pLast}
                  {p.last_link && (
                    <a
                      href={p.last_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn-secondary btn-xs"
                      style={{ padding: '0.1rem 0.35rem', fontSize: '0.7rem' }}
                    >
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
    const rowParticipants = entry.participants || [];

    return (
      <div
        key={rowKey}
        className={`event-channel-row ${isThread ? 'event-channel-row--thread' : ''}`}
      >
        <div className="event-channel-header">
          <div className="event-channel-title">
            {isThread ? (
              <span className="text-accent flex-row items-center gap-xs" style={{ fontSize: '0.8rem' }}>
                ↳ <MessageSquare size={13} />
              </span>
            ) : (
              <Hash size={14} className="text-accent" />
            )}

            {/* Curated channel name vs canonical slot name swap */}
            {entry.custom_name ? (
              <span className="event-channel-name">
                <strong>{entry.custom_name}</strong>{' '}
                <span className="event-channel-slot">(#{entry.channel_name})</span>
              </span>
            ) : (
              <span className="event-channel-name">
                <strong>{isThread ? entry.channel_name : `#${entry.channel_name}`}</strong>
              </span>
            )}

            <Badge variant="neutral" className="text-sm">
              {entry.message_count} msgs
            </Badge>
          </div>

          <div className="flex-row items-center gap-xs flex-wrap">
            {entry.start?.link && (
              <a
                href={entry.start.link}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-secondary btn-xs"
                style={{ padding: '0.15rem 0.45rem', fontSize: '0.72rem' }}
              >
                <ExternalLink size={10} /> First msg
              </a>
            )}
            {entry.end?.link && (
              <a
                href={entry.end.link}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-secondary btn-xs"
                style={{ padding: '0.15rem 0.45rem', fontSize: '0.72rem' }}
              >
                <ExternalLink size={10} /> Last msg
              </a>
            )}
            {rowParticipants.length > 0 && (
              <Button
                variant="secondary"
                size="xs"
                onClick={() => setExpandedRowKey(isExpanded ? null : rowKey)}
                icon={isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                title={isExpanded ? 'Hide participants' : 'Show participants'}
              >
                <Users size={12} style={{ marginRight: '0.2rem' }} />
                <span>{rowParticipants.length}</span>
              </Button>
            )}
          </div>
        </div>

        {isExpanded && renderParticipantsPanel(rowParticipants)}
      </div>
    );
  };

  const cardAccent = event.status === 'open' ? 'warning' : 'accent';

  return (
    <DataCard accent={cardAccent} className="flex-col gap-sm">
      {/* Header Row */}
      <div className="flex-row justify-between items-start flex-wrap gap-sm">
        <div className="flex-row items-baseline gap-xs flex-wrap">
          <strong className="text-primary" style={{ fontSize: '1.05rem' }}>
            {event.name || 'Unnamed Event'}
          </strong>
          <span className="event-channel-slot">({event.id})</span>

          {duration && (
            <Badge variant="accent" title={duration.tooltip} className="text-sm font-semibold">
              {duration.label}
            </Badge>
          )}

          <span className="text-secondary text-sm" style={{ marginLeft: '0.25rem' }}>
            {startTs && endTs ? `${startTs} — ${endTs}` : startTs || endTs || 'N/A'}
          </span>
        </div>

        {/* Status, msg count, and FAR RIGHT Edit Button */}
        <div className="flex-row items-center gap-xs flex-wrap">
          <Badge
            variant={event.status === 'open' ? 'warning' : 'success'}
            className="text-sm uppercase font-semibold"
          >
            {event.status}
          </Badge>

          <span className="text-secondary text-sm font-medium" style={{ margin: '0 0.25rem' }}>
            {event.message_count} msgs
          </span>

          {/* EDIT BUTTON ALWAYS ON THE FAR RIGHT */}
          {onEdit && (
            <Button
              variant="secondary"
              size="xs"
              onClick={() => onEdit(event)}
              icon={<Edit3 size={12} />}
              title="Edit event details"
            >
              Edit
            </Button>
          )}
        </div>
      </div>

      {/* Condensed Participant Pills (click to view Character Movement) */}
      {participantsList.length > 0 && (
        <div className="flex-col gap-xs">
          <div className="flex-row flex-wrap gap-xs items-center">
            <span className="text-muted text-sm" style={{ marginRight: '0.25rem' }}>
              Participants (click for path):
            </span>
            {participantsList.map(p => {
              const cid = p.char_id;
              const isActive = activeCharId === cid;
              return (
                <FilterChip
                  key={cid}
                  active={isActive}
                  onClick={() => setActiveCharId(isActive ? null : cid)}
                  title="Toggle character movement path across event channels"
                >
                  {getCharName(cid)}
                </FilterChip>
              );
            })}
          </div>

          {/* Character Movement Section */}
          {activeCharId !== null && (
            <div
              style={{
                background: 'rgba(139, 92, 246, 0.1)',
                border: '1px solid rgba(139, 92, 246, 0.35)',
                borderRadius: '6px',
                padding: '0.55rem 0.75rem',
                display: 'flex',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '0.4rem',
              }}
            >
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.3rem',
                  fontSize: '0.78rem',
                  fontWeight: 600,
                  color: '#c4b5fd',
                  marginRight: '0.25rem',
                }}
              >
                <Navigation size={13} /> {getCharName(activeCharId)} movement:
              </span>
              {activeMovements.length === 0 ? (
                <span className="text-secondary text-sm">
                  Only participated in event threads (no main channel hops).
                </span>
              ) : (
                activeMovements.map((hop, idx) => {
                  const hopLabel = hop.custom_name
                    ? `${hop.custom_name} (${hop.channel_name})`
                    : hop.channel_name;
                  return (
                    <React.Fragment key={`${hop.channel_id}-${hop.first_message_id}-${idx}`}>
                      {idx > 0 && <ArrowRight size={13} className="text-muted" />}
                      <a
                        href={hop.first_link}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={
                          hop.first_timestamp || hop.first_at
                            ? `First message at ${formatTimestamp(hop.first_timestamp || hop.first_at)}`
                            : 'Open in Discord'
                        }
                        className="btn btn-secondary btn-xs"
                        style={{
                          fontSize: '0.75rem',
                          background: 'rgba(0,0,0,0.35)',
                          border: '1px solid #8b5cf6',
                          color: '#e9d5ff',
                        }}
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

      {/* Event Channels & Indented Threads: 1 channel per full-width row */}
      <div className="event-channels-list">
        {(event.channels || []).map(ch => (
          <React.Fragment key={ch.scene_key || ch.scene_pk}>
            {renderChannelRow(ch, false)}
            {(ch.threads || []).map(th => renderChannelRow(th, true))}
          </React.Fragment>
        ))}
      </div>
    </DataCard>
  );
};

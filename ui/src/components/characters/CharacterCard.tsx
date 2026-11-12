import React, { useState } from 'react';
import { Edit2, ChevronDown, ChevronRight, Hash, User, Link as LinkIcon, UserPlus } from 'lucide-react';
import type { Character, CharacterVersion } from '../../types';
import { Badge, Button } from '../ui';

export interface CharacterCardProps {
  character: Character;
  onEdit: (char: Character, parent?: Character) => void;
  onAddTagFilter: (tag: string) => void;
  onAssignWriter?: (char: Character) => void;
  isNested?: boolean;
  disableAccordion?: boolean;
}

export const CharacterCard: React.FC<CharacterCardProps> = ({
  character,
  onEdit,
  onAddTagFilter,
  onAssignWriter,
  isNested = false,
  disableAccordion = false,
}) => {
  const [expanded, setExpanded] = useState(false);
  const assignWriterHandler = onAssignWriter;

  const mainName = character.names?.[0] || character.name || 'Unknown';
  const otherNames = character.names?.slice(1).join(', ');

  const hasWriter = Boolean(
    (character.writer && character.writer.length > 0 && character.writer.some(w => w && w.trim().length > 0)) ||
    character.writer_name ||
    character.writer_id
  );

  const mainWriter = character.writer?.[0] || character.writer_name || (hasWriter ? 'Unknown' : 'Unassigned');
  const otherWriters = character.writer?.slice(1).join(', ');

  const hasVersions = (character.versions && character.versions.length > 0) ||
    (character.other_versions && character.other_versions.length > 0);
  const versionsList = character.versions || character.other_versions || [];

  const nestedType = isNested
    ? (character.tags?.find((t: string) => ['familiar', 'npc', 'alter_ego', 'different_writer'].includes(t)) || character.version_type || 'other version')
    : null;

  return (
    <div
      className={`data-card character-card-full ${isNested ? 'event-channel-row--thread' : ''}`.trim()}
      style={{
        borderLeft: isNested ? '3px solid var(--accent-secondary)' : undefined,
      }}
    >
      <div className="flex-col gap-xs">
        {/* Header Row */}
        <div className="flex-row items-start justify-between flex-wrap gap-xs">
          <div>
            <div className="flex-row items-center gap-xs flex-wrap">
              <h4 style={{ margin: 0, fontSize: isNested ? '0.95rem' : '1.1rem', color: 'var(--text-primary)' }}>
                {mainName}
              </h4>
              {isNested && (
                <Badge variant="accent">
                  {nestedType?.replace('_', ' ')}
                </Badge>
              )}
            </div>

            {otherNames && (
              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                aka {otherNames}
              </div>
            )}

            {/* Flattened Parent Badge */}
            {character._parent && (
              <div className="flex-row items-center gap-xs" style={{ fontSize: '0.75rem', color: 'var(--accent-secondary)', marginTop: '0.2rem' }}>
                <LinkIcon size={11} /> Alt version of {character._parent.names?.[0] || character._parent.name} (ID: {character._parent.id})
              </div>
            )}

            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              ID: #{character.id}
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex-row items-center gap-xs">
            {!hasWriter && assignWriterHandler && (
              <Button
                variant="warning"
                size="xs"
                onClick={() => assignWriterHandler(character)}
                icon={<UserPlus size={12} />}
              >
                Assign Writer
              </Button>
            )}

            <Button
              variant="secondary"
              size="xs"
              onClick={() => onEdit(character, character._parent)}
              icon={<Edit2 size={12} />}
            >
              Edit
            </Button>
          </div>
        </div>

        {/* Writer Row */}
        <div className="flex-row items-center gap-xs" style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
          <User size={13} style={{ color: hasWriter ? 'var(--text-muted)' : 'var(--warning)' }} />
          <span style={{ fontWeight: hasWriter ? 500 : 600, color: hasWriter ? 'var(--text-primary)' : 'var(--warning-text)' }}>
            {mainWriter}
          </span>
          {otherWriters && <span style={{ opacity: 0.6 }}>(aka {otherWriters})</span>}
        </div>

        {/* Activity Stats when available */}
        {(character.scene_count != null || character.last_channel_name || character.last_active_at) && (
          <div className="flex-row items-center gap-sm flex-wrap" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            {character.scene_count != null && (
              <Badge variant="neutral">
                {character.scene_count} {character.scene_count === 1 ? 'scene' : 'scenes'}
              </Badge>
            )}
            {character.last_channel_name && (
              <span style={{ color: 'var(--text-muted)' }}>
                Last in #{character.last_channel_name}
              </span>
            )}
            {character.last_active_at && (
              <span style={{ color: 'var(--text-muted)' }}>
                ({new Date(character.last_active_at).toLocaleDateString()})
              </span>
            )}
          </div>
        )}

        {/* Tags Row */}
        {character.tags && character.tags.length > 0 && (
          <div className="flex-row items-center gap-xs flex-wrap" style={{ marginTop: '0.25rem' }}>
            {character.tags.map((tag: string) => (
              <button
                key={tag}
                type="button"
                className="chip"
                style={{ padding: '0.15rem 0.5rem', fontSize: '0.75rem' }}
                onClick={() => onAddTagFilter(tag)}
              >
                <Hash size={10} /> {tag.replace(/_/g, ' ')}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Other Versions Section */}
      {hasVersions && !isNested && !disableAccordion && (
        <div style={{ borderTop: '1px solid var(--border-color)', marginTop: '0.75rem', paddingTop: '0.5rem' }}>
          <button
            type="button"
            className="flex-row items-center gap-xs"
            onClick={() => setExpanded(!expanded)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              fontSize: '0.8rem',
              cursor: 'pointer',
              padding: '0.25rem 0',
            }}
          >
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <span>Other Versions ({versionsList.length})</span>
          </button>

          {expanded && (
            <div className="flex-col gap-xs" style={{ marginTop: '0.5rem', paddingLeft: '0.5rem' }}>
              {versionsList.map((v: CharacterVersion) => (
                <CharacterCard
                  key={v.id}
                  character={{ ...v, names: v.names || [v.name] }}
                  onEdit={(childChar) => onEdit(childChar, character)}
                  onAddTagFilter={onAddTagFilter}
                  onAssignWriter={onAssignWriter}
                  isNested={true}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

import React, { useState } from 'react';
import { Edit2, ChevronDown, ChevronRight, Users } from 'lucide-react';
import { CharacterCard } from './CharacterCard';
import type { Character, CharacterGroup } from '../../types';

interface GroupCardProps {
  group: CharacterGroup;
  members: Character[];
  onEditGroup: (group: CharacterGroup) => void;
  onEditCharacter: (char: Character, parent?: Character) => void;
  onAddTagFilter: (tag: string) => void;
  disableAccordion?: boolean;
}

export const GroupCard: React.FC<GroupCardProps> = ({
  group,
  members,
  onEditGroup,
  onEditCharacter,
  onAddTagFilter,
  disableAccordion = false,
}) => {
  const [expanded, setExpanded] = useState(true);

  const mainName = group.names?.[0] || 'Unnamed Group';
  const aliases = group.names?.slice(1) || [];
  const memberCount = members.length;

  return (
    <div
      style={{
        background: 'var(--bg-secondary)',
        borderRadius: '8px',
        overflow: 'hidden',
        border: '1px solid rgba(139, 92, 246, 0.35)',
        borderLeft: '4px solid var(--accent-primary)',
        boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
      }}
    >
      {/* Group Header Row */}
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: '0.85rem 1rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          cursor: 'pointer',
          background: 'rgba(139, 92, 246, 0.08)',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flex: 1, minWidth: 0 }}>
          <button
            onClick={e => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              padding: '0.15rem',
            }}
            aria-label={expanded ? 'Collapse group' : 'Expand group'}
          >
            {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
          </button>

          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '6px',
              background: 'rgba(139, 92, 246, 0.2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <Users size={18} style={{ color: 'var(--accent-secondary)' }} />
          </div>

          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
              <h3
                style={{
                  margin: 0,
                  fontSize: '1.15rem',
                  color: 'var(--text-primary)',
                  fontWeight: 600,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {mainName}
              </h3>
              <span
                style={{
                  fontSize: '0.65rem',
                  textTransform: 'uppercase',
                  fontWeight: 700,
                  letterSpacing: '0.05em',
                  color: 'var(--accent-secondary)',
                  background: 'rgba(139, 92, 246, 0.2)',
                  padding: '0.15rem 0.4rem',
                  borderRadius: '4px',
                }}
              >
                Group
              </span>
              <span
                style={{
                  fontSize: '0.75rem',
                  color: 'var(--text-secondary)',
                  background: 'var(--bg-tertiary)',
                  padding: '0.1rem 0.45rem',
                  borderRadius: '12px',
                  border: '1px solid var(--border-color)',
                }}
              >
                {memberCount} {memberCount === 1 ? 'member' : 'members'}
              </span>
            </div>

            {aliases.length > 0 && (
              <div
                style={{
                  fontSize: '0.85rem',
                  color: 'var(--text-secondary)',
                  marginTop: '0.15rem',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                aka {aliases.join(', ')}
              </div>
            )}
          </div>
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0, marginLeft: '0.5rem' }}>
          <button
            onClick={e => {
              e.stopPropagation();
              onEditGroup(group);
            }}
            style={{
              padding: '0.3rem 0.65rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.35rem',
              fontSize: '0.85rem',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-primary)',
              cursor: 'pointer',
              borderRadius: '4px',
            }}
            title="Edit Character Group"
          >
            <Edit2 size={13} />
            <span>Edit Group</span>
          </button>
        </div>
      </div>

      {/* Group Members Section */}
      {expanded && (
        <div
          style={{
            padding: '0.75rem 1rem',
            background: 'rgba(0, 0, 0, 0.2)',
            borderTop: '1px solid rgba(139, 92, 246, 0.2)',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.75rem',
          }}
        >
          {members.length === 0 ? (
            <div
              style={{
                padding: '1rem',
                textAlign: 'center',
                color: 'var(--text-secondary)',
                fontStyle: 'italic',
                fontSize: '0.85rem',
              }}
            >
              No characters assigned to this group yet. Click &quot;Edit Group&quot; to add member characters.
            </div>
          ) : (
            members.map(member => (
              <CharacterCard
                key={member.id}
                character={member}
                onEdit={onEditCharacter}
                onAddTagFilter={onAddTagFilter}
                disableAccordion={disableAccordion}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
};

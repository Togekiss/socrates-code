import React, { useState } from 'react';
import { Edit2, ChevronDown, ChevronRight, Users } from 'lucide-react';
import { CharacterCard } from './CharacterCard';
import type { Character, CharacterGroup } from '../../types';
import { Badge, Button } from '../ui';

interface GroupCardProps {
  group: CharacterGroup;
  members: Character[];
  onEditGroup: (group: CharacterGroup) => void;
  onEditCharacter: (char: Character, parent?: Character) => void;
  onAddTagFilter: (tag: string) => void;
  onAssignWriter?: (char: Character) => void;
  disableAccordion?: boolean;
}

export const GroupCard: React.FC<GroupCardProps> = ({
  group,
  members,
  onEditGroup,
  onEditCharacter,
  onAddTagFilter,
  onAssignWriter,
  disableAccordion = false,
}) => {
  const [expanded, setExpanded] = useState(true);

  const mainName = group.names?.[0] || group.name || 'Unnamed Group';
  const aliases = group.names?.slice(1) || [];
  const memberCount = members.length;

  return (
    <div
      className="panel-surface character-card-full"
      style={{
        borderLeft: '4px solid var(--accent-primary)',
        padding: 0,
        overflow: 'hidden',
      }}
    >
      {/* Group Header Row */}
      <div
        onClick={() => setExpanded(!expanded)}
        className="flex-row items-center justify-between"
        style={{
          padding: '0.85rem 1rem',
          cursor: 'pointer',
          background: 'rgba(139, 92, 246, 0.08)',
          userSelect: 'none',
        }}
      >
        <div className="flex-row items-center gap-sm flex-1 min-width-0">
          <button
            type="button"
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
              background: 'var(--accent-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <Users size={18} style={{ color: 'var(--accent-secondary)' }} />
          </div>

          <div className="flex-1 min-width-0">
            <div className="flex-row items-center gap-xs flex-wrap">
              <h3
                style={{
                  margin: 0,
                  fontSize: '1.1rem',
                  color: 'var(--text-primary)',
                  fontWeight: 600,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {mainName}
              </h3>
              <Badge variant="accent">
                Group
              </Badge>
              <Badge variant="neutral">
                {memberCount} {memberCount === 1 ? 'member' : 'members'}
              </Badge>
            </div>

            {aliases.length > 0 && (
              <div
                style={{
                  fontSize: '0.8rem',
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
        <div className="flex-row items-center gap-xs flex-shrink-0" style={{ marginLeft: '0.5rem' }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={e => {
              e.stopPropagation();
              onEditGroup(group);
            }}
            icon={<Edit2 size={12} />}
          >
            Edit Group
          </Button>
        </div>
      </div>

      {/* Group Members Section: Strict 1-character-per-row full-width layout */}
      {expanded && (
        <div
          style={{
            padding: '0.75rem 1rem',
            background: 'rgba(0, 0, 0, 0.15)',
            borderTop: '1px solid rgba(139, 92, 246, 0.2)',
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
            <div className="group-members-stack">
              {members.map(member => (
                <CharacterCard
                  key={member.id}
                  character={member}
                  onEdit={onEditCharacter}
                  onAddTagFilter={onAddTagFilter}
                  onAssignWriter={onAssignWriter}
                  disableAccordion={disableAccordion}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

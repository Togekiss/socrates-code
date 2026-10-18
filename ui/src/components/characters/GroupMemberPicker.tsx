import React from 'react';
import { Search, Check } from 'lucide-react';
import type { Character } from '../../types';

interface GroupMemberPickerProps {
  search: string;
  onSearchChange: (val: string) => void;
  filteredCharacters: Character[];
  memberIds: number[];
  onToggleMember: (id: number) => void;
}

export const GroupMemberPicker: React.FC<GroupMemberPickerProps> = ({
  search,
  onSearchChange,
  filteredCharacters,
  memberIds,
  onToggleMember,
}) => {
  return (
    <div>
      {/* Member Search */}
      <div
        style={{
          position: 'relative',
          display: 'flex',
          alignItems: 'center',
          marginBottom: '0.5rem',
        }}
      >
        <Search
          size={14}
          style={{
            position: 'absolute',
            left: '0.75rem',
            color: 'var(--text-muted)',
          }}
        />
        <input
          type="text"
          placeholder="Search characters to add..."
          value={search}
          onChange={e => onSearchChange(e.target.value)}
          style={{
            width: '100%',
            padding: '0.45rem 0.75rem 0.45rem 2.2rem',
            background: 'var(--bg-tertiary)',
            border: '1px solid var(--border-color)',
            borderRadius: '6px',
            color: 'white',
            fontSize: '0.85rem',
          }}
        />
      </div>

      {/* Character Selection List */}
      <div
        style={{
          border: '1px solid var(--border-color)',
          borderRadius: '6px',
          maxHeight: '180px',
          overflowY: 'auto',
          background: 'var(--bg-secondary)',
        }}
      >
        {filteredCharacters.length === 0 ? (
          <div
            style={{
              padding: '1rem',
              textAlign: 'center',
              color: 'var(--text-muted)',
              fontSize: '0.85rem',
            }}
          >
            No matching characters found.
          </div>
        ) : (
          filteredCharacters.map(char => {
            const isSelected = memberIds.includes(char.id);
            const charName = char.name || char.names?.[0] || `Character #${char.id}`;
            return (
              <div
                key={char.id}
                onClick={() => onToggleMember(char.id)}
                style={{
                  padding: '0.45rem 0.75rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  cursor: 'pointer',
                  borderBottom: '1px solid var(--border-color)',
                  background: isSelected
                    ? 'rgba(109, 40, 217, 0.15)'
                    : 'transparent',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <div
                    style={{
                      width: '18px',
                      height: '18px',
                      borderRadius: '4px',
                      border: `1px solid ${
                        isSelected
                          ? 'var(--accent-secondary)'
                          : 'var(--border-color)'
                      }`,
                      background: isSelected
                        ? 'var(--accent-primary)'
                        : 'var(--bg-tertiary)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    {isSelected && <Check size={12} color="#fff" />}
                  </div>
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-primary)' }}>
                    {charName}
                  </span>
                </div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  #{char.id}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

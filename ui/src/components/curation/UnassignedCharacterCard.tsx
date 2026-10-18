import React from 'react';
import type { UnassignedCharacter } from '../../types';

interface UnassignedCharacterCardProps {
  char: UnassignedCharacter;
  onAssign: (char: UnassignedCharacter) => void;
}

export const UnassignedCharacterCard: React.FC<UnassignedCharacterCardProps> = ({
  char,
  onAssign,
}) => {
  const charName = char.name || char.names?.[0] || `Character #${char.id}`;

  return (
    <div
      className="glass-panel"
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '1rem',
      }}
    >
      <div>
        <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.95rem' }}>
          {charName}
        </div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
          ID: #{char.id} {char.origin ? `• ${char.origin}` : ''}
        </div>
      </div>

      <button
        onClick={() => onAssign(char)}
        style={{
          padding: '0.35rem 0.75rem',
          background: 'var(--accent-primary)',
          color: '#fff',
          border: 'none',
          borderRadius: '4px',
          fontSize: '0.8rem',
          fontWeight: 600,
          cursor: 'pointer',
        }}
      >
        Assign Writer
      </button>
    </div>
  );
};

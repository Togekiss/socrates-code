import React from 'react';
import { UserPlus } from 'lucide-react';
import type { UnassignedCharacter } from '../../types';
import { DataCard, Button, Badge } from '../ui';

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
    <DataCard className="flex-row items-center justify-between" style={{ padding: '0.85rem 1rem' }}>
      <div className="flex-col gap-xs">
        <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.95rem' }}>
          {charName}
        </span>
        <div className="flex-row items-center gap-xs">
          <Badge variant="neutral">ID: #{char.id}</Badge>
          {char.origin && <span className="form-hint">• {char.origin}</span>}
          {char.scene_count != null && (
            <Badge variant="accent">
              {char.scene_count} {char.scene_count === 1 ? 'scene' : 'scenes'}
            </Badge>
          )}
        </div>
      </div>

      <Button
        variant="primary"
        size="xs"
        onClick={() => onAssign(char)}
        icon={<UserPlus size={13} />}
      >
        Assign Writer
      </Button>
    </DataCard>
  );
};

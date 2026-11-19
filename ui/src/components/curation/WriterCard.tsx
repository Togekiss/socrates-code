import React from 'react';
import { Edit2, Check } from 'lucide-react';
import type { WriterDetailed } from '../../types';
import { DataCard, Badge, Button } from '../ui';

interface WriterCardProps {
  writer: WriterDetailed;
  onEdit?: (writer: WriterDetailed) => void;
  showDiscordId?: boolean;
}

export const WriterCard: React.FC<WriterCardProps> = ({
  writer,
  onEdit,
  showDiscordId = true,
}) => {
  return (
    <DataCard
      accent={showDiscordId && writer.discord_user_id ? 'success' : undefined}
      className="flex-col justify-between gap-sm"
      style={{ minHeight: '180px' }}
    >
      <div className="flex-col gap-xs">
        <div className="flex-row items-start justify-between gap-sm">
          <div>
            <h3 style={{ margin: 0, fontSize: '1.1rem', color: 'var(--text-primary)' }}>
              {writer.display_name}
            </h3>

            {showDiscordId && (
              <div style={{ marginTop: '0.25rem' }}>
                {writer.discord_user_id ? (
                  <Badge variant="success">
                    <Check size={11} /> Discord: {writer.discord_user_id}
                  </Badge>
                ) : (
                  <span className="form-hint" style={{ fontStyle: 'italic'}}>
                    No Discord account linked
                  </span>
                )}
              </div>
            )}
          </div>

          {onEdit && (
            <Button
              variant="secondary"
              size="xs"
              onClick={() => onEdit(writer)}
              icon={<Edit2 size={12} />}
            >
              <span className="hide-in-mobile">Edit</span>
            </Button>
          )}
        </div>

        {writer.aliases && writer.aliases.length > 0 && (
          <div className="text-secondary" style={{ fontSize: '0.8rem'}}>
            <span style={{ color: 'var(--text-muted)' }}>Aliases: </span>
            {writer.aliases.join(', ')}
          </div>
        )}

        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)'}}>
          <strong style={{ color: 'var(--text-primary)' }}>
            {writer.characters?.length || 0}
          </strong>{' '}
          written characters
        </div>
      </div>

      {writer.characters && writer.characters.length > 0 && (
        <div
          className="flex-row items-center gap-xs flex-wrap"
          style={{
            maxHeight: '75px',
            overflowY: 'auto',
            padding: '0.35rem',
            background: 'var(--bg-elevated)',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          {writer.characters.map(c => (
            <Badge key={c.id} variant="neutral">
              {c.name}
            </Badge>
          ))}
        </div>
      )}
    </DataCard>
  );
};

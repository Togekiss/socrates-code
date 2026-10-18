import React from 'react';
import { Edit2, Check } from 'lucide-react';
import type { WriterDetailed } from '../../types';

interface WriterCardProps {
  writer: WriterDetailed;
  onEdit: (writer: WriterDetailed) => void;
}

export const WriterCard: React.FC<WriterCardProps> = ({ writer, onEdit }) => {
  return (
    <div
      className="glass-panel"
      style={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        gap: '0.75rem',
        padding: '1.25rem',
      }}
    >
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '1.1rem', color: 'var(--text-primary)' }}>
              {writer.display_name}
            </h3>
            {writer.discord_user_id ? (
              <span
                style={{
                  fontSize: '0.75rem',
                  color: 'var(--success)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.25rem',
                  marginTop: '0.2rem',
                }}
              >
                <Check size={12} /> Discord: <code>{writer.discord_user_id}</code>
              </span>
            ) : (
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontStyle: 'italic', display: 'block', marginTop: '0.2rem' }}>
                No Discord account linked
              </span>
            )}
          </div>

          <button
            onClick={() => onEdit(writer)}
            style={{
              padding: '0.35rem 0.65rem',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-secondary)',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '0.8rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.3rem',
            }}
            title="Edit Writer Profile"
          >
            <Edit2 size={12} /> Edit
          </button>
        </div>

        {writer.aliases && writer.aliases.length > 0 && (
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
            <span style={{ color: 'var(--text-muted)' }}>Aliases: </span>
            {writer.aliases.join(', ')}
          </div>
        )}

        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
            {writer.characters?.length || 0}
          </span>{' '}
          written characters
        </div>
      </div>

      {writer.characters && writer.characters.length > 0 && (
        <div
          style={{
            maxHeight: '80px',
            overflowY: 'auto',
            padding: '0.4rem',
            background: 'var(--bg-tertiary)',
            borderRadius: '6px',
            display: 'flex',
            flexWrap: 'wrap',
            gap: '0.3rem',
          }}
        >
          {writer.characters.map(c => (
            <span
              key={c.id}
              style={{
                fontSize: '0.75rem',
                padding: '0.1rem 0.4rem',
                borderRadius: '4px',
                background: 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-color)',
              }}
            >
              {c.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

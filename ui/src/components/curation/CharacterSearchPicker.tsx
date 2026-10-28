import React, { useState, useMemo } from 'react';
import { Search, X, Check } from 'lucide-react';

export interface CharacterOption {
  id: number;
  name: string;
  writerName?: string | null;
}

interface CharacterSearchPickerProps {
  options: CharacterOption[];
  selectedId: number | '';
  onSelect: (option: CharacterOption) => void;
  onClear: () => void;
  loading?: boolean;
  disabled?: boolean;
}

export const CharacterSearchPicker: React.FC<CharacterSearchPickerProps> = ({
  options,
  selectedId,
  onSelect,
  onClear,
  loading = false,
  disabled = false,
}) => {
  const [query, setQuery] = useState('');

  const selectedOption = useMemo(() => {
    if (selectedId === '') return null;
    return options.find(o => o.id === Number(selectedId)) || null;
  }, [options, selectedId]);

  const filteredOptions = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter(
      opt =>
        opt.name.toLowerCase().includes(q) ||
        String(opt.id).includes(q) ||
        (opt.writerName && opt.writerName.toLowerCase().includes(q))
    );
  }, [options, query]);

  if (selectedOption) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.65rem 0.85rem',
          background: 'var(--bg-tertiary)',
          border: '1px solid var(--accent-primary)',
          borderRadius: '6px',
          gap: '0.5rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <Check size={16} color="var(--success)" />
          <span style={{ fontWeight: 600, color: 'var(--accent-secondary)', fontSize: '0.85rem' }}>
            #{selectedOption.id}
          </span>
          <strong style={{ color: 'var(--text-primary)', fontSize: '0.9rem' }}>
            {selectedOption.name}
          </strong>
          {selectedOption.writerName && (
            <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
              ({selectedOption.writerName})
            </span>
          )}
        </div>
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            onClear();
            setQuery('');
          }}
          style={{
            background: 'transparent',
            border: '1px solid var(--border-color)',
            color: 'var(--text-secondary)',
            padding: '0.25rem 0.6rem',
            borderRadius: '4px',
            fontSize: '0.75rem',
            cursor: disabled ? 'not-allowed' : 'pointer',
          }}
        >
          Change
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
      <div
        style={{
          position: 'relative',
          display: 'flex',
          alignItems: 'center',
        }}
      >
        <Search
          size={14}
          style={{
            position: 'absolute',
            left: '0.75rem',
            color: 'var(--text-muted)',
            pointerEvents: 'none',
          }}
        />
        <input
          type="text"
          placeholder={loading ? 'Loading characters...' : 'Search character by name, ID, or writer...'}
          value={query}
          disabled={disabled || loading}
          onChange={e => setQuery(e.target.value)}
          style={{
            width: '100%',
            padding: '0.5rem 2rem 0.5rem 2.2rem',
            background: 'var(--bg-tertiary)',
            border: '1px solid var(--border-color)',
            borderRadius: '6px',
            color: 'white',
            fontSize: '0.85rem',
          }}
        />
        {query && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => setQuery('')}
            style={{
              position: 'absolute',
              right: '0.6rem',
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              display: 'flex',
              padding: '0.2rem',
            }}
          >
            <X size={14} />
          </button>
        )}
      </div>

      <div
        style={{
          maxHeight: '70px',
          overflowY: 'auto',
          border: '1px solid var(--border-color)',
          borderRadius: '6px',
          background: 'var(--bg-secondary)',
        }}
      >
        {loading ? (
          <div style={{ padding: '0.75rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            Loading character directory...
          </div>
        ) : filteredOptions.length === 0 ? (
          <div style={{ padding: '0.75rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            {query ? `No characters matching "${query}"` : 'No characters available'}
          </div>
        ) : (
          filteredOptions.map(opt => (
            <div
              key={opt.id}
              onClick={() => {
                onSelect(opt);
                setQuery('');
              }}
              style={{
                padding: '0.45rem 0.75rem',
                cursor: 'pointer',
                borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.85rem',
                color: 'var(--text-primary)',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.background = 'var(--bg-tertiary)';
              }}
              onMouseLeave={e => {
                e.currentTarget.style.background = 'transparent';
              }}
            >
              <div>
                <span style={{ color: 'var(--accent-secondary)', marginRight: '0.45rem', fontSize: '0.8rem' }}>
                  #{opt.id}
                </span>
                <span>{opt.name}</span>
              </div>
              {opt.writerName && (
                <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                  {opt.writerName}
                </span>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
};

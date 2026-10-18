import React, { useState } from 'react';
import { Search, Filter, Hash, Star } from 'lucide-react';

interface CharactersFilterProps {
  nameFilter: string;
  setNameFilter: (v: string) => void;
  writerFilter: string;
  setWriterFilter: (v: string) => void;
  tagsFilter: string[];
  setTagsFilter: (v: string[]) => void;
  availableTags?: string[];
  byMe: boolean;
  setByMe: (v: boolean) => void;
  isLoggedIn?: boolean;
}

export const CharactersFilter: React.FC<CharactersFilterProps> = ({
  nameFilter,
  setNameFilter,
  writerFilter,
  setWriterFilter,
  tagsFilter,
  setTagsFilter,
  availableTags = [],
  byMe,
  setByMe,
  isLoggedIn = true,
}) => {
  const [collapsed, setCollapsed] = useState(false);

  const handleSelectTag = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const tag = e.target.value;
    if (tag && !tagsFilter.includes(tag)) {
      setTagsFilter([...tagsFilter, tag]);
    }
    e.target.value = '';
  };

  const removeTag = (tagToRemove: string) => {
    setTagsFilter(tagsFilter.filter(t => t !== tagToRemove));
  };

  const isAnyFilterActive = Boolean(nameFilter || writerFilter || tagsFilter.length > 0 || byMe);

  return (
    <div
      style={{
        background: 'var(--bg-secondary)',
        borderRadius: '8px',
        border: '1px solid var(--border-color)',
        marginBottom: '1rem',
      }}
    >
      <div
        onClick={() => setCollapsed(!collapsed)}
        style={{
          padding: '0.75rem 1rem',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          cursor: 'pointer',
          userSelect: 'none',
        }}
      >
        <Filter size={16} color="var(--accent-secondary)" />
        <strong style={{ fontSize: '0.9rem', color: 'var(--text-primary)' }}>Filters</strong>
        {isAnyFilterActive && (
          <span
            style={{
              fontSize: '0.75rem',
              background: 'var(--accent-primary)',
              color: '#fff',
              padding: '0.1rem 0.5rem',
              borderRadius: '12px',
              fontWeight: 'bold',
              marginLeft: 'auto',
            }}
          >
            Active
          </span>
        )}
      </div>

      {!collapsed && (
        <div
          style={{
            padding: '1rem',
            borderTop: '1px solid var(--border-color)',
            display: 'flex',
            flexWrap: 'wrap',
            gap: '1rem',
          }}
        >
          {/* Character Name Filter */}
          <div style={{ flex: '1 1 200px' }}>
            <label
              style={{
                display: 'block',
                fontSize: '0.8rem',
                color: 'var(--text-secondary)',
                marginBottom: '0.25rem',
              }}
            >
              Character Name
            </label>
            <div style={{ position: 'relative' }}>
              <Search
                size={14}
                style={{
                  position: 'absolute',
                  left: '0.5rem',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  color: 'var(--text-muted)',
                }}
              />
              <input
                type="text"
                value={nameFilter}
                onChange={e => setNameFilter(e.target.value)}
                placeholder="Filter by name..."
                style={{
                  width: '100%',
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-color)',
                  color: 'white',
                  padding: '0.5rem 0.5rem 0.5rem 2rem',
                  borderRadius: '4px',
                  fontSize: '0.85rem',
                }}
              />
            </div>
          </div>

          {/* Writer Filter & By Me Toggle */}
          <div style={{ flex: '1 1 220px' }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '0.25rem',
              }}
            >
              <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                Writer
              </label>
              {isLoggedIn && (
                <button
                  type="button"
                  onClick={() => setByMe(!byMe)}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '0.25rem',
                    fontSize: '0.75rem',
                    padding: '0.15rem 0.45rem',
                    background: byMe ? 'var(--accent-primary)' : 'var(--bg-tertiary)',
                    border: '1px solid var(--border-color)',
                    color: byMe ? '#fff' : 'var(--text-secondary)',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    fontWeight: byMe ? 700 : 500,
                  }}
                  title="Filter to characters written by you"
                >
                  <Star size={12} fill={byMe ? '#fff' : 'none'} /> By Me
                </button>
              )}
            </div>
            <div style={{ position: 'relative' }}>
              <Search
                size={14}
                style={{
                  position: 'absolute',
                  left: '0.5rem',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  color: 'var(--text-muted)',
                }}
              />
              <input
                type="text"
                value={writerFilter}
                onChange={e => setWriterFilter(e.target.value)}
                placeholder="Filter by writer..."
                disabled={byMe}
                style={{
                  width: '100%',
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-color)',
                  color: 'white',
                  padding: '0.5rem 0.5rem 0.5rem 2rem',
                  borderRadius: '4px',
                  fontSize: '0.85rem',
                  opacity: byMe ? 0.5 : 1,
                }}
              />
            </div>
          </div>

          {/* Tags Filter */}
          <div style={{ flex: '1 1 300px' }}>
            <label
              style={{
                display: 'block',
                fontSize: '0.8rem',
                color: 'var(--text-secondary)',
                marginBottom: '0.25rem',
              }}
            >
              Tags (AND logic)
            </label>

            <select
              onChange={handleSelectTag}
              defaultValue=""
              style={{
                width: '100%',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                color: 'white',
                padding: '0.5rem',
                borderRadius: '4px',
                fontSize: '0.85rem',
              }}
            >
              <option value="" disabled>
                Select a tag to filter...
              </option>
              {availableTags
                .filter(t => !tagsFilter.includes(t))
                .map(tag => (
                  <option key={tag} value={tag}>
                    {tag.replace(/_/g, ' ')}
                  </option>
                ))}
            </select>

            {tagsFilter.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginTop: '0.5rem' }}>
                {tagsFilter.map(tag => (
                  <div
                    key={tag}
                    style={{
                      background: 'rgba(139, 92, 246, 0.2)',
                      color: 'var(--accent-secondary)',
                      border: '1px solid rgba(139, 92, 246, 0.35)',
                      padding: '0.15rem 0.45rem',
                      borderRadius: '12px',
                      fontSize: '0.75rem',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.25rem',
                    }}
                  >
                    <Hash size={11} /> {tag.replace(/_/g, ' ')}
                    <button
                      type="button"
                      onClick={() => removeTag(tag)}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: 'inherit',
                        padding: 0,
                        cursor: 'pointer',
                        display: 'flex',
                      }}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

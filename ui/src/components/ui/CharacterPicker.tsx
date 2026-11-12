import React, { useState, useMemo } from 'react';
import { Search, Check, X, User } from 'lucide-react';
import type { Character } from '../../types';
import { getCharacterDisplayName } from '../../utils/characters';
import { FilterChip } from './Badge';

export interface CharacterPickerProps {
  characters: Character[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  multiple?: boolean;
  placeholder?: string;
  includeVersions?: boolean;
  disabled?: boolean;
  className?: string;
  maxListHeight?: number;
}

interface FlattenedOption {
  id: number;
  name: string;
  writerName?: string | null;
  isVersion?: boolean;
  parentName?: string;
}

export const CharacterPicker: React.FC<CharacterPickerProps> = ({
  characters,
  selectedIds,
  onChange,
  multiple = false,
  placeholder,
  includeVersions = false,
  disabled = false,
  className = '',
  maxListHeight = 220,
}) => {
  const [query, setQuery] = useState('');

  // Flatten character options, optionally including nested versions
  const allOptions = useMemo<FlattenedOption[]>(() => {
    const list: FlattenedOption[] = [];
    for (const c of characters) {
      const charName = getCharacterDisplayName(c);
      const writer = c.writer_name || c.writer?.[0] || null;

      list.push({
        id: c.id,
        name: charName,
        writerName: writer,
      });

      if (includeVersions) {
        if (c.versions && Array.isArray(c.versions)) {
          for (const v of c.versions) {
            list.push({
              id: v.id,
              name: v.name,
              writerName: writer,
              isVersion: true,
              parentName: charName,
            });
          }
        }
        // Legacy versions check
        const legacy = (c as unknown as { other_versions?: Array<{ id: number; name?: string; names?: string[] }> }).other_versions;
        if (legacy && Array.isArray(legacy)) {
          for (const v of legacy) {
            const vName = (v.names && v.names.length > 0 && v.names[0]) ? v.names[0] : (v.name || `Version #${v.id}`);
            list.push({
              id: v.id,
              name: vName,
              writerName: writer,
              isVersion: true,
              parentName: charName,
            });
          }
        }
      }
    }
    return list;
  }, [characters, includeVersions]);

  // Filter options based on search query
  const filteredOptions = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return allOptions;

    return allOptions.filter(
      opt =>
        opt.name.toLowerCase().includes(q) ||
        String(opt.id).includes(q) ||
        (opt.writerName && opt.writerName.toLowerCase().includes(q)) ||
        (opt.parentName && opt.parentName.toLowerCase().includes(q))
    );
  }, [allOptions, query]);

  // Selected single character option (for single-select mode display)
  const singleSelectedOption = useMemo(() => {
    if (multiple || selectedIds.length === 0) return null;
    const targetId = selectedIds[0];
    return allOptions.find(o => o.id === targetId) || null;
  }, [multiple, selectedIds, allOptions]);

  const handleToggle = (id: number) => {
    if (disabled) return;
    if (multiple) {
      if (selectedIds.includes(id)) {
        onChange(selectedIds.filter(item => item !== id));
      } else {
        onChange([...selectedIds, id]);
      }
    } else {
      if (selectedIds.includes(id)) {
        onChange([]);
      } else {
        onChange([id]);
      }
    }
  };

  const handleClearSingle = () => {
    if (disabled) return;
    onChange([]);
    setQuery('');
  };

  const defaultPlaceholder = multiple
    ? 'Search characters to filter or assign...'
    : 'Search character by name or ID...';

  // Single select mode with a selected value: render clean selected view with Change button
  if (!multiple && singleSelectedOption && !query) {
    return (
      <div className={['character-picker', className].filter(Boolean).join(' ')}>
        <div className="character-picker-selected-card">
          <div className="character-picker-selected-info">
            <Check size={16} className="text-success" />
            <span className="character-picker-id">#{singleSelectedOption.id}</span>
            <strong className="character-picker-name">{singleSelectedOption.name}</strong>
            {singleSelectedOption.isVersion && (
              <span className="badge badge-accent">alt of {singleSelectedOption.parentName}</span>
            )}
            {singleSelectedOption.writerName && (
              <span className="character-picker-writer">
                <User size={12} /> {singleSelectedOption.writerName}
              </span>
            )}
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-xs"
            disabled={disabled}
            onClick={handleClearSingle}
          >
            Change
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={['character-picker', className].filter(Boolean).join(' ')}>
      {/* Multi-select active chips summary */}
      {multiple && selectedIds.length > 0 && (
        <div className="character-picker-chips">
          {selectedIds.map(id => {
            const opt = allOptions.find(o => o.id === id);
            const label = opt ? opt.name : `#${id}`;
            return (
              <FilterChip
                key={id}
                active
                onRemove={disabled ? undefined : () => handleToggle(id)}
              >
                {label}
              </FilterChip>
            );
          })}
          {!disabled && (
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              onClick={() => onChange([])}
            >
              Clear all
            </button>
          )}
        </div>
      )}

      {/* Search Input */}
      <div className="character-picker-search">
        <Search size={14} />
        <input
          type="text"
          className="input"
          placeholder={placeholder || defaultPlaceholder}
          value={query}
          disabled={disabled}
          onChange={e => setQuery(e.target.value)}
        />
        {query && (
          <button
            type="button"
            className="character-picker-clear-btn"
            onClick={() => setQuery('')}
            aria-label="Clear search"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* Options Dropdown List */}
      <div
        className="character-picker-list"
        style={{ maxHeight: `${maxListHeight}px` }}
      >
        {filteredOptions.length === 0 ? (
          <div className="character-picker-empty">
            No characters found matching "{query}".
          </div>
        ) : (
          filteredOptions.map(opt => {
            const isSelected = selectedIds.includes(opt.id);
            return (
              <div
                key={opt.id}
                className={[
                  'character-picker-item',
                  isSelected ? 'is-selected' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                onClick={() => handleToggle(opt.id)}
              >
                <div className="flex-row items-center gap-sm">
                  <div
                    className={[
                      'character-picker-checkbox',
                      isSelected ? 'is-checked' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                  >
                    {isSelected && <Check size={12} />}
                  </div>
                  <span className="character-picker-id">#{opt.id}</span>
                  <span className="character-picker-name">{opt.name}</span>
                  {opt.isVersion && (
                    <span className="badge badge-accent" style={{ fontSize: '0.65rem' }}>
                      alt
                    </span>
                  )}
                </div>

                {opt.writerName && (
                  <span className="character-picker-writer">
                    <User size={12} /> {opt.writerName}
                  </span>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

import React, { useState, useMemo, useRef, useEffect } from 'react';
import { Search, Check, X, User, Users } from 'lucide-react';
import type { Character, CharacterGroup } from '../../types';
import {
  buildCharacterPickerOptions,
  filterCharacterPickerOptions,
  type CharacterPickerOption,
} from '../../utils/characters';
import { FilterChip } from './Badge';

export interface CharacterPickerProps {
  characters: Character[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  groups?: CharacterGroup[];
  selectedGroupIds?: number[];
  onChangeGroups?: (groupIds: number[]) => void;
  multiple?: boolean;
  includeVersions?: boolean;
  variant?: 'inline' | 'dropdown';
  showSelectedChips?: boolean;
  excludeIds?: number[];
  fallbackOptions?: Array<{ id: number; name: string; writerName?: string | null }>;
  onSelectItem?: (item: { kind: 'character' | 'group'; id: number; name: string }) => void;
  placeholder?: string;
  loading?: boolean;
  disabled?: boolean;
  className?: string;
  maxListHeight?: number;
}

export const CharacterPicker: React.FC<CharacterPickerProps> = ({
  characters,
  selectedIds,
  onChange,
  groups,
  selectedGroupIds = [],
  onChangeGroups,
  multiple = false,
  includeVersions = false,
  variant = 'inline',
  showSelectedChips,
  excludeIds,
  fallbackOptions,
  onSelectItem,
  placeholder,
  loading = false,
  disabled = false,
  className = '',
  maxListHeight = 220,
}) => {
  const [query, setQuery] = useState('');
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const shouldShowChips = showSelectedChips ?? (variant === 'inline' && multiple);

  useEffect(() => {
    if (variant !== 'dropdown' || !dropdownOpen) return;

    const handleMouseDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        setDropdownOpen(false);
      }
    };

    document.addEventListener('mousedown', handleMouseDown);
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleMouseDown);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [variant, dropdownOpen]);

  const allOptions = useMemo<CharacterPickerOption[]>(
    () =>
      buildCharacterPickerOptions(characters, {
        includeVersions,
        groups,
        excludeIds,
        fallbackOptions,
      }),
    [characters, includeVersions, groups, excludeIds, fallbackOptions]
  );

  const filteredOptions = useMemo(
    () => filterCharacterPickerOptions(allOptions, query),
    [allOptions, query]
  );

  const singleSelectedOption = useMemo(() => {
    if (multiple || selectedIds.length === 0) return null;
    const targetId = selectedIds[0];
    return allOptions.find(o => o.kind === 'character' && o.id === targetId) || null;
  }, [multiple, selectedIds, allOptions]);

  const handleToggleOption = (opt: CharacterPickerOption) => {
    if (disabled) return;

    if (opt.kind === 'group') {
      if (!onChangeGroups) return;
      const isSelected = selectedGroupIds.includes(opt.id);
      if (isSelected) {
        onChangeGroups(selectedGroupIds.filter(id => id !== opt.id));
      } else {
        onChangeGroups([...selectedGroupIds, opt.id]);
        onSelectItem?.({ kind: 'group', id: opt.id, name: opt.displayName });
      }
      if (!multiple && variant === 'dropdown') {
        setDropdownOpen(false);
        setQuery('');
      }
      return;
    }

    const isSelected = selectedIds.includes(opt.id);
    if (multiple) {
      if (isSelected) {
        onChange(selectedIds.filter(item => item !== opt.id));
      } else {
        onChange([...selectedIds, opt.id]);
        onSelectItem?.({ kind: 'character', id: opt.id, name: opt.displayName });
      }
    } else {
      if (isSelected) {
        onChange([]);
      } else {
        onChange([opt.id]);
        onSelectItem?.({ kind: 'character', id: opt.id, name: opt.displayName });
      }
      if (variant === 'dropdown') {
        setDropdownOpen(false);
        setQuery('');
      }
    }
  };

  const handleClearSingle = () => {
    if (disabled) return;
    onChange([]);
    setQuery('');
  };

  const defaultPlaceholder = loading
    ? 'Loading characters...'
    : groups && groups.length > 0
      ? 'Search characters or groups...'
      : multiple
        ? 'Search characters to filter or assign...'
        : 'Search character by name, alias, or ID...';

  // Inline single-select mode with a selected value: show selected card + Change button
  if (variant === 'inline' && !multiple && singleSelectedOption && !query) {
    return (
      <div className={['character-picker', className].filter(Boolean).join(' ')}>
        <div className="character-picker-selected-card">
          <div className="character-picker-selected-info">
            <Check size={16} className="text-success" />
            <span className="character-picker-id">#{singleSelectedOption.id}</span>
            <strong className="character-picker-name">{singleSelectedOption.displayName}</strong>
            {singleSelectedOption.isVersion && (
              <span className="badge badge-accent">
                {singleSelectedOption.versionType?.replace('_', ' ') || 'alt'}
                {singleSelectedOption.parentName ? ` of ${singleSelectedOption.parentName}` : ''}
              </span>
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

  const listContent = (
    <div
      className="character-picker-list"
      style={{ maxHeight: `${maxListHeight}px` }}
    >
      {loading ? (
        <div className="character-picker-empty">Loading character directory...</div>
      ) : filteredOptions.length === 0 ? (
        <div className="character-picker-empty">
          {query
            ? `No characters found matching "${query}".`
            : 'No characters available.'}
        </div>
      ) : (
        filteredOptions.map(opt => {
          const isSelected =
            opt.kind === 'group'
              ? selectedGroupIds.includes(opt.id)
              : selectedIds.includes(opt.id);

          const aliasTooltip =
            opt.searchNames.length > 1
              ? `Aliases: ${opt.searchNames.slice(1).join(', ')}`
              : undefined;

          return (
            <div
              key={opt.key}
              className={[
                'character-picker-item',
                isSelected ? 'is-selected' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              title={aliasTooltip}
              onClick={() => handleToggleOption(opt)}
            >
              <div className="character-picker-item-main">
                {multiple && (
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
                )}

                {opt.kind === 'group' ? (
                  <>
                    <Users size={13} className="text-secondary flex-shrink-0" />
                    <span className="character-picker-name">
                      {opt.displayName} (Group)
                    </span>
                  </>
                ) : (
                  <>
                    <span className="character-picker-name">{opt.displayName}</span>
                    {opt.isVersion && (
                      <span className="badge badge-accent">
                        {opt.versionType?.replace('_', ' ') || 'alt'}
                        {opt.parentName ? ` of ${opt.parentName}` : ''}
                      </span>
                    )}
                  </>
                )}
              </div>

              <div className="character-picker-item-meta">
                {opt.kind === 'group' ? (
                  <span className="character-picker-writer">
                    {opt.memberCount ?? 0} {opt.memberCount === 1 ? 'member' : 'members'}
                  </span>
                ) : (
                  <>
                    {opt.writerName && (
                      <span className="character-picker-writer">
                        <User size={12} /> {opt.writerName}
                      </span>
                    )}
                    <span className="character-picker-id">ID: #{opt.id}</span>
                  </>
                )}
              </div>
            </div>
          );
        })
      )}
    </div>
  );

  return (
    <div
      ref={containerRef}
      className={[
        'character-picker',
        variant === 'dropdown' ? 'is-dropdown' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {/* Inline multi-select active chips summary */}
      {shouldShowChips && (selectedIds.length > 0 || selectedGroupIds.length > 0) && (
        <div className="character-picker-chips">
          {selectedGroupIds.map(gid => {
            const opt = allOptions.find(o => o.kind === 'group' && o.id === gid);
            const label = opt ? `${opt.displayName} (Group)` : `Group #${gid}`;
            return (
              <FilterChip
                key={`group-${gid}`}
                active
                onRemove={
                  disabled || !onChangeGroups
                    ? undefined
                    : () => onChangeGroups(selectedGroupIds.filter(id => id !== gid))
                }
              >
                {label}
              </FilterChip>
            );
          })}
          {selectedIds.map(id => {
            const opt = allOptions.find(o => o.kind === 'character' && o.id === id);
            const label = opt ? opt.displayName : `#${id}`;
            return (
              <FilterChip
                key={`char-${id}`}
                active
                onRemove={
                  disabled
                    ? undefined
                    : () => onChange(selectedIds.filter(item => item !== id))
                }
              >
                {label}
              </FilterChip>
            );
          })}
          {!disabled && (
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              onClick={() => {
                onChange([]);
                onChangeGroups?.([]);
              }}
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
          disabled={disabled || loading}
          onFocus={() => {
            if (variant === 'dropdown') setDropdownOpen(true);
          }}
          onChange={e => {
            setQuery(e.target.value);
            if (variant === 'dropdown' && !dropdownOpen) {
              setDropdownOpen(true);
            }
          }}
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

      {/* Options List (inline or floating dropdown) */}
      {variant === 'inline' ? (
        listContent
      ) : (
        dropdownOpen && <div className="character-picker-dropdown">{listContent}</div>
      )}
    </div>
  );
};

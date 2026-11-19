import React, { useState, useMemo, useRef, useEffect } from 'react';
import { Search, Check, X, UserCheck, Plus } from 'lucide-react';
import { api, getErrorMessage } from '../../api';
import type { WriterDetailed } from '../../types';
import { Button } from './Button';
import { ChipInput } from './ChipInput';
import { FilterChip } from './Badge';

export interface WriterPickerProps {
  writers: WriterDetailed[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  multiple?: boolean;
  variant?: 'inline' | 'dropdown';
  showSelectedChips?: boolean;
  allowUnassigned?: boolean;
  allowCreate?: boolean;
  backupId?: string;
  onWriterCreated?: (writer: WriterDetailed) => void;
  placeholder?: string;
  loading?: boolean;
  disabled?: boolean;
  className?: string;
  maxListHeight?: number;
}

function getOtherAliases(writer: WriterDetailed): string[] {
  const displayLower = writer.display_name.trim().toLowerCase();
  return (writer.aliases || []).filter(a => a && a.trim().toLowerCase() !== displayLower);
}

export const WriterPicker: React.FC<WriterPickerProps> = ({
  writers,
  selectedIds,
  onChange,
  multiple = false,
  variant = 'inline',
  showSelectedChips,
  allowUnassigned = false,
  allowCreate = false,
  backupId,
  onWriterCreated,
  placeholder,
  loading = false,
  disabled = false,
  className = '',
  maxListHeight = 200,
}) => {
  const [query, setQuery] = useState('');
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [isSearching, setIsSearching] = useState(false);

  // Inline "+ New Writer" creation state
  const [isCreating, setIsCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newAliases, setNewAliases] = useState<string[]>([]);
  const [newDiscordId, setNewDiscordId] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

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

  const filteredWriters = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return writers;
    return writers.filter(
      w =>
        w.display_name.toLowerCase().includes(q) ||
        (w.aliases || []).some(a => a.toLowerCase().includes(q)) ||
        String(w.id).includes(q)
    );
  }, [writers, query]);

  const singleSelectedWriter = useMemo(() => {
    if (multiple || selectedIds.length === 0) return null;
    return writers.find(w => w.id === selectedIds[0]) || null;
  }, [multiple, selectedIds, writers]);

  const hasExactMatch = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return false;
    return writers.some(
      w =>
        w.display_name.toLowerCase() === q ||
        (w.aliases || []).some(a => a.toLowerCase() === q)
    );
  }, [writers, query]);

  const handleToggleWriter = (writer: WriterDetailed) => {
    if (disabled) return;
    const isSelected = selectedIds.includes(writer.id);
    if (multiple) {
      if (isSelected) {
        onChange(selectedIds.filter(id => id !== writer.id));
      } else {
        onChange([...selectedIds, writer.id]);
      }
    } else {
      if (isSelected) {
        onChange([]);
      } else {
        onChange([writer.id]);
      }
      setIsSearching(false);
      if (variant === 'dropdown') {
        setDropdownOpen(false);
        setQuery('');
      }
    }
  };

  const openCreateForm = () => {
    setNewName(query.trim());
    setNewAliases([]);
    setNewDiscordId('');
    setCreateError(null);
    setIsCreating(true);
    setDropdownOpen(false);
  };

  const handleCreateWriter = async () => {
    if (!backupId) return;
    const trimmed = newName.trim();
    if (!trimmed) {
      setCreateError('Display name is required.');
      return;
    }

    setCreating(true);
    setCreateError(null);
    try {
      const created = await api.createWriter(backupId, {
        display_name: trimmed,
        aliases: newAliases.map(a => a.trim()).filter(Boolean),
        discord_user_id: newDiscordId.trim() || undefined,
      });
      onWriterCreated?.(created);
      if (multiple) {
        onChange([...selectedIds, created.id]);
      } else {
        onChange([created.id]);
      }
      setIsCreating(false);
      setIsSearching(false);
      setQuery('');
    } catch (err: unknown) {
      setCreateError(getErrorMessage(err, 'Failed to create writer.'));
    } finally {
      setCreating(false);
    }
  };

  const defaultPlaceholder = loading
    ? 'Loading writers...'
    : 'Search writers by name or alias...';

  // Inline "+ New Writer" sub-form
  if (allowCreate && isCreating) {
    return (
      <div className={['character-picker', className].filter(Boolean).join(' ')}>
        <div className="panel-surface flex-col gap-sm" style={{ padding: '0.85rem' }}>
          <div className="flex-row items-center justify-between">
            <strong className="text-md text-primary">Create New Writer</strong>
            <button
              type="button"
              className="modal-close"
              onClick={() => setIsCreating(false)}
              disabled={creating}
              aria-label="Cancel new writer"
            >
              <X size={14} />
            </button>
          </div>

          {createError && (
            <div className="banner-danger">
              <span>{createError}</span>
            </div>
          )}

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">Display Name</label>
            <input
              type="text"
              className="input"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="e.g. JaneDoe"
              disabled={creating}
              autoFocus
            />
          </div>

          <ChipInput
            label="Aliases & Nicknames (optional)"
            values={newAliases}
            onChange={setNewAliases}
            placeholder="Type alias and press Enter..."
            disabled={creating}
          />

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">Discord User ID (optional)</label>
            <input
              type="text"
              className="input"
              value={newDiscordId}
              onChange={e => setNewDiscordId(e.target.value)}
              placeholder="e.g. 123456789012345678"
              disabled={creating}
            />
          </div>

          <div className="flex-row items-center justify-end gap-sm">
            <Button
              variant="ghost"
              size="xs"
              onClick={() => setIsCreating(false)}
              disabled={creating}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="xs"
              onClick={handleCreateWriter}
              loading={creating}
            >
              Create &amp; Select
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // Inline single-select mode with a selected writer: show selected card + Change / Unassign
  if (variant === 'inline' && !multiple && singleSelectedWriter && !isSearching) {
    const otherAliases = getOtherAliases(singleSelectedWriter);
    const charCount = singleSelectedWriter.character_count ?? singleSelectedWriter.characters?.length ?? 0;

    return (
      <div className={['character-picker', className].filter(Boolean).join(' ')}>
        <div className="character-picker-selected-card">
          <div className="character-picker-selected-info">
            <Check size={16} className="text-success" />
            <strong className="character-picker-name">{singleSelectedWriter.display_name}</strong>
            {otherAliases.length > 0 && (
              <span className="character-picker-writer">
                aka {otherAliases.join(', ')}
              </span>
            )}
            <span className="character-picker-writer">
              · {charCount} {charCount === 1 ? 'character' : 'characters'}
            </span>
          </div>
          <div className="flex-row items-center gap-xs">
            <button
              type="button"
              className="btn btn-secondary btn-xs"
              disabled={disabled}
              onClick={() => {
                setQuery('');
                setIsSearching(true);
              }}
            >
              Change
            </button>
            {allowUnassigned && (
              <button
                type="button"
                className="btn btn-ghost btn-xs"
                disabled={disabled}
                onClick={() => {
                  onChange([]);
                  setIsSearching(false);
                }}
              >
                Unassign
              </button>
            )}
          </div>
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
        <div className="character-picker-empty">Loading writers...</div>
      ) : filteredWriters.length === 0 ? (
        <div className="character-picker-empty">
          {query
            ? `No writers found matching "${query}".`
            : 'No writer profiles exist yet.'}
        </div>
      ) : (
        filteredWriters.map(w => {
          const isSelected = selectedIds.includes(w.id);
          const otherAliases = getOtherAliases(w);
          const charCount = w.character_count ?? w.characters?.length ?? 0;

          return (
            <div
              key={w.id}
              className={[
                'character-picker-item',
                isSelected ? 'is-selected' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              title={otherAliases.length > 0 ? `Aliases: ${otherAliases.join(', ')}` : undefined}
              onClick={() => handleToggleWriter(w)}
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
                <UserCheck size={13} className="text-secondary flex-shrink-0" />
                <span className="character-picker-name">{w.display_name}</span>
                {otherAliases.length > 0 && (
                  <span className="character-picker-writer">
                    aka {otherAliases.join(', ')}
                  </span>
                )}
              </div>

              <div className="character-picker-item-meta">
                <span className="character-picker-writer">
                  {charCount} {charCount === 1 ? 'char' : 'chars'}
                </span>
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
      {shouldShowChips && selectedIds.length > 0 && (
        <div className="character-picker-chips">
          {selectedIds.map(id => {
            const w = writers.find(item => item.id === id);
            return (
              <FilterChip
                key={id}
                active
                onRemove={
                  disabled ? undefined : () => onChange(selectedIds.filter(x => x !== id))
                }
              >
                {w ? w.display_name : `Writer #${id}`}
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

      {/* Search Input (+ optional Cancel when changing an existing selection) */}
      <div className="flex-row items-center gap-xs">
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

        {variant === 'inline' && isSearching && singleSelectedWriter && (
          <Button
            variant="ghost"
            size="xs"
            onClick={() => {
              setIsSearching(false);
              setQuery('');
            }}
          >
            Cancel
          </Button>
        )}
      </div>

      {/* Options List */}
      {variant === 'inline' ? (
        <>
          {listContent}
          {allowCreate && backupId && !disabled && (
            <div className="flex-row items-center justify-between">
              <Button
                variant="secondary"
                size="xs"
                onClick={openCreateForm}
                icon={<Plus size={13} />}
              >
                {query.trim() && !hasExactMatch
                  ? `New Writer "${query.trim()}"`
                  : 'New Writer'}
              </Button>
              {allowUnassigned && selectedIds.length === 0 && (
                <span className="form-hint">Currently unassigned</span>
              )}
            </div>
          )}
        </>
      ) : (
        dropdownOpen && <div className="character-picker-dropdown">{listContent}</div>
      )}
    </div>
  );
};

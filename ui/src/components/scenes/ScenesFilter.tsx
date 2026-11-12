import React, { useState } from 'react';
import { User, UserCheck, Folder, Hash } from 'lucide-react';
import { CollapsibleFilterBar, SegmentedControl, FilterChip, Badge } from '../ui';
import { resolveCharacterName } from '../../utils/characters';
import type { Character } from '../../types';

export interface ScenesFilterProps {
  charactersFilter: number[];
  setCharactersFilter: (v: number[]) => void;
  characterLogic: 'AND' | 'OR';
  setCharacterLogic: (v: 'AND' | 'OR') => void;
  writersFilter: string[];
  setWritersFilter: (v: string[]) => void;
  writerLogic: 'AND' | 'OR';
  setWriterLogic: (v: 'AND' | 'OR') => void;
  categoriesFilter: string[];
  setCategoriesFilter: (v: string[]) => void;
  typesFilter: string[];
  setTypesFilter: (v: string[]) => void;
  statusesFilter: string[];
  setStatusesFilter: (v: string[]) => void;
  includeAlterEgos: boolean;
  setIncludeAlterEgos: (v: boolean) => void;
  includeFamiliars: boolean;
  setIncludeFamiliars: (v: boolean) => void;
  includeNPCs: boolean;
  setIncludeNPCs: (v: boolean) => void;
  before: string;
  setBefore: (v: string) => void;
  after: string;
  setAfter: (v: string) => void;
  byMe: boolean;
  setByMe: (v: boolean) => void;
  mode?: 'scenes' | 'sessions' | 'events';
  allCharacters: Character[];
}

export const ScenesFilter: React.FC<ScenesFilterProps> = ({
  charactersFilter,
  setCharactersFilter,
  characterLogic,
  setCharacterLogic,
  writersFilter,
  setWritersFilter,
  writerLogic,
  setWriterLogic,
  categoriesFilter,
  setCategoriesFilter,
  typesFilter,
  setTypesFilter,
  statusesFilter,
  setStatusesFilter,
  includeAlterEgos,
  setIncludeAlterEgos,
  includeFamiliars,
  setIncludeFamiliars,
  includeNPCs,
  setIncludeNPCs,
  before,
  setBefore,
  after,
  setAfter,
  byMe,
  setByMe,
  mode = 'scenes',
  allCharacters,
}) => {
  const [writerInput, setWriterInput] = useState('');
  const [categoryInput, setCategoryInput] = useState('');

  const addCharFilter = (id: number) => {
    if (!charactersFilter.includes(id)) {
      setCharactersFilter([...charactersFilter, id]);
    }
  };

  const removeCharFilter = (id: number) => {
    setCharactersFilter(charactersFilter.filter(x => x !== id));
  };

  const addWriterFilter = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = writerInput.trim();
    if (trimmed && !writersFilter.includes(trimmed)) {
      setWritersFilter([...writersFilter, trimmed]);
    }
    setWriterInput('');
  };

  const removeWriterFilter = (w: string) => {
    setWritersFilter(writersFilter.filter(x => x !== w));
  };

  const addCategoryFilter = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = categoryInput.trim();
    if (trimmed && !categoriesFilter.includes(trimmed)) {
      setCategoriesFilter([...categoriesFilter, trimmed]);
    }
    setCategoryInput('');
  };

  const removeCategoryFilter = (c: string) => {
    setCategoriesFilter(categoriesFilter.filter(x => x !== c));
  };

  const toggleArrayItem = (arr: string[], setArr: (v: string[]) => void, item: string) => {
    if (arr.includes(item)) {
      setArr(arr.filter(x => x !== item));
    } else {
      setArr([...arr, item]);
    }
  };

  const isChannelFilterMode = mode === 'sessions' || mode === 'events';
  const statusOptions = mode === 'events' ? ['closed', 'open'] : ['closed', 'open', 'no_end_tag'];
  const filtersTitle = mode === 'events' ? 'Event Searcher' : mode === 'sessions' ? 'Chat Session Searcher' : 'Scenes Searcher';

  const activeCount =
    charactersFilter.length +
    writersFilter.length +
    (byMe ? 1 : 0) +
    categoriesFilter.length +
    statusesFilter.length +
    typesFilter.length +
    (before ? 1 : 0) +
    (after ? 1 : 0);

  const handleClearAll = () => {
    setCharactersFilter([]);
    setWritersFilter([]);
    setByMe(false);
    setCategoriesFilter([]);
    setStatusesFilter([]);
    setTypesFilter([]);
    setBefore('');
    setAfter('');
    setIncludeAlterEgos(true);
    setIncludeFamiliars(true);
    setIncludeNPCs(true);
  };

  // Summary pills shown when the filter bar is collapsed
  const summaryPills = (
    <div className="flex-row items-center gap-xs flex-wrap">
      {byMe && <Badge variant="accent">★ By Me</Badge>}
      {charactersFilter.length > 0 && (
        <Badge variant="neutral">
          {charactersFilter.length} char{charactersFilter.length > 1 ? 's' : ''}
        </Badge>
      )}
      {writersFilter.length > 0 && (
        <Badge variant="neutral">
          {writersFilter.length} writer{writersFilter.length > 1 ? 's' : ''}
        </Badge>
      )}
      {categoriesFilter.length > 0 && (
        <Badge variant="neutral">
          {categoriesFilter.length} {isChannelFilterMode ? 'channels' : 'categories'}
        </Badge>
      )}
      {statusesFilter.length > 0 && (
        <Badge variant="neutral">
          {statusesFilter.map(s => (s === 'no_end_tag' ? 'issues' : s)).join(', ')}
        </Badge>
      )}
      {typesFilter.length > 0 && (
        <Badge variant="neutral">{typesFilter.join(', ')}</Badge>
      )}
      {(before || after) && <Badge variant="neutral">Date range</Badge>}
    </div>
  );

  return (
    <CollapsibleFilterBar
      title={filtersTitle}
      activeCount={activeCount}
      summaryPills={summaryPills}
      onClearAll={handleClearAll}
    >
      <div className='filter-cols-row'> 
        {/* Characters Filter Block */}
        <div className="filter-col filter-col-md">
          <div className="filter-col-header">
            <label className="text-secondary text-sm font-semibold">Characters</label>
            <SegmentedControl<'AND' | 'OR'>
              options={[
                { value: 'AND', label: 'AND' },
                { value: 'OR', label: 'OR' },
              ]}
              value={characterLogic}
              onChange={newLogic => {
                setCharacterLogic(newLogic);
                if (newLogic === 'AND') {
                  setIncludeAlterEgos(false);
                  setIncludeFamiliars(false);
                  setIncludeNPCs(false);
                } else {
                  setIncludeAlterEgos(true);
                  setIncludeFamiliars(true);
                  setIncludeNPCs(true);
                }
              }}
              ariaLabel="Character Logic"
            />
          </div>

          <select
            value=""
            onChange={e => addCharFilter(Number(e.target.value))}
            className="select"
          >
            <option value="" disabled>
              Select character to filter...
            </option>
            {allCharacters.flatMap(c => [
              <option key={c.id} value={c.id}>
                {c.names?.[0] || c.name}
              </option>,
              ...(c.versions || []).map(v => (
                <option key={v.id} value={v.id}>
                  {' '}
                  └ {v.name} ({v.version_type || 'Alt'})
                </option>
              )),
            ])}
          </select>

          

          {/* Sub-Type Inclusions */}
          <div className="flex-row flex-wrap gap-xs mt-sm">
            <FilterChip
              active={characterLogic === 'OR' && includeAlterEgos}
              onClick={() => setIncludeAlterEgos(!includeAlterEgos)}
              className={characterLogic === 'AND' ? 'chip-sm opacity-50 pointer-events-none' : 'chip-sm'}
              title={characterLogic === 'AND' ? 'Disabled in AND mode' : 'Include Alter Egos'}
            >
              + Alter Egos
            </FilterChip>
            <FilterChip
              active={characterLogic === 'OR' && includeFamiliars}
              onClick={() => setIncludeFamiliars(!includeFamiliars)}
              className={characterLogic === 'AND' ? 'chip-sm opacity-50 pointer-events-none' : 'chip-sm'}
              title={characterLogic === 'AND' ? 'Disabled in AND mode' : 'Include Familiars'}
            >
              + Familiars
            </FilterChip>
            <FilterChip
              active={characterLogic === 'OR' && includeNPCs}
              onClick={() => setIncludeNPCs(!includeNPCs)}
              className={characterLogic === 'AND' ? 'chip-sm opacity-50 pointer-events-none' : 'chip-sm'}
              title={characterLogic === 'AND' ? 'Disabled in AND mode' : 'Include NPCs'}
            >
              + NPCs
            </FilterChip>
          </div>
        </div>
        
        

        {/* Writers Filter Block */}
        <div className="filter-col filter-col-md">
          <div className="filter-col-header">
            <label className="text-secondary text-sm font-semibold">Writers</label>
            <div className="flex-row items-center gap-xs">
              <FilterChip
                active={byMe}
                onClick={() => setByMe(!byMe)}
                title="Filter to items written by your linked Discord user"
              >
                ★ By Me
              </FilterChip>
              <SegmentedControl<'AND' | 'OR'>
                options={[
                  { value: 'AND', label: 'AND' },
                  { value: 'OR', label: 'OR' },
                ]}
                value={writerLogic}
                onChange={setWriterLogic}
                ariaLabel="Writer Logic"
              />
            </div>
          </div>

          <form onSubmit={addWriterFilter} className="flex-row gap-xs">
            <input
              type="text"
              value={writerInput}
              onChange={e => setWriterInput(e.target.value)}
              placeholder={byMe ? 'Bound to user session' : 'Add writer...'}
              disabled={byMe}
              className="input"
            />
          </form>
        </div>

        {/* Categories / Channels Filter Block */}
        <div className="filter-col filter-col-md">
          <div className="filter-col-header">
            <label className="text-secondary text-sm font-semibold">
              {isChannelFilterMode ? 'Channel (OR)' : 'Category (OR)'}
            </label>
          </div>
          <form onSubmit={addCategoryFilter} className="flex-row gap-xs">
            <input
              type="text"
              value={categoryInput}
              onChange={e => setCategoryInput(e.target.value)}
              placeholder={isChannelFilterMode ? 'Add channel...' : 'Add category...'}
              className="input"
            />
          </form>
        </div>
      
        {/* Status & Type Filter Block */}
        <div className="filter-col filter-col-auto">
          <div className="filter-col-header">
            <label className="text-secondary text-sm font-semibold">Status (OR)</label>
          </div>
          <div className="flex-row flex-wrap gap-xs">
            {statusOptions.map(s => (
              <FilterChip
                key={s}
                active={statusesFilter.includes(s)}
                onClick={() => toggleArrayItem(statusesFilter, setStatusesFilter, s)}
              >
                {s === 'no_end_tag' ? 'issues' : s}
              </FilterChip>
            ))}
          </div>
        </div>

        {!isChannelFilterMode && (
          <div className="filter-col filter-col-auto">
            <div className="filter-col-header">
              <label className="text-secondary text-sm font-semibold">Type (OR)</label>
            </div>
            <div className="flex-row flex-wrap gap-xs">
              {['channel', 'thread', 'DM'].map(t => (
                <FilterChip
                  key={t}
                  active={typesFilter.includes(t)}
                  onClick={() => toggleArrayItem(typesFilter, setTypesFilter, t)}
                >
                  {t}
                </FilterChip>
              ))}
            </div>
          </div>
        )}
        

        {/* Date Range Filter Block */}
        <div className="filter-group">
          <div className="filter-col filter-col-xs">
            <div className="filter-col-header">
              <label className="text-secondary text-sm font-semibold">Before</label>
            </div>
            <div>
              <input
                type="date"
                value={before}
                onChange={e => setBefore(e.target.value)}
                className="input"
              />  
            </div>
          </div>
          <div className="filter-col filter-col-xs">
            <div className="filter-col-header">
              <label className="text-secondary text-sm font-semibold">After</label>
            </div>
            <div>
              <input
                type="date"
                value={after}
                onChange={e => setAfter(e.target.value)}
                className="input"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Inline Active Filter Chips Row (ordered: Characters -> Writers -> Categories/Channels) */}
      {(charactersFilter.length > 0 || writersFilter.length > 0 || categoriesFilter.length > 0) && (
        <div className="filter-active-chips-row">
          <span className="filter-active-chips-label">Filters:</span>
          {charactersFilter.map(id => (
            <FilterChip
              key={`char-${id}`}
              active
              variant="accent"
              icon={<User size={12} />}
              onRemove={() => removeCharFilter(id)}
              title="Remove character filter"
            >
              {resolveCharacterName(id, allCharacters) || `Unknown (${id})`}
            </FilterChip>
          ))}
          {writersFilter.map(w => (
            <FilterChip
              key={`writer-${w}`}
              active
              variant="info"
              icon={<UserCheck size={12} />}
              onRemove={() => removeWriterFilter(w)}
              title="Remove writer filter"
            >
              {w}
            </FilterChip>
          ))}
          {categoriesFilter.map(c => (
            <FilterChip
              key={`cat-${c}`}
              active
              variant="success"
              icon={isChannelFilterMode ? <Hash size={12} /> : <Folder size={12} />}
              onRemove={() => removeCategoryFilter(c)}
              title={isChannelFilterMode ? 'Remove channel filter' : 'Remove category filter'}
            >
              {c}
            </FilterChip>
          ))}
        </div>
      )}
    </CollapsibleFilterBar>
  );
};

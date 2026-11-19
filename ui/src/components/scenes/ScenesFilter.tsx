import React, { useMemo } from 'react';
import { User, Users, UserCheck, Search } from 'lucide-react';
import {
  CollapsibleFilterBar,
  SegmentedControl,
  FilterChip,
  Badge,
  CharacterPicker,
  WriterPicker,
} from '../ui';
import { getGroupDisplayName, resolveCharacterName } from '../../utils/characters';
import type { Character, CharacterGroup, WriterDetailed } from '../../types';

export interface ScenesFilterProps {
  search: string;
  setSearch: (v: string) => void;
  charactersFilter: number[];
  setCharactersFilter: (v: number[]) => void;
  groupsFilter?: number[];
  setGroupsFilter?: (v: number[]) => void;
  characterLogic: 'AND' | 'OR';
  setCharacterLogic: (v: 'AND' | 'OR') => void;
  writersFilter: string[];
  setWritersFilter: (v: string[]) => void;
  writerLogic: 'AND' | 'OR';
  setWriterLogic: (v: 'AND' | 'OR') => void;
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
  allGroups?: CharacterGroup[];
  allWriters?: WriterDetailed[];
}

export const ScenesFilter: React.FC<ScenesFilterProps> = ({
  search,
  setSearch,
  charactersFilter,
  setCharactersFilter,
  groupsFilter = [],
  setGroupsFilter,
  characterLogic,
  setCharacterLogic,
  writersFilter,
  setWritersFilter,
  writerLogic,
  setWriterLogic,
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
  allGroups = [],
  allWriters = [],
}) => {
  const selectedWriterIds = useMemo(() => {
    if (writersFilter.length === 0 || allWriters.length === 0) return [];
    const selectedNames = new Set(writersFilter.map(w => w.trim().toLowerCase()).filter(Boolean));
    return allWriters
      .filter(
        w =>
          selectedNames.has(w.display_name.trim().toLowerCase()) ||
          (w.aliases || []).some(a => selectedNames.has(a.trim().toLowerCase()))
      )
      .map(w => w.id);
  }, [writersFilter, allWriters]);

  const handleWriterIdsChange = (ids: number[]) => {
    const idSet = new Set(ids);
    const nextNames = allWriters.filter(w => idSet.has(w.id)).map(w => w.display_name);
    setWritersFilter(nextNames);
  };

  const removeCharFilter = (id: number) => {
    setCharactersFilter(charactersFilter.filter(x => x !== id));
  };

  const removeGroupFilter = (gid: number) => {
    setGroupsFilter?.(groupsFilter.filter(x => x !== gid));
  };

  const removeWriterFilter = (w: string) => {
    setWritersFilter(writersFilter.filter(x => x !== w));
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
  const filtersTitle = mode === 'events' ? 'Event' : mode === 'sessions' ? 'Chat Sessions' : 'Scenes';
  const trimmedSearch = search.trim();

  const activeCount =
    (trimmedSearch ? 1 : 0) +
    charactersFilter.length +
    groupsFilter.length +
    writersFilter.length +
    (byMe ? 1 : 0) +
    statusesFilter.length +
    typesFilter.length +
    (before ? 1 : 0) +
    (after ? 1 : 0);

  const handleClearAll = () => {
    setSearch('');
    setCharactersFilter([]);
    setGroupsFilter?.([]);
    setWritersFilter([]);
    setByMe(false);
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
      {trimmedSearch && <Badge variant="neutral">Search: &quot;{trimmedSearch}&quot;</Badge>}
      {byMe && <Badge variant="accent">★ By Me</Badge>}
      {charactersFilter.length > 0 && (
        <Badge variant="neutral">
          {charactersFilter.length} char{charactersFilter.length > 1 ? 's' : ''}
        </Badge>
      )}
      {groupsFilter.length > 0 && (
        <Badge variant="neutral">
          {groupsFilter.length} group{groupsFilter.length > 1 ? 's' : ''}
        </Badge>
      )}
      {writersFilter.length > 0 && (
        <Badge variant="neutral">
          {writersFilter.length} writer{writersFilter.length > 1 ? 's' : ''}
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

          <CharacterPicker
            characters={allCharacters}
            selectedIds={charactersFilter}
            onChange={setCharactersFilter}
            groups={allGroups}
            selectedGroupIds={groupsFilter}
            onChangeGroups={setGroupsFilter}
            multiple={true}
            includeVersions={true}
            variant="dropdown"
            showSelectedChips={false}
            placeholder="Search characters or groups..."
            maxListHeight={240}
          />

          

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

          <WriterPicker
            writers={allWriters}
            selectedIds={selectedWriterIds}
            onChange={handleWriterIdsChange}
            multiple={true}
            variant="dropdown"
            showSelectedChips={false}
            disabled={byMe}
            placeholder={byMe ? 'Bound to user session' : 'Search writers...'}
            maxListHeight={240}
          />
        </div>
        
        {/* Unified Search Filter Block (custom name, key, channel, category) */}
        <div className="filter-col filter-col-md">
          <div className="filter-col-header" style={{paddingTop:'0.5rem'}}>
            <label className="text-secondary text-sm font-semibold">Search</label>
          </div>
          <div className="search-input-wrapper">
            <Search size={14} />
            <input
              type="text"
              className="input"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Name, channel, or category..."
            />
          </div>
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

      {/* Inline Active Filter Chips Row (ordered: Groups/Characters -> Writers) */}
      {(groupsFilter.length > 0 || charactersFilter.length > 0 || writersFilter.length > 0) && (
        <div className="filter-active-chips-row">
          <span className="filter-active-chips-label">Filters:</span>
          {groupsFilter.map(gid => {
            const grp = allGroups.find(g => g.id === gid);
            const label = grp ? `${getGroupDisplayName(grp)} (Group)` : `Group #${gid}`;
            return (
              <FilterChip
                key={`group-${gid}`}
                active
                variant="accent"
                icon={<Users size={12} />}
                onRemove={() => removeGroupFilter(gid)}
                title="Remove character group filter"
              >
                {label}
              </FilterChip>
            );
          })}
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
        </div>
      )}
    </CollapsibleFilterBar>
  );
};

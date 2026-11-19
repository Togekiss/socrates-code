import React from 'react';
import { ArrowUpDown, Search } from 'lucide-react';
import {
  Badge,
  CollapsibleFilterBar,
  DualRangeSlider,
  FilterChip,
  SegmentedControl,
} from '../ui';

export type WriterLinkFilter = 'all' | 'linked' | 'unlinked';
export type WriterSortBy = 'name' | 'id';
export type WriterSortOrder = 'asc' | 'desc';

export interface WritersFilterProps {
  searchFilter: string;
  setSearchFilter: (v: string) => void;
  linkFilter: WriterLinkFilter;
  setLinkFilter: (v: WriterLinkFilter) => void;
  showLinkFilter?: boolean;
  charCountMin: number;
  setCharCountMin: (v: number) => void;
  charCountMax: number | null;
  setCharCountMax: (v: number | null) => void;
  maxCharacters: number;
  sortBy: WriterSortBy;
  setSortBy: (v: WriterSortBy) => void;
  sortOrder: WriterSortOrder;
  setSortOrder: (v: WriterSortOrder) => void;
}

const LINK_OPTIONS: Array<{ value: WriterLinkFilter; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'linked', label: 'Linked' },
  { value: 'unlinked', label: 'Unlinked' },
];

const SORT_OPTIONS: Array<{ value: WriterSortBy; label: string }> = [
  { value: 'name', label: 'Name' },
  { value: 'id', label: 'ID' },
];

export const WritersFilter: React.FC<WritersFilterProps> = ({
  searchFilter,
  setSearchFilter,
  linkFilter,
  setLinkFilter,
  showLinkFilter = true,
  charCountMin,
  setCharCountMin,
  charCountMax,
  setCharCountMax,
  maxCharacters,
  sortBy,
  setSortBy,
  sortOrder,
  setSortOrder,
}) => {
  const effectiveMin = Math.min(charCountMin, maxCharacters);
  const effectiveMax = Math.min(charCountMax ?? maxCharacters, maxCharacters);
  const isRangeActive = effectiveMin > 0 || effectiveMax < maxCharacters;

  const trimmedSearch = searchFilter.trim();
  let activeCount = 0;
  if (trimmedSearch) activeCount++;
  if (showLinkFilter && linkFilter !== 'all') activeCount++;
  if (isRangeActive) activeCount++;

  const handleClearAll = () => {
    setSearchFilter('');
    setLinkFilter('all');
    setCharCountMin(0);
    setCharCountMax(null);
  };

  const summaryPills = (
    <div className="flex-row items-center gap-xs">
      {trimmedSearch && <Badge variant="neutral">Name: &quot;{trimmedSearch}&quot;</Badge>}
      {showLinkFilter && linkFilter !== 'all' && (
        <Badge variant={linkFilter === 'linked' ? 'success' : 'warning'}>
          {linkFilter === 'linked' ? 'Linked' : 'Unlinked'}
        </Badge>
      )}
      {isRangeActive && (
        <Badge variant="info">
          Chars: {effectiveMin}–{effectiveMax}
        </Badge>
      )}
    </div>
  );

  return (
    <CollapsibleFilterBar
      title="Writers"
      activeCount={activeCount}
      summaryPills={summaryPills}
      onClearAll={handleClearAll}
    >
      <div className="filter-cols-row">
        {/* Writer Name / Alias Search */}
        <div className="filter-col filter-col-md">
          <div className="filter-col-header">
            <label className="text-secondary text-sm font-semibold">Writer Name / Alias</label>
          </div>
          <div className="search-input-wrapper">
            <Search size={14} />
            <input
              type="text"
              className="input"
              value={searchFilter}
              onChange={e => setSearchFilter(e.target.value)}
              placeholder="Filter by name or alias..."
            />
          </div>
        </div>

        {/* Linked / Unlinked Status */}
        {showLinkFilter && (
          <div className="filter-col filter-col-auto">
            <div className="filter-col-header">
              <label className="text-secondary text-sm font-semibold">Discord Link</label>
            </div>
            <SegmentedControl<WriterLinkFilter>
              options={LINK_OPTIONS}
              value={linkFilter}
              onChange={setLinkFilter}
              ariaLabel="Filter writers by Discord link status"
            />
          </div>
        )}

        {/* Assigned Character Count Double Range Slider */}
        <div className="filter-col filter-col-sm">
          <div className="filter-col-header">
            <label className="text-secondary text-sm font-semibold">Characters</label>
            <span className={isRangeActive ? 'filter-range-value is-active' : 'filter-range-value'}>
              {effectiveMin} – {effectiveMax}
            </span>
          </div>
          <div className="filter-slider-box">
            <DualRangeSlider
              min={0}
              max={maxCharacters}
              value={[effectiveMin, effectiveMax]}
              onChange={([nextMin, nextMax]) => {
                setCharCountMin(nextMin);
                setCharCountMax(nextMax >= maxCharacters ? null : nextMax);
              }}
              minAriaLabel="Minimum assigned characters"
              maxAriaLabel="Maximum assigned characters"
            />
          </div>
        </div>

        {/* Sort By (Alphabetical Display Name vs ID) */}
        <div className="filter-col filter-col-auto">
          <div className="filter-col-header">
            <label className="text-secondary text-sm font-semibold">Sort By</label>
          </div>
          <div className="flex-row" style={{ gap: '0.3rem'}}>
          <SegmentedControl<WriterSortBy>
            options={SORT_OPTIONS}
            value={sortBy}
            onChange={setSortBy}
            ariaLabel="Sort writers by"
          />
          <FilterChip
              active={sortOrder === 'desc'}
              onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
              title={
                sortOrder === 'asc'
                  ? 'Ascending order (click to reverse)'
                  : 'Descending order (click to reverse)'
              }
              className="chip-square"
            >
              <ArrowUpDown size={11} />
              {sortOrder === 'asc' ? 'Asc' : 'Desc'}
            </FilterChip>
            </div>
        </div>
      </div>
    </CollapsibleFilterBar>
  );
};

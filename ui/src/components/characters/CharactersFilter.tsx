import React from 'react';
import { Search, Star, Tag, UserX } from 'lucide-react';
import { CollapsibleFilterBar, FilterChip, Badge } from '../ui';

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
  unassignedOnly?: boolean;
  setUnassignedOnly?: (v: boolean) => void;
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
  unassignedOnly = false,
  setUnassignedOnly,
}) => {
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

  let activeCount = 0;
  if (nameFilter) activeCount++;
  if (writerFilter) activeCount++;
  if (byMe) activeCount++;
  if (unassignedOnly) activeCount++;
  activeCount += tagsFilter.length;

  const handleClearAll = () => {
    setNameFilter('');
    setWriterFilter('');
    setTagsFilter([]);
    setByMe(false);
    setUnassignedOnly?.(false);
  };

  const summaryPills = (
    <div className="flex-row items-center gap-xs">
      {nameFilter && <Badge variant="neutral">Name: &quot;{nameFilter}&quot;</Badge>}
      {writerFilter && <Badge variant="neutral">Writer: &quot;{writerFilter}&quot;</Badge>}
      {byMe && <Badge variant="accent">★ By Me</Badge>}
      {unassignedOnly && <Badge variant="warning">Unassigned</Badge>}
      {tagsFilter.length > 0 && (
        <Badge
          variant="info"
          title={tagsFilter.map(t => '#' + t.replace(/_/g, ' ')).join(', ')}
        >
          {tagsFilter.length === 1
            ? `#${tagsFilter[0].replace(/_/g, ' ')}`
            : `${tagsFilter.length} tags`}
        </Badge>
      )}
    </div>
  );

  return (
    <CollapsibleFilterBar
      title="Character Searcher"
      activeCount={activeCount}
      summaryPills={summaryPills}
      onClearAll={handleClearAll}
    >
      <div className="filter-cols-row">
        {/* Character Name Filter */}
        <div className="filter-col filter-col-md">
          <div className="filter-col-header">
            <label className="text-secondary text-sm font-semibold">Character Name</label>
          </div>
          <div className="search-input-wrapper">
            <Search size={14} />
            <input
              type="text"
              className="input"
              value={nameFilter}
              onChange={e => setNameFilter(e.target.value)}
              placeholder="Filter by name..."
            />
          </div>
        </div>

        {/* Writer Filter & Associated Toggles */}
        <div className="filter-col filter-col-md">
          <div className="filter-col-header">
            <label className="text-secondary text-sm font-semibold">Writer</label>
            <div className="flex-row items-center gap-xs">
              {isLoggedIn && (
                <FilterChip
                  active={byMe}
                  onClick={() => {
                    if (!byMe && unassignedOnly) setUnassignedOnly?.(false);
                    if (!byMe) setWriterFilter('');
                    setByMe(!byMe);
                  }}
                  title="Filter to characters written by you"
                >
                  <Star size={11} fill={byMe ? 'currentColor' : 'none'} /> By Me
                </FilterChip>
              )}

              {setUnassignedOnly && (
                <FilterChip
                  active={unassignedOnly}
                  onClick={() => {
                    if (!unassignedOnly && byMe) setByMe(false);
                    if (!unassignedOnly) setWriterFilter('');
                    setUnassignedOnly(!unassignedOnly);
                  }}
                  title="Show only characters without a designated writer"
                >
                  <UserX size={11} /> Unassigned
                </FilterChip>
              )}
            </div>
          </div>
          <div className="search-input-wrapper">
            <Search size={14} />
            <input
              type="text"
              className="input"
              value={writerFilter}
              onChange={e => setWriterFilter(e.target.value)}
              placeholder={
                byMe
                  ? 'Bound to your user'
                  : unassignedOnly
                  ? 'Showing unassigned'
                  : 'Filter by writer...'
              }
              disabled={byMe || unassignedOnly}
            />
          </div>
        </div>

        {/* Tag Selector */}
        {availableTags.length > 0 && (
          <div className="filter-col filter-col-sm filter-col-right">
            <div className="filter-col-header">
              <label className="text-secondary text-sm font-semibold">Tags (AND logic)</label>
            </div>
            <select
              className="select"
              onChange={handleSelectTag}
              defaultValue=""
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
          </div>
        )}
      </div>

      {/* Inline Active Tag Filter Chips Row */}
      {tagsFilter.length > 0 && (
        <div className="filter-active-chips-row">
          <span className="filter-active-chips-label">Filters:</span>
          {tagsFilter.map(tag => (
            <FilterChip
              key={`tag-${tag}`}
              active
              variant="info"
              icon={<Tag size={12} />}
              onRemove={() => removeTag(tag)}
              title="Remove tag filter"
            >
              {tag.replace(/_/g, ' ')}
            </FilterChip>
          ))}
        </div>
      )}
    </CollapsibleFilterBar>
  );
};

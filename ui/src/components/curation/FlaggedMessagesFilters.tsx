import React from 'react';
import { Plus } from 'lucide-react';
import { CollapsibleFilterBar, SegmentedControl, FilterChip, Badge, Button } from '../ui';

const KIND_OPTIONS = [
  { value: 'failed_tupper', label: 'Failed Tupper' },
  { value: 'ooc_boundary', label: 'OOC Boundary' },
  { value: 'ooc_message', label: 'OOC Message' },
  { value: 'manual', label: 'Manual' },
] as const;

const RESOLUTION_OPTIONS = [
  { value: 'override', label: 'Overridden' },
  { value: 'ignored', label: 'Ignored' },
  { value: 'kept', label: 'Kept' },
] as const;

export interface FlaggedMessagesFiltersProps {
  totalItems: number;
  statusFilter: 'unresolved' | 'resolved' | 'all';
  onStatusChange: (status: 'unresolved' | 'resolved' | 'all') => void;
  statusCounts: { unresolved: number; resolved: number; all: number };
  scopeCounts?: Record<string, number>;
  kindFilter: string;
  onKindChange: (kind: string) => void;
  sceneTypeFilter?: string;
  onSceneTypeChange?: (sceneType: string) => void;
  resolutionFilter: string;
  onResolutionChange: (res: string) => void;
  onOpenAddModal: () => void;
}

export const FlaggedMessagesFilters: React.FC<FlaggedMessagesFiltersProps> = ({
  totalItems,
  statusFilter,
  onStatusChange,
  statusCounts,
  scopeCounts,
  kindFilter,
  onKindChange,
  sceneTypeFilter = '',
  onSceneTypeChange,
  resolutionFilter,
  onResolutionChange,
  onOpenAddModal,
}) => {
  const handleKindClick = (value: string) => {
    onKindChange(kindFilter === value ? '' : value);
  };

  const handleResolutionClick = (value: string) => {
    onResolutionChange(resolutionFilter === value ? '' : value);
  };

  const activeCount =
    (statusFilter !== 'all' ? 1 : 0) +
    (sceneTypeFilter ? 1 : 0) +
    (kindFilter ? 1 : 0) +
    (resolutionFilter && statusFilter !== 'unresolved' ? 1 : 0);

  const handleClearAll = () => {
    onStatusChange('unresolved');
    if (onSceneTypeChange) onSceneTypeChange('');
    onKindChange('');
    onResolutionChange('');
  };

  const scopeOptions = [
    { value: '', label: 'All', count: scopeCounts?.all },
    { value: 'scene', label: 'Scene', count: scopeCounts?.scene },
    { value: 'session', label: 'Session', count: scopeCounts?.session },
    { value: 'event', label: 'Event', count: scopeCounts?.event },
  ];

  const statusOptions = [
    { value: 'unresolved' as const, label: 'Unresolved', count: statusCounts.unresolved },
    { value: 'resolved' as const, label: 'Resolved', count: statusCounts.resolved },
    { value: 'all' as const, label: 'All', count: statusCounts.all },
  ];

  const summaryPills = (
    <div className="flex-row items-center gap-xs flex-wrap">
      <Badge variant="accent">
        {statusFilter === 'unresolved'
          ? 'Unresolved'
          : statusFilter === 'resolved'
          ? 'Resolved'
          : 'All Statuses'}
      </Badge>
      {sceneTypeFilter && (
        <Badge variant="neutral">
          Scope:{' '}
          {sceneTypeFilter === 'scene'
            ? 'Scenes'
            : sceneTypeFilter === 'session'
            ? 'Sessions'
            : 'Events'}
        </Badge>
      )}
      {kindFilter && (
        <Badge variant="neutral">
          Kind: {KIND_OPTIONS.find(k => k.value === kindFilter)?.label || kindFilter}
        </Badge>
      )}
      {resolutionFilter && statusFilter !== 'unresolved' && (
        <Badge variant="neutral">
          Resolution:{' '}
          {RESOLUTION_OPTIONS.find(r => r.value === resolutionFilter)?.label || resolutionFilter}
        </Badge>
      )}
    </div>
  );

  return (
    <CollapsibleFilterBar
      title={`Flagged Messages Review Queue (${totalItems})`}
      activeCount={activeCount}
      summaryPills={summaryPills}
      onClearAll={handleClearAll}
      actions={
        <Button
          variant="secondary"
          size="xs"
          onClick={onOpenAddModal}
          icon={<Plus size={13} />}
          title="Add flagged message manually"
        >
          Add Message
        </Button>
      }
      className="mb-md"
    >
      <div className="flex-col gap-md pt-xs">
        {/* Prominent Controls: Status & Archive Scope Segmented Controls */}
        <div className="flex-row justify-between items-center flex-wrap gap-md">
          {/* Status Segmented Control */}
          <div className="flex-col gap-xs">
            <label className="text-secondary text-sm font-semibold">Status</label>
            <SegmentedControl<'unresolved' | 'resolved' | 'all'>
              options={statusOptions}
              value={statusFilter}
              onChange={onStatusChange}
              ariaLabel="Flagged Message Status Filter"
            />
          </div>

          {/* Archive Scope Segmented Control */}
          {onSceneTypeChange && (
            <div className="flex-col gap-xs">
              <label className="text-secondary text-sm font-semibold">Archive Scope</label>
              <SegmentedControl<string>
                options={scopeOptions}
                value={sceneTypeFilter}
                onChange={onSceneTypeChange}
                ariaLabel="Archive Scope Filter"
              />
            </div>
          )}
        </div>

        {/* Independent Kind & Resolution Toggles */}
        <div className="flex-row items-center justify-between flex-wrap gap-md pt-xs border-t border-color">
          {/* Flagged Message Kind Chips */}
          <div className="flex-col gap-xs">
            <label className="text-secondary text-sm font-semibold">Message Kind</label>
            <div className="flex-row items-center gap-xs flex-wrap">
              {KIND_OPTIONS.map(opt => (
                <FilterChip
                  key={opt.value}
                  active={kindFilter === opt.value}
                  onClick={() => handleKindClick(opt.value)}
                >
                  {opt.label}
                </FilterChip>
              ))}
            </div>
          </div>

          {/* Resolution Chips (only applicable when viewing resolved or all) */}
          {statusFilter !== 'unresolved' && (
            <div className="flex-col gap-xs">
              <label className="text-secondary text-sm font-semibold">Resolution</label>
              <div className="flex-row items-center gap-xs flex-wrap">
                {RESOLUTION_OPTIONS.map(opt => (
                  <FilterChip
                    key={opt.value}
                    active={resolutionFilter === opt.value}
                    onClick={() => handleResolutionClick(opt.value)}
                  >
                    {opt.label}
                  </FilterChip>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </CollapsibleFilterBar>
  );
};

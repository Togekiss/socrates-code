import React from 'react';
import { Plus } from 'lucide-react';
import { CollapsibleFilterBar, SegmentedControl, FilterChip, Badge, Button } from '../ui';

const KIND_OPTIONS = [
  { value: 'auto_split', label: 'Auto Split' },
  { value: 'soft_boundary', label: 'Soft Boundary' },
] as const;

const REASON_OPTIONS = [
  { value: '', label: 'All Reasons' },
  { value: 'separate_roster', label: 'Separate Roster' },
  { value: 'start_tag_roster_change', label: 'Start Tag, Roster Change' },
  { value: 'start_tag_same_roster', label: 'Start Tag, Same Roster' },
  { value: 'roster_change', label: 'Roster Change' },
  { value: 'inactivity_gap', label: 'Inactivity Gap' },
  { value: 'tupper_end_tag', label: 'Tupper End Tag' },
  { value: 'manual', label: 'Manual Split' },
] as const;

const KIND_TO_REASONS: Record<string, string[]> = {
  auto_split: ['separate_roster', 'start_tag_roster_change', 'inactivity_gap', 'manual'],
  soft_boundary: ['start_tag_same_roster', 'roster_change', 'manual', 'tupper_end_tag'],
};

export interface SceneIssuesFiltersProps {
  totalItems: number;
  statusFilter: 'unresolved' | 'resolved' | 'all';
  onStatusChange: (status: 'unresolved' | 'resolved' | 'all') => void;
  statusCounts: { unresolved: number; resolved: number; all: number };
  scopeCounts?: Record<string, number>;
  kindFilter: string;
  onKindChange: (kind: string) => void;
  sceneTypeFilter?: string;
  onSceneTypeChange?: (sceneType: string) => void;
  reasonFilter: string;
  onReasonChange: (reason: string) => void;
  onOpenManualSplit?: () => void;
}

export const SceneIssuesFilters: React.FC<SceneIssuesFiltersProps> = ({
  totalItems,
  statusFilter,
  onStatusChange,
  statusCounts,
  scopeCounts,
  kindFilter,
  onKindChange,
  sceneTypeFilter = '',
  onSceneTypeChange,
  reasonFilter,
  onReasonChange,
  onOpenManualSplit,
}) => {
  const handleKindClick = (value: string) => {
    const nextKind = kindFilter === value ? '' : value;
    onKindChange(nextKind);

    if (nextKind && reasonFilter) {
      const allowed = KIND_TO_REASONS[nextKind] || [];
      if (!allowed.includes(reasonFilter)) {
        onReasonChange('');
      }
    }
  };

  const visibleReasonOptions = REASON_OPTIONS.filter(opt => {
    if (!opt.value) return true;
    if (!kindFilter) return true;
    return KIND_TO_REASONS[kindFilter]?.includes(opt.value);
  });

  React.useEffect(() => {
    if (kindFilter && reasonFilter) {
      const allowed = KIND_TO_REASONS[kindFilter] || [];
      if (!allowed.includes(reasonFilter)) {
        onReasonChange('');
      }
    }
  }, [kindFilter, reasonFilter, onReasonChange]);

  const activeCount =
    (statusFilter !== 'all' ? 1 : 0) +
    (sceneTypeFilter ? 1 : 0) +
    (kindFilter ? 1 : 0) +
    (reasonFilter ? 1 : 0);

  const handleClearAll = () => {
    onStatusChange('unresolved');
    if (onSceneTypeChange) onSceneTypeChange('');
    onKindChange('');
    onReasonChange('');
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
          Kind: {kindFilter === 'auto_split' ? 'Auto Split' : 'Soft Boundary'}
        </Badge>
      )}
      {reasonFilter && (
        <Badge variant="neutral">Reason: {reasonFilter.replace(/_/g, ' ')}</Badge>
      )}
    </div>
  );

  return (
    <CollapsibleFilterBar
      title={`Scene Issues Review Queue (${totalItems})`}
      activeCount={activeCount}
      summaryPills={summaryPills}
      onClearAll={handleClearAll}
      actions={
        onOpenManualSplit && (
          <Button
            variant="secondary"
            size="xs"
            onClick={onOpenManualSplit}
            icon={<Plus size={13} />}
            title="Create manual scene split"
          >
            Manual Split
          </Button>
        )
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
              ariaLabel="Issue Status Filter"
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

        {/* Independent Kind & Reason Toggles */}
        <div className="flex-row items-center justify-between flex-wrap gap-md pt-xs border-t border-color">
          {/* Issue Kind Chips */}
          <div className="flex-col gap-xs">
            <label className="text-secondary text-sm font-semibold">Issue Kind</label>
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

          {/* Reason Filter Dropdown */}
          <div className="flex-col gap-xs" style={{ minWidth: '220px' }}>
            <label className="text-secondary text-sm font-semibold">Trigger Reason</label>
            <select
              value={reasonFilter}
              onChange={e => onReasonChange(e.target.value)}
              className="select"
              style={{ padding: '0.35rem 0.6rem', fontSize: '0.82rem' }}
            >
              {visibleReasonOptions.map(opt => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>
    </CollapsibleFilterBar>
  );
};

import React from 'react';
import { AlertTriangle, Plus } from 'lucide-react';

const KIND_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'auto_split', label: 'Auto Split' },
  { value: 'soft_boundary', label: 'Soft Boundary' },
] as const;

const REASON_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'separate_roster', label: 'Separate Roster' },
  { value: 'start_tag_roster_change', label: 'Start Tag, Roster Change' },
  { value: 'start_tag_same_roster', label: 'Start Tag, Same Roster' },
  { value: 'roster_change', label: 'Roster Change' },
  { value: 'manual', label: 'Manual Split' },
] as const;

const KIND_TO_REASONS: Record<string, string[]> = {
  auto_split: ['separate_roster', 'start_tag_roster_change'],
  soft_boundary: ['start_tag_same_roster', 'roster_change', 'manual'],
};

export interface SceneIssuesFiltersProps {
  totalItems: number;
  statusFilter: 'unresolved' | 'resolved' | 'all';
  onStatusChange: (status: 'unresolved' | 'resolved' | 'all') => void;
  statusCounts: { unresolved: number; resolved: number; all: number };
  kindFilter: string;
  onKindChange: (kind: string) => void;
  reasonFilter: string;
  onReasonChange: (reason: string) => void;
  onOpenManualSplit?: () => void;
}

export const SceneIssuesFilters: React.FC<SceneIssuesFiltersProps> = ({
  totalItems,
  statusFilter,
  onStatusChange,
  statusCounts,
  kindFilter,
  onKindChange,
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

  const handleReasonClick = (value: string) => {
    const nextReason = reasonFilter === value ? '' : value;
    onReasonChange(nextReason);
  };

  return (
    <div
      className="glass-panel"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '1.15rem',
      }}
    >
      {/* Top: Header Info & Status Filter & Manual Split */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div
            style={{
              width: '40px',
              height: '40px',
              borderRadius: '8px',
              background: 'rgba(239, 68, 68, 0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--danger)',
            }}
          >
            <AlertTriangle size={22} />
          </div>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.25rem', color: 'var(--text-primary)' }}>
              Scene Issues Review Queue
            </h2>
            <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-muted)' }}>
              Anomalous scenes flagged during pipeline indexing ({statusCounts.all || totalItems} total)
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          {/* Status Buttons */}
          <div style={{ display: 'flex', gap: '0.35rem' }}>
            {(['unresolved', 'resolved', 'all'] as const).map(st => (
              <button
                key={st}
                onClick={() => onStatusChange(st)}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.45rem',
                  padding: '0.35rem 0.8rem',
                  borderRadius: '6px',
                  fontSize: '0.85rem',
                  border: statusFilter === st ? '1px solid var(--accent-secondary)' : '1px solid var(--border-color)',
                  background: statusFilter === st ? 'rgba(109, 40, 217, 0.25)' : 'var(--bg-tertiary)',
                  color: statusFilter === st ? '#fff' : 'var(--text-secondary)',
                  fontWeight: statusFilter === st ? 600 : 400,
                  cursor: 'pointer',
                  transition: 'all var(--transition-fast)',
                }}
              >
                <span style={{ textTransform: 'capitalize' }}>{st}</span>
                <span
                  style={{
                    padding: '0.1rem 0.45rem',
                    borderRadius: '10px',
                    fontSize: '0.75rem',
                    fontWeight: 700,
                    background: statusFilter === st ? 'rgba(255, 255, 255, 0.2)' : 'rgba(255, 255, 255, 0.08)',
                    color: statusFilter === st ? '#fff' : 'var(--text-muted)',
                  }}
                >
                  {statusCounts[st] ?? 0}
                </span>
              </button>
            ))}
          </div>

          {/* Manual Split Button */}
          {onOpenManualSplit && (
            <button
              onClick={onOpenManualSplit}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.4rem',
                padding: '0.35rem 0.85rem',
                borderRadius: '6px',
                fontSize: '0.85rem',
                border: '1px solid var(--accent-secondary)',
                background: 'var(--accent-secondary)',
                color: '#fff',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              <Plus size={15} /> Manual Split
            </button>
          )}
        </div>
      </div>

      {/* Filter Rows: Kind and Reason */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '1rem',
          paddingTop: '0.85rem',
          borderTop: '1px solid var(--border-color)',
        }}
      >
        {/* Kind Buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 500 }}>Kind:</span>
          <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
            {KIND_OPTIONS.map(opt => {
              const isActive = kindFilter === opt.value;
              return (
                <button
                  key={opt.value}
                  onClick={() => handleKindClick(opt.value)}
                  style={{
                    padding: '0.35rem 0.75rem',
                    borderRadius: '6px',
                    fontSize: '0.85rem',
                    border: isActive ? '1px solid var(--accent-secondary)' : '1px solid var(--border-color)',
                    background: isActive ? 'rgba(109, 40, 217, 0.25)' : 'var(--bg-tertiary)',
                    color: isActive ? '#fff' : 'var(--text-secondary)',
                    fontWeight: isActive ? 600 : 400,
                    cursor: 'pointer',
                    transition: 'all var(--transition-fast)',
                  }}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Reason Buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 500 }}>Reason:</span>
          <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
            {REASON_OPTIONS.map(opt => {
              const isActive = reasonFilter === opt.value;
              const isDisabled =
                opt.value !== '' &&
                kindFilter !== '' &&
                !KIND_TO_REASONS[kindFilter]?.includes(opt.value);

              return (
                <button
                  key={opt.value}
                  disabled={isDisabled}
                  onClick={() => {
                    if (isDisabled) return;
                    handleReasonClick(opt.value);
                  }}
                  style={{
                    padding: '0.35rem 0.75rem',
                    borderRadius: '6px',
                    fontSize: '0.85rem',
                    border: isActive ? '1px solid var(--accent-secondary)' : '1px solid var(--border-color)',
                    background: isActive ? 'rgba(109, 40, 217, 0.25)' : 'var(--bg-tertiary)',
                    color: isDisabled ? 'var(--text-muted)' : isActive ? '#fff' : 'var(--text-secondary)',
                    fontWeight: isActive ? 600 : 400,
                    cursor: isDisabled ? 'not-allowed' : 'pointer',
                    opacity: isDisabled ? 0.35 : 1,
                    transition: 'all var(--transition-fast)',
                  }}
                  title={
                    isDisabled
                      ? `Not applicable to ${kindFilter === 'auto_split' ? 'Auto Split' : 'Soft Boundary'}`
                      : undefined
                  }
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};

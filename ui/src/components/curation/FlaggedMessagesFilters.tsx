import React from 'react';
import { MessageSquareCode, Plus } from 'lucide-react';

const KIND_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'failed_tupper', label: 'Failed Tupper' },
  { value: 'ooc_boundary', label: 'OOC Boundary' },
  { value: 'ooc_message', label: 'OOC Message' },
  { value: 'manual', label: 'Manual' },
] as const;

const RESOLUTION_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'override', label: 'Overridden' },
  { value: 'ignored', label: 'Ignored' },
  { value: 'kept', label: 'Kept' },
] as const;

export interface FlaggedMessagesFiltersProps {
  totalItems: number;
  statusFilter: 'unresolved' | 'resolved' | 'all';
  onStatusChange: (status: 'unresolved' | 'resolved' | 'all') => void;
  statusCounts: { unresolved: number; resolved: number; all: number };
  kindFilter: string;
  onKindChange: (kind: string) => void;
  resolutionFilter: string;
  onResolutionChange: (res: string) => void;
  onOpenAddModal: () => void;
}

export const FlaggedMessagesFilters: React.FC<FlaggedMessagesFiltersProps> = ({
  totalItems,
  statusFilter,
  onStatusChange,
  statusCounts,
  kindFilter,
  onKindChange,
  resolutionFilter,
  onResolutionChange,
  onOpenAddModal,
}) => {
  return (
    <div
      className="glass-panel"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '1.15rem',
      }}
    >
      {/* Top: Header Info & Status Filter & Add Button */}
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
              background: 'rgba(109, 40, 217, 0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--accent-secondary)',
            }}
          >
            <MessageSquareCode size={22} />
          </div>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.25rem', color: 'var(--text-primary)' }}>
              Flagged Messages Review Queue
            </h2>
            <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-muted)' }}>
              Non-tupper dialogue, OOC messages, and boundary anomalies ({statusCounts.all || totalItems} total)
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

          {/* Add Flagged Message Button */}
          <button
            onClick={onOpenAddModal}
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
            <Plus size={15} /> Add Flagged Message
          </button>
        </div>
      </div>

      {/* Filter Rows: Kind and Resolution */}
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
                  onClick={() => onKindChange(kindFilter === opt.value ? '' : opt.value)}
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

        {/* Resolution Buttons (Only visible when viewing resolved or all) */}
        {statusFilter !== 'unresolved' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 500 }}>Resolution:</span>
            <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
              {RESOLUTION_OPTIONS.map(opt => {
                const isActive = resolutionFilter === opt.value;
                return (
                  <button
                    key={opt.value}
                    onClick={() => onResolutionChange(resolutionFilter === opt.value ? '' : opt.value)}
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
        )}
      </div>
    </div>
  );
};

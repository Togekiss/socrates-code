import { useState, useEffect, useCallback } from 'react';
import {
  CheckCircle,
  Loader2,
  Info,
  ChevronDown,
} from 'lucide-react';
import { api } from '../api';
import { ResolveIssueModal } from './curation/ResolveIssueModal';
import { ActionConfirmationModal } from './curation/ActionConfirmationModal';
import { ManualSplitModal } from './curation/ManualSplitModal';
import { SceneIssueCard } from './curation/SceneIssueCard';
import { SceneIssuesFilters } from './curation/SceneIssuesFilters';
import type { SceneIssue, SceneIssuesResponse } from '../types';

interface SceneIssuesTabProps {
  backupId: string;
  onRefreshSummary?: () => void;
}

export const SceneIssuesTab = ({ backupId, onRefreshSummary }: SceneIssuesTabProps) => {
  const [data, setData] = useState<SceneIssuesResponse>({
    total_items: 0,
    issues: [],
    current_page: 1,
    per_page: 50,
    total_pages: 1,
  });
  const [statusCounts, setStatusCounts] = useState<{ unresolved: number; resolved: number; all: number }>({
    unresolved: 0,
    resolved: 0,
    all: 0,
  });
  const [statusFilter, setStatusFilter] = useState<'unresolved' | 'resolved' | 'all'>('unresolved');
  const [kindFilter, setKindFilter] = useState<string>('');
  const [reasonFilter, setReasonFilter] = useState<string>('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [resolvingIssue, setResolvingIssue] = useState<SceneIssue | null>(null);
  const [oppositeAction, setOppositeAction] = useState<{ action: 'merge' | 'split'; issue: SceneIssue } | null>(null);
  const [reopeningId, setReopeningId] = useState<number | null>(null);
  const [isManualSplitOpen, setIsManualSplitOpen] = useState(false);
  const [guideCollapsed, setGuideCollapsed] = useState(() => {
    return localStorage.getItem('socrates_scene_guide_collapsed') === 'true';
  });

  const toggleGuide = () => {
    setGuideCollapsed(prev => {
      const next = !prev;
      localStorage.setItem('socrates_scene_guide_collapsed', String(next));
      return next;
    });
  };

  const fetchIssues = useCallback(() => {
    if (!backupId) return;
    setLoading(true);

    const params = new URLSearchParams();
    params.append('page', page.toString());
    params.append('per_page', '50');
    if (statusFilter !== 'all') params.append('status', statusFilter);
    if (kindFilter) params.append('kind', kindFilter);
    if (reasonFilter) params.append('reason', reasonFilter);

    api
      .getSceneIssues(backupId, params)
      .then(res => {
        setData(res);
        if (res.status_counts) {
          setStatusCounts(res.status_counts);
        }
      })
      .catch(console.error)
      .finally(() => {
        setLoading(false);
        if (onRefreshSummary) onRefreshSummary();
      });
  }, [backupId, statusFilter, kindFilter, reasonFilter, page, onRefreshSummary]);

  useEffect(() => {
    fetchIssues();
  }, [fetchIssues]);

  const handleReopen = async (issueId: number) => {
    const targetIssue = data.issues.find(i => i.id === issueId);
    if (targetIssue?.action_performed) {
      if (
        !window.confirm(
          'Reopening this issue will undo the previous merge/split and modify scenes again. Continue?'
        )
      ) {
        return;
      }
    }
    setReopeningId(issueId);
    try {
      await api.reopenSceneIssue(backupId, issueId);
      fetchIssues();
    } catch (err) {
      console.error('Failed to reopen issue:', err);
    } finally {
      setReopeningId(null);
    }
  };

  const handleOpenOppositeAction = (action: 'merge' | 'split', issue: SceneIssue) => {
    setOppositeAction({ action, issue });
  };

  const handleCloseOppositeAction = () => {
    setOppositeAction(null);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header & Filter Controls */}
      <SceneIssuesFilters
        totalItems={data.total_items}
        statusFilter={statusFilter}
        onStatusChange={st => {
          setStatusFilter(st);
          setPage(1);
        }}
        statusCounts={statusCounts}
        kindFilter={kindFilter}
        onKindChange={k => {
          setKindFilter(k);
          setPage(1);
        }}
        reasonFilter={reasonFilter}
        onReasonChange={r => {
          setReasonFilter(r);
          setPage(1);
        }}
        onOpenManualSplit={() => setIsManualSplitOpen(true)}
      />

      {/* Informational Guide (Muted appearance, styled like Scenes tab Filters box) */}
      <div
        style={{
          background: 'var(--bg-secondary)',
          borderRadius: '8px',
          border: '1px solid var(--border-color)',
        }}
      >
        <div
          onClick={toggleGuide}
          style={{
            padding: '0.65rem 1rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            cursor: 'pointer',
            userSelect: 'none',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Info size={16} color="var(--accent-secondary)" />
            <strong style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
              How "Scene Issues" Work
            </strong>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--text-muted)', fontSize: '0.75rem' }}>
            <span>{guideCollapsed ? 'Show' : 'Hide'}</span>
            <ChevronDown
              size={14}
              style={{
                transform: guideCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
                transition: 'transform var(--transition-fast)',
              }}
            />
          </div>
        </div>

        {!guideCollapsed && (
          <div
            style={{
              padding: '0.85rem 1rem',
              borderTop: '1px solid var(--border-color)',
              fontSize: '0.825rem',
              lineHeight: '1.5',
              color: 'var(--text-secondary)',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.45rem',
            }}
          >
            <div>
              Socrates detects scenes using pattern recognition. When{' '}
              <code style={{ color: 'var(--accent-secondary)' }}>[END]</code> tags aren't clear, it makes a decision and leaves it here for human review.
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', marginTop: '0.15rem' }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem' }}>
                <span
                  style={{
                    background: 'rgba(234, 179, 8, 0.15)',
                    border: '1px solid rgba(234, 179, 8, 0.35)',
                    color: '#facc15',
                    padding: '0.08rem 0.4rem',
                    borderRadius: '4px',
                    fontSize: '0.7rem',
                    fontWeight: 700,
                    letterSpacing: '0.02em',
                    flexShrink: 0,
                  }}
                >
                  AUTO SPLIT
                </span>
                <span style={{ fontSize: '0.825rem', color: 'var(--text-muted)' }}>
                  Socrates registered this as the start of a new scene. If this is a mistake, you can merge the two scenes.
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem' }}>
                <span
                  style={{
                    background: 'rgba(139, 92, 246, 0.15)',
                    border: '1px solid rgba(139, 92, 246, 0.35)',
                    color: '#c4b5fd',
                    padding: '0.08rem 0.4rem',
                    borderRadius: '4px',
                    fontSize: '0.7rem',
                    fontWeight: 700,
                    letterSpacing: '0.02em',
                    flexShrink: 0,
                  }}
                >
                  SOFT BOUNDARY
                </span>
                <span style={{ fontSize: '0.825rem', color: 'var(--text-muted)' }}>
                  Socrates doubted, but didn't start a new scene. If this is a mistake, you can register this as a new scene.
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Issues List */}
      {loading ? (
        <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
          <Loader2 size={32} className="animate-spin" style={{ color: 'var(--accent-secondary)', margin: '0 auto 1rem auto' }} />
          <p style={{ color: 'var(--text-secondary)' }}>Loading scene issues...</p>
        </div>
      ) : data.issues.length === 0 ? (
        <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
          <CheckCircle size={36} style={{ color: 'var(--success)', marginBottom: '0.5rem' }} />
          <h3 style={{ margin: '0 0 0.5rem 0', color: 'var(--text-primary)' }}>
            No scene issues found
          </h3>
          <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            {statusFilter === 'unresolved'
              ? 'All scene issues for this backup have been resolved!'
              : 'No scene issues match your selected filters.'}
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {data.issues.map(iss => (
            <SceneIssueCard
              key={iss.id}
              issue={iss}
              isReopening={reopeningId === iss.id}
              onResolve={setResolvingIssue}
              onReopen={handleReopen}
              onOppositeAction={(action, targetIssue) => handleOpenOppositeAction(action, targetIssue)}
            />
          ))}
        </div>
      )}

      {/* Pagination Controls */}
      {data.total_pages > 1 && (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '0.75rem', marginTop: '0.5rem' }}>
          <button
            disabled={page <= 1}
            onClick={() => setPage(p => Math.max(1, p - 1))}
            style={{
              padding: '0.4rem 0.85rem',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-color)',
              color: 'white',
              borderRadius: '6px',
              cursor: page <= 1 ? 'not-allowed' : 'pointer',
              opacity: page <= 1 ? 0.45 : 1,
              fontSize: '0.85rem',
            }}
          >
            Previous
          </button>
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
            Page {page} of {data.total_pages} ({data.total_items} items)
          </span>
          <button
            disabled={page >= data.total_pages}
            onClick={() => setPage(p => p + 1)}
            style={{
              padding: '0.4rem 0.85rem',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-color)',
              color: 'white',
              borderRadius: '6px',
              cursor: page >= data.total_pages ? 'not-allowed' : 'pointer',
              opacity: page >= data.total_pages ? 0.45 : 1,
              fontSize: '0.85rem',
            }}
          >
            Next
          </button>
        </div>
      )}

      {/* Resolve Issue Modal */}
      {resolvingIssue && (
        <ResolveIssueModal
          backupId={backupId}
          issue={resolvingIssue}
          onClose={() => setResolvingIssue(null)}
          onResolved={fetchIssues}
        />
      )}

      {/* Opposite Action Confirmation Modal */}
      {oppositeAction && (
        <ActionConfirmationModal
          backupId={backupId}
          issue={oppositeAction.issue}
          action={oppositeAction.action}
          onClose={handleCloseOppositeAction}
          onResolved={fetchIssues}
        />
      )}

      {/* Manual Split Modal */}
      {isManualSplitOpen && (
        <ManualSplitModal
          backupId={backupId}
          onClose={() => setIsManualSplitOpen(false)}
          onSuccess={fetchIssues}
        />
      )}

    </div>
  );
};

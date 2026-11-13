import { useState, useEffect, useCallback } from 'react';
import {
  CheckCircle,
  Loader2,
  Info,
  ChevronDown,
} from 'lucide-react';
import { api, getErrorMessage } from '../api';
import { ResolveIssueModal } from './curation/ResolveIssueModal';
import { ActionConfirmationModal } from './curation/ActionConfirmationModal';
import { ManualSplitModal } from './curation/ManualSplitModal';
import { SceneIssueCard } from './curation/SceneIssueCard';
import { SceneIssuesFilters } from './curation/SceneIssuesFilters';
import { Pagination } from './ui';
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
  const [sceneTypeFilter, setSceneTypeFilter] = useState<string>('');
  const [reasonFilter, setReasonFilter] = useState<string>('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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

  useEffect(() => {
    setPage(1);
    setData({
      total_items: 0,
      issues: [],
      current_page: 1,
      per_page: 50,
      total_pages: 1,
    });
    setStatusCounts({ unresolved: 0, resolved: 0, all: 0 });
    setError(null);
  }, [backupId]);

  const fetchIssues = useCallback(() => {
    if (!backupId) return;
    setLoading(true);
    setError(null);

    const params = new URLSearchParams();
    params.append('page', page.toString());
    params.append('per_page', '50');
    if (statusFilter !== 'all') params.append('status', statusFilter);
    if (kindFilter) params.append('kind', kindFilter);
    if (sceneTypeFilter) params.append('scene_type', sceneTypeFilter);
    if (reasonFilter) params.append('reason', reasonFilter);

    api
      .getSceneIssues(backupId, params)
      .then(res => {
        setData(res);
        if (res.status_counts) {
          setStatusCounts(res.status_counts);
        }
      })
      .catch(err => {
        console.error(err);
        setData({
          total_items: 0,
          issues: [],
          current_page: 1,
          per_page: 50,
          total_pages: 1,
        });
        setError(getErrorMessage(err, 'Failed to load scene issues.'));
      })
      .finally(() => {
        setLoading(false);
      });
  }, [backupId, statusFilter, kindFilter, sceneTypeFilter, reasonFilter, page]);

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
      if (onRefreshSummary) onRefreshSummary();
    } catch (err) {
      console.error('Failed to reopen issue:', err);
      setError(getErrorMessage(err, 'Failed to reopen scene issue.'));
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
    <div className="flex-col gap-md">
      {/* Header & Filter Controls */}
      <SceneIssuesFilters
        totalItems={data.total_items}
        statusFilter={statusFilter}
        onStatusChange={st => {
          setStatusFilter(st);
          setPage(1);
        }}
        statusCounts={statusCounts}
        scopeCounts={data.scope_counts}
        kindFilter={kindFilter}
        onKindChange={k => {
          setKindFilter(k);
          setPage(1);
        }}
        sceneTypeFilter={sceneTypeFilter}
        onSceneTypeChange={t => {
          setSceneTypeFilter(t);
          setPage(1);
        }}
        reasonFilter={reasonFilter}
        onReasonChange={r => {
          setReasonFilter(r);
          setPage(1);
        }}
        onOpenManualSplit={() => setIsManualSplitOpen(true)}
      />

      {/* Informational Guide */}
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
          <div className="flex-row items-center gap-xs">
            <Info size={16} className="text-accent" />
            <strong className="text-secondary text-md">
              How &quot;Scene Issues&quot; Work
            </strong>
          </div>
          <div className="flex-row items-center gap-xs text-muted text-sm">
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
              <code style={{ color: 'var(--accent-secondary)' }}>[END]</code> tags aren&apos;t clear, it makes a decision and leaves it here for human review.
            </div>
            <div className="flex-col gap-xs mt-xs">
              <div className="flex-row items-baseline gap-xs">
                <span className="badge badge-warning text-sm" style={{ fontSize: '0.7rem', padding: '0.1rem 0.4rem', flexShrink: 0 }}>
                  AUTO SPLIT
                </span>
                <span className="text-muted text-sm">
                  Socrates registered this as the start of a new scene. If this is a mistake, you can merge the two scenes.
                </span>
              </div>
              <div className="flex-row items-baseline gap-xs">
                <span className="badge badge-accent text-sm" style={{ fontSize: '0.7rem', padding: '0.1rem 0.4rem', flexShrink: 0 }}>
                  SOFT BOUNDARY
                </span>
                <span className="text-muted text-sm">
                  Socrates doubted, but didn&apos;t start a new scene. If this is a mistake, you can register this as a new scene.
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Issues List */}
      {loading ? (
        <div className="glass-panel text-center p-xl">
          <Loader2 size={32} className="animate-spin text-accent" style={{ margin: '0 auto 1rem auto' }} />
          <p className="text-secondary">Loading scene issues...</p>
        </div>
      ) : error ? (
        <div className="banner-danger">
          <span className="text-md">{error}</span>
        </div>
      ) : data.issues.length === 0 ? (
        <div className="glass-panel text-center p-xl">
          <CheckCircle size={36} className="text-success mb-xs" style={{ margin: '0 auto' }} />
          <h3 className="text-primary mt-xs mb-xs">
            No scene issues found
          </h3>
          <p className="text-secondary text-md">
            {statusFilter === 'unresolved'
              ? 'All scene issues for this backup have been resolved!'
              : 'No scene issues match your selected filters.'}
          </p>
        </div>
      ) : (
        <div className="flex-col gap-sm">
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

      {/* Pagination */}
      <Pagination
        currentPage={data.current_page}
        totalPages={data.total_pages}
        totalItems={data.total_items}
        onPageChange={setPage}
      />

      {/* Resolve Issue Modal */}
      {resolvingIssue && (
        <ResolveIssueModal
          backupId={backupId}
          issue={resolvingIssue}
          onClose={() => setResolvingIssue(null)}
          onResolved={() => {
            fetchIssues();
            if (onRefreshSummary) onRefreshSummary();
          }}
        />
      )}

      {/* Opposite Action Confirmation Modal */}
      {oppositeAction && (
        <ActionConfirmationModal
          backupId={backupId}
          issue={oppositeAction.issue}
          action={oppositeAction.action}
          onClose={handleCloseOppositeAction}
          onResolved={() => {
            fetchIssues();
            if (onRefreshSummary) onRefreshSummary();
          }}
        />
      )}

      {/* Manual Split Modal */}
      {isManualSplitOpen && (
        <ManualSplitModal
          backupId={backupId}
          onClose={() => setIsManualSplitOpen(false)}
          onSuccess={() => {
            fetchIssues();
            if (onRefreshSummary) onRefreshSummary();
          }}
        />
      )}
    </div>
  );
};

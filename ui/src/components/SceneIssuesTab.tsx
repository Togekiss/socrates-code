import { useState, useEffect, useCallback, useRef } from 'react';
import {
  CheckCircle,
  Loader2,
  Plus,
} from 'lucide-react';
import { api, getErrorMessage } from '../api';
import { ResolveIssueModal } from './curation/ResolveIssueModal';
import { ActionConfirmationModal } from './curation/ActionConfirmationModal';
import { ManualSplitModal } from './curation/ManualSplitModal';
import { SceneIssueCard } from './curation/SceneIssueCard';
import { SceneIssuesFilters } from './curation/SceneIssuesFilters';
import { BackupStatusGuard } from './layout/BackupStatusGuard';
import { ListPageLayout } from './layout/ListPageLayout';
import { useBackupStatusGuard } from '../hooks/useBackupStatusGuard';
import { Button, Pagination } from './ui';
import type { BackupInfo, SceneIssue, SceneIssuesResponse } from '../types';
import { getRoleLevel, ROLE_LEVELS } from '../utils/rbac';

interface SceneIssuesTabProps {
  backupId: string;
  backupStatus?: string;
  backupInfo?: BackupInfo | null;
  backupError?: string | null;
  backupLoading?: boolean;
  roleLevel?: number;
  onRefreshSummary?: () => void;
}

export const SceneIssuesTab = ({
  backupId,
  backupStatus,
  backupInfo,
  backupError,
  backupLoading,
  roleLevel: propRoleLevel,
  onRefreshSummary,
}: SceneIssuesTabProps) => {
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
  const scrollRef = useRef<HTMLDivElement>(null);

  const statusGuard = useBackupStatusGuard({
    backupId,
    backupStatus,
    backupInfo,
    backupError,
    backupLoading,
  });

  const handlePageChange = (nextPage: number) => {
    setPage(nextPage);
    scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
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

  const effectiveRoleLevel = propRoleLevel ?? backupInfo?.role_level ?? getRoleLevel(backupInfo?.effective_role);
  const canCurate = effectiveRoleLevel >= ROLE_LEVELS.curator;

  const fetchIssues = useCallback(() => {
    if (!backupId || !statusGuard.isReady || !canCurate) return;
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
  }, [backupId, statusGuard.isReady, canCurate, statusFilter, kindFilter, sceneTypeFilter, reasonFilter, page]);

  useEffect(() => {
    if (statusGuard.isReady && canCurate) {
      fetchIssues();
    }
  }, [statusGuard.isReady, canCurate, fetchIssues]);

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

  if (!canCurate) {
    return (
      <div className="banner-danger" role="alert">
        Access Denied: Curation tools require Curator or Administrator permissions.
      </div>
    );
  }

  if (!statusGuard.isReady) {
    return <BackupStatusGuard title="Scene Issues" guard={statusGuard} />;
  }

  const filtersActive = Boolean(
    statusFilter !== 'all' ||
      sceneTypeFilter ||
      kindFilter ||
      reasonFilter
  );

  return (
    <ListPageLayout
      title="Scene Issues"
      descriptionKey="descSceneIssues"
      guideKey="sceneIssues"
      headerAction={
        <Button
          variant="secondary"
          size="md"
          disabled={!statusGuard.canMutate}
          onClick={() => setIsManualSplitOpen(true)}
          icon={<Plus size={14} />}
          title={!statusGuard.canMutate ? 'Curation edits are disabled while sync is in progress.' : 'Create manual scene split'}
        >
          Manual Split
        </Button>
      }
      banners={<BackupStatusGuard title="Scene Issues" guard={statusGuard} />}
      filterBar={
        <SceneIssuesFilters
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
        />
      }
      countText={
        !error ? (
          <span>
            Showing{' '}
            <strong>
              {data.total_items > data.issues.length
                ? `${data.issues.length} of ${data.total_items}`
                : data.total_items}
            </strong>{' '}
            scene {data.total_items === 1 ? 'issue' : 'issues'}
            {filtersActive && ' (filtered)'}
          </span>
        ) : undefined
      }
      scrollRef={scrollRef}
      modals={
        <>
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
        </>
      }
    >
      {/* Issues List */}
      {loading ? (
        <div className="glass-panel text-center p-xl">
          <Loader2
            size={32}
            className="animate-spin text-accent"
            style={{ margin: '0 auto 1rem auto' }}
          />
          <p className="text-secondary">Loading scene issues...</p>
        </div>
      ) : error ? (
        <div className="banner-danger">
          <span className="text-md">{error}</span>
        </div>
      ) : data.issues.length === 0 ? (
        <div className="glass-panel text-center p-xl">
          <CheckCircle size={36} className="text-success mb-xs" style={{ margin: '0 auto' }} />
          <h3 className="text-primary mt-xs mb-xs">No scene issues found</h3>
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
              mutationDisabled={!statusGuard.canMutate}
              onResolve={item => { if (statusGuard.canMutate) setResolvingIssue(item); }}
              onReopen={id => { if (statusGuard.canMutate) handleReopen(id); }}
              onOppositeAction={(action, targetIssue) => {
                if (statusGuard.canMutate) handleOpenOppositeAction(action, targetIssue);
              }}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {!loading && !error && data.total_pages > 1 && (
        <Pagination
          currentPage={data.current_page}
          totalPages={data.total_pages}
          totalItems={data.total_items}
          onPageChange={handlePageChange}
        />
      )}
    </ListPageLayout>
  );
};

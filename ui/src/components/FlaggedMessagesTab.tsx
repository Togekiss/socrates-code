import { useState, useEffect, useCallback, useRef } from 'react';
import { CheckCircle, Loader2, Plus } from 'lucide-react';
import { api, getErrorMessage } from '../api';
import { PromoteMessageModal } from './curation/PromoteMessageModal';
import { AddFlaggedMessageModal } from './curation/AddFlaggedMessageModal';
import { FlaggedMessageCard } from './curation/FlaggedMessageCard';
import { FlaggedMessagesFilters } from './curation/FlaggedMessagesFilters';
import { BackupStatusGuard } from './layout/BackupStatusGuard';
import { ListPageLayout } from './layout/ListPageLayout';
import { useBackupStatusGuard } from '../hooks/useBackupStatusGuard';
import { Button, Pagination } from './ui';
import type { BackupInfo, Character, FlaggedMessage, FlaggedMessagesResponse, FlaggedResolution } from '../types';
import { getRoleLevel, ROLE_LEVELS } from '../utils/rbac';

interface FlaggedMessagesTabProps {
  backupId: string;
  backupStatus?: string;
  backupInfo?: BackupInfo | null;
  backupError?: string | null;
  backupLoading?: boolean;
  roleLevel?: number;
  onRefreshSummary?: () => void;
}

export const FlaggedMessagesTab = ({
  backupId,
  backupStatus,
  backupInfo,
  backupError,
  backupLoading,
  roleLevel: propRoleLevel,
  onRefreshSummary,
}: FlaggedMessagesTabProps) => {
  const [data, setData] = useState<FlaggedMessagesResponse>({
    total_items: 0,
    messages: [],
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
  const [sceneTypeFilter, setSceneTypeFilter] = useState<string>('');
  const [kindFilter, setKindFilter] = useState<string>('');
  const [resolutionFilter, setResolutionFilter] = useState<string>('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [promotingMsg, setPromotingMsg] = useState<FlaggedMessage | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [reopeningId, setReopeningId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const handlePageChange = (nextPage: number) => {
    setPage(nextPage);
    scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const statusGuard = useBackupStatusGuard({
    backupId,
    backupStatus,
    backupInfo,
    backupError,
    backupLoading,
  });

  useEffect(() => {
    setPage(1);
    setCharacters([]);
    setData({
      total_items: 0,
      messages: [],
      current_page: 1,
      per_page: 50,
      total_pages: 1,
    });
    setStatusCounts({ unresolved: 0, resolved: 0, all: 0 });
    setError(null);
  }, [backupId]);

  const effectiveRoleLevel = propRoleLevel ?? backupInfo?.role_level ?? getRoleLevel(backupInfo?.effective_role);
  const canCurate = effectiveRoleLevel >= ROLE_LEVELS.curator;

  const fetchMessages = useCallback(() => {
    if (!backupId || !statusGuard.isReady || !canCurate) return;
    setLoading(true);
    setError(null);

    const params = new URLSearchParams();
    params.append('page', page.toString());
    params.append('per_page', '50');
    if (statusFilter !== 'all') params.append('status', statusFilter);
    if (sceneTypeFilter) params.append('scene_type', sceneTypeFilter);
    if (kindFilter) params.append('kind', kindFilter);
    if (resolutionFilter && statusFilter !== 'unresolved') params.append('resolution', resolutionFilter);

    api
      .getFlaggedMessages(backupId, params)
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
          messages: [],
          current_page: 1,
          per_page: 50,
          total_pages: 1,
        });
        setError(getErrorMessage(err, 'Failed to load flagged messages.'));
      })
      .finally(() => {
        setLoading(false);
      });
  }, [backupId, statusGuard.isReady, canCurate, statusFilter, sceneTypeFilter, kindFilter, resolutionFilter, page]);

  useEffect(() => {
    if (statusGuard.isReady && canCurate) {
      fetchMessages();
    }
  }, [statusGuard.isReady, canCurate, fetchMessages]);

  useEffect(() => {
    if (!backupId || !statusGuard.isReady || !canCurate) return;
    let cancelled = false;
    api
      .getCharacters(backupId)
      .then(res => {
        if (!cancelled && Array.isArray(res)) setCharacters(res);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [backupId, statusGuard.isReady, canCurate]);

  const handleResolve = async (msg: FlaggedMessage, resolution: FlaggedResolution) => {
    setResolvingId(msg.message_id);
    try {
      await api.resolveFlaggedMessage(backupId, msg.message_id, { resolution });
      fetchMessages();
      if (onRefreshSummary) onRefreshSummary();
    } catch (err) {
      console.error(`Failed to resolve message as ${resolution}:`, err);
      setError(getErrorMessage(err, `Failed to resolve message as ${resolution}.`));
    } finally {
      setResolvingId(null);
    }
  };

  const handleReopen = async (messageId: string) => {
    setReopeningId(messageId);
    try {
      await api.reopenFlaggedMessage(backupId, messageId);
      fetchMessages();
      if (onRefreshSummary) onRefreshSummary();
    } catch (err) {
      console.error('Failed to reopen flagged message:', err);
      setError(getErrorMessage(err, 'Failed to reopen flagged message.'));
    } finally {
      setReopeningId(null);
    }
  };

  if (!canCurate) {
    return (
      <div className="banner-danger" role="alert">
        Access Denied: Curation tools require Curator or Administrator permissions.
      </div>
    );
  }

  if (!statusGuard.isReady) {
    return <BackupStatusGuard title="Flagged Messages" guard={statusGuard} />;
  }

  const filtersActive = Boolean(
    statusFilter !== 'all' ||
      sceneTypeFilter ||
      kindFilter ||
      resolutionFilter
  );

  return (
    <ListPageLayout
      title="Flagged Messages"
      descriptionKey="descFlaggedMessages"
      guideKey="flaggedMessages"
      headerAction={
        <Button
          variant="secondary"
          size="md"
          disabled={!statusGuard.canMutate}
          onClick={() => setIsAddModalOpen(true)}
          icon={<Plus size={14} />}
          title={!statusGuard.canMutate ? 'Curation edits are disabled while sync is in progress.' : 'Add flagged message manually'}
        >
          Add Message
        </Button>
      }
      banners={<BackupStatusGuard title="Flagged Messages" guard={statusGuard} />}
      filterBar={
        <FlaggedMessagesFilters
          statusFilter={statusFilter}
          onStatusChange={st => {
            setStatusFilter(st);
            setPage(1);
          }}
          statusCounts={statusCounts}
          scopeCounts={data.scope_counts}
          sceneTypeFilter={sceneTypeFilter}
          onSceneTypeChange={t => {
            setSceneTypeFilter(t);
            setPage(1);
          }}
          kindFilter={kindFilter}
          onKindChange={k => {
            setKindFilter(k);
            setPage(1);
          }}
          resolutionFilter={resolutionFilter}
          onResolutionChange={r => {
            setResolutionFilter(r);
            setPage(1);
          }}
        />
      }
      countText={
        !error ? (
          <span>
            Showing{' '}
            <strong>
              {data.total_items > data.messages.length
                ? `${data.messages.length} of ${data.total_items}`
                : data.total_items}
            </strong>{' '}
            flagged {data.total_items === 1 ? 'message' : 'messages'}
            {filtersActive && ' (filtered)'}
          </span>
        ) : undefined
      }
      scrollRef={scrollRef}
      modals={
        <>
          {promotingMsg && (
            <PromoteMessageModal
              backupId={backupId}
              message={promotingMsg}
              allCharacters={characters.length > 0 ? characters : undefined}
              onClose={() => setPromotingMsg(null)}
              onPromoted={() => {
                fetchMessages();
                if (onRefreshSummary) onRefreshSummary();
              }}
            />
          )}

          {isAddModalOpen && (
            <AddFlaggedMessageModal
              backupId={backupId}
              onClose={() => setIsAddModalOpen(false)}
              onSuccess={newMsg => {
                fetchMessages();
                if (onRefreshSummary) onRefreshSummary();
                setPromotingMsg(newMsg);
              }}
            />
          )}
        </>
      }
    >
      {/* Main Content Area */}
      {loading ? (
        <div className="glass-panel text-center p-xl">
          <Loader2
            size={32}
            className="animate-spin text-accent"
            style={{ margin: '0 auto 1rem auto' }}
          />
          <p className="text-secondary">Loading flagged messages...</p>
        </div>
      ) : error ? (
        <div className="banner-danger">
          <span className="text-md">{error}</span>
        </div>
      ) : data.messages.length === 0 ? (
        <div className="glass-panel text-center p-xl">
          <CheckCircle size={36} className="text-success mb-xs" style={{ margin: '0 auto' }} />
          <h3 className="text-primary mt-xs mb-xs">No flagged messages found</h3>
          <p className="text-secondary text-md">
            {statusFilter === 'unresolved'
              ? 'All flagged messages in this backup have been resolved or dismissed.'
              : 'No messages match the current status and filter criteria.'}
          </p>
        </div>
      ) : (
        <div className="flex-col gap-sm">
          {data.messages.map(msg => (
            <FlaggedMessageCard
              key={msg.id}
              message={msg}
              isResolving={resolvingId === msg.message_id}
              isReopening={reopeningId === msg.message_id}
              mutationDisabled={!statusGuard.canMutate}
              onPromote={m => { if (statusGuard.canMutate) setPromotingMsg(m); }}
              onResolve={(m, res) => { if (statusGuard.canMutate) handleResolve(m, res); }}
              onReopen={id => { if (statusGuard.canMutate) handleReopen(id); }}
            />
          ))}
        </div>
      )}

      {/* Pagination Controls */}
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

import { useState, useEffect, useCallback } from 'react';
import { CheckCircle, Loader2 } from 'lucide-react';
import { api, getErrorMessage } from '../api';
import { PromoteMessageModal } from './curation/PromoteMessageModal';
import { AddFlaggedMessageModal } from './curation/AddFlaggedMessageModal';
import { FlaggedMessageCard } from './curation/FlaggedMessageCard';
import { FlaggedMessagesFilters } from './curation/FlaggedMessagesFilters';
import { Pagination } from './ui';
import type { FlaggedMessage, FlaggedMessagesResponse, FlaggedResolution } from '../types';

interface FlaggedMessagesTabProps {
  backupId: string;
  onRefreshSummary?: () => void;
}

export const FlaggedMessagesTab = ({ backupId, onRefreshSummary }: FlaggedMessagesTabProps) => {
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
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [reopeningId, setReopeningId] = useState<string | null>(null);

  useEffect(() => {
    setPage(1);
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

  const fetchMessages = useCallback(() => {
    if (!backupId) return;
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
  }, [backupId, statusFilter, sceneTypeFilter, kindFilter, resolutionFilter, page]);

  useEffect(() => {
    fetchMessages();
  }, [fetchMessages]);

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

  return (
    <div className="flex-col gap-md">
      {/* Header & Filter Controls */}
      <FlaggedMessagesFilters
        totalItems={data.total_items}
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
        onOpenAddModal={() => setIsAddModalOpen(true)}
      />

      {/* Main Content Area */}
      {loading ? (
        <div className="glass-panel text-center p-xl">
          <Loader2 size={32} className="animate-spin text-accent" style={{ margin: '0 auto 1rem auto' }} />
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
              onPromote={m => setPromotingMsg(m)}
              onResolve={handleResolve}
              onReopen={handleReopen}
            />
          ))}

          {/* Pagination Controls */}
          <Pagination
            currentPage={data.current_page}
            totalPages={data.total_pages}
            totalItems={data.total_items}
            onPageChange={setPage}
          />
        </div>
      )}

      {/* Modals */}
      {promotingMsg && (
        <PromoteMessageModal
          backupId={backupId}
          message={promotingMsg}
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
    </div>
  );
};

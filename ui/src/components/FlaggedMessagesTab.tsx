import { useState, useEffect, useCallback } from 'react';
import { CheckCircle, Loader2 } from 'lucide-react';
import { api } from '../api';
import { PromoteMessageModal } from './curation/PromoteMessageModal';
import { AddFlaggedMessageModal } from './curation/AddFlaggedMessageModal';
import { FlaggedMessageCard } from './curation/FlaggedMessageCard';
import { FlaggedMessagesFilters } from './curation/FlaggedMessagesFilters';
import type { FlaggedMessage, FlaggedMessagesResponse, FlaggedResolution } from '../types';

interface FlaggedMessagesTabProps {
  backupId: string;
  onRefreshSummary?: () => void;
}

const pageBtn = (disabled: boolean): React.CSSProperties => ({
  padding: '0.4rem 0.85rem',
  background: 'var(--bg-tertiary)',
  border: '1px solid var(--border-color)',
  color: 'white',
  borderRadius: '6px',
  cursor: disabled ? 'not-allowed' : 'pointer',
  opacity: disabled ? 0.45 : 1,
  fontSize: '0.85rem',
});

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
  const [kindFilter, setKindFilter] = useState<string>('');
  const [resolutionFilter, setResolutionFilter] = useState<string>('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const [promotingMsg, setPromotingMsg] = useState<FlaggedMessage | null>(null);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [reopeningId, setReopeningId] = useState<string | null>(null);

  const fetchMessages = useCallback(() => {
    if (!backupId) return;
    setLoading(true);

    const params = new URLSearchParams();
    params.append('page', page.toString());
    params.append('per_page', '50');
    if (statusFilter !== 'all') params.append('status', statusFilter);
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
      .catch(console.error)
      .finally(() => {
        setLoading(false);
        if (onRefreshSummary) onRefreshSummary();
      });
  }, [backupId, statusFilter, kindFilter, resolutionFilter, page, onRefreshSummary]);

  useEffect(() => {
    fetchMessages();
  }, [fetchMessages]);

  const handleResolve = async (msg: FlaggedMessage, resolution: FlaggedResolution) => {
    setResolvingId(msg.message_id);
    try {
      await api.resolveFlaggedMessage(backupId, msg.message_id, { resolution });
      fetchMessages();
    } catch (err) {
      console.error(`Failed to resolve message as ${resolution}:`, err);
    } finally {
      setResolvingId(null);
    }
  };

  const handleReopen = async (messageId: string) => {
    setReopeningId(messageId);
    try {
      await api.reopenFlaggedMessage(backupId, messageId);
      fetchMessages();
    } catch (err) {
      console.error('Failed to reopen flagged message:', err);
    } finally {
      setReopeningId(null);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header & Filter Controls */}
      <FlaggedMessagesFilters
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
        resolutionFilter={resolutionFilter}
        onResolutionChange={r => {
          setResolutionFilter(r);
          setPage(1);
        }}
        onOpenAddModal={() => setIsAddModalOpen(true)}
      />

      {/* Main Content Area */}
      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
          <Loader2 className="spin" size={32} />
        </div>
      ) : data.messages.length === 0 ? (
        <div
          className="glass-panel"
          style={{
            padding: '3rem 2rem',
            textAlign: 'center',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '0.75rem',
          }}
        >
          <CheckCircle size={36} color="var(--success)" />
          <h3 style={{ margin: 0, color: 'var(--text-primary)' }}>No flagged messages found</h3>
          <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.9rem', maxWidth: '420px' }}>
            {statusFilter === 'unresolved'
              ? 'All flagged messages in this backup have been resolved or dismissed.'
              : 'No messages match the current status and filter criteria.'}
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
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
          {data.total_pages > 1 && (
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '0.75rem 0',
                marginTop: '0.5rem',
              }}
            >
              <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                Showing page {data.current_page} of {data.total_pages} ({data.total_items} items)
              </span>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button
                  style={pageBtn(data.current_page <= 1)}
                  disabled={data.current_page <= 1}
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                >
                  Previous
                </button>
                <button
                  style={pageBtn(data.current_page >= data.total_pages)}
                  disabled={data.current_page >= data.total_pages}
                  onClick={() => setPage(p => Math.min(data.total_pages, p + 1))}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Modals */}
      {promotingMsg && (
        <PromoteMessageModal
          backupId={backupId}
          message={promotingMsg}
          onClose={() => setPromotingMsg(null)}
          onPromoted={fetchMessages}
        />
      )}

      {isAddModalOpen && (
        <AddFlaggedMessageModal
          backupId={backupId}
          onClose={() => setIsAddModalOpen(false)}
          onSuccess={newMsg => {
            fetchMessages();
            // Automatically open promote modal if user wants to attribute immediately
            setPromotingMsg(newMsg);
          }}
        />
      )}
    </div>
  );
};

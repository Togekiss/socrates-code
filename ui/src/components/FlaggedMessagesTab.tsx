import { useState, useEffect, useCallback } from 'react';
import {
  MessageSquareCode,
  ExternalLink,
  Check,
  CheckCircle,
  Loader2,
} from 'lucide-react';
import { api } from '../api';
import { PromoteMessageModal } from './curation/PromoteMessageModal';
import { MessageOverrideCard } from './curation/MessageOverrideCard';
import type {
  FlaggedMessage,
  FlaggedMessagesResponse,
  MessageOverridesResponse,
} from '../types';

interface FlaggedMessagesTabProps {
  backupId: string;
  onRefreshSummary?: () => void;
}

export const FlaggedMessagesTab = ({ backupId, onRefreshSummary }: FlaggedMessagesTabProps) => {
  const [subTab, setSubTab] = useState<'flagged' | 'overrides'>('flagged');
  const [flaggedData, setFlaggedData] = useState<FlaggedMessagesResponse>({
    total_items: 0,
    messages: [],
    current_page: 1,
    per_page: 50,
    total_pages: 1,
  });
  const [overridesData, setOverridesData] = useState<MessageOverridesResponse>({
    total_items: 0,
    overrides: [],
    current_page: 1,
    per_page: 50,
    total_pages: 1,
  });

  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [promotingMsg, setPromotingMsg] = useState<FlaggedMessage | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchData = useCallback(() => {
    if (!backupId) return;
    setLoading(true);

    const activeParams = new URLSearchParams();
    activeParams.append('page', page.toString());
    activeParams.append('per_page', '50');

    const countParams = new URLSearchParams();
    countParams.append('page', '1');
    countParams.append('per_page', '1');

    if (subTab === 'flagged') {
      Promise.all([
        api.getFlaggedMessages(backupId, activeParams),
        api.getMessageOverrides(backupId, countParams).catch(() => null),
      ])
        .then(([flaggedRes, overridesCountRes]) => {
          setFlaggedData(flaggedRes);
          if (overridesCountRes) {
            setOverridesData(prev => ({
              ...prev,
              total_items: overridesCountRes.total_items,
            }));
          }
        })
        .catch(console.error)
        .finally(() => {
          setLoading(false);
          if (onRefreshSummary) onRefreshSummary();
        });
    } else {
      Promise.all([
        api.getMessageOverrides(backupId, activeParams),
        api.getFlaggedMessages(backupId, countParams).catch(() => null),
      ])
        .then(([overridesRes, flaggedCountRes]) => {
          setOverridesData(overridesRes);
          if (flaggedCountRes) {
            setFlaggedData(prev => ({
              ...prev,
              total_items: flaggedCountRes.total_items,
            }));
          }
        })
        .catch(console.error)
        .finally(() => {
          setLoading(false);
          if (onRefreshSummary) onRefreshSummary();
        });
    }
  }, [backupId, subTab, page, onRefreshSummary]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleDeleteOverride = async (messageId: string) => {
    if (!window.confirm(`Delete override for message #${messageId}?`)) return;
    setDeletingId(messageId);
    try {
      await api.deleteMessageOverride(backupId, messageId);
      fetchData();
    } catch (err) {
      console.error('Failed to delete override:', err);
    } finally {
      setDeletingId(null);
    }
  };

  const activeTotalPages = subTab === 'flagged' ? flaggedData.total_pages : overridesData.total_pages;
  const activeTotalItems = subTab === 'flagged' ? flaggedData.total_items : overridesData.total_items;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header & Sub-Navigation */}
      <div
        className="glass-panel"
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
              background: 'rgba(139, 92, 246, 0.15)',
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
              Flagged Messages & Overrides
            </h2>
            <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-muted)' }}>
              Non-tupper dialogue promoting and manual override management
            </p>
          </div>
        </div>

        {/* Sub-Tabs */}
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            onClick={() => {
              setSubTab('flagged');
              setPage(1);
            }}
            style={{
              padding: '0.45rem 1rem',
              borderRadius: '6px',
              border: subTab === 'flagged' ? '1px solid var(--accent-secondary)' : '1px solid var(--border-color)',
              background: subTab === 'flagged' ? 'rgba(109, 40, 217, 0.25)' : 'var(--bg-tertiary)',
              color: subTab === 'flagged' ? '#fff' : 'var(--text-secondary)',
              fontWeight: subTab === 'flagged' ? 600 : 400,
              cursor: 'pointer',
              fontSize: '0.85rem',
            }}
          >
            Flagged Queue ({flaggedData.total_items})
          </button>
          <button
            onClick={() => {
              setSubTab('overrides');
              setPage(1);
            }}
            style={{
              padding: '0.45rem 1rem',
              borderRadius: '6px',
              border: subTab === 'overrides' ? '1px solid var(--accent-secondary)' : '1px solid var(--border-color)',
              background: subTab === 'overrides' ? 'rgba(109, 40, 217, 0.25)' : 'var(--bg-tertiary)',
              color: subTab === 'overrides' ? '#fff' : 'var(--text-secondary)',
              fontWeight: subTab === 'overrides' ? 600 : 400,
              cursor: 'pointer',
              fontSize: '0.85rem',
            }}
          >
            Active Overrides ({overridesData.total_items})
          </button>
        </div>
      </div>

      {/* Body List */}
      {loading ? (
        <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
          <Loader2 size={32} className="animate-spin" style={{ color: 'var(--accent-secondary)', margin: '0 auto 1rem auto' }} />
          <p style={{ color: 'var(--text-secondary)' }}>Loading messages...</p>
        </div>
      ) : subTab === 'flagged' ? (
        flaggedData.messages.length === 0 ? (
          <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
            <CheckCircle size={36} style={{ color: 'var(--success)', marginBottom: '0.5rem' }} />
            <h3 style={{ margin: '0 0 0.5rem 0', color: 'var(--text-primary)' }}>
              No flagged messages
            </h3>
            <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
              The flagged non-tupper dialogue review queue is clear!
            </p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {flaggedData.messages.map(msg => (
              <div
                key={msg.id}
                className="glass-panel"
                style={{
                  padding: '1.25rem',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.75rem',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.5rem' }}>
                  <div>
                    <strong style={{ fontSize: '1rem', color: 'var(--text-primary)' }}>
                      {msg.author?.name || msg.author?.nickname || 'Unknown Author'}
                    </strong>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                      Channel: #{msg.channel_name} • Kind: <code>{msg.kind}</code> •{' '}
                      {msg.flagged_at ? new Date(msg.flagged_at).toLocaleString() : ''}
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    {msg.discord_link && (
                      <a
                        href={msg.discord_link}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '0.3rem',
                          padding: '0.35rem 0.75rem',
                          fontSize: '0.8rem',
                          background: 'var(--bg-tertiary)',
                          border: '1px solid var(--border-color)',
                          color: 'var(--text-primary)',
                          borderRadius: '6px',
                          textDecoration: 'none',
                        }}
                      >
                        <ExternalLink size={12} /> View in Discord
                      </a>
                    )}

                    <button
                      onClick={() => setPromotingMsg(msg)}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.3rem',
                        padding: '0.35rem 0.85rem',
                        fontSize: '0.8rem',
                        background: 'var(--accent-primary)',
                        color: '#fff',
                        border: 'none',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        fontWeight: 600,
                      }}
                    >
                      <Check size={14} /> Promote to Override
                    </button>
                  </div>
                </div>

                <div
                  style={{
                    background: 'var(--bg-tertiary)',
                    padding: '0.85rem 1rem',
                    borderRadius: '6px',
                    fontSize: '0.9rem',
                    color: 'var(--text-primary)',
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.5,
                    border: '1px solid var(--border-color)',
                  }}
                >
                  {msg.content}
                </div>
              </div>
            ))}
          </div>
        )
      ) : (
        /* Overrides List */
        overridesData.overrides.length === 0 ? (
          <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
            <MessageSquareCode size={36} style={{ color: 'var(--text-muted)', marginBottom: '0.5rem', opacity: 0.5 }} />
            <h3 style={{ margin: '0 0 0.5rem 0', color: 'var(--text-primary)' }}>
              No active message overrides
            </h3>
            <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
              Promoting a message from the flagged queue registers it here.
            </p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {overridesData.overrides.map(ov => (
              <MessageOverrideCard
                key={ov.id}
                override={ov}
                isDeleting={deletingId === ov.message_id}
                onDelete={handleDeleteOverride}
              />
            ))}
          </div>
        )
      )}

      {/* Pagination Controls */}
      {activeTotalPages > 1 && (
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
            Page {page} of {activeTotalPages} ({activeTotalItems} items)
          </span>
          <button
            disabled={page >= activeTotalPages}
            onClick={() => setPage(p => p + 1)}
            style={{
              padding: '0.4rem 0.85rem',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-color)',
              color: 'white',
              borderRadius: '6px',
              cursor: page >= activeTotalPages ? 'not-allowed' : 'pointer',
              opacity: page >= activeTotalPages ? 0.45 : 1,
              fontSize: '0.85rem',
            }}
          >
            Next
          </button>
        </div>
      )}

      {/* Promote Modal */}
      {promotingMsg && (
        <PromoteMessageModal
          backupId={backupId}
          message={promotingMsg}
          onClose={() => setPromotingMsg(null)}
          onPromoted={fetchData}
        />
      )}
    </div>
  );
};

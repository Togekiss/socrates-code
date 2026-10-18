import { useState, useEffect, useCallback } from 'react';
import {
  AlertTriangle,
  CheckCircle,
  Loader2,
} from 'lucide-react';
import { api } from '../api';
import { ResolveIssueModal } from './curation/ResolveIssueModal';
import { SceneIssueCard } from './curation/SceneIssueCard';
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
  const [statusFilter, setStatusFilter] = useState<'unresolved' | 'resolved' | 'all'>('unresolved');
  const [kindFilter, setKindFilter] = useState<string>('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [resolvingIssue, setResolvingIssue] = useState<SceneIssue | null>(null);
  const [reopeningId, setReopeningId] = useState<number | null>(null);

  const fetchIssues = useCallback(() => {
    if (!backupId) return;
    setLoading(true);

    const params = new URLSearchParams();
    params.append('page', page.toString());
    params.append('per_page', '50');
    if (statusFilter !== 'all') params.append('status', statusFilter);
    if (kindFilter) params.append('kind', kindFilter);

    api
      .getSceneIssues(backupId, params)
      .then(res => {
        setData(res);
      })
      .catch(console.error)
      .finally(() => {
        setLoading(false);
        if (onRefreshSummary) onRefreshSummary();
      });
  }, [backupId, statusFilter, kindFilter, page, onRefreshSummary]);

  useEffect(() => {
    fetchIssues();
  }, [fetchIssues]);

  const handleReopen = async (issueId: number) => {
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header & Filter Controls */}
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
              Anomalous scenes flagged during pipeline indexing ({data.total_items} total)
            </p>
          </div>
        </div>

        {/* Filter Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          {/* Status Buttons */}
          <div style={{ display: 'flex', gap: '0.35rem' }}>
            {(['unresolved', 'resolved', 'all'] as const).map(st => (
              <button
                key={st}
                onClick={() => {
                  setStatusFilter(st);
                  setPage(1);
                }}
                style={{
                  padding: '0.35rem 0.8rem',
                  borderRadius: '6px',
                  fontSize: '0.85rem',
                  textTransform: 'capitalize',
                  border: statusFilter === st ? '1px solid var(--accent-secondary)' : '1px solid var(--border-color)',
                  background: statusFilter === st ? 'rgba(109, 40, 217, 0.25)' : 'var(--bg-tertiary)',
                  color: statusFilter === st ? '#fff' : 'var(--text-secondary)',
                  fontWeight: statusFilter === st ? 600 : 400,
                  cursor: 'pointer',
                }}
              >
                {st}
              </button>
            ))}
          </div>

          {/* Kind Select */}
          <select
            value={kindFilter}
            onChange={e => {
              setKindFilter(e.target.value);
              setPage(1);
            }}
            style={{
              padding: '0.4rem 0.75rem',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-color)',
              borderRadius: '6px',
              color: 'white',
              fontSize: '0.85rem',
            }}
          >
            <option value="">All Issue Kinds</option>
            <option value="non_tupper_author">Non-Tupper Author</option>
            <option value="gap">Gap</option>
            <option value="consecutive">Consecutive</option>
            <option value="early_end_merged">Early End Merged</option>
            <option value="late_start_merged">Late Start Merged</option>
            <option value="overlap">Overlap</option>
          </select>
        </div>
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
    </div>
  );
};

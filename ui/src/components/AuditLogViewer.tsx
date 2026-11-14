import { Fragment, useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, RefreshCw, ScrollText } from 'lucide-react';
import { getErrorMessage, type ApiError } from '../api';
import type { AuditLogEntry, AuditLogsResponse } from '../types';
import { Button, PanelSurface } from './ui';

interface AuditLogViewerProps {
  title: string;
  description?: string;
  fetchLogs: (params: URLSearchParams) => Promise<AuditLogsResponse>;
  showBackupColumn?: boolean;
  refreshKey?: string | number;
}

interface FilterState {
  action: string;
  status: string;
  actor_user_id: string;
  target_type: string;
  from_ts: string;
  to_ts: string;
}

const EMPTY_FILTERS: FilterState = {
  action: '',
  status: '',
  actor_user_id: '',
  target_type: '',
  from_ts: '',
  to_ts: '',
};

const formatUtcTimestamp = (raw?: string): string => {
  if (!raw) return '—';
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return `${parsed.toISOString().replace('T', ' ').slice(0, 19)} UTC`;
};

const statusBadgeStyle = (status?: string) => {
  const s = (status || '').toLowerCase();
  if (s === 'denied') {
    return {
      color: 'var(--danger-color, #ef4444)',
      borderColor: 'rgba(239, 68, 68, 0.35)',
      background: 'rgba(239, 68, 68, 0.1)',
    };
  }
  if (s === 'error' || s === 'failed') {
    return {
      color: '#f59e0b',
      borderColor: 'rgba(245, 158, 11, 0.35)',
      background: 'rgba(245, 158, 11, 0.1)',
    };
  }
  return {
    color: '#22c55e',
    borderColor: 'rgba(34, 197, 94, 0.35)',
    background: 'rgba(34, 197, 94, 0.1)',
  };
};

export const AuditLogViewer = ({
  title,
  description,
  fetchLogs,
  showBackupColumn = false,
  refreshKey,
}: AuditLogViewerProps) => {
  const [items, setItems] = useState<AuditLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [perPage] = useState(25);

  const [draftFilters, setDraftFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<FilterState>(EMPTY_FILTERS);

  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const params = new URLSearchParams();
      params.set('page', String(page));
      params.set('per_page', String(perPage));
      if (appliedFilters.action.trim()) params.set('action', appliedFilters.action.trim());
      if (appliedFilters.status) params.set('status', appliedFilters.status);
      if (appliedFilters.actor_user_id.trim()) params.set('actor_user_id', appliedFilters.actor_user_id.trim());
      if (appliedFilters.target_type.trim()) params.set('target_type', appliedFilters.target_type.trim());
      if (appliedFilters.from_ts.trim()) params.set('from_ts', appliedFilters.from_ts.trim());
      if (appliedFilters.to_ts.trim()) params.set('to_ts', appliedFilters.to_ts.trim());

      const res = await fetchLogs(params);
      setItems(Array.isArray(res.items) ? res.items : []);
      setTotal(typeof res.total === 'number' ? res.total : 0);
      setTotalPages(typeof res.total_pages === 'number' && res.total_pages >= 1 ? res.total_pages : 1);
    } catch (err) {
      const apiErr = err as ApiError;
      if (apiErr.status === 404 || apiErr.status === 501) {
        setItems([]);
        setErrorMsg('Audit log viewer is not enabled on this server yet.');
      } else {
        setItems([]);
        setErrorMsg(getErrorMessage(err, 'Failed to load audit logs.'));
      }
    } finally {
      setLoading(false);
    }
  }, [fetchLogs, page, perPage, appliedFilters]);

  useEffect(() => {
    setPage(1);
  }, [refreshKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const applyFilters = () => {
    setPage(1);
    setAppliedFilters({ ...draftFilters });
  };

  const resetFilters = () => {
    setDraftFilters(EMPTY_FILTERS);
    setAppliedFilters(EMPTY_FILTERS);
    setPage(1);
  };

  const colCount = showBackupColumn ? 7 : 6;

  return (
    <PanelSurface className="flex-col gap-md">
      <div className="flex-row items-center justify-between gap-md flex-wrap">
        <div className="flex-row items-center gap-sm">
          <ScrollText size={18} style={{ color: 'var(--text-secondary)' }} />
          <div>
            <h3 style={{ margin: 0, fontSize: '1.05rem', color: 'var(--text-primary)' }}>{title}</h3>
            {description && (
              <p className="text-sm text-muted" style={{ margin: 0 }}>
                {description}
              </p>
            )}
          </div>
        </div>
        <Button type="button" variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
        </Button>
      </div>

      {/* Filters */}
      <div className="flex-row gap-xs flex-wrap items-center">
        <input
          type="text"
          value={draftFilters.action}
          onChange={e => setDraftFilters(prev => ({ ...prev, action: e.target.value }))}
          onKeyDown={e => e.key === 'Enter' && applyFilters()}
          placeholder="Action (e.g. writer.update)"
          style={{ minWidth: '170px', fontSize: '0.8rem', padding: '0.35rem 0.5rem' }}
        />
        <select
          value={draftFilters.status}
          onChange={e => setDraftFilters(prev => ({ ...prev, status: e.target.value }))}
          style={{ fontSize: '0.8rem', padding: '0.35rem 0.5rem' }}
        >
          <option value="">All statuses</option>
          <option value="success">success</option>
          <option value="denied">denied</option>
          <option value="error">error</option>
        </select>
        <input
          type="text"
          value={draftFilters.actor_user_id}
          onChange={e => setDraftFilters(prev => ({ ...prev, actor_user_id: e.target.value }))}
          onKeyDown={e => e.key === 'Enter' && applyFilters()}
          placeholder="Actor ID"
          style={{ width: '140px', fontSize: '0.8rem', padding: '0.35rem 0.5rem' }}
        />
        <input
          type="text"
          value={draftFilters.target_type}
          onChange={e => setDraftFilters(prev => ({ ...prev, target_type: e.target.value }))}
          onKeyDown={e => e.key === 'Enter' && applyFilters()}
          placeholder="Target type"
          style={{ width: '125px', fontSize: '0.8rem', padding: '0.35rem 0.5rem' }}
        />
        <input
          type="text"
          value={draftFilters.from_ts}
          onChange={e => setDraftFilters(prev => ({ ...prev, from_ts: e.target.value }))}
          onKeyDown={e => e.key === 'Enter' && applyFilters()}
          placeholder="From UTC ISO"
          style={{ width: '155px', fontSize: '0.8rem', padding: '0.35rem 0.5rem' }}
        />
        <input
          type="text"
          value={draftFilters.to_ts}
          onChange={e => setDraftFilters(prev => ({ ...prev, to_ts: e.target.value }))}
          onKeyDown={e => e.key === 'Enter' && applyFilters()}
          placeholder="To UTC ISO"
          style={{ width: '155px', fontSize: '0.8rem', padding: '0.35rem 0.5rem' }}
        />
        <Button type="button" variant="secondary" size="sm" onClick={applyFilters}>
          Filter
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={resetFilters}>
          Reset
        </Button>
      </div>

      {errorMsg ? (
        <div
          className="text-sm text-muted"
          style={{
            padding: '0.75rem 1rem',
            borderRadius: '6px',
            border: '1px dashed var(--border-color)',
            background: 'var(--bg-secondary)',
          }}
        >
          {errorMsg}
        </div>
      ) : items.length === 0 ? (
        <div
          className="text-sm text-muted"
          style={{
            padding: '0.75rem 1rem',
            borderRadius: '6px',
            border: '1px dashed var(--border-color)',
          }}
        >
          {loading ? 'Loading audit log entries...' : 'No audit log entries match the current filters.'}
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-color)', textAlign: 'left' }}>
                <th style={{ padding: '0.45rem 0.5rem', width: '28px' }}></th>
                <th style={{ padding: '0.45rem 0.5rem' }}>Time (UTC)</th>
                <th style={{ padding: '0.45rem 0.5rem' }}>Actor</th>
                <th style={{ padding: '0.45rem 0.5rem' }}>Action</th>
                <th style={{ padding: '0.45rem 0.5rem' }}>Status</th>
                {showBackupColumn && <th style={{ padding: '0.45rem 0.5rem' }}>Backup</th>}
                <th style={{ padding: '0.45rem 0.5rem' }}>Target</th>
              </tr>
            </thead>
            <tbody>
              {items.map(entry => {
                const isExpanded = expandedId === entry.id;
                const actorLabel = entry.actor_username || entry.actor_user_id || 'system';
                const targetLabel = entry.target_type
                  ? entry.target_id
                    ? `${entry.target_type}:${entry.target_id}`
                    : entry.target_type
                  : entry.target_id || '—';

                return (
                  <Fragment key={entry.id}>
                    <tr
                      style={{ borderBottom: '1px solid var(--border-color)', cursor: 'pointer' }}
                      onClick={() => setExpandedId(isExpanded ? null : entry.id)}
                    >
                      <td style={{ padding: '0.45rem 0.5rem', color: 'var(--text-muted)' }}>
                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </td>
                      <td style={{ padding: '0.45rem 0.5rem', whiteSpace: 'nowrap', fontFamily: 'monospace' }}>
                        {formatUtcTimestamp(entry.created_at)}
                      </td>
                      <td style={{ padding: '0.45rem 0.5rem' }}>
                        <div>{actorLabel}</div>
                        {entry.actor_role && (
                          <div className="text-xs text-muted">{entry.actor_role}</div>
                        )}
                      </td>
                      <td style={{ padding: '0.45rem 0.5rem', fontFamily: 'monospace' }}>{entry.action}</td>
                      <td style={{ padding: '0.45rem 0.5rem' }}>
                        <span
                          style={{
                            ...statusBadgeStyle(entry.status),
                            border: '1px solid',
                            borderRadius: '999px',
                            padding: '0.1rem 0.45rem',
                            fontSize: '0.72rem',
                            fontWeight: 600,
                          }}
                        >
                          {entry.status}
                        </span>
                      </td>
                      {showBackupColumn && (
                        <td style={{ padding: '0.45rem 0.5rem', fontFamily: 'monospace' }}>
                          {entry.backup_id || '—'}
                        </td>
                      )}
                      <td style={{ padding: '0.45rem 0.5rem', fontFamily: 'monospace' }}>{targetLabel}</td>
                    </tr>
                    {isExpanded && (
                      <tr style={{ borderBottom: '1px solid var(--border-color)', background: 'var(--bg-secondary)' }}>
                        <td colSpan={colCount} style={{ padding: '0.75rem' }}>
                          <div className="flex-col gap-xs text-xs">
                            <div className="flex-row gap-md flex-wrap text-muted">
                              <span>Actor ID: <code>{entry.actor_user_id || '—'}</code></span>
                              <span>Auth: <code>{entry.auth_method || '—'}</code></span>
                              <span>IP: <code>{entry.request_ip || '—'}</code></span>
                              <span>Timestamp: <code>{entry.created_at}</code></span>
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.5rem', marginTop: '0.25rem' }}>
                              <div>
                                <div className="text-muted" style={{ fontWeight: 600, marginBottom: '0.2rem' }}>Before</div>
                                <pre style={{ margin: 0, padding: '0.5rem', borderRadius: '4px', background: 'var(--bg-primary)', overflowX: 'auto', maxHeight: '220px' }}>
                                  {entry.before !== undefined && entry.before !== null ? JSON.stringify(entry.before, null, 2) : '—'}
                                </pre>
                              </div>
                              <div>
                                <div className="text-muted" style={{ fontWeight: 600, marginBottom: '0.2rem' }}>After</div>
                                <pre style={{ margin: 0, padding: '0.5rem', borderRadius: '4px', background: 'var(--bg-primary)', overflowX: 'auto', maxHeight: '220px' }}>
                                  {entry.after !== undefined && entry.after !== null ? JSON.stringify(entry.after, null, 2) : '—'}
                                </pre>
                              </div>
                              <div>
                                <div className="text-muted" style={{ fontWeight: 600, marginBottom: '0.2rem' }}>Metadata</div>
                                <pre style={{ margin: 0, padding: '0.5rem', borderRadius: '4px', background: 'var(--bg-primary)', overflowX: 'auto', maxHeight: '220px' }}>
                                  {entry.metadata !== undefined && entry.metadata !== null ? JSON.stringify(entry.metadata, null, 2) : '—'}
                                </pre>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      <div className="flex-row items-center justify-between gap-md flex-wrap text-xs text-muted">
        <span>
          Showing page {page} of {totalPages} ({total} {total === 1 ? 'entry' : 'entries'})
        </span>
        <div className="flex-row gap-xs">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={loading || page <= 1}
          >
            Previous
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={loading || page >= totalPages}
          >
            Next
          </Button>
        </div>
      </div>
    </PanelSurface>
  );
};

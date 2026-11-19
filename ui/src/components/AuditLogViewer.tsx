import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, RefreshCw, ScrollText, Search } from 'lucide-react';
import { getErrorMessage, type ApiError } from '../api';
import type { AuditLogEntry, AuditLogsResponse } from '../types';
import {
  Badge,
  Button,
  CollapsibleFilterBar,
  FilterChip,
  Pagination,
  PanelSurface,
  type BadgeVariant,
} from './ui';

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

const getStatusBadgeVariant = (status?: string): BadgeVariant => {
  const s = (status || '').toLowerCase();
  if (s === 'denied') return 'danger';
  if (s === 'error' || s === 'failed') return 'warning';
  return 'success';
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

  const clearSingleFilter = (key: keyof FilterState) => {
    setDraftFilters(prev => ({ ...prev, [key]: '' }));
    setAppliedFilters(prev => ({ ...prev, [key]: '' }));
    setPage(1);
  };

  const activeFilterEntries = useMemo(() => {
    const entries: Array<{ key: keyof FilterState; label: string; value: string }> = [];
    if (appliedFilters.action.trim()) {
      entries.push({ key: 'action', label: 'Action', value: appliedFilters.action.trim() });
    }
    if (appliedFilters.status) {
      entries.push({ key: 'status', label: 'Status', value: appliedFilters.status });
    }
    if (appliedFilters.actor_user_id.trim()) {
      entries.push({ key: 'actor_user_id', label: 'Actor', value: appliedFilters.actor_user_id.trim() });
    }
    if (appliedFilters.target_type.trim()) {
      entries.push({ key: 'target_type', label: 'Target', value: appliedFilters.target_type.trim() });
    }
    if (appliedFilters.from_ts.trim()) {
      entries.push({ key: 'from_ts', label: 'From', value: appliedFilters.from_ts.trim() });
    }
    if (appliedFilters.to_ts.trim()) {
      entries.push({ key: 'to_ts', label: 'To', value: appliedFilters.to_ts.trim() });
    }
    return entries;
  }, [appliedFilters]);

  const summaryPills = useMemo(() => {
    if (activeFilterEntries.length === 0) return null;
    return activeFilterEntries.map(entry => (
      <Badge key={entry.key} variant="neutral">
        {entry.label}: {entry.value}
      </Badge>
    ));
  }, [activeFilterEntries]);

  const colCount = showBackupColumn ? 7 : 6;

  return (
    <PanelSurface className="flex-col gap-lg">
      <div className="section-header">
        <div className="section-header-title-row">
          <ScrollText size={18} className="section-header-icon section-header-icon--secondary" />
          <div>
            <h3 className="section-header-title">{title}</h3>
            {description && <p className="section-header-desc">{description}</p>}
          </div>
        </div>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => void load()}
          disabled={loading}
          icon={<RefreshCw size={14} className={loading ? 'animate-spin' : ''} />}
        >
          Refresh
        </Button>
      </div>

      <CollapsibleFilterBar
        title="Audit Filters"
        activeCount={activeFilterEntries.length}
        summaryPills={summaryPills}
        onClearAll={resetFilters}
        actions={
          <Button type="button" variant="primary" size="xs" onClick={applyFilters}>
            Apply
          </Button>
        }
      >
        <div className="filter-cols-row">
          <div className="filter-col filter-col-sm">
            <div className="filter-col-header">
              <label htmlFor="audit-filter-action" className="text-secondary">
                Action
              </label>
            </div>
            <div className="search-input-wrapper">
              <Search size={14} />
              <input
                id="audit-filter-action"
                type="text"
                value={draftFilters.action}
                onChange={e => setDraftFilters(prev => ({ ...prev, action: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && applyFilters()}
                placeholder="e.g. writer.update"
              />
            </div>
          </div>

          <div className="filter-col filter-col-xs">
            <div className="filter-col-header">
              <label htmlFor="audit-filter-status" className="text-secondary">
                Status
              </label>
            </div>
            <select
              id="audit-filter-status"
              className="select"
              value={draftFilters.status}
              onChange={e => setDraftFilters(prev => ({ ...prev, status: e.target.value }))}
            >
              <option value="">All statuses</option>
              <option value="success">success</option>
              <option value="denied">denied</option>
              <option value="error">error</option>
            </select>
          </div>

          <div className="filter-col filter-col-xs">
            <div className="filter-col-header">
              <label htmlFor="audit-filter-actor" className="text-secondary">
                Actor ID
              </label>
            </div>
            <input
              id="audit-filter-actor"
              type="text"
              className="input"
              value={draftFilters.actor_user_id}
              onChange={e => setDraftFilters(prev => ({ ...prev, actor_user_id: e.target.value }))}
              onKeyDown={e => e.key === 'Enter' && applyFilters()}
              placeholder="Discord ID"
            />
          </div>

          <div className="filter-col filter-col-xs">
            <div className="filter-col-header">
              <label htmlFor="audit-filter-target" className="text-secondary">
                Target Type
              </label>
            </div>
            <input
              id="audit-filter-target"
              type="text"
              className="input"
              value={draftFilters.target_type}
              onChange={e => setDraftFilters(prev => ({ ...prev, target_type: e.target.value }))}
              onKeyDown={e => e.key === 'Enter' && applyFilters()}
              placeholder="e.g. writer"
            />
          </div>

          <div className="filter-group">
            <div className="filter-col filter-col-xs">
              <div className="filter-col-header">
                <label htmlFor="audit-filter-from" className="text-secondary">
                  From (UTC ISO)
                </label>
              </div>
              <input
                id="audit-filter-from"
                type="text"
                className="input"
                value={draftFilters.from_ts}
                onChange={e => setDraftFilters(prev => ({ ...prev, from_ts: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && applyFilters()}
                placeholder="YYYY-MM-DD"
              />
            </div>

            <div className="filter-col filter-col-xs">
              <div className="filter-col-header">
                <label htmlFor="audit-filter-to" className="text-secondary">
                  To (UTC ISO)
                </label>
              </div>
              <input
                id="audit-filter-to"
                type="text"
                className="input"
                value={draftFilters.to_ts}
                onChange={e => setDraftFilters(prev => ({ ...prev, to_ts: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && applyFilters()}
                placeholder="YYYY-MM-DD"
              />
            </div>
          </div>
        </div>

        {activeFilterEntries.length > 0 && (
          <div className="filter-active-chips-row">
            <span className="filter-active-chips-label">Filters:</span>
            {activeFilterEntries.map(entry => (
              <FilterChip
                key={entry.key}
                active
                variant="info"
                onRemove={() => clearSingleFilter(entry.key)}
              >
                {entry.label}: {entry.value}
              </FilterChip>
            ))}
          </div>
        )}
      </CollapsibleFilterBar>

      {errorMsg ? (
        <div className="banner-danger mb-0" role="alert">
          <span className="text-sm">{errorMsg}</span>
        </div>
      ) : items.length === 0 ? (
        <div className="empty-state audit-empty-state">
          <ScrollText size={28} className="empty-state-icon" />
          <p className="m-0 text-sm text-secondary">
            {loading ? 'Loading audit log entries...' : 'No audit log entries match the current filters.'}
          </p>
        </div>
      ) : (
        <div className="audit-table-wrapper">
          <table className="audit-table">
            <thead>
              <tr>
                <th className="audit-table-chevron" aria-label="Expand details" />
                <th>Time (UTC)</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Status</th>
                {showBackupColumn && <th>Backup</th>}
                <th>Target</th>
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
                      className={`audit-table-row ${isExpanded ? 'is-expanded' : ''}`}
                      onClick={() => setExpandedId(isExpanded ? null : entry.id)}
                    >
                      <td className="audit-table-chevron">
                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </td>
                      <td className="audit-table-nowrap font-mono">
                        {formatUtcTimestamp(entry.created_at)}
                      </td>
                      <td>
                        <div>{actorLabel}</div>
                        {entry.actor_role && (
                          <div className="text-sm text-muted">{entry.actor_role}</div>
                        )}
                      </td>
                      <td className="font-mono">{entry.action}</td>
                      <td>
                        <Badge variant={getStatusBadgeVariant(entry.status)}>
                          {entry.status}
                        </Badge>
                      </td>
                      {showBackupColumn && (
                        <td className="font-mono">{entry.backup_id || '—'}</td>
                      )}
                      <td className="font-mono">{targetLabel}</td>
                    </tr>
                    {isExpanded && (
                      <tr className="audit-table-detail-row">
                        <td colSpan={colCount}>
                          <div className="audit-detail-meta">
                            <span>
                              Actor ID: <code>{entry.actor_user_id || '—'}</code>
                            </span>
                            <span>
                              Auth: <code>{entry.auth_method || '—'}</code>
                            </span>
                            <span>
                              IP: <code>{entry.request_ip || '—'}</code>
                            </span>
                            <span>
                              Timestamp: <code>{entry.created_at}</code>
                            </span>
                          </div>
                          <div className="audit-detail-grid">
                            <div>
                              <div className="audit-detail-label">Before</div>
                              <pre className="audit-detail-pre">
                                {entry.before !== undefined && entry.before !== null
                                  ? JSON.stringify(entry.before, null, 2)
                                  : '—'}
                              </pre>
                            </div>
                            <div>
                              <div className="audit-detail-label">After</div>
                              <pre className="audit-detail-pre">
                                {entry.after !== undefined && entry.after !== null
                                  ? JSON.stringify(entry.after, null, 2)
                                  : '—'}
                              </pre>
                            </div>
                            <div>
                              <div className="audit-detail-label">Metadata</div>
                              <pre className="audit-detail-pre">
                                {entry.metadata !== undefined && entry.metadata !== null
                                  ? JSON.stringify(entry.metadata, null, 2)
                                  : '—'}
                              </pre>
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

      <Pagination
        currentPage={page}
        totalPages={totalPages}
        totalItems={total}
        onPageChange={setPage}
      />
    </PanelSurface>
  );
};

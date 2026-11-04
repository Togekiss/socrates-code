import { useEffect, useState, useMemo, useCallback } from 'react';
import { api } from '../api';
import { ScenesFilter } from './scenes/ScenesFilter';
import { EventCard } from './scenes/EventCard';
import { EventEditModal } from './scenes/EventEditModal';
import { AlertCircle, ArrowRight, Search, ArrowUpDown } from 'lucide-react';
import type { Character, EventRecord, MyWriter } from '../types';

interface EventsTabProps {
  backupId: string;
  backupStatus?: string;
  onNavigateToWriters?: () => void;
  myWriter?: MyWriter | null;
  onRefreshSummary?: () => void;
}

export const EventsTab = ({
  backupId,
  backupStatus,
  onNavigateToWriters,
  myWriter: initialMyWriter,
  onRefreshSummary,
}: EventsTabProps) => {
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);

  const [allCharacters, setAllCharacters] = useState<Character[]>([]);
  const [myWriter, setMyWriter] = useState<MyWriter | null>(initialMyWriter || null);
  const [editingEvent, setEditingEvent] = useState<EventRecord | null>(null);

  // Filters
  const [charactersFilter, setCharactersFilter] = useState<number[]>([]);
  const [characterLogic, setCharacterLogic] = useState<'AND' | 'OR'>('OR');
  const [writersFilter, setWritersFilter] = useState<string[]>([]);
  const [writerLogic, setWriterLogic] = useState<'AND' | 'OR'>('OR');
  const [channelsFilter, setChannelsFilter] = useState<string[]>([]);
  const [typesFilter, setTypesFilter] = useState<string[]>([]);
  const [statusesFilter, setStatusesFilter] = useState<string[]>([]);
  const [includeAlterEgos, setIncludeAlterEgos] = useState(true);
  const [includeFamiliars, setIncludeFamiliars] = useState(true);
  const [includeNPCs, setIncludeNPCs] = useState(true);
  const [before, setBefore] = useState('');
  const [after, setAfter] = useState('');
  const [byMe, setByMe] = useState(false);
  const [search, setSearch] = useState('');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');

  const [fetchedStatus, setFetchedStatus] = useState<string | null>(null);

  useEffect(() => {
    if (backupStatus) {
      setFetchedStatus(backupStatus);
    } else {
      api
        .getBackupInfo(backupId)
        .then(res => setFetchedStatus(res.status))
        .catch(console.error);
    }
  }, [backupId, backupStatus]);

  const isReady = fetchedStatus === 'success' || fetchedStatus === 'ready' || fetchedStatus === 'READY';

  useEffect(() => {
    if (isReady) {
      Promise.all([
        api.getCharacters(backupId).then(res => {
          if (Array.isArray(res)) setAllCharacters(res);
        }),
        api.getMyWriter(backupId).then(setMyWriter).catch(() => null),
      ]).catch(console.error);
    }
  }, [backupId, isReady]);

  const resolvedCharacterIds = useMemo(() => {
    if (charactersFilter.length === 0) return [];
    const resolved = new Set<number>();
    charactersFilter.forEach(id => {
      resolved.add(id);
      const char = allCharacters.find(c => c.id === id);
      if (char && char.versions) {
        char.versions.forEach(v => {
          if (includeAlterEgos && v.version_type === 'alter_ego') resolved.add(v.id);
          if (includeFamiliars && v.version_type === 'familiar') resolved.add(v.id);
          if (includeNPCs && v.version_type === 'npc') resolved.add(v.id);
        });
      }
    });
    return Array.from(resolved);
  }, [charactersFilter, includeAlterEgos, includeFamiliars, includeNPCs, allCharacters]);

  const buildQueryParams = useCallback(
    (targetPage: number) => {
      const params = new URLSearchParams();
      params.append('page', targetPage.toString());
      params.append('per_page', '50');
      params.append('sort', sortOrder);

      if (search.trim()) params.append('search', search.trim());
      channelsFilter.forEach(ch => params.append('channels', ch));
      statusesFilter.forEach(s => params.append('statuses', s));

      resolvedCharacterIds.forEach(id => params.append('characters', id.toString()));
      params.append('character_logic', characterLogic);

      writersFilter.forEach(w => params.append('writers', w));
      params.append('writer_logic', writerLogic);

      params.append('include_alter_egos', includeAlterEgos.toString());
      params.append('include_familiars', includeFamiliars.toString());
      params.append('include_npcs', includeNPCs.toString());

      if (byMe) params.append('by_me', 'true');
      if (before) params.append('before', before + 'T00:00:00Z');
      if (after) params.append('after', after + 'T23:59:59Z');

      return params;
    },
    [
      sortOrder,
      search,
      channelsFilter,
      statusesFilter,
      resolvedCharacterIds,
      characterLogic,
      writersFilter,
      writerLogic,
      includeAlterEgos,
      includeFamiliars,
      includeNPCs,
      byMe,
      before,
      after,
    ]
  );

  const loadEvents = useCallback(
    (targetPage: number, reset: boolean = false) => {
      if (!isReady) return;
      setLoading(true);
      if (reset) setError(null);

      api
        .getEvents(backupId, buildQueryParams(targetPage))
        .then(res => {
          const data = res.events || [];
          setEvents(prev => (reset ? data : [...prev, ...data]));
          setHasMore(targetPage < (res.total_pages || 1));
          setLoading(false);
        })
        .catch(err => {
          setError(err.message);
          setLoading(false);
        });
    },
    [backupId, isReady, buildQueryParams]
  );

  useEffect(() => {
    setPage(1);
    const timeout = setTimeout(() => {
      loadEvents(1, true);
    }, 300);
    return () => clearTimeout(timeout);
  }, [loadEvents]);

  if (!isReady) {
    return (
      <div className="glass-panel" style={{ opacity: 0.5, pointerEvents: 'none' }}>
        <h2>Events</h2>
        <p>Backup is not ready. Run the pipeline first.</p>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      {byMe && !myWriter && (
        <div
          style={{
            background: 'rgba(245, 158, 11, 0.1)',
            border: '1px solid var(--warning)',
            borderRadius: '8px',
            padding: '1rem 1.25rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '1rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <AlertCircle size={22} style={{ color: 'var(--warning)', flexShrink: 0 }} />
            <div>
              <strong style={{ color: 'var(--text-primary)', display: 'block', fontSize: '0.95rem' }}>
                Your Discord account is not yet linked to a writer profile
              </strong>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                Link your profile in the Writers tab to filter events written by your characters.
              </span>
            </div>
          </div>
          {onNavigateToWriters && (
            <button
              onClick={onNavigateToWriters}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.4rem',
                padding: '0.45rem 1rem',
                background: 'var(--warning)',
                color: '#000',
                border: 'none',
                borderRadius: '6px',
                fontWeight: 600,
                fontSize: '0.85rem',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              Go to Writers <ArrowRight size={14} />
            </button>
          )}
        </div>
      )}

      {/* Search & Sort Bar */}
      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: '1 1 260px' }}>
          <Search
            size={16}
            style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }}
          />
          <input
            type="text"
            placeholder="Search events or location custom names..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{
              width: '100%',
              padding: '0.5rem 0.75rem 0.5rem 2.25rem',
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border-color)',
              color: 'white',
              borderRadius: '6px',
              fontSize: '0.88rem',
            }}
          />
        </div>

        <button
          type="button"
          onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.4rem',
            padding: '0.5rem 0.85rem',
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            color: 'var(--text-primary)',
            borderRadius: '6px',
            fontSize: '0.85rem',
            cursor: 'pointer',
          }}
        >
          <ArrowUpDown size={15} />
          {sortOrder === 'asc' ? 'Oldest First' : 'Newest First'}
        </button>
      </div>

      <ScenesFilter
        mode="events"
        charactersFilter={charactersFilter}
        setCharactersFilter={setCharactersFilter}
        characterLogic={characterLogic}
        setCharacterLogic={setCharacterLogic}
        writersFilter={writersFilter}
        setWritersFilter={setWritersFilter}
        writerLogic={writerLogic}
        setWriterLogic={setWriterLogic}
        categoriesFilter={channelsFilter}
        setCategoriesFilter={setChannelsFilter}
        typesFilter={typesFilter}
        setTypesFilter={setTypesFilter}
        statusesFilter={statusesFilter}
        setStatusesFilter={setStatusesFilter}
        includeAlterEgos={includeAlterEgos}
        setIncludeAlterEgos={setIncludeAlterEgos}
        includeFamiliars={includeFamiliars}
        setIncludeFamiliars={setIncludeFamiliars}
        includeNPCs={includeNPCs}
        setIncludeNPCs={setIncludeNPCs}
        before={before}
        setBefore={setBefore}
        after={after}
        setAfter={setAfter}
        byMe={byMe}
        setByMe={setByMe}
        allCharacters={allCharacters}
      />

      {error && <div style={{ color: 'var(--danger)', padding: '0.75rem' }}>{error}</div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
        {events.length === 0 && !loading ? (
          <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>
            No events match the current filters.
          </div>
        ) : (
          events.map(ev => (
            <EventCard
              key={ev.pk || ev.id}
              event={ev}
              allCharacters={allCharacters}
              onEdit={target => setEditingEvent(target)}
            />
          ))
        )}
      </div>

      {hasMore && (
        <button
          type="button"
          onClick={() => {
            const next = page + 1;
            setPage(next);
            loadEvents(next, false);
          }}
          disabled={loading}
          style={{
            alignSelf: 'center',
            padding: '0.5rem 1.25rem',
            background: 'var(--bg-tertiary)',
            border: '1px solid var(--border-color)',
            color: 'var(--text-primary)',
            borderRadius: '6px',
            cursor: loading ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? 'Loading...' : 'Load More Events'}
        </button>
      )}

      {editingEvent && (
        <EventEditModal
          backupId={backupId}
          event={editingEvent}
          allEvents={events}
          onClose={() => setEditingEvent(null)}
          onUpdated={() => {
            loadEvents(1, true);
            if (onRefreshSummary) onRefreshSummary();
          }}
        />
      )}
    </div>
  );
};

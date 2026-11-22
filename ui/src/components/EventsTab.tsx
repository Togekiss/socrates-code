import { useEffect, useState, useCallback, useRef } from 'react';
import { ArrowUpDown, Loader2 } from 'lucide-react';
import { api, getErrorMessage } from '../api';
import { ScenesFilter } from './scenes/ScenesFilter';
import { EventCard } from './scenes/EventCard';
import { EventEditModal } from './scenes/EventEditModal';
import { Button, Pagination, PanelSurface, ResponsiveText } from './ui';
import { UnlinkedWriterBanner } from './layout/UnlinkedWriterBanner';
import { BackupStatusGuard } from './layout/BackupStatusGuard';
import { ListPageLayout } from './layout/ListPageLayout';
import { useBackupStatusGuard } from '../hooks/useBackupStatusGuard';
import { useArchiveRoster } from '../hooks/useArchiveRoster';
import type { BackupInfo, EventRecord, MyWriter } from '../types';
import { getRoleLevel, ROLE_LEVELS } from '../utils/rbac';

interface EventsTabProps {
  backupId: string;
  backupStatus?: string;
  backupInfo?: BackupInfo | null;
  backupError?: string | null;
  backupLoading?: boolean;
  roleLevel?: number;
  onNavigateToWriters?: () => void;
  myWriter?: MyWriter | null;
  onRefreshSummary?: () => void;
}

export const EventsTab = ({
  backupId,
  backupStatus,
  backupInfo,
  backupError,
  backupLoading,
  roleLevel: propRoleLevel,
  onNavigateToWriters,
  myWriter: initialMyWriter,
  onRefreshSummary,
}: EventsTabProps) => {
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const scrollRef = useRef<HTMLDivElement>(null);

  const [myWriter, setMyWriter] = useState<MyWriter | null>(initialMyWriter || null);
  const [editingEvent, setEditingEvent] = useState<EventRecord | null>(null);

  // Filters
  const [charactersFilter, setCharactersFilter] = useState<number[]>([]);
  const [groupsFilter, setGroupsFilter] = useState<number[]>([]);
  const [characterLogic, setCharacterLogic] = useState<'AND' | 'OR'>('AND');
  const [writersFilter, setWritersFilter] = useState<string[]>([]);
  const [writerLogic, setWriterLogic] = useState<'AND' | 'OR'>('AND');
  const [typesFilter, setTypesFilter] = useState<string[]>([]);
  const [statusesFilter, setStatusesFilter] = useState<string[]>([]);
  const [includeAlterEgos, setIncludeAlterEgos] = useState(true);
  const [includeFamiliars, setIncludeFamiliars] = useState(true);
  const [includeNPCs, setIncludeNPCs] = useState(true);
  const [before, setBefore] = useState('');
  const [after, setAfter] = useState('');
  const [byMe, setByMe] = useState(false);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');

  const statusGuard = useBackupStatusGuard({
    backupId,
    backupStatus,
    backupInfo,
    backupError,
    backupLoading,
  });
  const { isReady } = statusGuard;
  const { allCharacters, allGroups, allWriters } = useArchiveRoster(backupId, isReady);

  useEffect(() => {
    setMyWriter(initialMyWriter || null);
  }, [initialMyWriter]);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 350);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    setEvents([]);
    setTotalItems(0);
    setTotalPages(1);
    setPage(1);
    setError(null);
  }, [backupId]);

  const buildQueryParams = useCallback(
    (targetPage: number) => {
      const params = new URLSearchParams();
      params.append('page', targetPage.toString());
      params.append('per_page', '50');
      params.append('sort', sortOrder);
      if (debouncedSearch.trim()) params.append('search', debouncedSearch.trim());

      typesFilter.forEach(t => params.append('types', t));
      statusesFilter.forEach(s => params.append('statuses', s));

      if (before) params.append('before', before);
      if (after) params.append('after', after);

      if (byMe) {
        params.append('by_me', 'true');
      } else {
        writersFilter.forEach(w => params.append('writers', w));
        if (writersFilter.length > 0) {
          params.append('writer_logic', writerLogic);
        }
      }

      charactersFilter.forEach(id => params.append('characters', id.toString()));
      groupsFilter.forEach(gid => params.append('character_groups', gid.toString()));
      if (charactersFilter.length > 0 || groupsFilter.length > 0) {
        params.append('character_logic', characterLogic);
        const allowVersions = characterLogic === 'OR';
        params.append('include_alter_egos', String(allowVersions && includeAlterEgos));
        params.append('include_familiars', String(allowVersions && includeFamiliars));
        params.append('include_npcs', String(allowVersions && includeNPCs));
      }

      return params;
    },
    [
      sortOrder,
      debouncedSearch,
      typesFilter,
      statusesFilter,
      before,
      after,
      byMe,
      writersFilter,
      writerLogic,
      charactersFilter,
      groupsFilter,
      characterLogic,
      includeAlterEgos,
      includeFamiliars,
      includeNPCs,
    ]
  );

  const loadEvents = useCallback(
    (targetPage: number) => {
      if (!isReady) return;
      setLoading(true);
      setError(null);

      const params = buildQueryParams(targetPage);

      api
        .getEvents(backupId, params)
        .then(res => {
          const nextEvents = res.events || [];
          setEvents(nextEvents);
          setTotalItems(res.total_items ?? nextEvents.length);
          setTotalPages(Math.max(1, res.total_pages ?? 1));
        })
        .catch(err => {
          console.error(err);
          setEvents([]);
          setTotalItems(0);
          setTotalPages(1);
          setError(getErrorMessage(err, 'Failed to fetch events.'));
        })
        .finally(() => setLoading(false));
    },
    [backupId, isReady, buildQueryParams]
  );

  const filterKey = JSON.stringify({
    backupId,
    debouncedSearch,
    charactersFilter,
    groupsFilter,
    characterLogic,
    includeAlterEgos,
    includeFamiliars,
    includeNPCs,
    writersFilter,
    writerLogic,
    typesFilter,
    statusesFilter,
    before,
    after,
    byMe,
    sortOrder,
  });
  const prevFilterKeyRef = useRef(filterKey);

  useEffect(() => {
    if (!isReady) return;
    if (prevFilterKeyRef.current !== filterKey) {
      prevFilterKeyRef.current = filterKey;
      if (page !== 1) {
        setPage(1);
        return;
      }
    }
    loadEvents(page);
  }, [isReady, filterKey, page, loadEvents]);

  const handlePageChange = (nextPage: number) => {
    setPage(nextPage);
    scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const effectiveRoleLevel = propRoleLevel ?? backupInfo?.role_level ?? getRoleLevel(backupInfo?.effective_role);
  const canCurate = effectiveRoleLevel >= ROLE_LEVELS.curator;

  if (!isReady) {
    return <BackupStatusGuard title="Events" guard={statusGuard} />;
  }

  const filtersActive = Boolean(
    debouncedSearch.trim() ||
      charactersFilter.length > 0 ||
      groupsFilter.length > 0 ||
      writersFilter.length > 0 ||
      statusesFilter.length > 0 ||
      before ||
      after ||
      byMe
  );

  return (
    <ListPageLayout
      title="Events"
      descriptionKey="descEvents"
      guideKey="events"
      headerAction={
        <Button
          variant="secondary"
          size="md"
          onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
          icon={<ArrowUpDown size={14} />}
        >
          <ResponsiveText textKey={sortOrder === 'asc' ? 'sortOldest' : 'sortNewest'} />
        </Button>
      }
      filterBar={
        <ScenesFilter
          mode="events"
          search={search}
          setSearch={setSearch}
          charactersFilter={charactersFilter}
          setCharactersFilter={setCharactersFilter}
          groupsFilter={groupsFilter}
          setGroupsFilter={setGroupsFilter}
          characterLogic={characterLogic}
          setCharacterLogic={setCharacterLogic}
          writersFilter={writersFilter}
          setWritersFilter={setWritersFilter}
          writerLogic={writerLogic}
          setWriterLogic={setWriterLogic}
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
          allGroups={allGroups}
          allWriters={allWriters}
        />
      }
      banners={
        <>
          <BackupStatusGuard title="Events" guard={statusGuard} />
          {byMe && !myWriter && (
            <UnlinkedWriterBanner onNavigateToWriters={onNavigateToWriters} />
          )}
        </>
      }
      countText={
        !error && (!loading || totalItems > 0) ? (
          <span>
            Showing{' '}
            <strong>
              {totalItems > events.length ? `${events.length} of ${totalItems}` : totalItems}
            </strong>{' '}
            {totalItems === 1 ? 'event' : 'events'}
            {filtersActive && ' (filtered)'}
          </span>
        ) : undefined
      }
      scrollRef={scrollRef}
      modals={
        canCurate && editingEvent ? (
          <EventEditModal
            backupId={backupId}
            event={editingEvent}
            allEvents={events}
            onClose={() => setEditingEvent(null)}
            onUpdated={() => {
              loadEvents(page);
              if (onRefreshSummary) onRefreshSummary();
            }}
          />
        ) : undefined
      }
    >
      {loading ? (
        <PanelSurface className="text-center p-xl">
          <Loader2
            size={32}
            className="animate-spin text-accent"
            style={{ margin: '0 auto 1rem auto' }}
          />
          <p className="text-secondary">Loading events...</p>
        </PanelSurface>
      ) : error ? (
        <div className="banner-danger">
          <span className="text-md">{error}</span>
        </div>
      ) : events.length === 0 ? (
        <div className="text-secondary text-center p-xl">
          No events match the current filters.
        </div>
      ) : (
        <div className="flex-col gap-sm">
          {events.map(ev => (
            <EventCard
              key={ev.pk || ev.id}
              event={ev}
              allCharacters={allCharacters}
              onEdit={canCurate ? target => { if (statusGuard.canMutate) setEditingEvent(target); } : undefined}
              editDisabled={!statusGuard.canMutate}
            />
          ))}
        </div>
      )}

      {!loading && !error && totalPages > 1 && (
        <Pagination
          currentPage={page}
          totalPages={totalPages}
          totalItems={totalItems}
          onPageChange={handlePageChange}
        />
      )}
    </ListPageLayout>
  );
};

import { useEffect, useState, useCallback, useRef } from 'react';
import { ArrowUpDown, Loader2 } from 'lucide-react';
import { api, getErrorMessage } from '../api';
import { ScenesFilter } from './scenes/ScenesFilter';
import { SceneCard } from './scenes/SceneCard';
import { SceneEditModal } from './scenes/SceneEditModal';
import { Button, Pagination, PanelSurface, ResponsiveText } from './ui';
import { UnlinkedWriterBanner } from './layout/UnlinkedWriterBanner';
import { BackupStatusGuard } from './layout/BackupStatusGuard';
import { ListPageLayout } from './layout/ListPageLayout';
import { useBackupStatusGuard } from '../hooks/useBackupStatusGuard';
import { useArchiveRoster } from '../hooks/useArchiveRoster';
import type { BackupInfo, MyWriter, Scene } from '../types';
import { getRoleLevel, ROLE_LEVELS } from '../utils/rbac';

interface ScenesTabProps {
  backupId: string;
  backupStatus?: string;
  backupInfo?: BackupInfo | null;
  backupError?: string | null;
  backupLoading?: boolean;
  roleLevel?: number;
  onNavigateToWriters?: () => void;
  myWriter?: MyWriter | null;
}

export const ScenesTab = ({
  backupId,
  backupStatus,
  backupInfo,
  backupError,
  backupLoading,
  roleLevel: propRoleLevel,
  onNavigateToWriters,
  myWriter: initialMyWriter,
}: ScenesTabProps) => {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [editingScene, setEditingScene] = useState<Scene | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const [myWriter, setMyWriter] = useState<MyWriter | null>(initialMyWriter || null);

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
    setScenes([]);
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

  const fetchScenes = useCallback(
    (targetPage: number) => {
      if (!isReady) return;
      setLoading(true);
      setError(null);

      const params = buildQueryParams(targetPage);

      api
        .getScenes(backupId, params)
        .then(res => {
          const nextScenes = res.scenes || [];
          setScenes(nextScenes);
          setTotalItems(res.total_items ?? nextScenes.length);
          setTotalPages(Math.max(1, res.total_pages ?? 1));
        })
        .catch(err => {
          console.error(err);
          setScenes([]);
          setTotalItems(0);
          setTotalPages(1);
          setError(getErrorMessage(err, 'Failed to fetch scenes.'));
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
    fetchScenes(page);
  }, [isReady, filterKey, page, fetchScenes]);

  const handlePageChange = (nextPage: number) => {
    setPage(nextPage);
    scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const effectiveRoleLevel = propRoleLevel ?? backupInfo?.role_level ?? getRoleLevel(backupInfo?.effective_role);
  const canCurate = effectiveRoleLevel >= ROLE_LEVELS.curator;

  if (!isReady) {
    return <BackupStatusGuard title="Scenes" guard={statusGuard} />;
  }

  const filtersActive = Boolean(
    debouncedSearch.trim() ||
      charactersFilter.length > 0 ||
      groupsFilter.length > 0 ||
      writersFilter.length > 0 ||
      typesFilter.length > 0 ||
      statusesFilter.length > 0 ||
      before ||
      after ||
      byMe
  );

  return (
    <ListPageLayout
      title="Scenes"
      descriptionKey="descScenes"
      guideKey="scenes"
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
          <BackupStatusGuard title="Scenes" guard={statusGuard} />
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
              {totalItems > scenes.length ? `${scenes.length} of ${totalItems}` : totalItems}
            </strong>{' '}
            {totalItems === 1 ? 'scene' : 'scenes'}
            {filtersActive && ' (filtered)'}
          </span>
        ) : undefined
      }
      scrollRef={scrollRef}
      modals={
        canCurate && editingScene ? (
          <SceneEditModal
            backupId={backupId}
            scene={editingScene}
            onClose={() => setEditingScene(null)}
            onUpdated={updated => {
              if (updated) {
                setScenes(prev =>
                  prev.map(s =>
                    s.scene_key === updated.scene_key ||
                    s.id === updated.scene_key ||
                    (updated.pk && (s.pk === updated.pk || s.scene_pk === updated.pk))
                      ? { ...s, custom_name: updated.custom_name }
                      : s
                  )
                );
              } else {
                fetchScenes(page);
              }
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
          <p className="text-secondary">Loading scenes...</p>
        </PanelSurface>
      ) : error ? (
        <div className="banner-danger">
          <span className="text-md">{error}</span>
        </div>
      ) : scenes.length === 0 ? (
        <div className="text-secondary text-center p-xl">
          No scenes match the current filters.
        </div>
      ) : (
        <div className="flex-col gap-sm">
          {scenes.map(scene => (
            <SceneCard
              key={scene.pk ?? scene.scene_pk ?? scene.scene_key ?? scene.id}
              scene={scene}
              allCharacters={allCharacters}
              charactersFilter={charactersFilter}
              setCharactersFilter={setCharactersFilter}
              onEdit={canCurate ? item => { if (statusGuard.canMutate) setEditingScene(item); } : undefined}
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

import { useEffect, useState, useMemo, useCallback } from 'react';
import { api, getErrorMessage } from '../api';
import { ScenesFilter } from './scenes/ScenesFilter';
import { VirtualSceneList } from './scenes/VirtualSceneList';
import { SceneEditModal } from './scenes/SceneEditModal';
import { Search, ArrowUpDown } from 'lucide-react';
import { Button, ResponsiveText } from './ui';
import { UnlinkedWriterBanner } from './layout/UnlinkedWriterBanner';
import { BackupStatusGuard } from './layout/BackupStatusGuard';
import { useBackupStatusGuard } from '../hooks/useBackupStatusGuard';
import type { BackupInfo, Character, MyWriter, Scene } from '../types';

interface ScenesTabProps {
  backupId: string;
  backupStatus?: string;
  backupInfo?: BackupInfo | null;
  backupError?: string | null;
  backupLoading?: boolean;
  onNavigateToWriters?: () => void;
  myWriter?: MyWriter | null;
}

export const ScenesTab = ({
  backupId,
  backupStatus,
  backupInfo,
  backupError,
  backupLoading,
  onNavigateToWriters,
  myWriter: initialMyWriter,
}: ScenesTabProps) => {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [editingScene, setEditingScene] = useState<Scene | null>(null);

  const [allCharacters, setAllCharacters] = useState<Character[]>([]);
  const [myWriter, setMyWriter] = useState<MyWriter | null>(initialMyWriter || null);

  // Filters
  const [charactersFilter, setCharactersFilter] = useState<number[]>([]);
  const [characterLogic, setCharacterLogic] = useState<'AND' | 'OR'>('AND');
  const [writersFilter, setWritersFilter] = useState<string[]>([]);
  const [writerLogic, setWriterLogic] = useState<'AND' | 'OR'>('AND');
  const [categoriesFilter, setCategoriesFilter] = useState<string[]>([]);
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

  const statusGuard = useBackupStatusGuard({
    backupId,
    backupStatus,
    backupInfo,
    backupError,
    backupLoading,
  });
  const { isReady } = statusGuard;

  useEffect(() => {
    setScenes([]);
    setPage(1);
    setHasMore(false);
    setError(null);
    setAllCharacters([]);
  }, [backupId]);

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

      categoriesFilter.forEach(c => params.append('categories', c));
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

      resolvedCharacterIds.forEach(id => params.append('characters', id.toString()));
      if (resolvedCharacterIds.length > 0) {
        params.append('character_logic', characterLogic);
      }

      return params;
    },
    [
      sortOrder,
      search,
      categoriesFilter,
      typesFilter,
      statusesFilter,
      before,
      after,
      byMe,
      writersFilter,
      writerLogic,
      resolvedCharacterIds,
      characterLogic,
    ]
  );

  const fetchScenes = useCallback(
    (targetPage: number, reset = false) => {
      if (!isReady) return;
      setLoading(true);
      setError(null);

      const params = buildQueryParams(targetPage);

      api
        .getScenes(backupId, params)
        .then(res => {
          const newScenes = res.scenes || [];
          setScenes(prev => (reset ? newScenes : [...prev, ...newScenes]));
          setHasMore(newScenes.length === 50);
        })
        .catch(err => {
          console.error(err);
          setHasMore(false);
          setError(getErrorMessage(err, 'Failed to fetch scenes.'));
        })
        .finally(() => setLoading(false));
    },
    [backupId, isReady, buildQueryParams]
  );

  // Debounced filter effect
  useEffect(() => {
    setPage(1);
    const timeout = setTimeout(() => {
      fetchScenes(1, true);
    }, 400);
    return () => clearTimeout(timeout);
  }, [
    backupId,
    isReady,
    resolvedCharacterIds,
    characterLogic,
    writersFilter,
    writerLogic,
    categoriesFilter,
    typesFilter,
    statusesFilter,
    before,
    after,
    byMe,
    search,
    sortOrder,
    fetchScenes,
  ]);

  const loadMore = () => {
    const nextPage = page + 1;
    setPage(nextPage);
    fetchScenes(nextPage);
  };

  if (!isReady) {
    return <BackupStatusGuard title="Scenes" guard={statusGuard} />;
  }

  return (
    <div className="flex-col gap-md">
      {/* Guidance Banner when By Me is active and User is unlinked */}
      {byMe && !myWriter && (
        <UnlinkedWriterBanner onNavigateToWriters={onNavigateToWriters} className="mb-sm" />
      )}

      {/* Search & Sort Bar */}
      <div className="flex-row gap-sm items-center">
        <div className="search-input-wrapper" style={{ flex: '1 1 260px' }}>
          <Search size={16} />
          <input
            type="text"
            className="input"
            placeholder="Search scenes or custom names..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>

        <Button
          variant="secondary"
          size="md"
          onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
          icon={<ArrowUpDown size={14} />}
        >
          <ResponsiveText textKey={sortOrder === 'asc' ? 'sortOldest' : 'sortNewest'} />
        </Button>
      </div>

      <ScenesFilter
        charactersFilter={charactersFilter}
        setCharactersFilter={setCharactersFilter}
        characterLogic={characterLogic}
        setCharacterLogic={setCharacterLogic}
        writersFilter={writersFilter}
        setWritersFilter={setWritersFilter}
        writerLogic={writerLogic}
        setWriterLogic={setWriterLogic}
        categoriesFilter={categoriesFilter}
        setCategoriesFilter={setCategoriesFilter}
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

      {error && (
        <div className="banner-danger">
          <span className="text-md">{error}</span>
        </div>
      )}

      <VirtualSceneList
        scenes={scenes}
        allCharacters={allCharacters}
        charactersFilter={charactersFilter}
        setCharactersFilter={setCharactersFilter}
        loadMore={loadMore}
        hasMore={hasMore}
        loading={loading}
        error={error}
        onEdit={item => setEditingScene(item as Scene)}
      />

      {editingScene && (
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
              fetchScenes(1, true);
            }
          }}
        />
      )}
    </div>
  );
};

import { useEffect, useState, useMemo, useCallback } from 'react';
import { api } from '../api';
import { ScenesFilter } from './scenes/ScenesFilter';
import { VirtualSceneList } from './scenes/VirtualSceneList';
import { AlertCircle, ArrowRight } from 'lucide-react';
import type { Character, MyWriter, Scene } from '../types';

interface ScenesTabProps {
  backupId: string;
  backupStatus?: string;
  onNavigateToWriters?: () => void;
  myWriter?: MyWriter | null;
}

export const ScenesTab = ({
  backupId,
  backupStatus,
  onNavigateToWriters,
  myWriter: initialMyWriter,
}: ScenesTabProps) => {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);

  const [allCharacters, setAllCharacters] = useState<Character[]>([]);
  const [myWriter, setMyWriter] = useState<MyWriter | null>(initialMyWriter || null);

  // Filters
  const [charactersFilter, setCharactersFilter] = useState<number[]>([]);
  const [characterLogic, setCharacterLogic] = useState<'AND' | 'OR'>('OR');
  const [writersFilter, setWritersFilter] = useState<string[]>([]);
  const [writerLogic, setWriterLogic] = useState<'AND' | 'OR'>('OR');
  const [categoriesFilter, setCategoriesFilter] = useState<string[]>([]);
  const [typesFilter, setTypesFilter] = useState<string[]>([]);
  const [statusesFilter, setStatusesFilter] = useState<string[]>([]);
  const [includeAlterEgos, setIncludeAlterEgos] = useState(true);
  const [includeFamiliars, setIncludeFamiliars] = useState(true);
  const [includeNPCs, setIncludeNPCs] = useState(true);
  const [before, setBefore] = useState('');
  const [after, setAfter] = useState('');
  const [byMe, setByMe] = useState(false);

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

      categoriesFilter.forEach(c => params.append('categories', c));
      statusesFilter.forEach(s => params.append('statuses', s));
      typesFilter.forEach(t => params.append('types', t));

      resolvedCharacterIds.forEach(id => params.append('characters', id.toString()));
      params.append('character_logic', characterLogic);

      writersFilter.forEach(w => params.append('writers', w));
      params.append('writer_logic', writerLogic);

      if (byMe) params.append('by_me', 'true');
      if (before) params.append('before', before + 'T00:00:00Z');
      if (after) params.append('after', after + 'T23:59:59Z');

      return params;
    },
    [
      categoriesFilter,
      statusesFilter,
      typesFilter,
      resolvedCharacterIds,
      characterLogic,
      writersFilter,
      writerLogic,
      byMe,
      before,
      after,
    ]
  );

  const fetchScenes = useCallback(
    (targetPage: number, reset: boolean = false) => {
      if (!isReady) return;
      setLoading(true);
      if (reset) setError(null);

      api
        .getScenes(backupId, buildQueryParams(targetPage))
        .then(res => {
          const data = res.scenes || [];
          setScenes(prev => (reset ? data : [...prev, ...data]));
          setHasMore(data.length === 50);
          setLoading(false);
        })
        .catch(err => {
          setError(err.message);
          setLoading(false);
        });
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
    fetchScenes,
  ]);

  const loadMore = () => {
    const nextPage = page + 1;
    setPage(nextPage);
    fetchScenes(nextPage);
  };

  if (!isReady) {
    return (
      <div className="glass-panel" style={{ opacity: 0.5, pointerEvents: 'none' }}>
        <h2>Scenes</h2>
        <p>Backup is not ready. Run the pipeline first.</p>
      </div>
    );
  }

  return (
    <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Guidance Banner when By Me is active and User is unlinked */}
      {byMe && !myWriter && (
        <div
          style={{
            background: 'rgba(245, 158, 11, 0.1)',
            border: '1px solid var(--warning)',
            borderRadius: '8px',
            padding: '1rem 1.25rem',
            marginBottom: '1rem',
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
                Link your profile in the Writers tab to filter scenes written by your characters.
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

      {error && <div style={{ color: 'var(--danger)', padding: '1rem' }}>{error}</div>}

      <VirtualSceneList
        scenes={scenes}
        allCharacters={allCharacters}
        charactersFilter={charactersFilter}
        setCharactersFilter={setCharactersFilter}
        loadMore={loadMore}
        hasMore={hasMore}
        loading={loading}
      />
    </div>
  );
};

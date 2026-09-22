import { useEffect, useState, useMemo } from 'react';
import { api } from '../api';
import { ScenesFilter } from './scenes/ScenesFilter';
import { VirtualSceneList } from './scenes/VirtualSceneList';

export const ScenesTab = ({ backupId, backupStatus }: { backupId: string, backupStatus?: string }) => {
  const [scenes, setScenes] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);

  const [allCharacters, setAllCharacters] = useState<any[]>([]);

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

  const [fetchedStatus, setFetchedStatus] = useState<string | null>(null);

  useEffect(() => {
    if (backupStatus) {
      setFetchedStatus(backupStatus);
    } else {
      api.getBackupInfo(backupId).then(res => setFetchedStatus(res.status)).catch(console.error);
    }
  }, [backupId, backupStatus]);

  const isReady = fetchedStatus === 'success' || fetchedStatus === 'ready' || fetchedStatus === 'READY';

  useEffect(() => {
    if (isReady) {
      api.getCharacters(backupId).then(res => {
        if (Array.isArray(res)) setAllCharacters(res);
      }).catch(console.error);
    }
  }, [backupId, isReady]);

  const resolvedCharacterIds = useMemo(() => {
    if (charactersFilter.length === 0) return [];
    let resolved = new Set<number>();
    charactersFilter.forEach(id => {
        resolved.add(id);
        const char = allCharacters.find(c => c.id === id);
        if (char && char.other_versions) {
            char.other_versions.forEach((v: any) => {
                if (includeAlterEgos && v.tags?.includes('alter_ego')) resolved.add(v.id);
                if (includeFamiliars && v.tags?.includes('familiar')) resolved.add(v.id);
                if (includeNPCs && v.tags?.includes('npc')) resolved.add(v.id);
            });
        }
    });
    return Array.from(resolved);
  }, [charactersFilter, includeAlterEgos, includeFamiliars, includeNPCs, allCharacters]);

  const buildQueryParams = (targetPage: number) => {
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
    
    if (before) params.append('before', before + 'T00:00:00Z');
    if (after) params.append('after', after + 'T23:59:59Z');
    
    return params;
  };

  const fetchScenes = (targetPage: number, reset: boolean = false) => {
    if (!isReady) return;
    setLoading(true);
    if (reset) setError(null);
    
    api.getScenes(backupId, buildQueryParams(targetPage))
      .then(res => {
        const data = res.scenes || [];
        setScenes(prev => reset ? data : [...prev, ...data]);
        setHasMore(data.length === 50); // Assuming per_page=50
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  };

  // Debounced filter effect
  useEffect(() => {
    setPage(1);
    const timeout = setTimeout(() => {
      fetchScenes(1, true);
    }, 500);
    return () => clearTimeout(timeout);
  }, [
    backupId, isReady, resolvedCharacterIds, characterLogic,
    writersFilter, writerLogic, categoriesFilter, typesFilter, statusesFilter,
    before, after
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
      <ScenesFilter 
        charactersFilter={charactersFilter} setCharactersFilter={setCharactersFilter}
        characterLogic={characterLogic} setCharacterLogic={setCharacterLogic}
        writersFilter={writersFilter} setWritersFilter={setWritersFilter}
        writerLogic={writerLogic} setWriterLogic={setWriterLogic}
        categoriesFilter={categoriesFilter} setCategoriesFilter={setCategoriesFilter}
        typesFilter={typesFilter} setTypesFilter={setTypesFilter}
        statusesFilter={statusesFilter} setStatusesFilter={setStatusesFilter}
        includeAlterEgos={includeAlterEgos} setIncludeAlterEgos={setIncludeAlterEgos}
        includeFamiliars={includeFamiliars} setIncludeFamiliars={setIncludeFamiliars}
        includeNPCs={includeNPCs} setIncludeNPCs={setIncludeNPCs}
        before={before} setBefore={setBefore}
        after={after} setAfter={setAfter}
        allCharacters={allCharacters}
      />
      
      {error && <div style={{ color: 'var(--error-color)', padding: '1rem' }}>{error}</div>}
      
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

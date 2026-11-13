import { useEffect, useState, useMemo, useCallback } from 'react';
import { api, getErrorMessage } from '../api';
import { ScenesFilter } from './scenes/ScenesFilter';
import { VirtualSceneList } from './scenes/VirtualSceneList';
import { SceneEditModal } from './scenes/SceneEditModal';
import { Search, ArrowUpDown } from 'lucide-react';
import { Button, ResponsiveText } from './ui';
import { UnlinkedWriterBanner } from './layout/UnlinkedWriterBanner';
import type { BackupInfo, Character, ChatSession, MyWriter } from '../types';

interface ChatSessionsTabProps {
  backupId: string;
  backupStatus?: string;
  backupInfo?: BackupInfo | null;
  backupError?: string | null;
  backupLoading?: boolean;
  onNavigateToWriters?: () => void;
  myWriter?: MyWriter | null;
}

export const ChatSessionsTab = ({
  backupId,
  backupStatus,
  backupInfo,
  backupError,
  backupLoading,
  onNavigateToWriters,
  myWriter: initialMyWriter,
}: ChatSessionsTabProps) => {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [editingSession, setEditingSession] = useState<ChatSession | null>(null);

  const [allCharacters, setAllCharacters] = useState<Character[]>([]);
  const [myWriter, setMyWriter] = useState<MyWriter | null>(initialMyWriter || null);

  // Filters: note that categoriesFilter is bound to channels for sessions mode
  const [charactersFilter, setCharactersFilter] = useState<number[]>([]);
  const [characterLogic, setCharacterLogic] = useState<'AND' | 'OR'>('AND');
  const [writersFilter, setWritersFilter] = useState<string[]>([]);
  const [writerLogic, setWriterLogic] = useState<'AND' | 'OR'>('AND');
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

  const [fetchedStatus, setFetchedStatus] = useState<string | null>(backupInfo?.status ?? backupStatus ?? null);
  const [localBackupInfo, setLocalBackupInfo] = useState<BackupInfo | null>(null);
  const [localBackupError, setLocalBackupError] = useState<string | null>(null);
  const [localBackupLoading, setLocalBackupLoading] = useState(false);

  useEffect(() => {
    setSessions([]);
    setPage(1);
    setHasMore(false);
    setError(null);
    setAllCharacters([]);
  }, [backupId]);

  useEffect(() => {
    if (backupInfo !== undefined || backupError !== undefined) {
      setFetchedStatus(backupInfo?.status ?? backupStatus ?? null);
      setLocalBackupInfo(backupInfo ?? null);
      setLocalBackupError(null);
      setLocalBackupLoading(false);
      return;
    }

    if (backupStatus) {
      setFetchedStatus(backupStatus);
      setLocalBackupError(null);
      return;
    }

    let cancelled = false;
    setLocalBackupLoading(true);
    setLocalBackupError(null);
    api
      .getBackupInfo(backupId)
      .then(res => {
        if (cancelled) return;
        setLocalBackupInfo(res);
        setFetchedStatus(res.status);
      })
      .catch(err => {
        if (cancelled) return;
        console.error(err);
        setFetchedStatus(null);
        setLocalBackupError(getErrorMessage(err, 'Failed to load backup information.'));
      })
      .finally(() => {
        if (!cancelled) setLocalBackupLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [backupId, backupStatus, backupInfo, backupError]);

  const effectiveBackupInfo = backupInfo ?? localBackupInfo;
  const effectiveBackupError = backupError ?? localBackupError;
  const effectiveBackupLoading = backupLoading ?? localBackupLoading;
  const isSchemaOutdated = Boolean(effectiveBackupInfo?.is_schema_outdated);
  const isReady =
    !effectiveBackupError &&
    !isSchemaOutdated &&
    (fetchedStatus === 'success' || fetchedStatus === 'ready' || fetchedStatus === 'READY');

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
      channelsFilter,
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

  const fetchSessions = useCallback(
    (targetPage: number, reset = false) => {
      if (!isReady) return;
      setLoading(true);
      setError(null);

      const params = buildQueryParams(targetPage);

      api
        .getSessions(backupId, params)
        .then(res => {
          const newSessions = res.sessions || [];
          setSessions(prev => (reset ? newSessions : [...prev, ...newSessions]));
          setHasMore(newSessions.length === 50);
        })
        .catch(err => {
          console.error(err);
          setHasMore(false);
          setError(getErrorMessage(err, 'Failed to fetch chat sessions.'));
        })
        .finally(() => setLoading(false));
    },
    [backupId, isReady, buildQueryParams]
  );

  // Debounced filter effect
  useEffect(() => {
    setPage(1);
    const timeout = setTimeout(() => {
      fetchSessions(1, true);
    }, 400);
    return () => clearTimeout(timeout);
  }, [
    backupId,
    isReady,
    resolvedCharacterIds,
    characterLogic,
    writersFilter,
    writerLogic,
    channelsFilter,
    typesFilter,
    statusesFilter,
    before,
    after,
    byMe,
    search,
    sortOrder,
    fetchSessions,
  ]);

  const loadMore = () => {
    const nextPage = page + 1;
    setPage(nextPage);
    fetchSessions(nextPage);
  };

  if (effectiveBackupLoading) {
    return (
      <div className="glass-panel p-lg">
        <h2>Chat Sessions</h2>
        <p className="text-secondary">Loading backup status...</p>
      </div>
    );
  }

  if (effectiveBackupError) {
    return (
      <div className="glass-panel p-lg">
        <h2>Chat Sessions</h2>
        <div className="banner-danger mt-md">
          <span className="text-md">{effectiveBackupError}</span>
        </div>
      </div>
    );
  }

  if (isSchemaOutdated) {
    return (
      <div className="glass-panel p-lg">
        <h2>Chat Sessions</h2>
        <div className="banner-danger mt-md">
          <span className="text-md">
            This backup database uses an outdated schema (v{effectiveBackupInfo?.schema_version ?? '?'}) and cannot be queried until it is upgraded from the Status tab.
          </span>
        </div>
      </div>
    );
  }

  if (!isReady) {
    return (
      <div className="glass-panel opacity-50 pointer-events-none p-lg">
        <h2>Chat Sessions</h2>
        <p className="text-secondary">Backup is not ready. Run the pipeline first.</p>
      </div>
    );
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
            placeholder="Search chat sessions or custom names..."
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
        mode="sessions"
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

      {error && (
        <div className="banner-danger">
          <span className="text-md">{error}</span>
        </div>
      )}

      <VirtualSceneList
        mode="sessions"
        scenes={sessions}
        allCharacters={allCharacters}
        charactersFilter={charactersFilter}
        setCharactersFilter={setCharactersFilter}
        loadMore={loadMore}
        hasMore={hasMore}
        loading={loading}
        error={error}
        onEdit={item => setEditingSession(item as ChatSession)}
      />

      {editingSession && (
        <SceneEditModal
          backupId={backupId}
          scene={editingSession}
          onClose={() => setEditingSession(null)}
          onUpdated={updated => {
            if (updated) {
              setSessions(prev =>
                prev.map(s =>
                  s.scene_key === updated.scene_key ||
                  s.id === updated.scene_key ||
                  (updated.pk && (s.pk === updated.pk || s.scene_pk === updated.pk))
                    ? { ...s, custom_name: updated.custom_name }
                    : s
                )
              );
            } else {
              fetchSessions(1, true);
            }
          }}
        />
      )}
    </div>
  );
};

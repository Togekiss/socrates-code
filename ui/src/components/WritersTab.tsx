import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Plus,
  Users,
  Loader2,
  RotateCcw,
} from 'lucide-react';
import { api, getErrorMessage } from '../api';
import { WriterEditModal } from './curation/WriterEditModal';
import { WriterCard } from './curation/WriterCard';
import { WriterLinkSuggestions } from './curation/WriterLinkSuggestions';
import {
  WritersFilter,
  type WriterLinkFilter,
  type WriterSortBy,
  type WriterSortOrder,
} from './curation/WritersFilter';
import { BackupStatusGuard } from './layout/BackupStatusGuard';
import { ListPageLayout } from './layout/ListPageLayout';
import { useBackupStatusGuard } from '../hooks/useBackupStatusGuard';
import { PanelSurface, Button } from './ui';
import type { BackupInfo, User, WriterDetailed, WriterLinkSuggestion } from '../types';
import { getRoleLevel, ROLE_LEVELS } from '../utils/rbac';

interface WritersTabProps {
  backupId: string;
  backupStatus?: string;
  backupInfo?: BackupInfo | null;
  backupError?: string | null;
  backupLoading?: boolean;
  currentUser?: User | null;
  roleLevel?: number;
  onRefreshSummary?: () => void;
}

export const WritersTab = ({
  backupId,
  backupStatus,
  backupInfo,
  backupError,
  backupLoading,
  currentUser,
  roleLevel: propRoleLevel,
  onRefreshSummary,
}: WritersTabProps) => {
  const [writers, setWriters] = useState<WriterDetailed[]>([]);
  const [suggestions, setSuggestions] = useState<WriterLinkSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters & sorting state
  const [search, setSearch] = useState('');
  const [linkFilter, setLinkFilter] = useState<WriterLinkFilter>('all');
  const [charCountMin, setCharCountMin] = useState(0);
  const [charCountMax, setCharCountMax] = useState<number | null>(null);
  const [sortBy, setSortBy] = useState<WriterSortBy>('name');
  const [sortOrder, setSortOrder] = useState<WriterSortOrder>('asc');

  // Modals state
  const [editingWriter, setEditingWriter] = useState<WriterDetailed | null>(null);
  const [isCreatingWriter, setIsCreatingWriter] = useState(false);
  const [linkingSuggestionId, setLinkingSuggestionId] = useState<number | null>(null);

  const effectiveRoleLevel = propRoleLevel ?? backupInfo?.role_level ?? getRoleLevel(backupInfo?.effective_role);
  const canCurate = effectiveRoleLevel >= ROLE_LEVELS.curator;
  const isParticipant = effectiveRoleLevel === ROLE_LEVELS.participant;

  const statusGuard = useBackupStatusGuard({
    backupId,
    backupStatus,
    backupInfo,
    backupError,
    backupLoading,
  });

  useEffect(() => {
    setWriters([]);
    setSuggestions([]);
    setError(null);
    setCharCountMin(0);
    setCharCountMax(null);
  }, [backupId]);

  const fetchData = useCallback(() => {
    if (!backupId || !statusGuard.isReady) return;
    setLoading(true);
    setError(null);
    Promise.all([
      api.getWritersDetailed(backupId),
      canCurate ? api.getWriterLinkSuggestions(backupId).catch(() => []) : Promise.resolve([]),
    ])
      .then(([wData, sData]) => {
        setWriters(Array.isArray(wData) ? wData : []);
        setSuggestions(canCurate && Array.isArray(sData) ? sData : []);
      })
      .catch(err => {
        console.error(err);
        setWriters([]);
        setSuggestions([]);
        setError(getErrorMessage(err, 'Failed to load writers data.'));
      })
      .finally(() => {
        setLoading(false);
      });
  }, [backupId, statusGuard.isReady, canCurate]);

  useEffect(() => {
    if (statusGuard.isReady) {
      fetchData();
    }
  }, [statusGuard.isReady, fetchData]);

  const handleAcceptSuggestion = async (sugg: WriterLinkSuggestion) => {
    const writerId = sugg.writer_id ?? sugg.writer_pk;
    const discordId = sugg.suggested_discord_id ?? sugg.suggested_discord_user_id;
    if (!writerId || !discordId) return;

    setLinkingSuggestionId(writerId);
    try {
      await api.updateWriter(backupId, writerId, {
        discord_user_id: discordId,
      });
      fetchData();
      if (onRefreshSummary) onRefreshSummary();
    } catch (err) {
      console.error('Failed to link suggestion:', err);
      setError(getErrorMessage(err, 'Failed to link writer suggestion.'));
    } finally {
      setLinkingSuggestionId(null);
    }
  };

  const maxCharacters = useMemo(
    () => writers.reduce((max, w) => Math.max(max, w.characters?.length ?? w.character_count ?? 0), 0),
    [writers]
  );

  const effectiveCharMin = Math.min(charCountMin, maxCharacters);
  const effectiveCharMax = Math.min(charCountMax ?? maxCharacters, maxCharacters);
  const filtersActive = Boolean(
    search.trim() ||
      (canCurate && linkFilter !== 'all') ||
      effectiveCharMin > 0 ||
      effectiveCharMax < maxCharacters
  );

  const handleResetFilters = () => {
    setSearch('');
    setLinkFilter('all');
    setCharCountMin(0);
    setCharCountMax(null);
  };

  const filteredWriters = useMemo(() => {
    const q = search.trim().toLowerCase();

    const filtered = writers.filter(w => {
      if (q) {
        const hasNameMatch = w.display_name.toLowerCase().includes(q);
        const hasAliasMatch = w.aliases?.some(a => a.toLowerCase().includes(q));
        if (!hasNameMatch && !hasAliasMatch) return false;
      }

      if (canCurate && linkFilter !== 'all') {
        const isLinked = Boolean(w.discord_user_id && w.discord_user_id.trim().length > 0);
        if (linkFilter === 'linked' && !isLinked) return false;
        if (linkFilter === 'unlinked' && isLinked) return false;
      }

      const charCount = w.characters?.length ?? w.character_count ?? 0;
      if (charCount < effectiveCharMin || charCount > effectiveCharMax) {
        return false;
      }

      return true;
    });

    return [...filtered].sort((a, b) => {
      let cmp = 0;
      if (sortBy === 'id') {
        cmp = a.id - b.id;
      } else {
        cmp = a.display_name.localeCompare(b.display_name, undefined, { sensitivity: 'base' });
        if (cmp === 0) cmp = a.id - b.id;
      }
      return sortOrder === 'asc' ? cmp : -cmp;
    });
  }, [writers, search, canCurate, linkFilter, effectiveCharMin, effectiveCharMax, sortBy, sortOrder]);

  if (!statusGuard.isReady) {
    return <BackupStatusGuard title="Writers" guard={statusGuard} />;
  }

  return (
    <ListPageLayout
      title="Writers"
      descriptionKey="descWriters"
      guideKey="writers"
      headerAction={
        canCurate ? (
          <Button
            variant="secondary"
            size="md"
            onClick={() => setIsCreatingWriter(true)}
            icon={<Plus size={14} />}
          >
            New Writer
          </Button>
        ) : undefined
      }
      filterBar={
        <WritersFilter
          searchFilter={search}
          setSearchFilter={setSearch}
          linkFilter={linkFilter}
          setLinkFilter={setLinkFilter}
          showLinkFilter={canCurate}
          charCountMin={charCountMin}
          setCharCountMin={setCharCountMin}
          charCountMax={charCountMax}
          setCharCountMax={setCharCountMax}
          maxCharacters={maxCharacters}
          sortBy={sortBy}
          setSortBy={setSortBy}
          sortOrder={sortOrder}
          setSortOrder={setSortOrder}
        />
      }
      countText={
        !loading && !error && writers.length > 0 ? (
          <span>
            Showing <strong>{filteredWriters.length}</strong> of <strong>{writers.length}</strong>{' '}
            {writers.length === 1 ? 'writer' : 'writers'}
            {filtersActive && ' (filtered)'}
          </span>
        ) : undefined
      }
      modals={
        (canCurate && isCreatingWriter) || (editingWriter && (canCurate || isParticipant)) ? (
          <WriterEditModal
            backupId={backupId}
            writer={editingWriter}
            isParticipantSelfEdit={!canCurate && isParticipant}
            onClose={() => {
              setIsCreatingWriter(false);
              setEditingWriter(null);
            }}
            onSaved={() => {
              fetchData();
              if (onRefreshSummary) onRefreshSummary();
            }}
          />
        ) : undefined
      }
    >
      {/* Discord Link Suggestions Banner (scrollable with cards) */}
      {canCurate && (
        <WriterLinkSuggestions
          suggestions={suggestions}
          linkingSuggestionId={linkingSuggestionId}
          onAcceptSuggestion={handleAcceptSuggestion}
        />
      )}

      {/* Writers Roster Grid */}
      {loading ? (
        <PanelSurface className="text-center p-xl">
          <Loader2
            size={32}
            className="animate-spin text-accent"
            style={{ margin: '0 auto 1rem auto' }}
          />
          <p className="text-secondary">Loading writers data...</p>
        </PanelSurface>
      ) : error ? (
        <div className="banner-danger">
          <span className="text-md">{error}</span>
        </div>
      ) : filteredWriters.length === 0 ? (
        <div className="empty-state">
          <Users size={40} className="empty-state-icon" />
          <h3 className="empty-state-title">No writers found</h3>
          <p className="empty-state-desc">
            {filtersActive
              ? 'No writers match the active filters.'
              : 'No writer profiles exist yet.'}
          </p>
          {filtersActive ? (
            <Button
              variant="secondary"
              size="sm"
              onClick={handleResetFilters}
              icon={<RotateCcw size={14} />}
            >
              Reset Filters
            </Button>
          ) : (
            canCurate && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setIsCreatingWriter(true)}
                icon={<Plus size={14} />}
              >
                Create Writer
              </Button>
            )
          )}
        </div>
      ) : (
        <div className="writers-grid">
          {filteredWriters.map(writer => {
            const isSelfWriter = Boolean(
              writer.is_self ||
                (currentUser?.id && writer.discord_user_id && writer.discord_user_id === currentUser.id)
            );
            const canEditWriter = canCurate || (isParticipant && isSelfWriter);
            const showDiscordId = canCurate || isSelfWriter;
            return (
              <WriterCard
                key={writer.id}
                writer={writer}
                showDiscordId={showDiscordId}
                onEdit={canEditWriter ? setEditingWriter : undefined}
              />
            );
          })}
        </div>
      )}
    </ListPageLayout>
  );
};

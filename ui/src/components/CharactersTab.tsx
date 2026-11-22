import { useEffect, useState, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Plus, Loader2 } from 'lucide-react';
import { api, getErrorMessage } from '../api';
import { CharactersFilter } from './characters/CharactersFilter';
import { VirtualScrollList, type VirtualListItem } from './characters/VirtualScrollList';
import { CharacterEditModal } from './characters/CharacterEditModal';
import { GroupEditModal } from './characters/GroupEditModal';
import { AssignWriterModal } from './curation/AssignWriterModal';
import { UnlinkedWriterBanner } from './layout/UnlinkedWriterBanner';
import { BackupStatusGuard } from './layout/BackupStatusGuard';
import { ListPageLayout } from './layout/ListPageLayout';
import { useBackupStatusGuard } from '../hooks/useBackupStatusGuard';
import { Button, PanelSurface, ResponsiveText } from './ui';
import type { BackupInfo, Character, CharacterGroup, MyWriter, User, WriterDetailed } from '../types';
import { getRoleLevel, ROLE_LEVELS } from '../utils/rbac';

interface CharactersTabProps {
  backupId: string;
  backupStatus?: string;
  backupInfo?: BackupInfo | null;
  backupError?: string | null;
  backupLoading?: boolean;
  currentUser?: User | null;
  roleLevel?: number;
  onNavigateToWriters?: () => void;
  myWriter?: MyWriter | null;
}

export const CharactersTab = ({
  backupId,
  backupStatus,
  backupInfo,
  backupError,
  backupLoading,
  currentUser,
  roleLevel: propRoleLevel,
  onNavigateToWriters,
  myWriter: initialMyWriter,
}: CharactersTabProps) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [characters, setCharacters] = useState<Character[] | null>(null);
  const [groups, setGroups] = useState<CharacterGroup[] | null>(null);
  const [writers, setWriters] = useState<WriterDetailed[]>([]);
  const [myWriter, setMyWriter] = useState<MyWriter | null>(initialMyWriter || null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Filters state
  const [nameFilter, setNameFilter] = useState('');
  const [writerFilter, setWriterFilter] = useState('');
  const [tagsFilter, setTagsFilter] = useState<string[]>([]);
  const [byMe, setByMe] = useState(false);
  const [unassignedOnly, setUnassignedOnly] = useState(() => searchParams.get('unassigned') === '1');

  // Sync unassigned filter with query params
  useEffect(() => {
    const isUnassigned = searchParams.get('unassigned') === '1';
    if (isUnassigned !== unassignedOnly) {
      setUnassignedOnly(isUnassigned);
    }
  }, [searchParams, unassignedOnly]);

  const handleSetUnassignedOnly = (val: boolean) => {
    setUnassignedOnly(val);
    setSearchParams(
      prev => {
        const next = new URLSearchParams(prev);
        if (val) next.set('unassigned', '1');
        else next.delete('unassigned');
        return next;
      },
      { replace: true }
    );
  };

  // Edit / Action state
  const [editingChar, setEditingChar] = useState<{ char: Character; parent?: Character } | null>(null);
  const [editingGroup, setEditingGroup] = useState<CharacterGroup | null>(null);
  const [isCreatingGroup, setIsCreatingGroup] = useState(false);
  const [assigningChar, setAssigningChar] = useState<Character | null>(null);

  const statusGuard = useBackupStatusGuard({
    backupId,
    backupStatus,
    backupInfo,
    backupError,
    backupLoading,
  });

  useEffect(() => {
    setMyWriter(initialMyWriter || null);
  }, [initialMyWriter]);

  const fetchCharacters = useCallback(() => {
    if (!backupId || !statusGuard.isReady) return;
    setLoading(true);
    setError(null);
    setCharacters(null);
    setGroups(null);
    Promise.all([
      api.getCharacters(backupId, byMe),
      api.getGroups(backupId),
      api.getWritersDetailed(backupId).catch(() => []),
    ])
      .then(([charsRes, groupsRes, writersRes]) => {
        setCharacters(Array.isArray(charsRes) ? charsRes : []);
        setGroups(Array.isArray(groupsRes) ? groupsRes : []);
        if (Array.isArray(writersRes)) setWriters(writersRes);
      })
      .catch(err => setError(getErrorMessage(err, 'Failed to load characters.')))
      .finally(() => setLoading(false));
  }, [backupId, byMe, statusGuard.isReady]);

  useEffect(() => {
    if (statusGuard.isReady) {
      fetchCharacters();
    }
  }, [statusGuard.isReady, fetchCharacters]);

  // Extract all unique tags
  const availableTags = useMemo(() => {
    if (!characters) return [];
    const tags = new Set<string>();
    characters.forEach(c => {
      if (c.tags) c.tags.forEach(t => tags.add(t));
      if (c.versions) {
        c.versions.forEach(v => {
          if (v.version_type) tags.add(v.version_type);
        });
      }
    });
    return Array.from(tags).sort();
  }, [characters]);

  // Derived state: Filtered and grouped items to display
  const { displayItems, filtersActive } = useMemo(() => {
    if (!characters) return { displayItems: [], filtersActive: false };

    const currentGroups = groups || [];
    const isActive = Boolean(nameFilter || writerFilter || tagsFilter.length > 0 || byMe || unassignedOnly);

    const matchesFilters = (char: Character): boolean => {
      if (unassignedOnly) {
        const hasWriter = Boolean(
          (char.writer && char.writer.length > 0 && char.writer.some(w => w && w.trim().length > 0)) ||
          char.writer_name ||
          char.writer_id
        );
        if (hasWriter) return false;
      }
      if (nameFilter) {
        const q = nameFilter.toLowerCase();
        const hasNameMatch = char.names?.some(n => n.toLowerCase().includes(q));
        if (!hasNameMatch) return false;
      }
      if (writerFilter) {
        const q = writerFilter.toLowerCase();
        const hasWriterMatch = char.writer?.some(w => w.toLowerCase().includes(q));
        if (!hasWriterMatch) return false;
      }
      if (tagsFilter.length > 0) {
        const cTags = char.tags || [];
        const hasTagsMatch = tagsFilter.every(t => cTags.includes(t));
        if (!hasTagsMatch) return false;
      }
      return true;
    };

    // Map character IDs to character objects
    const charMap = new Map<number, Character>();
    characters.forEach(c => charMap.set(c.id, c));

    // Track which characters belong to any group
    const groupedCharIds = new Set<number>();
    currentGroups.forEach(g => {
      (g.members || []).forEach(m => {
        const mid = typeof m === 'object' ? m.id : m;
        groupedCharIds.add(mid);
      });
    });

    const items: VirtualListItem[] = [];

    if (!isActive) {
      // 1. Group Cards (only include groups with at least 1 member)
      currentGroups.forEach(g => {
        const members = (g.members || [])
          .map(m => {
            const mid = typeof m === 'object' ? m.id : m;
            return charMap.get(mid);
          })
          .filter(Boolean) as Character[];

        items.push({
          _isGroup: true,
          id: `group-${g.id}`,
          group: g,
          members,
        });
      });

      // 2. Standalone Characters (not part of any group)
      characters.forEach(c => {
        if (!groupedCharIds.has(c.id)) {
          items.push({
            _isGroup: false,
            id: c.id,
            character: c,
          });
        }
      });

      return { displayItems: items, filtersActive: false };
    }

    // Active filters: Include groups only if they have MATCHING members
    currentGroups.forEach(g => {
      const allMembers = (g.members || [])
        .map(m => {
          const mid = typeof m === 'object' ? m.id : m;
          return charMap.get(mid);
        })
        .filter(Boolean) as Character[];

      const matchingMembers = allMembers.filter(m => matchesFilters(m));

      const groupNameMatches = nameFilter
        ? g.names?.some(n => n.toLowerCase().includes(nameFilter.toLowerCase()))
        : false;

      // Rule: Never render ghost groups with 0 matching members when filters or byMe are active!
      const shouldIncludeGroup =
        matchingMembers.length > 0 ||
        (groupNameMatches && !writerFilter && tagsFilter.length === 0 && !byMe && !unassignedOnly && allMembers.length > 0);

      if (shouldIncludeGroup) {
        const displayMembers = matchingMembers.length > 0 ? matchingMembers : allMembers;
        items.push({
          _isGroup: true,
          id: `group-${g.id}`,
          group: g,
          members: displayMembers,
        });
      }
    });

    // Standalone Characters matching filter
    characters.forEach(c => {
      if (!groupedCharIds.has(c.id) && matchesFilters(c)) {
        items.push({
          _isGroup: false,
          id: c.id,
          character: c,
        });
      }
    });

    return { displayItems: items, filtersActive: true };
  }, [characters, groups, nameFilter, writerFilter, tagsFilter, byMe, unassignedOnly]);

  const effectiveRoleLevel = propRoleLevel ?? backupInfo?.role_level ?? getRoleLevel(backupInfo?.effective_role);
  const canCurate = effectiveRoleLevel >= ROLE_LEVELS.curator;
  const isParticipant = effectiveRoleLevel === ROLE_LEVELS.participant;
  const selfWriterId = useMemo(() => {
    if (myWriter?.id != null) return myWriter.id;
    const matched = writers.find(
      w => w.is_self || (currentUser?.id && w.discord_user_id && w.discord_user_id === currentUser.id)
    );
    return matched?.id ?? null;
  }, [myWriter, writers, currentUser]);

  const selfCharacterIds = useMemo(
    () => new Set(myWriter?.character_ids ?? []),
    [myWriter]
  );

  const selfWriterNames = useMemo(() => {
    const names = new Set<string>();
    const pushName = (n?: string | null) => {
      const trimmed = n?.trim().toLowerCase();
      if (trimmed) names.add(trimmed);
    };
    pushName(myWriter?.display_name);
    myWriter?.aliases?.forEach(pushName);
    const matched = writers.find(
      w => w.is_self || (currentUser?.id && w.discord_user_id && w.discord_user_id === currentUser.id)
    );
    pushName(matched?.display_name);
    matched?.aliases?.forEach(pushName);
    return names;
  }, [myWriter, writers, currentUser]);

  const canEditCharacter = useCallback(
    (char: Character, parent?: Character): boolean => {
      if (!statusGuard.canMutate) return false;
      if (canCurate) return true;
      if (!isParticipant || selfWriterId == null) return false;
      if (selfCharacterIds.has(char.id)) return true;
      if (char.writer_id != null) return char.writer_id === selfWriterId;
      if (
        char.writer_id === undefined &&
        selfWriterNames.size > 0 &&
        char.writer?.some(w => selfWriterNames.has(w.trim().toLowerCase()))
      ) {
        return true;
      }
      if (parent) {
        if (selfCharacterIds.has(parent.id)) return true;
        if (parent.writer_id != null) return parent.writer_id === selfWriterId;
      }
      return false;
    },
    [statusGuard.canMutate, canCurate, isParticipant, selfWriterId, selfCharacterIds, selfWriterNames]
  );

  if (!statusGuard.isReady) {
    return <BackupStatusGuard title="Characters & Groups" guard={statusGuard} />;
  }

  return (
    <ListPageLayout
      title="Characters"
      descriptionKey="descCharacters"
      guideKey="characters"
      headerAction={
        canCurate ? (
          <Button
            variant="secondary"
            size="md"
            disabled={!statusGuard.canMutate}
            title={!statusGuard.canMutate ? 'Editing is disabled while sync is in progress.' : undefined}
            onClick={() => setIsCreatingGroup(true)}
            icon={<Plus size={14} />}
          >
            <ResponsiveText textKey="newCharacterGroup" />
          </Button>
        ) : undefined
      }
      filterBar={
        <CharactersFilter
          nameFilter={nameFilter}
          setNameFilter={setNameFilter}
          writerFilter={writerFilter}
          setWriterFilter={setWriterFilter}
          tagsFilter={tagsFilter}
          setTagsFilter={setTagsFilter}
          availableTags={availableTags}
          byMe={byMe}
          setByMe={setByMe}
          isLoggedIn={true}
          unassignedOnly={unassignedOnly}
          setUnassignedOnly={handleSetUnassignedOnly}
        />
      }
      banners={
        <>
          <BackupStatusGuard title="Characters & Groups" guard={statusGuard} />
          {byMe && !myWriter && (
            <UnlinkedWriterBanner onNavigateToWriters={onNavigateToWriters} />
          )}
        </>
      }
      countText={
        <span>
          Showing <strong>{displayItems.length}</strong> characters and groups
          {filtersActive && ' (filtered)'}
        </span>
      }
      modals={
        <>
          {/* Edit Character Modal */}
          {editingChar && canEditCharacter(editingChar.char, editingChar.parent) && (
            <CharacterEditModal
              backupId={backupId}
              character={editingChar.char}
              parentCharacter={editingChar.parent}
              allCharacters={characters || []}
              allGroups={groups || []}
              allWriters={writers}
              onWriterCreated={created =>
                setWriters(prev =>
                  [...prev.filter(w => w.id !== created.id), created].sort((a, b) =>
                    a.display_name.localeCompare(b.display_name)
                  )
                )
              }
              isParticipantMode={!canCurate && isParticipant}
              selfWriterId={selfWriterId}
              selfCharacterIds={myWriter?.character_ids || []}
              onClose={() => setEditingChar(null)}
              onSaved={fetchCharacters}
            />
          )}

          {/* Create / Edit Group Modal */}
          {canCurate && (isCreatingGroup || editingGroup) && (
            <GroupEditModal
              backupId={backupId}
              group={editingGroup}
              allCharacters={characters || []}
              onClose={() => {
                setIsCreatingGroup(false);
                setEditingGroup(null);
              }}
              onSaved={fetchCharacters}
            />
          )}

          {/* Assign Writer Modal */}
          {canCurate && assigningChar && (
            <AssignWriterModal
              backupId={backupId}
              character={assigningChar}
              writers={writers}
              onWriterCreated={created =>
                setWriters(prev =>
                  [...prev.filter(w => w.id !== created.id), created].sort((a, b) =>
                    a.display_name.localeCompare(b.display_name)
                  )
                )
              }
              onClose={() => setAssigningChar(null)}
              onAssigned={fetchCharacters}
            />
          )}
        </>
      }
    >
      {/* Characters Virtual List (1-character-per-row stack) */}
      {loading ? (
        <PanelSurface className="text-center p-xl">
          <Loader2
            size={32}
            className="animate-spin text-accent"
            style={{ margin: '0 auto 1rem auto' }}
          />
          <p className="text-secondary">Loading characters...</p>
        </PanelSurface>
      ) : error ? (
        <div className="banner-danger">{error}</div>
      ) : (
        <div className="character-list-stack">
          <VirtualScrollList
            items={displayItems}
            onEdit={(canCurate || isParticipant) && statusGuard.canMutate ? (char, parent) => setEditingChar({ char, parent }) : undefined}
            canEdit={canEditCharacter}
            onEditGroup={canCurate && statusGuard.canMutate ? g => setEditingGroup(g) : undefined}
            onAssignWriter={canCurate && statusGuard.canMutate ? setAssigningChar : undefined}
            onAddTagFilter={tag => {
              if (!tagsFilter.includes(tag)) setTagsFilter([...tagsFilter, tag]);
            }}
          />
        </div>
      )}
    </ListPageLayout>
  );
};

import { useEffect, useState, useMemo, useCallback } from 'react';
import { Plus, AlertCircle, ArrowRight, Loader2 } from 'lucide-react';
import { api } from '../api';
import { CharactersFilter } from './characters/CharactersFilter';
import { VirtualScrollList, type VirtualListItem } from './characters/VirtualScrollList';
import { CharacterEditModal } from './characters/CharacterEditModal';
import { GroupEditModal } from './characters/GroupEditModal';
import type { Character, CharacterGroup, MyWriter } from '../types';

interface CharactersTabProps {
  backupId: string;
  onNavigateToWriters?: () => void;
  myWriter?: MyWriter | null;
}

export const CharactersTab = ({
  backupId,
  onNavigateToWriters,
  myWriter: initialMyWriter,
}: CharactersTabProps) => {
  const [characters, setCharacters] = useState<Character[] | null>(null);
  const [groups, setGroups] = useState<CharacterGroup[] | null>(null);
  const [myWriter, setMyWriter] = useState<MyWriter | null>(initialMyWriter || null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Filters state
  const [nameFilter, setNameFilter] = useState('');
  const [writerFilter, setWriterFilter] = useState('');
  const [tagsFilter, setTagsFilter] = useState<string[]>([]);
  const [byMe, setByMe] = useState(false);

  // Edit state
  const [editingChar, setEditingChar] = useState<{ char: Character; parent?: Character } | null>(null);
  const [editingGroup, setEditingGroup] = useState<CharacterGroup | null>(null);
  const [isCreatingGroup, setIsCreatingGroup] = useState(false);

  const fetchCharacters = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.getCharacters(backupId, byMe),
      api.getGroups(backupId),
      api.getMyWriter(backupId).catch(() => null),
    ])
      .then(([charsRes, groupsRes, writerRes]) => {
        setCharacters(Array.isArray(charsRes) ? charsRes : []);
        setGroups(Array.isArray(groupsRes) ? groupsRes : []);
        if (writerRes !== undefined) setMyWriter(writerRes);
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, [backupId, byMe]);

  useEffect(() => {
    fetchCharacters();
  }, [fetchCharacters]);

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
    const isActive = Boolean(nameFilter || writerFilter || tagsFilter.length > 0 || byMe);

    const matchesFilters = (char: Character): boolean => {
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
        (groupNameMatches && !writerFilter && tagsFilter.length === 0 && !byMe && allMembers.length > 0);

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
  }, [characters, groups, nameFilter, writerFilter, tagsFilter, byMe]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      {/* Filter Bar */}
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
      />

      {/* Unlinked Writer Guidance Banner for "By Me" */}
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
                Link your Discord user ID in the Writers view so &quot;★ By Me&quot; can identify your characters.
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

      {/* Roster Controls */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 0.25rem' }}>
        <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
          Showing <strong>{displayItems.length}</strong> characters and groups
          {filtersActive && ' (filtered)'}
        </div>
        <button
          onClick={() => setIsCreatingGroup(true)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.4rem',
            padding: '0.45rem 0.9rem',
            background: 'var(--bg-tertiary)',
            border: '1px solid var(--border-color)',
            color: 'var(--text-primary)',
            borderRadius: '6px',
            fontSize: '0.85rem',
            fontWeight: 500,
            cursor: 'pointer',
          }}
        >
          <Plus size={15} /> New Character Group
        </button>
      </div>

      {/* Characters Virtual List */}
      {loading ? (
        <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
          <Loader2 size={32} className="animate-spin" style={{ color: 'var(--accent-secondary)', margin: '0 auto 1rem auto' }} />
          <p style={{ color: 'var(--text-secondary)' }}>Loading characters...</p>
        </div>
      ) : error ? (
        <div className="glass-panel" style={{ textAlign: 'center', padding: '2rem', color: 'var(--danger)' }}>
          {error}
        </div>
      ) : (
        <VirtualScrollList
          items={displayItems}
          onEdit={(char, parent) => setEditingChar({ char, parent })}
          onEditGroup={g => setEditingGroup(g)}
          onAddTagFilter={tag => {
            if (!tagsFilter.includes(tag)) setTagsFilter([...tagsFilter, tag]);
          }}
        />
      )}

      {/* Edit Character Modal */}
      {editingChar && (
        <CharacterEditModal
          backupId={backupId}
          character={editingChar.char}
          parentCharacter={editingChar.parent}
          allCharacters={characters || []}
          onClose={() => setEditingChar(null)}
          onSaved={fetchCharacters}
        />
      )}

      {/* Create / Edit Group Modal */}
      {(isCreatingGroup || editingGroup) && (
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
    </div>
  );
};

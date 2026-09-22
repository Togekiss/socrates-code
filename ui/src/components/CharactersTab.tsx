import { useEffect, useState, useMemo } from 'react';
import { api } from '../api';
import { CharactersFilter } from './characters/CharactersFilter';
import { VirtualScrollList } from './characters/VirtualScrollList';
import { CharacterEditModal } from './characters/CharacterEditModal';

export const CharactersTab = ({ backupId }: { backupId: string }) => {
  const [characters, setCharacters] = useState<any[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Filters state
  const [nameFilter, setNameFilter] = useState('');
  const [writerFilter, setWriterFilter] = useState('');
  const [tagsFilter, setTagsFilter] = useState<string[]>([]);

  // Edit state
  const [editingChar, setEditingChar] = useState<{char: any, parent: any} | null>(null);

  const fetchCharacters = () => {
    setLoading(true);
    api.getCharacters(backupId)
      .then(res => setCharacters(Array.isArray(res) ? res : []))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchCharacters();
  }, [backupId]);

  // Extract all unique tags
  const availableTags = useMemo(() => {
    if (!characters) return [];
    const tags = new Set<string>();
    characters.forEach(c => {
      if (c.tags) c.tags.forEach((t: string) => tags.add(t));
      if (c.other_versions) {
        c.other_versions.forEach((v: any) => {
          if (v.tags) v.tags.forEach((t: string) => tags.add(t));
        });
      }
    });
    return Array.from(tags).sort();
  }, [characters]);

  // Derived state: Filtered and hierarchy-built characters
  const { displayCharacters, filtersActive } = useMemo(() => {
    if (!characters) return { displayCharacters: [], filtersActive: false };

    const isActive = !!nameFilter || !!writerFilter || tagsFilter.length > 0;

    const matchesFilters = (char: any) => {
      let matches = true;
      if (nameFilter) {
        const q = nameFilter.toLowerCase();
        const hasNameMatch = char.names?.some((n: string) => n.toLowerCase().includes(q));
        if (!hasNameMatch) matches = false;
      }
      if (writerFilter && matches) {
        const q = writerFilter.toLowerCase();
        const hasWriterMatch = char.writer?.some((w: string) => w.toLowerCase().includes(q));
        if (!hasWriterMatch) matches = false;
      }
      if (tagsFilter.length > 0 && matches) {
        const cTags = char.tags || [];
        const hasTagsMatch = tagsFilter.every(t => cTags.includes(t));
        if (!hasTagsMatch) matches = false;
      }
      return matches;
    };

    if (!isActive) {
      return { displayCharacters: characters, filtersActive: false };
    }

    // Flatten when filters are active
    const flattened: any[] = [];
    characters.forEach(c => {
      if (matchesFilters(c)) {
        flattened.push(c);
      }
      if (c.other_versions) {
        c.other_versions.forEach((v: any) => {
          if (matchesFilters(v)) {
            flattened.push({ ...v, _parent: c });
          }
        });
      }
    });

    return { displayCharacters: flattened, filtersActive: true };
  }, [characters, nameFilter, writerFilter, tagsFilter]);

  if (error) {
    return <div className="glass-panel" style={{ color: 'var(--error-color)' }}>Error loading characters: {error}</div>;
  }

  if (!characters || loading) {
    return <div className="glass-panel">Loading characters...</div>;
  }

  return (
    <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      
      <CharactersFilter 
        nameFilter={nameFilter} setNameFilter={setNameFilter}
        writerFilter={writerFilter} setWriterFilter={setWriterFilter}
        tagsFilter={tagsFilter} setTagsFilter={setTagsFilter}
        availableTags={availableTags}
      />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
        <h2 style={{ margin: 0 }}>Characters ({displayCharacters.length})</h2>
      </div>

      <VirtualScrollList 
        characters={displayCharacters}
        onEdit={(char, parent) => setEditingChar({ char, parent })}
        onAddTagFilter={(tag) => {
          if (!tagsFilter.includes(tag)) setTagsFilter([...tagsFilter, tag]);
        }}
        disableAccordion={filtersActive}
      />

      {editingChar && (
        <CharacterEditModal 
          backupId={backupId}
          character={editingChar.char}
          parentCharacter={editingChar.parent}
          allCharacters={characters}
          onClose={() => setEditingChar(null)}
          onSaved={fetchCharacters}
        />
      )}

    </div>
  );
};
